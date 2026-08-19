#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Summarize experiment results from output/<experiment>/episode_XXX directories.

Experiments have the form: <TaskName>_<policy>_<YYYYMMDD_HHMMSS>
"""

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class EpisodeResult:
    task: str
    policy: str
    experiment_dir: str
    episode_idx: int
    success: Optional[bool]
    score: Optional[float]
    duration_s: float
    avg_inference_time_s: Optional[float]
    notes: str
    instruction: str
    valid: Optional[bool] = None
    # Trajectory metrics (from trajectory_metrics in meta.json)
    ee_sparc: Optional[float] = None
    ee_isj: Optional[float] = None
    ee_path_length: Optional[float] = None
    ee_speed_mean: Optional[float] = None
    joint_sparc_mean: Optional[float] = None
    # Wrong objects grabbed
    wrong_object_grabbed: list = field(default_factory=list)


@dataclass
class ExperimentSummary:
    task: str
    policy: str
    experiment_dir: str
    total_runs: int = 0
    successes: int = 0
    total_score_fails: float = 0.0
    fail_count_with_score: int = 0
    total_duration_s: float = 0.0
    total_inference_time_s: float = 0.0
    inference_time_count: int = 0
    episodes: list = field(default_factory=list)
    # Trajectory metrics aggregates
    total_ee_sparc: float = 0.0
    total_ee_isj: float = 0.0
    total_ee_path_length: float = 0.0
    total_ee_speed_mean: float = 0.0
    total_joint_sparc_mean: float = 0.0
    trajectory_metrics_count: int = 0

    @property
    def success_pct(self) -> float:
        return (self.successes / self.total_runs * 100) if self.total_runs > 0 else 0.0

    @property
    def avg_score_fails(self) -> Optional[float]:
        if self.fail_count_with_score > 0:
            return self.total_score_fails / self.fail_count_with_score
        return None

    @property
    def avg_duration_s(self) -> float:
        return self.total_duration_s / self.total_runs if self.total_runs > 0 else 0.0

    @property
    def avg_inference_time_s(self) -> Optional[float]:
        if self.inference_time_count > 0:
            return self.total_inference_time_s / self.inference_time_count
        return None

    @property
    def avg_ee_sparc(self) -> Optional[float]:
        if self.trajectory_metrics_count > 0:
            return self.total_ee_sparc / self.trajectory_metrics_count
        return None

    @property
    def avg_ee_path_length(self) -> Optional[float]:
        if self.trajectory_metrics_count > 0:
            return self.total_ee_path_length / self.trajectory_metrics_count
        return None

    @property
    def avg_ee_speed_mean(self) -> Optional[float]:
        if self.trajectory_metrics_count > 0:
            return self.total_ee_speed_mean / self.trajectory_metrics_count
        return None


def parse_experiment_dir_name(dir_name: str) -> Optional[tuple[str, str, str]]:
    """
    Parse experiment directory name into (TaskName, policy, date).
    Expected format: <TaskName>_<policy>_<YYYYMMDD_HHMMSS>
    """
    # Pattern: TaskName_policy_YYYYMMDD_HHMMSS
    pattern = r'^(.+?)_([a-zA-Z0-9_]+?)_(\d{8}_\d{6})$'
    match = re.match(pattern, dir_name)
    if match:
        task_name = match.group(1)
        policy = match.group(2)
        date = match.group(3)
        return task_name, policy, date
    return None


def load_episode_meta(meta_path: Path) -> Optional[dict]:
    """Load and return episode metadata from meta.json."""
    try:
        with open(meta_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: Could not load {meta_path}: {e}", file=sys.stderr)
        return None


def process_episode(meta: dict, experiment_dir: str, episode_idx: int) -> EpisodeResult:
    """Process a single episode's metadata into an EpisodeResult."""
    task = meta.get('task', 'Unknown')
    policy = meta.get('policy', {}).get('name', 'unknown')

    success = meta.get('success')
    score = meta.get('score')

    t_start = meta.get('t_start_wall_s', 0)
    t_end = meta.get('t_end_wall_s', 0)
    duration_s = t_end - t_start

    inference_time = meta.get('inference_time', {})
    avg_inference_time_s = inference_time.get('mean_s')

    # Get notes - prefer episode_notes, fall back to notes
    notes = meta.get('episode_notes', '') or meta.get('notes', '')
    instruction = meta.get('instruction', '')
    valid = meta.get('valid')

    # Extract trajectory metrics if available
    traj_metrics = meta.get('trajectory_metrics', {})
    ee_sparc = traj_metrics.get('ee_sparc')
    ee_isj = traj_metrics.get('ee_isj')
    ee_path_length = traj_metrics.get('ee_path_length')
    ee_speed_mean = traj_metrics.get('ee_speed_mean')
    joint_sparc_mean = traj_metrics.get('joint_sparc_mean')

    # Extract wrong objects grabbed
    wrong_object_grabbed = meta.get('wrong_object_grabbed', []) or []

    return EpisodeResult(
        task=task,
        policy=policy,
        experiment_dir=experiment_dir,
        episode_idx=episode_idx,
        success=success,
        score=score,
        duration_s=duration_s,
        avg_inference_time_s=avg_inference_time_s,
        notes=notes,
        instruction=instruction,
        valid=valid,
        ee_sparc=ee_sparc,
        ee_isj=ee_isj,
        ee_path_length=ee_path_length,
        ee_speed_mean=ee_speed_mean,
        joint_sparc_mean=joint_sparc_mean,
        wrong_object_grabbed=wrong_object_grabbed,
    )


