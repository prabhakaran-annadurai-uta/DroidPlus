# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Leader-arm abstraction for teleop.

``run_teleop_episode`` consumes a :class:`LeaderArm`, so adding a device means
adding an adapter here (or in a device module) rather than editing the control
loop. Every adapter is responsible for producing Franka joint targets directly.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Protocol

import numpy as np

from droid_plus.datagen.so101 import (
    action_to_so101_joints_deg,
    extract_so101_gripper_deg,
    so101_gripper_to_robotiq,
    so101_to_franka,
)

if TYPE_CHECKING:
    from droid_plus.robot import DroidPlus

LEADER_KINDS = ("so101", "gello")


@dataclass(frozen=True)
class LeaderCommand:
    """One control-step command from a leader device."""

    q_franka: np.ndarray
    """Franka joint targets, shape ``(7,)``, radians."""

    gripper_bits: int | None = None
    """Robotiq target: 0 = fully open, 255 = fully closed. ``None`` = no gripper input."""


class LeaderArm(Protocol):
    """Teleop input device that emits Franka joint targets."""

    name: str

    def read(self) -> LeaderCommand:
        """Sample the device once. Called every control tick."""
        ...

    def joint_positions(self) -> np.ndarray:
        """Current device pose in Franka joint space, bypassing any rate limiter."""
        ...

    def sync_to(self, q_franka: np.ndarray) -> None:
        """Seed the internal command state so the next ``read`` starts from ``q_franka``."""
        ...

    def close(self) -> None:
        ...


class So101Leader:
    """Adapter around LeRobot's SO-101 teleoperator."""

    name = "so101"

    def __init__(self, teleop: Any) -> None:
        self._teleop = teleop

    def read(self) -> LeaderCommand:
        action = self._teleop.get_action()
        q_franka = so101_to_franka(np.deg2rad(action_to_so101_joints_deg(action)))
        gripper_deg = extract_so101_gripper_deg(action)
        gripper_bits = None if gripper_deg is None else so101_gripper_to_robotiq(gripper_deg)
        return LeaderCommand(q_franka=q_franka, gripper_bits=gripper_bits)

    def joint_positions(self) -> np.ndarray:
        return self.read().q_franka

    def sync_to(self, q_franka: np.ndarray) -> None:
        """No-op: the SO-101 mapping is stateless."""

    def close(self) -> None:
        try:
            self._teleop.disconnect()
        except Exception:
            pass


# ── Startup alignment ────────────────────────────────────────────────────────

def joint_alignment_error(leader: LeaderArm, droid: "DroidPlus") -> tuple[np.ndarray, np.ndarray]:
    """Return ``(per_joint_error, leader_q)`` between the leader pose and the robot."""
    q_leader = np.asarray(leader.joint_positions(), dtype=float).reshape(-1)
    q_robot = np.asarray(droid.get_current_joint_state()["positions"], dtype=float).reshape(-1)
    return q_leader - q_robot, q_leader


def wait_for_alignment(
    leader: LeaderArm,
    droid: "DroidPlus",
    *,
    tol_rad: float = 0.25,
    timeout_s: float = 60.0,
    should_stop: Callable[[], bool] | None = None,
    verbose: bool = True,
) -> bool:
    """Block until the leader pose matches the robot pose within ``tol_rad``.

    A 1:1 leader such as GELLO commands absolute joint targets, so streaming
    before the operator has matched the robot's pose would command a large
    step. Returns ``True`` once aligned, ``False`` on timeout/abort.
    """
    if verbose:
        q_robot = np.asarray(droid.get_current_joint_state()["positions"], dtype=float)
        print(f"\n[align] Waiting for the {leader.name} leader to match the robot "
              f"(tolerance {tol_rad} rad, {timeout_s:.0f}s timeout).")
        print(f"[align] Robot pose: {[round(float(v), 3) for v in q_robot]}")
        print("[align] Move the leader until every joint error is inside the tolerance. "
              "ESC aborts.")

    deadline = time.time() + float(timeout_s)
    last_print = 0.0
    while time.time() < deadline:
        if should_stop is not None and should_stop():
            if verbose:
                print("\n[align] Aborted.")
            return False
        try:
            error, _ = joint_alignment_error(leader, droid)
        except Exception as e:
            if verbose:
                print(f"[align] Warning: {e}")
            time.sleep(0.2)
            continue

        worst = int(np.argmax(np.abs(error)))
        if float(np.abs(error[worst])) <= tol_rad:
            if verbose:
                print(f"\n[align] Aligned (max error {np.abs(error[worst]):.3f} rad). Streaming.")
            leader.sync_to(np.asarray(droid.get_current_joint_state()["positions"], dtype=float))
            return True

        now = time.time()
        if verbose and now - last_print > 0.25:
            deltas = " ".join(
                f"j{i}:{e:+.2f}{'*' if abs(e) > tol_rad else ' '}" for i, e in enumerate(error)
            )
            remaining = deadline - now
            print(f"[align] {deltas} | worst j{worst} {error[worst]:+.3f} "
                  f"| {remaining:4.0f}s left", end="\r", flush=True)
            last_print = now
        time.sleep(0.05)

    if verbose:
        print(f"\n[align] Timed out after {timeout_s:.0f}s without reaching {tol_rad} rad.")
        print("[align] If the errors never shrank, the GELLO calibration is likely wrong — "
              "re-run scripts/gello_calibrate.py, or pass --no-align-check to bypass "
              "(the robot will then jump to the leader pose).")
    return False
