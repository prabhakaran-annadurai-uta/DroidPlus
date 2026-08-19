# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
CLI entry point for ``droid_plus.logging.lerobot_export``.

Exposed as the ``export-lerobot`` console script (see ``pyproject.toml``).

Examples:
    export-lerobot output/BananaInBowl_pi0_20260118_123456
    export-lerobot output/run --out-dir output/lerobot/run --overwrite
    export-lerobot output/run --push hugo/banana_in_bowl --private
"""
from __future__ import annotations

import argparse
from pathlib import Path

from droid_plus.logging.lerobot_export import (
    DEFAULT_CRF,
    DEFAULT_PIX_FMT,
    DEFAULT_ROBOT_TYPE,
    DEFAULT_VCODEC,
    ExportConfig,
    LeRobotExporter,
    push_to_hub,
)


def _default_out_dir(run_dir: Path) -> Path:
    return run_dir.parent / "lerobot" / run_dir.name


def main() -> None:
    p = argparse.ArgumentParser(
        prog="export-lerobot",
        description="Export a franky_service run directory to LeRobot v2.1.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "run_dir",
        type=Path,
        help="Path to the run directory (containing episode_NNN/ folders).",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Destination dataset directory (default: <run_dir>/../lerobot/<run_name>).",
    )
    p.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Override fps; default reads control.record_rate_hz, then control.rate_hz.",
    )
    p.add_argument(
        "--robot-type",
        type=str,
        default=DEFAULT_ROBOT_TYPE,
        help="Robot type string in info.json.",
    )
    p.add_argument("--vcodec", type=str, default=DEFAULT_VCODEC, help="ffmpeg video codec.")
    p.add_argument("--pix-fmt", type=str, default=DEFAULT_PIX_FMT, help="ffmpeg pixel format.")
    p.add_argument("--crf", type=int, default=DEFAULT_CRF, help="x264 CRF (lower = higher quality).")
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace --out-dir if it already exists.",
    )
    p.add_argument(
        "--push",
        type=str,
        default=None,
        metavar="REPO_ID",
        help="After export, push to the Hugging Face Hub at <user>/<dataset> (requires lerobot installed).",
    )
    p.add_argument(
        "--private",
        action="store_true",
        help="When pushing to the Hub, create a private repo.",
    )
    args = p.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.exists():
        p.error(f"run_dir does not exist: {run_dir}")

    out_dir = (args.out_dir or _default_out_dir(run_dir)).expanduser().resolve()

    cfg = ExportConfig(
        run_dir=run_dir,
        out_dir=out_dir,
        fps=args.fps,
        robot_type=args.robot_type,
        vcodec=args.vcodec,
        pix_fmt=args.pix_fmt,
        crf=args.crf,
        overwrite=args.overwrite,
    )

    print(f"[export_lerobot] {run_dir}")
    print(f"[export_lerobot]   -> {out_dir}")
    out = LeRobotExporter(cfg).export()
    print(f"[export_lerobot] done: {out}")

    if args.push:
        print(f"[export_lerobot] pushing to Hub: {args.push} (private={args.private})")
        push_to_hub(out, repo_id=args.push, private=args.private)
        print("[export_lerobot] push complete")


if __name__ == "__main__":
    main()