def collect_experiments(output_dir: Path) -> dict[str, ExperimentSummary]:
    """Collect and aggregate all experiment results."""
    experiments = {}

    for exp_dir in sorted(output_dir.iterdir()):
        if not exp_dir.is_dir():
            continue

        parsed = parse_experiment_dir_name(exp_dir.name)
        if parsed is None:
            # Skip directories that don't match the expected pattern
            continue

        task_name, policy, date = parsed
        exp_key = exp_dir.name

        # Initialize experiment summary
        summary = ExperimentSummary(
            task=task_name,
            policy=policy,
            experiment_dir=exp_dir.name,
        )

        # Process each episode
        episode_dirs = sorted(exp_dir.glob('episode_*'))
        for ep_dir in episode_dirs:
            if not ep_dir.is_dir():
                continue

            meta_path = ep_dir / 'meta.json'
            if not meta_path.exists():
                continue

            meta = load_episode_meta(meta_path)
            if meta is None:
                continue

            # Extract episode index from directory name
            ep_match = re.match(r'episode_(\d+)', ep_dir.name)
            episode_idx = int(ep_match.group(1)) if ep_match else 0

            episode = process_episode(meta, exp_dir.name, episode_idx)
            summary.episodes.append(episode)

            # Update task and policy from meta.json (use first episode's values)
            if summary.total_runs == 0:
                summary.task = episode.task
                summary.policy = episode.policy

            # Update aggregates
            summary.total_runs += 1
            summary.total_duration_s += episode.duration_s

            if episode.success is True:
                summary.successes += 1
            elif episode.success is False and episode.score is not None:
                summary.total_score_fails += episode.score
                summary.fail_count_with_score += 1

            if episode.avg_inference_time_s is not None:
                summary.total_inference_time_s += episode.avg_inference_time_s
                summary.inference_time_count += 1

            # Aggregate trajectory metrics
            if episode.ee_sparc is not None:
                summary.total_ee_sparc += episode.ee_sparc
                summary.total_ee_isj += episode.ee_isj or 0.0
                summary.total_ee_path_length += episode.ee_path_length or 0.0
                summary.total_ee_speed_mean += episode.ee_speed_mean or 0.0
                summary.total_joint_sparc_mean += episode.joint_sparc_mean or 0.0
                summary.trajectory_metrics_count += 1

        if summary.total_runs > 0:
            experiments[exp_key] = summary

    return experiments


