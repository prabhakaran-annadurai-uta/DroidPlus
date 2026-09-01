#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
GELLO calibration — determine assembly offsets and gripper range.

Procedure:
  1. Hold/park the GELLO arm in the calibration pose (the same pose the Franka
     reaches at joint angles ``0, 0, 0, -pi/2, 0, pi/2, 0``) and leave the
     gripper trigger fully released.
  2. Run this script. It reads the raw Dynamixel registers once, snaps the
     pose difference to the nearest 90 degrees per joint, and derives the
     gripper's closed position from its open rest position.
  3. Save the printed config and point teleop at it:
         python scripts/gello_calibrate.py --out gello_config.json
         python scripts/run_teleop_cli.py --leader gello --gello-config gello_config.json

Verify with --check, which streams the resulting joint angles so you can
confirm every joint moves in the expected direction and magnitude.

Usage:
    python scripts/gello_calibrate.py
    python scripts/gello_calibrate.py --port /dev/ttyUSB0 --out gello_config.json
    python scripts/gello_calibrate.py --check --gello-config gello_config.json
"""
from __future__ import annotations

import argparse
import time
from dataclasses import replace

import numpy as np

from droid_plus.datagen.dynamixel import DEFAULT_BAUDRATE, DynamixelBus
from droid_plus.datagen.gello import (
    DEFAULT_GELLO_PORT,
    GELLO_CALIBRATION_POSE,
    GRIPPER_OPEN_TO_CLOSED_RAD,
    GelloConfig,
    GelloLeader,
    load_gello_config,
    normalize_joint_positions,
)

_CYAN = "\033[96m"
_RESET = "\033[0m"


def determine_offsets(
    arm_raw: np.ndarray, start_joints: np.ndarray, joint_signs: np.ndarray
) -> np.ndarray:
    """Snap the leader/pose mismatch to the nearest multiple of pi/2, in [0, 2pi)."""
    normalized = normalize_joint_positions(arm_raw, np.zeros_like(arm_raw), joint_signs)
    offsets = np.round((normalized - start_joints) / (np.pi / 2)) * (np.pi / 2)
    return np.mod(offsets, 2 * np.pi)


def calibrate(args: argparse.Namespace) -> GelloConfig:
    base = GelloConfig(
        port=args.port,
        baudrate=args.baudrate,
        gripper=not args.no_gripper,
        joint_signs=tuple(args.joint_signs),
    )
    signs = np.array(base.joint_signs, dtype=float)
    start = np.array(args.start_joints, dtype=float)

    bus = DynamixelBus(base.servo_ids, port=base.port, baudrate=base.baudrate)
    try:
        bus.set_torque(False)
        time.sleep(0.2)  # let a couple of polls land before sampling
        raw = bus.read_positions()
    finally:
        bus.close()

    offsets = determine_offsets(raw[: base.num_arm_joints], start, signs)

    gripper_range = base.gripper_range_rad
    if base.gripper:
        gripper_open = float(raw[-1])
        gripper_range = (gripper_open + GRIPPER_OPEN_TO_CLOSED_RAD, gripper_open)

    config = replace(
        base,
        joint_offsets=tuple(round(float(o), 3) for o in offsets),
        gripper_range_rad=(round(gripper_range[0], 3), round(gripper_range[1], 3)),
    )

    print(f"\n{_CYAN}GELLO calibration{_RESET}")
    print(f"  raw registers    : {[round(float(r), 3) for r in raw]}")
    print(f"  joint_signs      : {list(config.joint_signs)}")
    print(f"  joint_offsets    : {list(config.joint_offsets)}  # rad")
    if config.gripper:
        print(f"  gripper_range_rad: {list(config.gripper_range_rad)}  # (closed, open)")
    return config


def check(config: GelloConfig, *, rate_hz: float) -> None:
    """Stream mapped joint angles so the operator can sanity-check signs."""
    leader = GelloLeader(config)
    dt = 1.0 / max(1.0, rate_hz)
    print(f"\n{_CYAN}Streaming mapped joint angles — Ctrl+C to stop.{_RESET}")
    print("Move each joint one at a time; a joint that moves the wrong way needs "
          "its sign flipped in joint_signs.\n")
    try:
        while True:
            command = leader.read()
            joints = " ".join(f"j{i}:{v:+6.3f}" for i, v in enumerate(command.q_franka))
            gripper = "" if command.gripper_bits is None else f" | gripper:{command.gripper_bits:3d}/255"
            print(f"\r{joints}{gripper}", end="", flush=True)
            time.sleep(dt)
    except KeyboardInterrupt:
        print()
    finally:
        leader.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Calibrate a 7-DoF GELLO leader arm")
    p.add_argument("--port", default=DEFAULT_GELLO_PORT, help="GELLO serial port")
    p.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE, help="Dynamixel baudrate")
    p.add_argument("--no-gripper", action="store_true", help="GELLO has no gripper trigger")
    p.add_argument("--start-joints", type=float, nargs=7, default=list(GELLO_CALIBRATION_POSE),
        metavar="RAD", help="Franka joint angles the GELLO is held at during calibration")
    p.add_argument("--joint-signs", type=int, nargs=7, choices=(-1, 1),
        default=list(GelloConfig().joint_signs), metavar="SIGN",
        help="Per-joint motor direction; flip a sign if that joint moves backwards under --check")
    p.add_argument("--out", default=None, help="Write the resulting config to this JSON path")
    p.add_argument("--check", action="store_true",
        help="Skip calibration and stream mapped joint angles from an existing config")
    p.add_argument("--gello-config", default=None,
        help="Config to load for --check (default: $GELLO_CONFIG, else built-in defaults)")
    p.add_argument("--check-rate-hz", type=float, default=20.0, help="Print rate for --check")
    args = p.parse_args()

    if args.check:
        config = load_gello_config(args.gello_config, port=args.port, baudrate=args.baudrate)
        check(config, rate_hz=args.check_rate_hz)
        return

    print(f"Place the GELLO in the calibration pose {list(args.start_joints)} "
          f"with the gripper trigger released.")
    config = calibrate(args)

    if args.out:
        print(f"\nWrote {config.to_json(args.out)}")
        print(f"Use it with: python scripts/run_teleop_cli.py --leader gello --gello-config {args.out}")
    else:
        print("\nRe-run with --out gello_config.json to save these values.")


if __name__ == "__main__":
    main()
