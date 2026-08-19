#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Plot end-effector trajectories from multiple episodes on a single plot.

Usage:
    # Plot all episodes for a specific task and policy:
    python scripts/plot_ee_trajectories.py --task BananaAndBlockInBowl --policy pi05

    # Plot specific experiment run:
    python scripts/plot_ee_trajectories.py output/BananaAndBlockInBowl_pi05_20260114_140144

    # Save plot to file:
    python scripts/plot_ee_trajectories.py --task BananaAndBlockInBowl --policy pi05 --out trajectory.png

    # 3D trajectory plot:
    python scripts/plot_ee_trajectories.py --task BananaAndBlockInBowl --policy pi05 --3d
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

import numpy as np

# Add parent directory to path for imports when running as script
sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_experiment_dir_name(dir_name: str) -> Optional[tuple[str, str, str]]:
    """
    Parse experiment directory name into (TaskName, policy, date).
    Expected format: <TaskName>_<policy>_<YYYYMMDD_HHMMSS>
    """
    pattern = r'^(.+?)_([a-zA-Z0-9_]+?)_(\d{8}_\d{6})$'
    match = re.match(pattern, dir_name)
    if match:
        return match.group(1), match.group(2), match.group(3)
    return None


def find_experiment_dirs(
    output_dir: Path,
    task_filter: Optional[str] = None,
    policy_filter: Optional[str] = None,
) -> list[Path]:
    """Find experiment directories matching the given filters."""
    exp_dirs = []

    for exp_dir in sorted(output_dir.iterdir()):
        if not exp_dir.is_dir():
            continue

        parsed = parse_experiment_dir_name(exp_dir.name)
        if parsed is None:
            continue

        task_name, policy, _date = parsed

        # Apply filters (case-insensitive partial match)
        if task_filter and task_filter.lower() not in task_name.lower():
            continue
        if policy_filter and policy_filter.lower() not in policy.lower():
            continue

        exp_dirs.append(exp_dir)

    return exp_dirs


def find_episode_dirs(run_dir: Path) -> list[Path]:
    """Find all episode directories in a run directory."""
    if (run_dir / "steps.jsonl").exists():
        return [run_dir]
    eps = sorted([p for p in run_dir.glob("episode_*") if p.is_dir()])
    return [p for p in eps if (p / "steps.jsonl").exists()]


