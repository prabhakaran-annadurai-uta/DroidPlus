#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
CLI teleop runner — a leader arm streams to the Franka, with recording.

Supported leaders: ``so101`` (LeRobot SO-101) and ``gello`` (7-DoF GELLO).

Multi-episode loop: SPACE to start, ESC to stop, then a keep/discard prompt
(r = discard the run and re-record it under the same episode index) followed
by the post-episode labels (valid/success/score/notes). Records by default;
pass --no-record to disable.

Between episodes: T streams the leader to the robot without recording so you
can reposition the object for the next take (SPACE/ESC to end), O opens the
gripper in place (drops the object, arm stays put), H homes the arm and drops
the object.

With --lift-stop-height, an episode ends automatically once the grasped object
is lifted that far above the table (the --min-z floor).

Usage:
    python scripts/run_teleop_cli.py
    python scripts/run_teleop_cli.py --lift-stop-height 0.10
    python scripts/run_teleop_cli.py --leader gello
    python scripts/run_teleop_cli.py --leader gello --port /dev/ttyUSB0 --gello-config gello_config.json
    python scripts/run_teleop_cli.py --port /dev/ttyACM1 --no-gripper
    python scripts/run_teleop_cli.py --no-record
    python scripts/run_teleop_cli.py --task "pick_banana" --notes "first attempt"
