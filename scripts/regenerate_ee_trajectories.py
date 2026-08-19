#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Regenerate end-effector trajectory files for existing experiment runs.

This script computes EE trajectories using forward kinematics from recorded
joint positions and saves them as ee_trajectory.json in each episode folder.

Usage:
    # Process a specific run folder:
    python scripts/regenerate_ee_trajectories.py output/BananaAndBlockInBowl_pi0_20260114_160542

    # Process all runs in output/:
    python scripts/regenerate_ee_trajectories.py output/

    # Force recompute even if ee_trajectory.json exists:
    python scripts/regenerate_ee_trajectories.py output/ --overwrite

    # Use action (commanded) positions instead of state:
    python scripts/regenerate_ee_trajectories.py output/ --use-action
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Add parent directory to path for imports when running as script
sys.path.insert(0, str(Path(__file__).parent.parent))

from droid_plus.analysis.end_effector_pose import (
    _find_episode_dirs,
    compute_and_save_ee_trajectories,
)
from droid_plus.constants import FRANKY_SERVICE_URL


def find_run_dirs(base_path: Path) -> list[Path]:
    """
    Find all run directories under a base path.

    A run directory is one that contains episode_*/ subdirectories with steps.jsonl,
    or directly contains steps.jsonl (single episode run).
    """
    base_path = base_path.resolve()

    # If this path directly contains episodes, it's a run directory
    if _find_episode_dirs(base_path):
        return [base_path]

    # Otherwise, look for subdirectories that are run directories
    run_dirs = []
    for child in sorted(base_path.iterdir()):
        if child.is_dir():
            if _find_episode_dirs(child):
                run_dirs.append(child)

    return run_dirs


def main() -> None:
    p = argparse.ArgumentParser(
        description="Regenerate end-effector trajectory files for experiment runs."
    )
    p.add_argument(
        "path",
        nargs="?",
        default="output",
        help="Path to a run folder or parent directory containing run folders (default: output/)",
    )
    p.add_argument(
        "--service-url",
        default=FRANKY_SERVICE_URL,
        help="franky_service URL for fetching URDF",
    )
    p.add_argument(
        "--use-action",
        action="store_true",
        help="Use action (commanded) positions instead of state",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Recompute even if ee_trajectory.json already exists",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-episode progress messages",
    )
    args = p.parse_args()

    base_path = Path(os.path.expanduser(args.path)).resolve()
    if not base_path.exists():
        print(f"Error: Path not found: {base_path}")
        sys.exit(1)

    # Find all run directories
    run_dirs = find_run_dirs(base_path)
    if not run_dirs:
        print(f"No run directories with episodes found under {base_path}")
        sys.exit(0)

    print(f"Found {len(run_dirs)} run(s) to process:\n")
    for rd in run_dirs:
        print(f"  {rd.name}")
    print()

    total_saved = 0
    total_errors = 0

    for run_dir in run_dirs:
        print(f"Processing: {run_dir.name}")

        try:
            saved_files = compute_and_save_ee_trajectories(
                run_dir=run_dir,
                service_url=args.service_url,
                use_action=args.use_action,
                overwrite=args.overwrite,
                verbose=not args.quiet,
            )
            total_saved += len(saved_files)
        except Exception as e:
            print(f"  ERROR: {e}")
            total_errors += 1

        print()

    print("=" * 60)
    print(f"Summary: {total_saved} trajectories saved, {total_errors} errors")


if __name__ == "__main__":
    main()