def load_ee_trajectory(episode_dir: Path) -> Optional[dict]:
    """Load ee_trajectory.json from an episode directory."""
    traj_path = episode_dir / "ee_trajectory.json"
    if not traj_path.exists():
        return None
    try:
        with open(traj_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return None


def load_episode_meta(episode_dir: Path) -> Optional[dict]:
    """Load meta.json from an episode directory."""
    meta_path = episode_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        with open(meta_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return None


def collect_trajectories(
    output_dir: Path,
    task_filter: Optional[str] = None,
    policy_filter: Optional[str] = None,
    run_path: Optional[Path] = None,
    valid_only: bool = False,
) -> list[dict]:
    """
    Collect all trajectories matching the filters.

    Returns list of dicts with keys:
        - trajectory: the ee_trajectory data
        - episode_dir: Path to episode directory
        - experiment: experiment directory name
        - episode_idx: episode index
        - meta: episode metadata (if available)
    """
    trajectories = []

    if run_path is not None:
        # Process specific run path
        exp_dirs = [run_path] if run_path.is_dir() else []
    else:
        exp_dirs = find_experiment_dirs(output_dir, task_filter, policy_filter)

    for exp_dir in exp_dirs:
        episode_dirs = find_episode_dirs(exp_dir)

        for ep_dir in episode_dirs:
            # Load metadata
            meta = load_episode_meta(ep_dir)

            # Filter by valid if requested
            if valid_only and (meta is None or meta.get('valid') is not True):
                continue

            # Load trajectory
            traj = load_ee_trajectory(ep_dir)
            if traj is None:
                continue

            # Extract episode index from directory name
            ep_match = re.match(r'episode_(\d+)', ep_dir.name)
            episode_idx = int(ep_match.group(1)) if ep_match else 0

            trajectories.append({
                'trajectory': traj,
                'episode_dir': ep_dir,
                'experiment': exp_dir.name,
                'episode_idx': episode_idx,
                'meta': meta,
            })

    return trajectories


def plot_trajectories_2d(
    trajectories: list[dict],
    title: str = "",
    show: bool = True,
    out_path: Optional[Path] = None,
    color_by: str = "episode",
) -> None:
    """
    Plot multiple end-effector trajectories on 2D subplots (position + orientation).

    Args:
        trajectories: List of trajectory dicts from collect_trajectories
        title: Plot title
        show: Whether to display the plot interactively
        out_path: Path to save the plot image
        color_by: How to color trajectories - "episode", "experiment", or "success"
    """
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    if not trajectories:
        print("No trajectories to plot.")
        return

    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True, constrained_layout=True)

    # Color schemes
    cmap = plt.cm.tab10
    n_colors = 10

    # Determine color mapping
    if color_by == "experiment":
        unique_exps = sorted(set(t['experiment'] for t in trajectories))
        color_map = {exp: cmap(i % n_colors) for i, exp in enumerate(unique_exps)}

        def get_color(t):
            return color_map[t['experiment']]

        legend_items = [(exp, color_map[exp]) for exp in unique_exps]
    elif color_by == "success":
        def get_color(t):
            meta = t.get('meta') or {}
            success = meta.get('success')
            if success is True:
                return 'green'
            elif success is False:
                return 'red'
            return 'gray'
        legend_items = [("Success", 'green'), ("Failure", 'red'), ("Unknown", 'gray')]
    else:  # episode
        def get_color(t):
            return cmap(t['episode_idx'] % n_colors)

        legend_items = None

    ax_pos = axes[0]
    ax_rpy = axes[1]

    for traj_data in trajectories:
        traj = traj_data['trajectory']
        t = np.array(traj["t_rel_s"])
        pos = np.array(traj["position"])
        rpy = np.array(traj["rpy"])
        color = get_color(traj_data)
        alpha = 0.7
        lw = 1.2

        # Position plot
        ax_pos.plot(t, pos[:, 0], color=color, alpha=alpha, lw=lw, linestyle='-')
        ax_pos.plot(t, pos[:, 1], color=color, alpha=alpha, lw=lw, linestyle='--')
        ax_pos.plot(t, pos[:, 2], color=color, alpha=alpha, lw=lw, linestyle=':')

        # RPY plot
        rad2deg = 180.0 / np.pi
        ax_rpy.plot(t, rpy[:, 0] * rad2deg, color=color, alpha=alpha, lw=lw, linestyle='-')
        ax_rpy.plot(t, rpy[:, 1] * rad2deg, color=color, alpha=alpha, lw=lw, linestyle='--')
        ax_rpy.plot(t, rpy[:, 2] * rad2deg, color=color, alpha=alpha, lw=lw, linestyle=':')

    # Position plot formatting
    ax_pos.set_ylabel("Position (m)")
    ax_pos.set_title(title or f"End-Effector Trajectories ({len(trajectories)} episodes)")
    ax_pos.grid(True, which="major", alpha=0.25)
    ax_pos.minorticks_on()
    ax_pos.grid(True, which="minor", alpha=0.1, linestyle=":")

    # Add x/y/z legend for line styles
    style_legend = [
        Line2D([0], [0], color='black', linestyle='-', label='x'),
        Line2D([0], [0], color='black', linestyle='--', label='y'),
        Line2D([0], [0], color='black', linestyle=':', label='z'),
    ]
    ax_pos.legend(handles=style_legend, loc='upper right')

    # RPY plot formatting
    ax_rpy.set_ylabel("Orientation (deg)")
    ax_rpy.set_xlabel("Time since episode start (s)")
    ax_rpy.grid(True, which="major", alpha=0.25)
    ax_rpy.minorticks_on()
    ax_rpy.grid(True, which="minor", alpha=0.1, linestyle=":")

    # Add roll/pitch/yaw legend for line styles
    style_legend_rpy = [
        Line2D([0], [0], color='black', linestyle='-', label='roll'),
        Line2D([0], [0], color='black', linestyle='--', label='pitch'),
        Line2D([0], [0], color='black', linestyle=':', label='yaw'),
    ]
    ax_rpy.legend(handles=style_legend_rpy, loc='upper right')

    # Add color legend if applicable
    if legend_items:
        color_handles = [Line2D([0], [0], color=c, lw=2, label=lbl) for lbl, c in legend_items]
        fig.legend(handles=color_handles, loc='upper left', bbox_to_anchor=(0.01, 0.99))

    if out_path is not None:
        fig.savefig(out_path, dpi=150)
        print(f"Saved plot to {out_path}")

    if show:
        plt.show()
    else:
        plt.close(fig)


def interpolate_trajectories(trajectories: list[dict], n_points: int = 200) -> tuple[np.ndarray, np.ndarray]:
    """
    Interpolate all trajectories to the same number of points (normalized time).

    Args:
        trajectories: List of trajectory dicts
        n_points: Number of points to interpolate to

    Returns:
        (mean_pos, std_pos) each of shape (n_points, 3)
    """
    from scipy import interpolate

    all_interpolated = []

    for traj_data in trajectories:
        traj = traj_data['trajectory']
        pos = np.array(traj["position"])
        t_rel = np.array(traj["t_rel_s"])

        # Normalize time to [0, 1]
        if t_rel[-1] > t_rel[0]:
            t_norm = (t_rel - t_rel[0]) / (t_rel[-1] - t_rel[0])
        else:
            t_norm = np.linspace(0, 1, len(t_rel))

        # Interpolate to common time points
        t_common = np.linspace(0, 1, n_points)
        pos_interp = np.zeros((n_points, 3))

        for dim in range(3):
            f = interpolate.interp1d(t_norm, pos[:, dim], kind='linear', fill_value='extrapolate')
            pos_interp[:, dim] = f(t_common)

        all_interpolated.append(pos_interp)

    all_interpolated = np.array(all_interpolated)  # (n_traj, n_points, 3)

    mean_pos = np.mean(all_interpolated, axis=0)
    std_pos = np.std(all_interpolated, axis=0)

    return mean_pos, std_pos


def plot_trajectories_3d_average(
    trajectories: list[dict],
    title: str = "",
    show: bool = True,
    out_path: Optional[Path] = None,
    n_std: float = 1.0,
) -> None:
    """
    Plot average end-effector trajectory with individual trajectories faded in background.

    Args:
        trajectories: List of trajectory dicts from collect_trajectories
        title: Plot title
        show: Whether to display the plot interactively
        out_path: Path to save the plot image
        n_std: Not used in this visualization, kept for API compatibility
    """
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

    if not trajectories:
        print("No trajectories to plot.")
        return

    if len(trajectories) < 2:
        print("Need at least 2 trajectories to compute average.")
        return

    # Interpolate all trajectories to common time points
    mean_pos, std_pos = interpolate_trajectories(trajectories)

    fig = plt.figure(figsize=(12, 10))
    ax = fig.add_subplot(111, projection='3d')

    # Plot individual trajectories as faint gray lines
    for traj_data in trajectories:
        traj = traj_data['trajectory']
        pos = np.array(traj["position"])
        ax.plot(pos[:, 0], pos[:, 1], pos[:, 2],
                color='gray', alpha=0.25, lw=0.8)

    # Plot mean trajectory bold on top
    ax.plot(mean_pos[:, 0], mean_pos[:, 1], mean_pos[:, 2],
            color='blue', lw=3, label='Mean trajectory')

    # Mark start and end of mean trajectory
    ax.scatter(mean_pos[0, 0], mean_pos[0, 1], mean_pos[0, 2],
               color='green', s=120, marker='o', label='Start', zorder=10)
    ax.scatter(mean_pos[-1, 0], mean_pos[-1, 1], mean_pos[-1, 2],
               color='red', s=120, marker='X', label='End', zorder=10)

    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_zlabel("Z (m)")
    ax.set_title(title or f"Average EE Trajectory ({len(trajectories)} episodes)")
    ax.legend(loc='upper right')

    # 1m total axis length centered around data center
    all_pos = np.concatenate([np.array(t['trajectory']['position']) for t in trajectories])
    mid_x = (all_pos[:, 0].max() + all_pos[:, 0].min()) / 2.0
    mid_y = (all_pos[:, 1].max() + all_pos[:, 1].min()) / 2.0
    mid_z = (all_pos[:, 2].max() + all_pos[:, 2].min()) / 2.0
    half_range = 0.5
    ax.set_xlim(mid_x - half_range, mid_x + half_range)
    ax.set_ylim(mid_y - half_range, mid_y + half_range)
    ax.set_zlim(mid_z - half_range, mid_z + half_range)

    if out_path is not None:
        fig.savefig(out_path, dpi=150)
        print(f"Saved plot to {out_path}")

    if show:
        plt.show()
    else:
        plt.close(fig)


def plot_trajectories_3d(
    trajectories: list[dict],
    title: str = "",
    show: bool = True,
    out_path: Optional[Path] = None,
    color_by: str = "episode",
) -> None:
    """
    Plot multiple end-effector trajectories in 3D space.

    Args:
        trajectories: List of trajectory dicts from collect_trajectories
        title: Plot title
        show: Whether to display the plot interactively
        out_path: Path to save the plot image
        color_by: How to color trajectories - "episode", "experiment", or "success"
    """
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

    if not trajectories:
        print("No trajectories to plot.")
        return

    fig = plt.figure(figsize=(12, 10))
    ax = fig.add_subplot(111, projection='3d')

    # Color schemes
    cmap = plt.cm.tab10
    n_colors = 10

    # Determine color mapping
    if color_by == "experiment":
        unique_exps = sorted(set(t['experiment'] for t in trajectories))
        color_map = {exp: cmap(i % n_colors) for i, exp in enumerate(unique_exps)}

        def get_color(t):
            return color_map[t['experiment']]

    elif color_by == "success":
        def get_color(t):
            meta = t.get('meta') or {}
            success = meta.get('success')
            if success is True:
                return 'green'
            elif success is False:
                return 'red'
            return 'gray'
    else:  # episode
        def get_color(t):
            return cmap(t['episode_idx'] % n_colors)

    for traj_data in trajectories:
        traj = traj_data['trajectory']
        pos = np.array(traj["position"])
        color = get_color(traj_data)
        alpha = 0.7
        lw = 1.5

        label = f"ep{traj_data['episode_idx']:03d}"

        ax.plot(pos[:, 0], pos[:, 1], pos[:, 2], color=color, alpha=alpha, lw=lw, label=label)

        # Mark start and end points
        ax.scatter(pos[0, 0], pos[0, 1], pos[0, 2], color=color, s=50, marker='o', alpha=0.8)
        ax.scatter(pos[-1, 0], pos[-1, 1], pos[-1, 2], color=color, s=50, marker='x', alpha=0.8)

    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_zlabel("Z (m)")
    ax.set_title(title or f"End-Effector Trajectories 3D ({len(trajectories)} episodes)")

    # 1m total axis length centered around data center
    all_pos = np.concatenate([np.array(t['trajectory']['position']) for t in trajectories])
    mid_x = (all_pos[:, 0].max() + all_pos[:, 0].min()) / 2.0
    mid_y = (all_pos[:, 1].max() + all_pos[:, 1].min()) / 2.0
    mid_z = (all_pos[:, 2].max() + all_pos[:, 2].min()) / 2.0
    half_range = 0.5  # 1m total, so ±0.5m from center
    ax.set_xlim(mid_x - half_range, mid_x + half_range)
    ax.set_ylim(mid_y - half_range, mid_y + half_range)
    ax.set_zlim(mid_z - half_range, mid_z + half_range)

    if out_path is not None:
        fig.savefig(out_path, dpi=150)
        print(f"Saved plot to {out_path}")

    if show:
        plt.show()
    else:
        plt.close(fig)


def plot_trajectories_xy(
    trajectories: list[dict],
    title: str = "",
    show: bool = True,
    out_path: Optional[Path] = None,
    color_by: str = "episode",
) -> None:
    """
    Plot multiple end-effector trajectories as XY top-down view.

    Args:
        trajectories: List of trajectory dicts from collect_trajectories
        title: Plot title
        show: Whether to display the plot interactively
        out_path: Path to save the plot image
        color_by: How to color trajectories - "episode", "experiment", or "success"
    """
    import matplotlib.pyplot as plt

    if not trajectories:
        print("No trajectories to plot.")
        return

    fig, ax = plt.subplots(figsize=(10, 10), constrained_layout=True)

    # Color schemes
    cmap = plt.cm.tab10
    n_colors = 10

    # Determine color mapping
    if color_by == "experiment":
        unique_exps = sorted(set(t['experiment'] for t in trajectories))
        color_map = {exp: cmap(i % n_colors) for i, exp in enumerate(unique_exps)}

        def get_color(t):
            return color_map[t['experiment']]

    elif color_by == "success":
        def get_color(t):
            meta = t.get('meta') or {}
            success = meta.get('success')
            if success is True:
                return 'green'
            elif success is False:
                return 'red'
            return 'gray'
    else:  # episode
        def get_color(t):
            return cmap(t['episode_idx'] % n_colors)

    for traj_data in trajectories:
        traj = traj_data['trajectory']
        pos = np.array(traj["position"])
        color = get_color(traj_data)
        alpha = 0.7
        lw = 1.5

        ax.plot(pos[:, 0], pos[:, 1], color=color, alpha=alpha, lw=lw)

        # Mark start and end points
        ax.scatter(pos[0, 0], pos[0, 1], color=color, s=80, marker='o', alpha=0.8, zorder=5)
        ax.scatter(pos[-1, 0], pos[-1, 1], color=color, s=80, marker='x', alpha=0.8, zorder=5)

    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_title(title or f"End-Effector Trajectories XY ({len(trajectories)} episodes)")
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.3)

    if out_path is not None:
        fig.savefig(out_path, dpi=150)
        print(f"Saved plot to {out_path}")

    if show:
        plt.show()
    else:
        plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Plot end-effector trajectories from multiple episodes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to a specific run folder (optional if using --task/--policy filters)",
    )
    p.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=Path(__file__).parent.parent / "output",
        help="Path to output directory (default: output/)",
    )
    p.add_argument(
        "--task", "-t",
        type=str,
        default=None,
        help="Filter by task name (partial match, case-insensitive)",
    )
    p.add_argument(
        "--policy", "-p",
        type=str,
        default=None,
        help="Filter by policy name (partial match, case-insensitive)",
    )
    p.add_argument(
        "--valid",
        action="store_true",
        help="Only include valid episodes",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path for plot image (e.g., trajectory.png)",
    )
    p.add_argument(
        "--no-show",
        action="store_true",
        help="Don't open interactive plot window",
    )
    p.add_argument(
        "--3d",
        dest="plot_3d",
        action="store_true",
        help="Plot trajectories in 3D space",
    )
    p.add_argument(
        "--xy",
        action="store_true",
        help="Plot trajectories as XY top-down view",
    )
    p.add_argument(
        "--color-by",
        choices=["episode", "experiment", "success"],
        default="episode",
        help="How to color trajectories (default: episode)",
    )
    p.add_argument(
        "--title",
        type=str,
        default=None,
        help="Custom plot title",
    )
    p.add_argument(
        "--average",
        action="store_true",
        help="Plot average trajectory with variance tube instead of individual trajectories",
    )
    p.add_argument(
        "--n-std",
        type=float,
        default=1.0,
        help="Number of standard deviations for variance tube (default: 1.0)",
    )

    args = p.parse_args()

    # Determine run path
    run_path = None
    if args.path:
        run_path = Path(args.path).resolve()
        if not run_path.exists():
            print(f"Error: Path not found: {run_path}", file=sys.stderr)
            sys.exit(1)

    # Check filters
    if run_path is None and args.task is None and args.policy is None:
        print("Error: Must specify either a path or --task/--policy filters", file=sys.stderr)
        sys.exit(1)

    # Collect trajectories
    trajectories = collect_trajectories(
        output_dir=args.output_dir,
        task_filter=args.task,
        policy_filter=args.policy,
        run_path=run_path,
        valid_only=args.valid,
    )

    if not trajectories:
        print("No trajectories found matching the specified filters.")
        print("Have you generated ee_trajectory.json files? Run:")
        print("  python scripts/regenerate_ee_trajectories.py output/")
        sys.exit(1)

    print(f"Found {len(trajectories)} episode(s) with EE trajectories")

    # Build title
    if args.title:
        title = args.title
    else:
        parts = []
        if args.task:
            parts.append(f"task={args.task}")
        if args.policy:
            parts.append(f"policy={args.policy}")
        if run_path:
            parts.append(run_path.name)
        title = ", ".join(parts) if parts else ""

    # Plot
    show = not args.no_show
    if args.average:
        # Average trajectory with variance tube (3D only for now)
        plot_trajectories_3d_average(trajectories, title=title, show=show, out_path=args.out, n_std=args.n_std)
    elif args.plot_3d:
        plot_trajectories_3d(trajectories, title=title, show=show, out_path=args.out, color_by=args.color_by)
    elif args.xy:
        plot_trajectories_xy(trajectories, title=title, show=show, out_path=args.out, color_by=args.color_by)
    else:
        plot_trajectories_2d(trajectories, title=title, show=show, out_path=args.out, color_by=args.color_by)


if __name__ == "__main__":
    main()