"""
from __future__ import annotations

import argparse
import shutil
import signal
import sys
import time
from dataclasses import replace
from typing import Any, Callable

from droid_plus.analysis.end_effector_pose import compute_and_save_ee_trajectory_single
from droid_plus.constants import FRANKY_SERVICE_URL, RECORD_JPEG_QUALITY
from droid_plus.datagen import (
    DEFAULT_LEADER_PORTS,
    DEFAULT_MIN_EE_Z,
    LEADER_KINDS,
    TeleopSessionConfig,
    build_fk_model,
    connect_leader,
    finalize_teleop_episode_recording,
    init_gripper,
    make_teleop_run_dir,
    run_teleop_episode,
    wait_for_alignment,
)
from droid_plus.eval.episode_runner import EpisodeConfig
from droid_plus.eval.experiment_setup import wait_for_cameras
from droid_plus.logging import EpisodeRecorder
from droid_plus.robot import DroidPlus
from droid_plus.utils import (
    KeyPoller,
    prompt_redo,
    prompt_score,
    prompt_success,
    prompt_text,
    prompt_valid,
)

_CYAN = "\033[96m"
_YELLOW = "\033[93m"
_RESET = "\033[0m"


def _home_and_drop(droid: DroidPlus, *, drop: bool) -> None:
    """Send the arm to its home pose and release the held object (open the gripper).

    Runs entirely between episodes, from the teleop process that owns the gripper
    connection -- do NOT trigger a gripper open from franky_service while teleop is up.
    """
    try:
        droid.go_home()
        print(f"{_CYAN}Home: arm moving to home pose.{_RESET}")
    except Exception as e:
        print(f"{_YELLOW}Home failed: {type(e).__name__}: {e}{_RESET}")
    if drop:
        try:
            droid.gripper.open()  # blocking; we're in dead time between episodes
            print(f"{_CYAN}Home: gripper opened (object released).{_RESET}")
        except Exception as e:
            print(f"{_YELLOW}Gripper open failed: {type(e).__name__}: {e}{_RESET}")


def _open_gripper(droid: DroidPlus) -> None:
    """Open the gripper in place (release the held object) without homing the arm.

    Runs entirely between episodes, from the teleop process that owns the gripper
    connection -- do NOT trigger a gripper open from franky_service while teleop is up.
    """
    try:
        droid.gripper.open()  # blocking; we're in dead time between episodes
        print(f"{_CYAN}Gripper opened (object released).{_RESET}")
    except Exception as e:
        print(f"{_YELLOW}Gripper open failed: {type(e).__name__}: {e}{_RESET}")


def _free_teleop(
    *,
    droid: DroidPlus,
    leader: Any,
    session: TeleopSessionConfig,
    gripper_initialized: bool,
    pin_model: Any,
    pin_data: Any,
    ee_frame: str,
    keys: KeyPoller,
    stop_flag: list[bool],
) -> None:
    """Stream the leader to the robot with no recording — used between episodes
    to reposition the object (or the arm) for the next take.

    SPACE or ESC returns to the episode prompt; Ctrl+C quits the session.
    """
    print(f"{_CYAN}Free teleop (NOT recording) — move the object, then SPACE/ESC to stop.{_RESET}")

    def _should_stop() -> bool:
        if stop_flag[0]:
            return True
        ch = keys.poll_char()
        return ch in (" ", "\x1b")

    # Reuse the episode runner without a recorder; drop the lift auto-stop so
    # raising the arm to reposition doesn't cut it short.
    run_teleop_episode(
        config=EpisodeConfig(),
        session=replace(session, lift_stop_height=0.0),
        droid=droid,
        leader=leader,
        gripper_initialized=gripper_initialized,
        pin_model=pin_model,
        pin_data=pin_data,
        ee_frame=ee_frame,
        recorder=None,
        should_stop=_should_stop,
    )
    print(f"{_CYAN}Free teleop stopped.{_RESET}")


def _make_cli_should_stop(keys: KeyPoller, stop_flag: list[bool]) -> Callable[[], bool]:
    """ESC (during episode) or Ctrl+C (via stop_flag) ends the episode."""
    def should_stop() -> bool:
        if stop_flag[0]:
            return True
        if sys.stdin.isatty():
            ch = keys.poll_char()
            if ch == "\x1b":
                return True
        return False
    return should_stop


def main() -> None:
    parser = argparse.ArgumentParser(description="Teleop a leader arm to the Franka with recording")
    parser.add_argument("--leader", choices=LEADER_KINDS, default="so101",
        help="Leader device (default: so101)")
    parser.add_argument("--port", default=None,
        help="Leader serial port (default: /dev/ttyACM0 for so101, /dev/ttyUSB0 for gello)")
    parser.add_argument("--gello-config", default=None,
        help="Path to a GELLO calibration JSON (see scripts/gello_calibrate.py); "
             "falls back to $GELLO_CONFIG, then built-in Franka GELLO defaults")
    parser.add_argument("--gello-max-speed", type=float, default=None,
        help="GELLO command slew limit (rad/s); <=0 disables rate limiting")
    parser.add_argument("--align-tol", type=float, default=0.25,
        help="Max per-joint leader/robot mismatch (rad) tolerated before an episode starts")
    parser.add_argument("--no-align-check", action="store_true",
        help="Skip the pre-episode leader/robot pose alignment gate")
    parser.add_argument("--franky-service-url", default=FRANKY_SERVICE_URL,
        help="Franky service URL (used for URDF fetch)")
    parser.add_argument("--no-gripper", action="store_true", help="Skip gripper initialization")
    parser.add_argument("--rate-hz", type=float, default=100.0, help="Control loop rate (Hz)")
    parser.add_argument("--min-z", type=float, default=DEFAULT_MIN_EE_Z,
        help=f"Minimum EE Z height (m) — table safety threshold (default: {DEFAULT_MIN_EE_Z})")
    parser.add_argument("--lift-stop-height", type=float, default=0.0,
        help="Auto-stop the episode once the EE lifts this many metres above --min-z "
             "(e.g. 0.10 for 10 cm). 0 disables (default).")
    parser.add_argument("--no-lift-require-grasp", action="store_true",
        help="With --lift-stop-height, trigger on EE height alone rather than "
             "requiring a latched force-grasp.")
    parser.add_argument("--grasp-force", type=int, default=160,
        help="Force the latched grasp holds, in bits (255 ~ 50 N ceiling; "
             "default 160 ~ 31 N). Lower for deformable objects.")
    parser.add_argument("--grasp-speed", type=int, default=128,
        help="Grasp closing speed in bits (255 ~ 0.1 m/s; default 128 ~ 0.05 m/s).")
    parser.add_argument("--grasp-width", type=float, default=0.0,
        help="Grasp to this object width in metres, e.g. 0.045. Recommended: a "
             "grasp(0.0) 'squeeze' often reports failure and releases on a thick "
             "object. 0 = legacy squeeze-shut.")
    parser.add_argument("--grasp-epsilon", type=float, default=0.01,
        help="Success-band half-width (m) around --grasp-width (default 0.01). "
             "Ignored when --grasp-width is 0.")
    parser.add_argument("--no-record", action="store_true", help="Disable data recording")
    parser.add_argument("--record-rate-hz", type=float, default=15.0,
        help="Recording rate (images + state/action captured at this rate)")
    parser.add_argument("--record-jpeg-quality", type=int, default=RECORD_JPEG_QUALITY,
        help=f"JPEG quality for recorded images (default: {RECORD_JPEG_QUALITY})")
    parser.add_argument("--output-dir", default="output", help="Base output directory for recordings")
    parser.add_argument("--task", default="", help="Task name (recorded in meta.json + run dir)")
    parser.add_argument("--notes", default="", help="Free-form notes (recorded in meta.json)")
    parser.add_argument("--dry-run", action="store_true",
        help="Read the leader but do not command the robot or gripper")
    args = parser.parse_args()

    record = not args.no_record
    leader_port = args.port or DEFAULT_LEADER_PORTS[args.leader]

    session = TeleopSessionConfig(
        rate_hz=float(args.rate_hz),
        record_rate_hz=float(args.record_rate_hz),
        record_jpeg_quality=int(args.record_jpeg_quality),
        min_z=float(args.min_z),
        lift_stop_height=float(args.lift_stop_height),
        lift_stop_require_grasp=not args.no_lift_require_grasp,
        grasp_force_bits=int(args.grasp_force),
        grasp_speed_bits=int(args.grasp_speed),
        grasp_width_m=float(args.grasp_width),
        grasp_epsilon_m=float(args.grasp_epsilon),
        dry_run=bool(args.dry_run),
        record=bool(record),
        policy_name=f"teleop_{args.leader}",
    )

    # ── Robot + cameras ──────────────────────────────────────────────────
    print("Initializing robot...")
    droid = DroidPlus()
    wait_for_cameras(droid)

    pin_model, pin_data, ee_frame = build_fk_model(args.franky_service_url)

    # Safety: stop before anything moves.
    try:
        droid.stop()
    except Exception:
        pass

    # ── Gripper, then leader (ordering matters for shared USB hub) ──────
    gripper_initialized = False
    if not args.no_gripper and not args.dry_run:
        gripper_initialized = init_gripper(droid)
    else:
        reason = "dry-run" if args.dry_run else "--no-gripper"
        print(f"Skipping gripper initialization ({reason}).")

    leader = connect_leader(
        args.leader,
        leader_port,
        settle_s=2.0 if gripper_initialized else 0.0,
        gello_config_path=args.gello_config,
        gello_max_joint_speed_rad_s=args.gello_max_speed,
    )

    # ── Run directory ────────────────────────────────────────────────────
    base_run_dir: str | None = None
    if session.record:
        base_run_dir = make_teleop_run_dir(args.task, parent=args.output_dir)
        print(f"Recording to {base_run_dir}")
        record_every_n = max(1, round(session.rate_hz / session.record_rate_hz))
        print(f"Control loop: {session.rate_hz} Hz | Recording every {record_every_n} ticks "
              f"(~{session.rate_hz / record_every_n:.1f} Hz)")

    print(f"Leader: {args.leader} on {leader_port}")
    if session.grasp_width_m > 0.0:
        print(f"Grasp: width {session.grasp_width_m * 1000:.0f} mm "
              f"(+/-{session.grasp_epsilon_m * 1000:.0f} mm), "
              f"{session.grasp_force_bits} bits (~{session.grasp_force_bits / 255 * 50:.0f} N)")
    else:
        print(f"{_YELLOW}Grasp: width 0 (squeeze) — pass --grasp-width <object width, e.g. 0.045> "
              f"for a firm hold. force {session.grasp_force_bits} bits "
              f"(~{session.grasp_force_bits / 255 * 50:.0f} N){_RESET}")
    if session.lift_stop_height > 0.0:
        gate = "grasp + height" if session.lift_stop_require_grasp else "height only"
        print(f"Lift auto-stop: EE > min_z + {session.lift_stop_height:.2f} m "
              f"(z >= {session.min_z + session.lift_stop_height:.3f} m), {gate}")

    # ── Stop flag for SIGINT/SIGTERM ─────────────────────────────────────
    stop_flag: list[bool] = [False]

    def _request_stop(*_sig: Any) -> None:
        stop_flag[0] = True

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    if not sys.stdin.isatty():
        print("stdin is not a TTY; starting immediately and disabling space/escape controls.")

    # ── Episode loop ─────────────────────────────────────────────────────
    episode_idx = 0

    with KeyPoller() as keys:
        while not stop_flag[0]:
            # Wait for SPACE when interactive.
            if sys.stdin.isatty():
                def _print_prompt() -> None:
                    print(f"\n{_CYAN}Press SPACE to start episode {episode_idx}, "
                          f"T to teleop (no recording) and reposition the object, "
                          f"O to open the gripper (drop object, arm stays put), "
                          f"H to home + drop object, ESC/Ctrl+C to quit.{_RESET}")
                _print_prompt()
                while not stop_flag[0]:
                    ch = keys.poll_char()
                    if ch is None:
                        time.sleep(0.05)
                        continue
                    if ch == "\x1b":
                        stop_flag[0] = True
                        break
                    if ch in ("o", "O"):
                        if gripper_initialized and not args.dry_run:
                            _open_gripper(droid)
                        else:
                            reason = "dry-run" if args.dry_run else "gripper not initialized"
                            print(f"{_YELLOW}Open gripper unavailable ({reason}).{_RESET}")
                        _print_prompt()
                        continue
                    if ch in ("h", "H"):
                        _home_and_drop(droid, drop=gripper_initialized and not args.dry_run)
                        _print_prompt()
                        continue
                    if ch in ("t", "T"):
                        if args.dry_run:
                            print(f"{_YELLOW}Free teleop unavailable in --dry-run.{_RESET}")
                        else:
                            _free_teleop(
                                droid=droid,
                                leader=leader,
                                session=session,
                                gripper_initialized=gripper_initialized,
                                pin_model=pin_model,
                                pin_data=pin_data,
                                ee_frame=ee_frame,
                                keys=keys,
                                stop_flag=stop_flag,
                            )
                        _print_prompt()
                        continue
                    if ch == " ":
                        break
                if stop_flag[0]:
                    break

            config = EpisodeConfig(
                task=args.task,
                notes=args.notes,
            )

            should_stop = _make_cli_should_stop(keys, stop_flag)

            if not args.no_align_check and not args.dry_run:
                if not wait_for_alignment(
                    leader, droid, tol_rad=float(args.align_tol), should_stop=should_stop
                ):
                    print(f"{_YELLOW}Skipping episode {episode_idx}: leader never aligned.{_RESET}")
                    if stop_flag[0]:
                        break
                    continue

            recorder: EpisodeRecorder | None = None
            if session.record and base_run_dir is not None:
                recorder = EpisodeRecorder(
                    base_run_dir=base_run_dir,
                    episode_idx=episode_idx,
                    jpeg_quality=session.record_jpeg_quality,
                    cameras=["left", "wrist", "right"],
                )
                print(f"Recording episode {episode_idx} to {recorder.episode_dir}  "
                      f"(rate={session.record_rate_hz} Hz)")

            result = run_teleop_episode(
                config=config,
                session=session,
                droid=droid,
                leader=leader,
                gripper_initialized=gripper_initialized,
                pin_model=pin_model,
                pin_data=pin_data,
                ee_frame=ee_frame,
                recorder=recorder,
                should_stop=should_stop,
            )

            duration = result.t_end - result.t_start
            reason = (
                "lift auto-stop" if result.stopped_by_lift
                else "step limit" if result.stopped_by_limit
                else "stopped by user"
            )
            print(f"\n{_YELLOW}Episode {episode_idx} ended ({reason}): {result.seq} recorded steps, "
                  f"{duration:.1f}s{_RESET}")
            if result.stopped_by_lift:
                print(f"{_CYAN}Recording stopped — object lifted. "
                      f"Place it back on the table before the next episode.{_RESET}")

            # Offer to discard a bad run and re-record it under the same index.
            if sys.stdin.isatty() and prompt_redo(keys):
                if result.recorder is not None:
                    ep_dir = result.recorder.episode_dir
                    result.recorder.close()
                    try:
                        shutil.rmtree(ep_dir)
                        print(f"{_YELLOW}Discarded {ep_dir} — re-recording episode {episode_idx}.{_RESET}")
                    except Exception as e:
                        print(f"{_YELLOW}Failed to remove {ep_dir}: {e}{_RESET}")
                else:
                    print(f"{_YELLOW}Discarded — re-running episode {episode_idx}.{_RESET}")
                continue  # episode_idx not incremented (press H to home + drop)

            # Post-episode labels.
            episode_valid: bool | None = None
            episode_success: bool | None = None
            episode_score: float | None = None
            episode_notes: str | None = None
            if sys.stdin.isatty():
                episode_valid = prompt_valid(keys)
                episode_success = prompt_success(keys)
                episode_score = prompt_score(keys)
                episode_notes = prompt_text(keys, "episode_notes?")

            if session.record and result.recorder is not None:
                finalize_teleop_episode_recording(
                    result=result,
                    config=config,
                    session=session,
                    episode_valid=episode_valid,
                    episode_success=episode_success,
                    episode_score=episode_score,
                    episode_notes=episode_notes,
                )
                print(f"Recording saved to {result.recorder.episode_dir}")

                try:
                    compute_and_save_ee_trajectory_single(
                        episode_dir=result.recorder.episode_dir,
                        overwrite=True,
                        verbose=True,
                    )
                except Exception as e:
                    print(f"Warning: Failed to compute EE trajectory: {e}")

            episode_idx += 1

    # ── Cleanup ──────────────────────────────────────────────────────────
    leader.close()
    if gripper_initialized:
        try:
            droid.gripper.shutdown_async()
        except Exception as e:
            print(f"Gripper shutdown error: {e}")


if __name__ == "__main__":
    main()
