# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Geometry helpers shared across droid_plus pipelines.

Pure-numpy / scipy utilities for:
- Back-projecting depth images into 3D point clouds
- Applying SE(3) transforms to point clouds
- Converting between 4x4 SE(3) matrices and pos+quat ([x,y,z,qw,qx,qy,qz])
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
from scipy.spatial.transform import Rotation


def depth_to_point_cloud(
    depth_m: np.ndarray,
    cam_k: np.ndarray,
    mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Back-project a depth image into a 3D point cloud (camera frame).

    Args:
        depth_m: (H, W) depth map in metres. Pixels with ``depth <= 0`` are
            treated as invalid and dropped.
        cam_k: (3, 3) camera intrinsic matrix (pinhole, no distortion).
        mask: (H, W) optional boolean / uint mask. If provided, only pixels
            where ``mask > 0`` are included.

    Returns:
        (N, 3) array of 3D points in the camera coordinate frame, where
        +Z points along the optical axis.
    """
    H, W = depth_m.shape
    u, v = np.meshgrid(np.arange(W), np.arange(H))

    fx, fy = cam_k[0, 0], cam_k[1, 1]
    cx, cy = cam_k[0, 2], cam_k[1, 2]

    z = depth_m
    x = (u - cx) * z / fx
    y = (v - cy) * z / fy

    points = np.stack([x, y, z], axis=-1)

    valid = z > 0
    if mask is not None:
        valid = valid & (mask > 0)

    return points[valid]


def transform_point_cloud(points: np.ndarray, T: np.ndarray) -> np.ndarray:
    """Apply a 4x4 homogeneous transform to an (N, 3) point cloud.

    Args:
        points: (N, 3) array of 3D points.
        T: (4, 4) homogeneous transformation matrix.

    Returns:
        (N, 3) transformed points.
    """
    ones = np.ones((points.shape[0], 1), dtype=points.dtype)
    pts_h = np.hstack([points, ones])
    pts_t = (T @ pts_h.T).T
    return pts_t[:, :3]


def se3_to_pos_quat(T: np.ndarray) -> List[float]:
    """Convert a 4x4 SE(3) matrix to [x, y, z, qw, qx, qy, qz].

    Quaternion ordering is wxyz.

    Args:
        T: (4, 4) homogeneous transformation matrix.

    Returns:
        7-element list ``[x, y, z, qw, qx, qy, qz]``.
    """
    position = T[:3, 3].tolist()
    rot = Rotation.from_matrix(T[:3, :3])
    qx, qy, qz, qw = rot.as_quat()
    return position + [qw, qx, qy, qz]


def pos_quat_to_se3(position: List[float], quaternion_wxyz: List[float]) -> np.ndarray:
    """Build a 4x4 SE(3) matrix from position + quaternion (w, x, y, z).

    Inverse of :func:`se3_to_pos_quat`.

    Args:
        position: 3-element list ``[x, y, z]``.
        quaternion_wxyz: 4-element list ``[qw, qx, qy, qz]``.

    Returns:
        (4, 4) homogeneous transformation matrix (float64).
    """
    T = np.eye(4, dtype=np.float64)
    qw, qx, qy, qz = quaternion_wxyz
    T[:3, :3] = Rotation.from_quat([qx, qy, qz, qw]).as_matrix()
    T[:3, 3] = position
    return T
