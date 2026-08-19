# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ``droid_plus.utils.geometry``."""
from __future__ import annotations

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from droid_plus.utils.geometry import (
    depth_to_point_cloud,
    pos_quat_to_se3,
    se3_to_pos_quat,
    transform_point_cloud,
)

# ── se3_to_pos_quat ↔ pos_quat_to_se3 round-trip ────────────────────────────

def _random_se3(rng: np.random.Generator) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = Rotation.random(random_state=rng).as_matrix()
    T[:3, 3] = rng.uniform(-2.0, 2.0, size=3)
    return T


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_se3_pos_quat_round_trip(seed: int) -> None:
    """Random SE(3) → pos_quat → SE(3) is a no-op (within numerical tolerance)."""
    rng = np.random.default_rng(seed)
    T = _random_se3(rng)

    pq = se3_to_pos_quat(T)
    assert len(pq) == 7

    T_round = pos_quat_to_se3(pq[:3], pq[3:])
    np.testing.assert_allclose(T_round, T, atol=1e-10)


def test_pos_quat_to_se3_identity() -> None:
    """Identity quaternion (wxyz = [1,0,0,0]) and zero translation give I_4."""
    T = pos_quat_to_se3([0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0])
    np.testing.assert_allclose(T, np.eye(4), atol=1e-12)


def test_se3_to_pos_quat_returns_wxyz() -> None:
    """A 90° rotation around z must serialise to wxyz, not xyzw."""
    T = np.eye(4)
    T[:3, :3] = Rotation.from_euler("z", 90.0, degrees=True).as_matrix()
    T[:3, 3] = [1.0, 2.0, 3.0]

    pq = se3_to_pos_quat(T)
    np.testing.assert_allclose(pq[:3], [1.0, 2.0, 3.0], atol=1e-12)

    expected_wxyz = [np.cos(np.pi / 4), 0.0, 0.0, np.sin(np.pi / 4)]
    qw, qx, qy, qz = pq[3:]
    if qw < 0:
        qw, qx, qy, qz = -qw, -qx, -qy, -qz
    np.testing.assert_allclose([qw, qx, qy, qz], expected_wxyz, atol=1e-10)


# ── transform_point_cloud ────────────────────────────────────────────────────

def test_transform_point_cloud_identity() -> None:
    pts = np.array([[1.0, 2.0, 3.0], [-0.5, 0.0, 0.5]])
    out = transform_point_cloud(pts, np.eye(4))
    np.testing.assert_allclose(out, pts)


def test_transform_point_cloud_round_trip() -> None:
    rng = np.random.default_rng(123)
    T = _random_se3(rng)
    pts = rng.uniform(-1.0, 1.0, size=(50, 3))
    out = transform_point_cloud(pts, T)
    back = transform_point_cloud(out, np.linalg.inv(T))
    np.testing.assert_allclose(back, pts, atol=1e-10)


def test_transform_point_cloud_shape() -> None:
    pts = np.zeros((7, 3))
    out = transform_point_cloud(pts, np.eye(4))
    assert out.shape == (7, 3)


# ── depth_to_point_cloud ─────────────────────────────────────────────────────

def test_depth_to_point_cloud_constant_depth() -> None:
    """A constant depth image gives a flat z=d plane through the camera frame."""
    H, W = 16, 24
    fx, fy, cx, cy = 100.0, 100.0, W / 2.0, H / 2.0
    cam_k = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1.0]])

    depth = np.full((H, W), 1.5, dtype=np.float32)
    pts = depth_to_point_cloud(depth, cam_k)

    assert pts.shape == (H * W, 3)
    np.testing.assert_allclose(pts[:, 2], 1.5)

    centre_pixel_idx = int(cy) * W + int(cx)
    np.testing.assert_allclose(pts[centre_pixel_idx, :2], [0.0, 0.0], atol=1e-10)


def test_depth_to_point_cloud_invalid_dropped() -> None:
    """Depth pixels with value <= 0 must be discarded."""
    H, W = 4, 4
    cam_k = np.array([[100.0, 0, 2.0], [0, 100.0, 2.0], [0, 0, 1.0]])
    depth = np.zeros((H, W), dtype=np.float32)
    depth[1, 1] = 1.0
    depth[2, 3] = 0.5
    pts = depth_to_point_cloud(depth, cam_k)
    assert pts.shape == (2, 3)
    assert set(pts[:, 2].tolist()) == {1.0, 0.5}


def test_depth_to_point_cloud_with_mask() -> None:
    H, W = 8, 8
    cam_k = np.array([[100.0, 0, 4.0], [0, 100.0, 4.0], [0, 0, 1.0]])
    depth = np.full((H, W), 1.0, dtype=np.float32)
    mask = np.zeros((H, W), dtype=np.uint8)
    mask[3:5, 3:5] = 1
    pts = depth_to_point_cloud(depth, cam_k, mask=mask)
    assert pts.shape == (4, 3)