def filter_valid_episodes(experiments: dict[str, ExperimentSummary]) -> dict[str, ExperimentSummary]:
    """Filter experiments to only include valid episodes and recalculate statistics."""
    filtered = {}

    for exp_key, summary in experiments.items():
        # Filter to only valid episodes
        valid_episodes = [ep for ep in summary.episodes if ep.valid is True]

        if not valid_episodes:
            continue

        # Create new summary with recalculated stats
        new_summary = ExperimentSummary(
            task=summary.task,
            policy=summary.policy,
            experiment_dir=summary.experiment_dir,
        )
        new_summary.episodes = valid_episodes

        for episode in valid_episodes:
            new_summary.total_runs += 1
            new_summary.total_duration_s += episode.duration_s

            if episode.success is True:
                new_summary.successes += 1
            elif episode.success is False and episode.score is not None:
                new_summary.total_score_fails += episode.score
                new_summary.fail_count_with_score += 1

            if episode.avg_inference_time_s is not None:
                new_summary.total_inference_time_s += episode.avg_inference_time_s
                new_summary.inference_time_count += 1

            # Aggregate trajectory metrics
            if episode.ee_sparc is not None:
                new_summary.total_ee_sparc += episode.ee_sparc
                new_summary.total_ee_isj += episode.ee_isj or 0.0
                new_summary.total_ee_path_length += episode.ee_path_length or 0.0
                new_summary.total_ee_speed_mean += episode.ee_speed_mean or 0.0
                new_summary.total_joint_sparc_mean += episode.joint_sparc_mean or 0.0
                new_summary.trajectory_metrics_count += 1

        filtered[exp_key] = new_summary

    return filtered


