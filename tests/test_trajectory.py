# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ``droid_plus.utils.trajectory``."""
from __future__ import annotations

import numpy as np
import pytest

from droid_plus.utils.trajectory import trajectory_times_from_dt, upsample_trajectory


def test_trajectory_times_from_dt_basic() -> None:
    times = trajectory_times_from_dt(5, 0.02)
    assert times == [0.0, 0.02, 0.04, 0.06, 0.08]


def test_trajectory_times_from_dt_empty() -> None:
    assert trajectory_times_from_dt(0, 0.1) == []


def test_trajectory_times_from_dt_single() -> None:
    assert trajectory_times_from_dt(1, 0.05) == [0.0]


# ── upsample_trajectory ──────────────────────────────────────────────────────

def test_upsample_trajectory_short_passthrough() -> None:
    """Input with < 2 points must be returned unchanged."""
    pos_in = [[0.1, 0.2, 0.3]]
    vel_in = [[0.0, 0.0, 0.0]]
    pos_out, vel_out, dt_out = upsample_trajectory(pos_in, vel_in, dt=0.02)
    assert pos_out == pos_in
    assert vel_out == vel_in
    assert dt_out == 0.02


def test_upsample_trajectory_endpoints_preserved() -> None:
    """PCHIP interpolation passes through every input control point exactly."""
    pos_in = [
        [0.0, 0.0, 0.0],
        [0.1, 0.2, 0.3],
        [0.2, 0.5, 0.4],
        [0.3, 0.7, 0.5],
    ]
    vel_in = [[0.0] * 3] * 4
    pos_out, vel_out, dt_out = upsample_trajectory(pos_in, vel_in, dt=0.02, upsample_factor=4)

    assert dt_out == pytest.approx(0.005)
    assert len(pos_out) == len(vel_out)
    assert len(pos_out) >= 4 * len(pos_in) - 3

    np.testing.assert_allclose(pos_out[0], pos_in[0], atol=1e-10)
    np.testing.assert_allclose(pos_out[-1], pos_in[-1], atol=1e-10)


def test_upsample_trajectory_increases_density() -> None:
    """An upsample_factor of k roughly multiplies the sample count by k."""
    pos_in = [[float(i)] for i in range(5)]
    vel_in = [[1.0]] * 5
    pos_out, _vel_out, dt_out = upsample_trajectory(pos_in, vel_in, dt=0.1, upsample_factor=4)
    assert len(pos_out) > 4 * 4
    assert dt_out == pytest.approx(0.025)


def test_upsample_trajectory_velocity_matches_slope() -> None:
    """For a linear position ramp, PCHIP-derived velocity equals slope/dt (units/sec)."""
    n = 6
    slope_per_step = 0.5
    dt = 0.02
    pos_in = [[i * slope_per_step] for i in range(n)]
    vel_in = [[slope_per_step / dt]] * n
    pos_out, vel_out, _ = upsample_trajectory(pos_in, vel_in, dt=dt, upsample_factor=4)

    expected_v = slope_per_step / dt
    interior = vel_out[3:-3]
    assert len(interior) > 0
    np.testing.assert_allclose([v[0] for v in interior], expected_v, atol=1e-6)


def test_upsample_trajectory_multi_joint_shape() -> None:
    n_pts, n_joints = 4, 7
    rng = np.random.default_rng(0)
    pos_in = rng.uniform(-1.0, 1.0, size=(n_pts, n_joints)).tolist()
    vel_in = np.zeros((n_pts, n_joints)).tolist()
    pos_out, vel_out, _ = upsample_trajectory(pos_in, vel_in, dt=0.05, upsample_factor=2)
    pos_arr = np.array(pos_out)
    vel_arr = np.array(vel_out)
    assert pos_arr.shape[1] == n_joints
    assert vel_arr.shape == pos_arr.shape
