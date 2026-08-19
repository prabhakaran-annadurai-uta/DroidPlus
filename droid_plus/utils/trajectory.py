# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Joint-space trajectory helpers (no robot dependency).

- :func:`trajectory_times_from_dt` builds an absolute timestamp array for a
  fixed-dt trajectory.
- :func:`upsample_trajectory` interpolates a coarse joint trajectory with
  PCHIP (monotonic cubic Hermite) splines, returning new positions and
  analytically differentiated velocities.
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np


def trajectory_times_from_dt(n_waypoints: int, dt: float) -> List[float]:
    """Build an array of absolute timestamps ``[0, dt, 2*dt, ...]`` for a trajectory."""
    return [i * dt for i in range(n_waypoints)]


def upsample_trajectory(
    positions: List[List[float]],
    velocities: List[List[float]],
    dt: float,
    upsample_factor: int = 4,
) -> Tuple[List[List[float]], List[List[float]], float]:
    """Upsample a joint trajectory using PCHIP interpolation.

    Args:
        positions: (N, J) sequence of joint positions, sampled at uniform ``dt``.
        velocities: (N, J) sequence of joint velocities. Currently unused (we
            re-derive velocities from the interpolated position spline) but
            accepted for API symmetry with the pre-upsample data structure.
        dt: Sample period of the input trajectory, in seconds.
        upsample_factor: Output sample rate is ``input_rate * upsample_factor``.

    Returns:
        Tuple ``(new_positions, new_velocities, new_dt)``. If ``positions`` has
        fewer than 2 rows the input is returned unchanged.
    """
    from scipy.interpolate import PchipInterpolator

    pos_arr = np.array(positions)
    n_pts, n_joints = pos_arr.shape
    if n_pts < 2:
        return positions, velocities, dt

    t_orig = np.arange(n_pts) * dt
    new_dt = dt / upsample_factor
    t_new = np.arange(0, t_orig[-1] + new_dt * 0.5, new_dt)

    new_pos = np.zeros((len(t_new), n_joints))
    new_vel = np.zeros((len(t_new), n_joints))
    for j in range(n_joints):
        interp = PchipInterpolator(t_orig, pos_arr[:, j])
        new_pos[:, j] = interp(t_new)
        new_vel[:, j] = interp(t_new, 1)

    return new_pos.tolist(), new_vel.tolist(), new_dt