def format_duration(seconds: float) -> str:
    """Format duration in a readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.1f}s"


def print_summary_table(experiments: dict[str, ExperimentSummary]):
    """Print the summary table."""
    # Check if any experiment has trajectory metrics
    has_traj_metrics = any(s.trajectory_metrics_count > 0 for s in experiments.values())

    print("\n" + "=" * (150 if has_traj_metrics else 120))
    print("EXPERIMENT SUMMARY")
    print("=" * (150 if has_traj_metrics else 120))

    headers = ["Task", "Policy", "Runs", "Success", "Success %", "Score(fail)", "Avg Duration(s)", "Avg Infer Time"]
    col_widths = [25, 10, 5, 7, 9, 11, 14, 12]

    if has_traj_metrics:
        headers.extend(["SPARC", "PathLen(m)", "Speed(m/s)"])
        col_widths.extend([10, 10, 10])

    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(header_line)
    print("-" * len(header_line))

    for exp_key, summary in sorted(experiments.items(), key=lambda x: (x[1].task, x[1].policy)):
        avg_infer = summary.avg_inference_time_s
        avg_infer_str = f"{avg_infer*1000:.1f}ms" if avg_infer is not None else "N/A"

        avg_score_fail = summary.avg_score_fails
        avg_score_str = f"{avg_score_fail:.2f}" if avg_score_fail is not None else "N/A"

        row = [
            summary.task[:col_widths[0]],
            summary.policy[:col_widths[1]],
            str(summary.total_runs),
            str(summary.successes),
            f"{summary.success_pct:.1f}%",
            avg_score_str,
            f"{summary.avg_duration_s:.1f}",
            avg_infer_str,
        ]

        if has_traj_metrics:
            sparc = summary.avg_ee_sparc
            path_len = summary.avg_ee_path_length
            speed = summary.avg_ee_speed_mean
            row.extend([
                f"{sparc:.2f}" if sparc is not None else "N/A",
                f"{path_len:.2f}" if path_len is not None else "N/A",
                f"{speed:.3f}" if speed is not None else "N/A",
            ])

        row_line = "  ".join(r.ljust(w) for r, w in zip(row, col_widths))
        print(row_line)


def wrap_text(text: str, width: int) -> list[str]:
    """Wrap text to specified width, returning list of lines."""
    if not text:
        return [""]

    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        if not current_line:
            current_line = word
        elif len(current_line) + 1 + len(word) <= width:
            current_line += " " + word
        else:
            lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else [""]


def print_detailed_table(experiments: dict[str, ExperimentSummary], verbose: bool = False):
    """Print detailed per-episode table."""
    # Check if any episode has trajectory metrics
    has_traj_metrics = any(
        ep.ee_sparc is not None
        for s in experiments.values()
        for ep in s.episodes
    )

    # Check if any episode has wrong objects
    has_wrong_objects = verbose and any(
        ep.wrong_object_grabbed
        for s in experiments.values()
        for ep in s.episodes
    )

    print("\n" + "=" * (200 if has_traj_metrics else 170))
    print("DETAILED EPISODE RESULTS")
    print("=" * (200 if has_traj_metrics else 170))

    headers = ["Experiment", "Task", "Ep#", "Success", "Score", "Valid?", "Duration(s)"]
    col_widths = [38, 20, 4, 7, 6, 6, 10]

    if has_traj_metrics:
        headers.extend(["SPARC", "PathLen", "Speed"])
        col_widths.extend([9, 8, 8])

    if has_wrong_objects:
        headers.extend(["Wrong Objs", "Instruction", "Notes"])
        col_widths.extend([15, 30, 40])
    else:
        headers.extend(["Instruction", "Notes"])
        col_widths.extend([35, 50])

    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(header_line)
    print("-" * len(header_line))

    # Calculate prefix width (all columns before Notes)
    prefix_width = sum(col_widths[:-1]) + 2 * (len(col_widths) - 1)

    for exp_key, summary in sorted(experiments.items(), key=lambda x: (x[1].task, x[1].policy)):
        for episode in summary.episodes:
            success_str = "Yes" if episode.success is True else ("No" if episode.success is False else "N/A")
            valid_str = "Yes" if episode.valid is True else ("No" if episode.valid is False else "N/A")

            # Score only shown when failed
            if episode.success is False and episode.score is not None:
                score_str = f"{episode.score:.2f}"
            else:
                score_str = "N/A"

            # Find instruction and notes column indices
            col_idx = 7
            if has_traj_metrics:
                col_idx += 3
            if has_wrong_objects:
                wrong_obj_idx = col_idx
                instr_idx = col_idx + 1
                notes_idx = col_idx + 2
            else:
                instr_idx = col_idx
                notes_idx = col_idx + 1

            instr_width = col_widths[instr_idx]
            notes_width = col_widths[notes_idx]

            # Truncate instruction
            instruction = episode.instruction[:instr_width-3] + "..." if len(episode.instruction) > instr_width else episode.instruction

            # Wrap notes across multiple lines
            notes_lines = wrap_text(episode.notes, notes_width)

            row = [
                summary.experiment_dir[:col_widths[0]],
                episode.task[:col_widths[1]],
                str(episode.episode_idx),
                success_str,
                score_str,
                valid_str,
                f"{episode.duration_s:.1f}",
            ]

            if has_traj_metrics:
                row.extend([
                    f"{episode.ee_sparc:.2f}" if episode.ee_sparc is not None else "N/A",
                    f"{episode.ee_path_length:.2f}" if episode.ee_path_length is not None else "N/A",
                    f"{episode.ee_speed_mean:.3f}" if episode.ee_speed_mean is not None else "N/A",
                ])

            if has_wrong_objects:
                # Format wrong objects grabbed
                wrong_objs_str = ", ".join(episode.wrong_object_grabbed) if episode.wrong_object_grabbed else "-"
                wrong_objs_width = col_widths[wrong_obj_idx]
                wrong_objs_display = wrong_objs_str[:wrong_objs_width-3] + "..." if len(wrong_objs_str) > wrong_objs_width else wrong_objs_str
                row.append(wrong_objs_display)

            row.extend([instruction, notes_lines[0]])

            row_line = "  ".join(r.ljust(w) for r, w in zip(row, col_widths))
            print(row_line)

            # Print continuation lines for notes
            for note_line in notes_lines[1:]:
                print(" " * prefix_width + "  " + note_line)


def compute_stddev(values: list) -> Optional[float]:
    """Compute standard deviation of a list of values, ignoring None."""
    filtered = [v for v in values if v is not None]
    if len(filtered) < 2:
        return None
    mean = sum(filtered) / len(filtered)
    variance = sum((x - mean) ** 2 for x in filtered) / (len(filtered) - 1)
    return math.sqrt(variance)


def print_csv_summary(experiments: dict[str, ExperimentSummary]):
    """Print CSV format summary with mean and stddev for each metric."""
    # Check if any experiment has trajectory metrics
    has_traj_metrics = any(s.trajectory_metrics_count > 0 for s in experiments.values())

    # Build header
    header_parts = [
        "Task", "Policy", "Total Runs", "Success", "Success %",
        "Avg Score (fail)",
        "Avg Duration (s)", "Std Duration (s)",
        "Avg Inference Time (s)", "Std Inference Time (s)",
    ]
    if has_traj_metrics:
        header_parts.extend([
            "Avg SPARC", "Std SPARC",
            "Avg Path Length (m)", "Std Path Length (m)",
            "Avg Speed (m/s)", "Std Speed (m/s)",
        ])
    header_parts.append("Wrong Objects Grabbed")
    print(",".join(header_parts))

    for exp_key, summary in sorted(experiments.items(), key=lambda x: (x[1].task, x[1].policy)):
        episodes = summary.episodes

        # Compute duration stats
        durations = [ep.duration_s for ep in episodes]
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        std_duration = compute_stddev(durations)

        # Compute inference time stats
        infer_times = [ep.avg_inference_time_s for ep in episodes if ep.avg_inference_time_s is not None]
        avg_infer = sum(infer_times) / len(infer_times) if infer_times else None
        std_infer = compute_stddev(infer_times)

        # Compute avg score for failed episodes
        avg_score_fail = summary.avg_score_fails
        avg_score_str = f"{avg_score_fail:.4f}" if avg_score_fail is not None else ""

        # Collect all wrong objects grabbed across episodes
        all_wrong_objects = set()
        for ep in episodes:
            all_wrong_objects.update(ep.wrong_object_grabbed)
        wrong_objects_str = "; ".join(sorted(all_wrong_objects)) if all_wrong_objects else ""

        row_parts = [
            summary.task,
            summary.policy,
            str(summary.total_runs),
            str(summary.successes),
            f"{summary.success_pct:.2f}",
            avg_score_str,
            f"{avg_duration:.4f}",
            f"{std_duration:.4f}" if std_duration is not None else "",
            f"{avg_infer:.4f}" if avg_infer is not None else "",
            f"{std_infer:.4f}" if std_infer is not None else "",
        ]

        if has_traj_metrics:
            # Compute trajectory metrics stats
            sparc_vals = [ep.ee_sparc for ep in episodes if ep.ee_sparc is not None]
            path_vals = [ep.ee_path_length for ep in episodes if ep.ee_path_length is not None]
            speed_vals = [ep.ee_speed_mean for ep in episodes if ep.ee_speed_mean is not None]

            avg_sparc = sum(sparc_vals) / len(sparc_vals) if sparc_vals else None
            std_sparc = compute_stddev(sparc_vals)

            avg_path = sum(path_vals) / len(path_vals) if path_vals else None
            std_path = compute_stddev(path_vals)

            avg_speed = sum(speed_vals) / len(speed_vals) if speed_vals else None
            std_speed = compute_stddev(speed_vals)

            row_parts.extend([
                f"{avg_sparc:.4f}" if avg_sparc is not None else "",
                f"{std_sparc:.4f}" if std_sparc is not None else "",
                f"{avg_path:.4f}" if avg_path is not None else "",
                f"{std_path:.4f}" if std_path is not None else "",
                f"{avg_speed:.4f}" if avg_speed is not None else "",
                f"{std_speed:.4f}" if std_speed is not None else "",
            ])

        row_parts.append(wrong_objects_str)
        print(",".join(row_parts))


def aggregate_by_policy(experiments: dict[str, ExperimentSummary]) -> dict[str, ExperimentSummary]:
    """Aggregate all experiments by policy, combining results across tasks."""
    by_policy = {}

    for summary in experiments.values():
        policy = summary.policy
        if policy not in by_policy:
            by_policy[policy] = ExperimentSummary(
                task="(all tasks)",
                policy=policy,
                experiment_dir="",
            )

        agg = by_policy[policy]
        agg.total_runs += summary.total_runs
        agg.successes += summary.successes
        agg.total_score_fails += summary.total_score_fails
        agg.fail_count_with_score += summary.fail_count_with_score
        agg.total_duration_s += summary.total_duration_s
        agg.total_inference_time_s += summary.total_inference_time_s
        agg.inference_time_count += summary.inference_time_count
        agg.episodes.extend(summary.episodes)
        # Aggregate trajectory metrics
        agg.total_ee_sparc += summary.total_ee_sparc
        agg.total_ee_isj += summary.total_ee_isj
        agg.total_ee_path_length += summary.total_ee_path_length
        agg.total_ee_speed_mean += summary.total_ee_speed_mean
        agg.total_joint_sparc_mean += summary.total_joint_sparc_mean
        agg.trajectory_metrics_count += summary.trajectory_metrics_count

    return by_policy


def aggregate_by_task(experiments: dict[str, ExperimentSummary]) -> dict[str, ExperimentSummary]:
    """Aggregate all experiments by task, combining results across policies."""
    by_task = {}

    for summary in experiments.values():
        task = summary.task
        if task not in by_task:
            by_task[task] = ExperimentSummary(
                task=task,
                policy="(all policies)",
                experiment_dir="",
            )

        agg = by_task[task]
        agg.total_runs += summary.total_runs
        agg.successes += summary.successes
        agg.total_score_fails += summary.total_score_fails
        agg.fail_count_with_score += summary.fail_count_with_score
        agg.total_duration_s += summary.total_duration_s
        agg.total_inference_time_s += summary.total_inference_time_s
        agg.inference_time_count += summary.inference_time_count
        agg.episodes.extend(summary.episodes)
        # Aggregate trajectory metrics
        agg.total_ee_sparc += summary.total_ee_sparc
        agg.total_ee_isj += summary.total_ee_isj
        agg.total_ee_path_length += summary.total_ee_path_length
        agg.total_ee_speed_mean += summary.total_ee_speed_mean
        agg.total_joint_sparc_mean += summary.total_joint_sparc_mean
        agg.trajectory_metrics_count += summary.trajectory_metrics_count

    return by_task


def print_csv_by_policy(aggregated: dict[str, ExperimentSummary]):
    """Print CSV format for by-policy aggregation with mean and stddev."""
    # Check if any experiment has trajectory metrics
    has_traj_metrics = any(s.trajectory_metrics_count > 0 for s in aggregated.values())

    # Build header matching the table format plus stddev columns
    header_parts = [
        "Policy", "Tasks", "Runs", "Success", "Success %",
        "Score(fail)",
        "Avg Duration(s)", "Std Duration(s)",
        "Avg Infer Time(ms)", "Std Infer Time(ms)",
    ]
    if has_traj_metrics:
        header_parts.extend([
            "SPARC", "Std SPARC",
            "PathLen(m)", "Std PathLen(m)",
            "Speed(m/s)", "Std Speed(m/s)",
        ])
    header_parts.append("Wrong Objects Grabbed")
    print(",".join(header_parts))

    for key, summary in sorted(aggregated.items()):
        episodes = summary.episodes

        # Count unique tasks
        unique_tasks = len(set(ep.task for ep in episodes))

        # Compute duration stats
        durations = [ep.duration_s for ep in episodes]
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        std_duration = compute_stddev(durations)

        # Compute inference time stats (in ms for display)
        infer_times = [ep.avg_inference_time_s for ep in episodes if ep.avg_inference_time_s is not None]
        avg_infer_ms = (sum(infer_times) / len(infer_times) * 1000) if infer_times else None
        std_infer_ms = (compute_stddev(infer_times) * 1000) if infer_times and compute_stddev(infer_times) is not None else None

        # Compute avg score for failed episodes
        avg_score_fail = summary.avg_score_fails
        avg_score_str = f"{avg_score_fail:.2f}" if avg_score_fail is not None else ""

        # Collect all wrong objects grabbed across episodes
        all_wrong_objects = set()
        for ep in episodes:
            all_wrong_objects.update(ep.wrong_object_grabbed)
        wrong_objects_str = "; ".join(sorted(all_wrong_objects)) if all_wrong_objects else ""

        row_parts = [
            summary.policy,
            str(unique_tasks),
            str(summary.total_runs),
            str(summary.successes),
            f"{summary.success_pct:.1f}",
            avg_score_str,
            f"{avg_duration:.1f}",
            f"{std_duration:.1f}" if std_duration is not None else "",
            f"{avg_infer_ms:.1f}" if avg_infer_ms is not None else "",
            f"{std_infer_ms:.1f}" if std_infer_ms is not None else "",
        ]

        if has_traj_metrics:
            # Compute trajectory metrics stats
            sparc_vals = [ep.ee_sparc for ep in episodes if ep.ee_sparc is not None]
            path_vals = [ep.ee_path_length for ep in episodes if ep.ee_path_length is not None]
            speed_vals = [ep.ee_speed_mean for ep in episodes if ep.ee_speed_mean is not None]

            avg_sparc = sum(sparc_vals) / len(sparc_vals) if sparc_vals else None
            std_sparc = compute_stddev(sparc_vals)

            avg_path = sum(path_vals) / len(path_vals) if path_vals else None
            std_path = compute_stddev(path_vals)

            avg_speed = sum(speed_vals) / len(speed_vals) if speed_vals else None
            std_speed = compute_stddev(speed_vals)

            row_parts.extend([
                f"{avg_sparc:.2f}" if avg_sparc is not None else "",
                f"{std_sparc:.2f}" if std_sparc is not None else "",
                f"{avg_path:.2f}" if avg_path is not None else "",
                f"{std_path:.2f}" if std_path is not None else "",
                f"{avg_speed:.3f}" if avg_speed is not None else "",
                f"{std_speed:.3f}" if std_speed is not None else "",
            ])

        row_parts.append(wrong_objects_str)
        print(",".join(row_parts))


def print_aggregated_table(aggregated: dict[str, ExperimentSummary], group_by: str):
    """Print aggregated summary table."""
    label = "Policy" if group_by == "policy" else "Task"

    # Check if any experiment has trajectory metrics
    has_traj_metrics = any(s.trajectory_metrics_count > 0 for s in aggregated.values())

    print("\n" + "=" * (130 if has_traj_metrics else 100))
    print(f"RESULTS BY {label.upper()}")
    print("=" * (130 if has_traj_metrics else 100))

    if group_by == "policy":
        headers = ["Policy", "Tasks", "Runs", "Success", "Success %", "Score(fail)", "Avg Duration(s)", "Avg Infer Time"]
        col_widths = [15, 8, 5, 7, 9, 11, 14, 12]
    else:
        headers = ["Task", "Policies", "Runs", "Success", "Success %", "Score(fail)", "Avg Duration(s)", "Avg Infer Time"]
        col_widths = [25, 8, 5, 7, 9, 11, 14, 12]

    if has_traj_metrics:
        headers.extend(["SPARC", "PathLen(m)", "Speed(m/s)"])
        col_widths.extend([10, 10, 10])

    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(header_line)
    print("-" * len(header_line))

    for key, summary in sorted(aggregated.items()):
        avg_infer = summary.avg_inference_time_s
        avg_infer_str = f"{avg_infer*1000:.1f}ms" if avg_infer is not None else "N/A"

        avg_score_fail = summary.avg_score_fails
        avg_score_str = f"{avg_score_fail:.2f}" if avg_score_fail is not None else "N/A"

        # Count unique tasks or policies
        if group_by == "policy":
            unique_count = len(set(ep.task for ep in summary.episodes))
            name_col = summary.policy
        else:
            unique_count = len(set(ep.policy for ep in summary.episodes))
            name_col = summary.task

        row = [
            name_col[:col_widths[0]],
            str(unique_count),
            str(summary.total_runs),
            str(summary.successes),
            f"{summary.success_pct:.1f}%",
            avg_score_str,
            f"{summary.avg_duration_s:.1f}",
            avg_infer_str,
        ]

        if has_traj_metrics:
            sparc = summary.avg_ee_sparc
            path_len = summary.avg_ee_path_length
            speed = summary.avg_ee_speed_mean
            row.extend([
                f"{sparc:.2f}" if sparc is not None else "N/A",
                f"{path_len:.2f}" if path_len is not None else "N/A",
                f"{speed:.3f}" if speed is not None else "N/A",
            ])

        row_line = "  ".join(r.ljust(w) for r, w in zip(row, col_widths))
        print(row_line)


def main():
    parser = argparse.ArgumentParser(
        description="Summarize experiment results from output directories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Summarize all experiments
  %(prog)s --task FoodPacking       # Filter by task name (partial match)
  %(prog)s --policy pi0             # Filter by policy
  %(prog)s --csv                    # Output in CSV format
  %(prog)s --detailed-only          # Show only detailed per-episode results
  %(prog)s --valid                  # Only include valid runs in results
  %(prog)s --by-policy              # Aggregate results by policy across all tasks
  %(prog)s --by-task                # Aggregate results by task across all policies
        """
    )
    parser.add_argument(
        '--output-dir', '-o',
        type=Path,
        default=Path(__file__).parent.parent / 'output',
        help='Path to output directory (default: output/ relative to repo root)'
    )
    parser.add_argument(
        '--task', '-t',
        type=str,
        default=None,
        help='Filter by task name (partial match, case-insensitive)'
    )
    parser.add_argument(
        '--policy', '-p',
        type=str,
        default=None,
        help='Filter by policy name (partial match, case-insensitive)'
    )
    parser.add_argument(
        '--csv',
        action='store_true',
        help='Output summary in CSV format'
    )
    parser.add_argument(
        '--summary-only', '-s',
        action='store_true',
        help='Show only summary table (no detailed results)'
    )
    parser.add_argument(
        '--detailed-only', '-d',
        action='store_true',
        help='Show only detailed per-episode results'
    )
    parser.add_argument(
        '--valid', '-v',
        action='store_true',
        help='Only include valid runs in results and averages'
    )
    parser.add_argument(
        '--by-policy',
        action='store_true',
        help='Aggregate results by policy (averaged across all tasks)'
    )
    parser.add_argument(
        '--by-task',
        action='store_true',
        help='Aggregate results by task (averaged across all policies)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show additional details including wrong objects grabbed'
    )

    args = parser.parse_args()

    if not args.output_dir.exists():
        print(f"Error: Output directory not found: {args.output_dir}", file=sys.stderr)
        sys.exit(1)

    experiments = collect_experiments(args.output_dir)

    if not experiments:
        print("No experiments found.", file=sys.stderr)
        sys.exit(0)

    # Apply filters
    if args.task:
        experiments = {k: v for k, v in experiments.items()
                       if args.task.lower() in v.task.lower()}

    if args.policy:
        experiments = {k: v for k, v in experiments.items()
                       if args.policy.lower() in v.policy.lower()}

    if args.valid:
        experiments = filter_valid_episodes(experiments)

    if not experiments:
        print("No experiments match the specified filters.", file=sys.stderr)
        sys.exit(0)

    # Output results
    if args.csv and args.by_policy:
        # CSV output aggregated by policy
        aggregated = aggregate_by_policy(experiments)
        print_csv_by_policy(aggregated)
    elif args.csv:
        print_csv_summary(experiments)
    elif args.by_policy:
        aggregated = aggregate_by_policy(experiments)
        print_aggregated_table(aggregated, "policy")
    elif args.by_task:
        aggregated = aggregate_by_task(experiments)
        print_aggregated_table(aggregated, "task")
    else:
        if not args.detailed_only:
            print_summary_table(experiments)
        if not args.summary_only:
            print_detailed_table(experiments, verbose=args.verbose)


if __name__ == '__main__':
    main()
