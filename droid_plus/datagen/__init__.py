# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Data-generation (teleop) utilities for DROID+.

Mirrors ``droid_plus.eval`` in structure: a runner that executes a single
episode, a setup module that owns session-level bootstrap, plus
teleop-specific adapters (SO-101 mapping, FK safety clamp).
"""

from droid_plus.datagen.safety import DEFAULT_MIN_EE_Z, enforce_min_z
from droid_plus.datagen.setup import (
    build_fk_model,
    compute_record_every_n,
    connect_so101,
    init_gripper,
    make_teleop_run_dir,
)
from droid_plus.datagen.so101 import (
    SO101_ACTION_KEYS,
    SO101_GRIPPER_KEYS,
    action_to_so101_joints_deg,
    extract_so101_gripper_deg,
    so101_gripper_to_robotiq,
    so101_to_franka,
)
from droid_plus.datagen.teleop_runner import (
    TeleopSessionConfig,
    finalize_teleop_episode_recording,
    run_teleop_episode,
)

__all__ = [
    "DEFAULT_MIN_EE_Z",
    "SO101_ACTION_KEYS",
    "SO101_GRIPPER_KEYS",
    "TeleopSessionConfig",
    "action_to_so101_joints_deg",
    "build_fk_model",
    "compute_record_every_n",
    "connect_so101",
    "enforce_min_z",
    "extract_so101_gripper_deg",
    "finalize_teleop_episode_recording",
    "init_gripper",
    "make_teleop_run_dir",
    "run_teleop_episode",
    "so101_gripper_to_robotiq",
    "so101_to_franka",
]
