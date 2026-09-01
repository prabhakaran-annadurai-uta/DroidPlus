# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
GELLO leader-arm adapter (7-DoF Franka variant).

GELLO is a kinematic replica of the arm, so the mapping to Franka joint space
is identity once assembly offsets and motor direction signs are removed. The
work here is turning raw Dynamixel registers into continuous, limit-respecting
joint targets:

  1. Raw registers reset to ``[0, 2pi)`` on power-up, losing multi-turn count —
     resolved once at startup by wrapping around the FR3 joint mid-range.
  2. Subsequent updates are applied as deltas so the estimate stays continuous.
  3. Targets are clipped to FR3 joint limits and rate-limited before leaving.

Calibration constants follow the ``franka_gello_state_publisher`` conventions;
run ``scripts/gello_calibrate.py`` to produce them for a specific assembly.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import numpy as np

from droid_plus.datagen.dynamixel import DEFAULT_BAUDRATE, DynamixelBus
from droid_plus.datagen.leader import LeaderCommand

# Franka FR3 joint position limits (rad).
# https://frankarobotics.github.io/docs/robot_specifications.html
FR3_JOINT_LIMITS = np.array(
    [
        [-2.9007, 2.9007],
        [-1.8361, 1.8361],
        [-2.9007, 2.9007],
        [-3.0770, -0.1169],
        [-2.8763, 2.8763],
        [0.4398, 4.6216],
        [-3.0508, 3.0508],
    ]
)
FR3_JOINT_MID = FR3_JOINT_LIMITS.mean(axis=1)

DEFAULT_GELLO_PORT = "/dev/ttyUSB0"
GELLO_CONFIG_ENV = "GELLO_CONFIG"

# Signed span from the gripper trigger's open rest position to fully squeezed.
GRIPPER_OPEN_TO_CLOSED_RAD = -1.22

# Pose the operator holds GELLO in during calibration (Franka joint space, rad).
GELLO_CALIBRATION_POSE = (0.0, 0.0, 0.0, -1.571, 0.0, 1.571, 0.0)


@dataclass(frozen=True)
class GelloConfig:
    """Per-assembly GELLO calibration + tuning.

    ``joint_signs`` defaults to the direction set measured on our 7-DoF Franka
    GELLO, which differs from the upstream ``franka_gello_state_publisher``
    reference (``1 -1 1 -1 1 1 1``) on j1 and j5. ``joint_offsets`` are only
    valid for the signs they were measured with, so always re-run
    ``scripts/gello_calibrate.py`` after changing signs.
    """

    port: str = DEFAULT_GELLO_PORT
    baudrate: int = DEFAULT_BAUDRATE
    joint_signs: tuple[int, ...] = (1, 1, 1, -1, 1, -1, 1)
    joint_offsets: tuple[float, ...] = (0.000, 0.000, 3.142, 3.142, 3.142, 4.712, 0.000)
    gripper: bool = True
    gripper_range_rad: tuple[float, float] = (2.00, 3.22)
    """``(closed_rad, open_rad)`` raw trigger positions."""

    max_joint_speed_rad_s: float = 2.0
    """Command slew limit. ``<= 0`` disables rate limiting."""

    smoothing_alpha: float = 0.85
    """Exponential smoothing on the raw pose estimate; 1.0 disables it."""

    def __post_init__(self) -> None:
        if len(self.joint_signs) != len(self.joint_offsets):
            raise ValueError("joint_signs and joint_offsets must have the same length")
        if len(self.joint_signs) != 7:
            raise ValueError("Only the 7-DoF GELLO (Franka) layout is supported")
        if not all(s in (1, -1) for s in self.joint_signs):
            raise ValueError(f"joint_signs must all be +1/-1, got {self.joint_signs}")
        if self.gripper and self.gripper_range_rad[0] == self.gripper_range_rad[1]:
            raise ValueError("gripper_range_rad must span a non-zero interval")

    @property
    def num_arm_joints(self) -> int:
        return len(self.joint_signs)

    @property
    def servo_ids(self) -> list[int]:
        return list(range(1, self.num_arm_joints + (1 if self.gripper else 0) + 1))

    @classmethod
    def from_dict(cls, data: dict) -> "GelloConfig":
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown GELLO config keys: {sorted(unknown)}")
        kwargs = dict(data)
        for key in ("joint_signs", "joint_offsets", "gripper_range_rad"):
            if key in kwargs:
                kwargs[key] = tuple(kwargs[key])
        if "joint_signs" in kwargs:
            kwargs["joint_signs"] = tuple(int(s) for s in kwargs["joint_signs"])
        return cls(**kwargs)

    @classmethod
    def from_json(cls, path: str | os.PathLike[str]) -> "GelloConfig":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def to_json(self, path: str | os.PathLike[str]) -> str:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
            f.write("\n")
        return str(path)


def load_gello_config(path: str | None = None, **overrides) -> GelloConfig:
    """Load a GELLO config from ``path``, then ``$GELLO_CONFIG``, else defaults."""
    source = path or os.getenv(GELLO_CONFIG_ENV) or None
    config = GelloConfig.from_json(source) if source else GelloConfig()
    overrides = {k: v for k, v in overrides.items() if v is not None}
    return replace(config, **overrides) if overrides else config


