# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Observation building utilities for policy inference.
"""
from __future__ import annotations

from typing import Any

import numpy as np


def make_policy_observation(
    *,
    left_rgb: np.ndarray,
    wrist_rgb: np.ndarray,
    joint_pos: np.ndarray,
    gripper_pos: float = 0.0,
) -> dict[str, Any]:
    """
    Build a numpy-native observation dict for policy inference.

    This creates the standard observation format expected by Pi0 and similar
    policies, without requiring PyTorch.

    Args:
        left_rgb: Left camera RGB image (H, W, 3) uint8
        wrist_rgb: Wrist camera RGB image (H, W, 3) uint8
        joint_pos: Joint positions (7,) float
        gripper_pos: Gripper position in [0, 1] (0=open, 1=closed)

    Returns:
        Observation dictionary with keys:
            - "left_image": np.ndarray (H, W, 3) uint8
            - "wrist_image": np.ndarray (H, W, 3) uint8
            - "joint_position": np.ndarray (7,) float32
            - "gripper_position": float
    """
    return {
        "left_image": np.asarray(left_rgb, dtype=np.uint8),
        "wrist_image": np.asarray(wrist_rgb, dtype=np.uint8),
        "joint_position": np.asarray(joint_pos, dtype=np.float32).reshape(-1),
        "gripper_position": float(gripper_pos),
    }


def validate_observation(obs: dict[str, Any]) -> None:
    """
    Validate that an observation dict has the expected format.

    Args:
        obs: Observation dictionary to validate

    Raises:
        ValueError: If observation is missing required keys or has wrong shapes
    """
    required_keys = ["left_image", "wrist_image", "joint_position"]
    for key in required_keys:
        if key not in obs:
            raise ValueError(f"Observation missing required key: {key}")

    left = np.asarray(obs["left_image"])
    if left.ndim != 3 or left.shape[2] != 3:
        raise ValueError(f"left_image must be (H, W, 3), got shape {left.shape}")

    wrist = np.asarray(obs["wrist_image"])
    if wrist.ndim != 3 or wrist.shape[2] != 3:
        raise ValueError(f"wrist_image must be (H, W, 3), got shape {wrist.shape}")

    joint_pos = np.asarray(obs["joint_position"]).reshape(-1)
    if joint_pos.shape[0] != 7:
        raise ValueError(f"joint_position must have length 7, got {joint_pos.shape[0]}")


def pack_state_action(
    joint_pos: np.ndarray,
    joint_vel: np.ndarray,
    gripper_pos: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Pack joint state + gripper into 8-dim arrays for recording.

    Args:
        joint_pos: Joint positions (7,)
        joint_vel: Joint velocities (7,)
        gripper_pos: Gripper position in [0, 1]

    Returns:
        Tuple of (positions_8, velocities_8)
    """
    positions = np.concatenate([
        np.asarray(joint_pos, dtype=np.float64).reshape(-1),
        np.array([float(gripper_pos)], dtype=np.float64)
    ])
    velocities = np.concatenate([
        np.asarray(joint_vel, dtype=np.float64).reshape(-1),
        np.array([0.0], dtype=np.float64)
    ])
    return positions, velocities
