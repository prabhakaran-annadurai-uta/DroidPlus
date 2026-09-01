# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Data-generation (teleop) utilities for DROID+.

Mirrors ``droid_plus.eval`` in structure: a runner that executes a single
episode, a setup module that owns session-level bootstrap, plus
teleop-specific adapters (leader-arm devices, FK safety clamp).
"""

from droid_plus.datagen.gello import (
    DEFAULT_GELLO_PORT,
    FR3_JOINT_LIMITS,
    GelloConfig,
    GelloLeader,
    clamp_to_fr3_limits,
    load_gello_config,
    normalize_joint_positions,
)
from droid_plus.datagen.leader import (
    LEADER_KINDS,
    LeaderArm,
    LeaderCommand,
    So101Leader,
    joint_alignment_error,
    wait_for_alignment,
)
from droid_plus.datagen.safety import DEFAULT_MIN_EE_Z, enforce_min_z
from droid_plus.datagen.setup import (
    DEFAULT_LEADER_PORTS,
    build_fk_model,
    compute_record_every_n,
    connect_gello,
    connect_leader,
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
    "DEFAULT_GELLO_PORT",
    "DEFAULT_LEADER_PORTS",
    "DEFAULT_MIN_EE_Z",
    "FR3_JOINT_LIMITS",
    "LEADER_KINDS",
    "SO101_ACTION_KEYS",
    "SO101_GRIPPER_KEYS",
    "GelloConfig",
    "GelloLeader",
    "LeaderArm",
    "LeaderCommand",
    "So101Leader",
    "TeleopSessionConfig",
    "action_to_so101_joints_deg",
    "build_fk_model",
    "clamp_to_fr3_limits",
    "compute_record_every_n",
    "connect_gello",
    "connect_leader",
    "connect_so101",
    "enforce_min_z",
    "extract_so101_gripper_deg",
    "finalize_teleop_episode_recording",
    "init_gripper",
    "joint_alignment_error",
    "load_gello_config",
    "make_teleop_run_dir",
    "normalize_joint_positions",
    "run_teleop_episode",
    "so101_gripper_to_robotiq",
    "so101_to_franka",
    "wait_for_alignment",
]