# ── Pure mapping helpers ─────────────────────────────────────────────────────

def normalize_joint_positions(
    raw_positions: np.ndarray, joint_offsets: np.ndarray, joint_signs: np.ndarray
) -> np.ndarray:
    """Resolve raw motor registers to absolute joint angles near the FR3 mid-range.

    Applies direction signs, removes assembly offsets, then wraps into
    ``[mid - pi, mid + pi)`` to pick the branch consistent with a physically
    reachable pose. ``joint_offsets`` are expressed *after* the sign flip, which
    is the space ``scripts/gello_calibrate.py`` measures them in.
    """
    return (
        np.mod(raw_positions * joint_signs - joint_offsets - FR3_JOINT_MID, 2 * np.pi)
        - np.pi
        + FR3_JOINT_MID
    )


def clamp_to_fr3_limits(q: np.ndarray) -> np.ndarray:
    return np.clip(q, FR3_JOINT_LIMITS[:, 0], FR3_JOINT_LIMITS[:, 1])


def gripper_raw_to_width_frac(raw_rad: float, gripper_range_rad: tuple[float, float]) -> float:
    """Raw trigger position → open-width fraction (0 = closed, 1 = open)."""
    closed, opened = gripper_range_rad
    frac = (float(raw_rad) - closed) / (opened - closed)
    return float(np.clip(frac, 0.0, 1.0))


def gripper_width_frac_to_robotiq(width_frac: float) -> int:
    """Open-width fraction → Robotiq bits (0 = open, 255 = closed)."""
    bits = round(255.0 * (1.0 - float(np.clip(width_frac, 0.0, 1.0))))
    return int(np.clip(bits, 0, 255))


# ── Leader ───────────────────────────────────────────────────────────────────

@dataclass
class _PoseState:
    prev_raw: np.ndarray
    q: np.ndarray
    q_cmd: np.ndarray
    t_last: float = field(default_factory=time.monotonic)


class GelloLeader:
    """7-DoF GELLO leader arm streaming Franka joint targets."""

    name = "gello"

    def __init__(self, config: GelloConfig | None = None) -> None:
        self.config = config or GelloConfig()
        self._n = self.config.num_arm_joints
        self._signs = np.array(self.config.joint_signs, dtype=float)
        self._offsets = np.array(self.config.joint_offsets, dtype=float)

        self._bus = DynamixelBus(
            self.config.servo_ids, port=self.config.port, baudrate=self.config.baudrate
        )
        # GELLO is hand-guided: torque must stay off or the operator fights the servos.
        self._bus.set_torque(False)

        raw = self._bus.read_positions()
        arm_raw = raw[: self._n]
        q0 = normalize_joint_positions(arm_raw, self._offsets, self._signs)
        self._state = _PoseState(
            prev_raw=arm_raw.copy(), q=q0.copy(), q_cmd=clamp_to_fr3_limits(q0)
        )

    # ── Internals ────────────────────────────────────────────────────────

    def _advance_pose(self, raw: np.ndarray) -> np.ndarray:
        """Integrate raw deltas into the continuous pose estimate; returns clamped q."""
        arm_raw = raw[: self._n]
        # Wrap the raw delta: the register is single-turn and rolls over at 2*pi.
        raw_delta = np.mod(arm_raw - self._state.prev_raw + np.pi, 2 * np.pi) - np.pi
        q = self._state.q + raw_delta * self._signs

        alpha = float(np.clip(self.config.smoothing_alpha, 0.0, 1.0))
        if alpha < 1.0:
            q = self._state.q * (1.0 - alpha) + q * alpha

        self._state.q = q
        self._state.prev_raw = arm_raw
        return clamp_to_fr3_limits(q)

    def _rate_limit(self, q_target: np.ndarray) -> np.ndarray:
        max_speed = float(self.config.max_joint_speed_rad_s)
        now = time.monotonic()
        dt = min(max(now - self._state.t_last, 1e-4), 0.1)
        self._state.t_last = now

        if max_speed <= 0.0:
            self._state.q_cmd = q_target
            return q_target

        max_step = max_speed * dt
        step = np.clip(q_target - self._state.q_cmd, -max_step, max_step)
        self._state.q_cmd = self._state.q_cmd + step
        return self._state.q_cmd.copy()

    # ── LeaderArm interface ──────────────────────────────────────────────

    def read(self) -> LeaderCommand:
        raw = self._bus.read_positions()
        q_franka = self._rate_limit(self._advance_pose(raw))

        gripper_bits = None
        if self.config.gripper:
            width_frac = gripper_raw_to_width_frac(float(raw[-1]), self.config.gripper_range_rad)
            gripper_bits = gripper_width_frac_to_robotiq(width_frac)

        return LeaderCommand(q_franka=q_franka, gripper_bits=gripper_bits)

    def joint_positions(self) -> np.ndarray:
        return self._advance_pose(self._bus.read_positions())

    def sync_to(self, q_franka: np.ndarray) -> None:
        q = np.asarray(q_franka, dtype=float).reshape(-1)
        if q.shape != (self._n,):
            raise ValueError(f"Expected {self._n} joint values, got {q.shape}")
        self._state.q_cmd = q.copy()
        self._state.t_last = time.monotonic()

    def close(self) -> None:
        self._bus.close()
