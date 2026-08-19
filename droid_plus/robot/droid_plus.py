# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import time
from typing import Any

import numpy as np
import scipy.interpolate

from droid_plus.constants import (
    CAMERA_SERVICE_URL,
    FRANKY_SERVICE_URL,
    GRIPPER_SERVICE_URL,
    LEFT_CAMERA_SERIAL,
    RIGHT_CAMERA_SERIAL,
    WRIST_CAMERA_SERIAL,
)
from droid_plus.services.camera_client import CameraClient
from droid_plus.services.franky_client import (
    ALT_POSITION_1,
    ALT_POSITION_2,
    ALT_POSITION_3,
    ALT_POSITION_4,
    HOME_POSITION,
    FrankyClient,
)
from droid_plus.services.gripper_client import GripperClient


def _serial_to_camera_id(serial: str) -> str:
    """
    Convert a user-provided serial string into the camera_service `camera_id`.

    `ZedCameraManager` uses `camera_id = str(int(dev.serial_number))`, so leading
    zeros in constants like "001673090201" must be stripped.
    """
    s = str(serial).strip()
    try:
        return str(int(s))
    except ValueError:
        # If it's not numeric, assume caller already passed a camera_id.
        return s


class DroidPlus:
    """
    Combined interface for:
      - `camera_service.py` (ZED RGB + depth snapshots)
      - `franky_service.py` (Franka joint streaming control)
    """

    def __init__(
        self,
        *,
        camera_client: CameraClient | None = None,
        robot_client: FrankyClient | None = None,
        gripper_client: GripperClient | None = None,
        camera_service_url: str | None = None,
        franky_service_url: str | None = None,
        gripper_service_url: str | None = None,
        wrist_camera_serial: str = WRIST_CAMERA_SERIAL,
        left_camera_serial: str = LEFT_CAMERA_SERIAL,
        right_camera_serial: str = RIGHT_CAMERA_SERIAL,
    ):
        self.camera = camera_client or CameraClient(
            base_url=camera_service_url or CAMERA_SERVICE_URL
        )
        self.robot = robot_client or FrankyClient(
            base_url=franky_service_url or FRANKY_SERVICE_URL
        )
        self.gripper = gripper_client or GripperClient(
            base_url=gripper_service_url or GRIPPER_SERVICE_URL
        )

        self.wrist_camera_id = _serial_to_camera_id(wrist_camera_serial)
        self.left_camera_id = _serial_to_camera_id(left_camera_serial)
        self.right_camera_id = _serial_to_camera_id(right_camera_serial)

    # --- Camera helpers ---

    def get_wrist_image(self, *, jpeg_quality: int = 85, return_timestamp: bool = False):
        fr = self.camera.get_rgb(self.wrist_camera_id, jpeg_quality=jpeg_quality)
        return (fr.image, fr.timestamp_s) if return_timestamp else fr.image

    def get_left_image(self, *, jpeg_quality: int = 85, return_timestamp: bool = False):
        fr = self.camera.get_rgb(self.left_camera_id, jpeg_quality=jpeg_quality)
        return (fr.image, fr.timestamp_s) if return_timestamp else fr.image

    def get_right_image(self, *, jpeg_quality: int = 85, return_timestamp: bool = False):
        fr = self.camera.get_rgb(self.right_camera_id, jpeg_quality=jpeg_quality)
        return (fr.image, fr.timestamp_s) if return_timestamp else fr.image

    def get_wrist_depth(self, *, scale: float = 1.0, max_value: int = 65535, return_timestamp: bool = False):
        fr = self.camera.get_depth_mm(self.wrist_camera_id, scale=scale, max_value=max_value)
        return (fr.image, fr.timestamp_s) if return_timestamp else fr.image

    def get_left_depth(self, *, scale: float = 1.0, max_value: int = 65535, return_timestamp: bool = False):
        fr = self.camera.get_depth_mm(self.left_camera_id, scale=scale, max_value=max_value)
        return (fr.image, fr.timestamp_s) if return_timestamp else fr.image

    def get_right_depth(self, *, scale: float = 1.0, max_value: int = 65535, return_timestamp: bool = False):
        fr = self.camera.get_depth_mm(self.right_camera_id, scale=scale, max_value=max_value)
        return (fr.image, fr.timestamp_s) if return_timestamp else fr.image

    def get_wrist_point_cloud(self):
        raise NotImplementedError(
            "Point clouds are not available yet: camera_service exposes RGB+depth only. "
            "To enable, add intrinsics + pointcloud endpoints or provide calibration and compute client-side."
        )

    def get_left_point_cloud(self):
        raise NotImplementedError(
            "Point clouds are not available yet: camera_service exposes RGB+depth only. "
            "To enable, add intrinsics + pointcloud endpoints or provide calibration and compute client-side."
        )

    def get_right_point_cloud(self):
        raise NotImplementedError(
            "Point clouds are not available yet: camera_service exposes RGB+depth only. "
            "To enable, add intrinsics + pointcloud endpoints or provide calibration and compute client-side."
        )

    # --- Robot helpers (pass-through) ---

    def stop(self) -> dict[str, Any]:
        return self.robot.stop()

    def set_target_joint_state(
        self,
        positions: Any,
        velocities: Any | None = None,
        *,
        seq: int | None = None,
    ) -> dict[str, Any]:
        return self.robot.set_target_joint_state(positions, velocities, seq=seq)

    def get_current_joint_state(self) -> dict[str, Any]:
        return self.robot.get_current_joint_state()

    def get_target_joint_state(self) -> dict[str, Any]:
        return self.robot.get_target_joint_state()

    # --- Gripper helpers (pass-through) ---

    def connect_gripper(self) -> dict[str, Any]:
        return self.gripper.connect()

    def activate_gripper(self) -> dict[str, Any]:
        return self.gripper.activate()

    def open_gripper(self, *, speed: int = 255, force: int = 255, wait: bool = True) -> dict[str, Any]:
        return self.gripper.open(speed=speed, force=force, wait=wait)

    def close_gripper(self, *, speed: int = 255, force: int = 255, wait: bool = True) -> dict[str, Any]:
        return self.gripper.close(speed=speed, force=force, wait=wait)

    def open_gripper_async(self, *, speed: int = 255, force: int = 255, wait: bool = False) -> None:
        """Fire-and-forget open (latest-wins)."""
        self.gripper.open_async(speed=speed, force=force, wait=wait)

    def close_gripper_async(self, *, speed: int = 255, force: int = 255, wait: bool = False) -> None:
        """Fire-and-forget close (latest-wins)."""
        self.gripper.close_async(speed=speed, force=force, wait=wait)

    def shutdown_gripper_async(self, *, join_timeout_s: float = 0.5) -> None:
        """Stop the gripper async worker (best-effort)."""
        self.gripper.shutdown_async(join_timeout_s=join_timeout_s)

    def get_gripper_obs_value(self) -> float:
        """
        Return a gripper position fraction in [0,1] for policy observation.
        This is position_bits / 255 from the gripper service.
        """
        return float(self.gripper.gripper_position_frac())

    def move_to_home(self):
        self.set_target_joint_state(HOME_POSITION)

    def move_to_alt_position_1(self):
        self.set_target_joint_state(ALT_POSITION_1)

    def move_to_alt_position_2(self):
        self.set_target_joint_state(ALT_POSITION_2)

    # Follow a trajectory
    def joint_space_trajectory(self, trajectory: list[list[float]], times_s: list[float]):
        if len(trajectory) != len(times_s):
            raise ValueError("trajectory and times_s must have the same length")
        if len(trajectory) == 0:
            return

        # times_s are absolute waypoint times (e.g., [0, 1, 2]), so sleep deltas.
        for i in range(len(trajectory)):
            self.set_target_joint_state(trajectory[i])
            if i < len(trajectory) - 1:
                dt = float(times_s[i + 1]) - float(times_s[i])
                if dt < 0:
                    raise ValueError("times_s must be non-decreasing")
                time.sleep(dt)

    def joint_space_trajectory_with_velocity(self, trajectory: list[list[float]], velocities: list[list[float]], times_s: list[float]):
        """
        Send each waypoint (positions+velocities) and wait until the next waypoint time.

        `times_s` are absolute waypoint times (e.g., [0, 1, 2]), not per-step sleeps.
        """
        if not (len(trajectory) == len(velocities) == len(times_s)):
            raise ValueError("trajectory, velocities, and times_s must have the same length")
        if len(trajectory) == 0:
            return

        for i in range(len(trajectory)):
            self.set_target_joint_state(trajectory[i], velocities[i])
            if i < len(trajectory) - 1:
                dt = float(times_s[i + 1]) - float(times_s[i])
                if dt < 0:
                    raise ValueError("times_s must be non-decreasing")
                time.sleep(dt)

    def joint_space_trajectory_interpolated(self, trajectory: list[list[float]], times_s: list[float]):
        # PCHIP interpolate the trajectory the times are absolute already, so no need to cumsum.
        # We will interpolate to 100Hz.
        t_interp = np.linspace(times_s[0], times_s[-1], len(times_s) * 100)
        trajectory_interp = scipy.interpolate.pchip(times_s, trajectory)(t_interp)
        self.joint_space_trajectory(trajectory_interp, t_interp)

    def joint_space_trajectory_interpolated_with_velocity(self, trajectory: list[list[float]], velocities: list[list[float]], times_s: list[float]):
        t_interp = np.linspace(times_s[0], times_s[-1], len(times_s) * 100)
        trajectory_interp = scipy.interpolate.pchip(times_s, trajectory)(t_interp)
        velocities_interp = scipy.interpolate.pchip(times_s, velocities)(t_interp)
        self.joint_space_trajectory_with_velocity(trajectory_interp, velocities_interp, t_interp)

    def joint_space_interpolate_and_infer_velocity(self, trajectory: list[list[float]], times_s: list[float]):
        """
        Interpolate joint positions with PCHIP and infer joint velocities via the spline derivative.

        This uses SciPy's `PchipInterpolator(...).derivative()` so the inferred velocities are defined
        at the same timestamps as the interpolated positions (no off-by-one like np.diff).
        """
        if len(trajectory) != len(times_s):
            raise ValueError("trajectory and times_s must have the same length")
        if len(times_s) < 2:
            raise ValueError("Need at least 2 waypoints to infer velocities")

        t0 = float(times_s[0])
        t1 = float(times_s[-1])
        if t1 < t0:
            raise ValueError("times_s must be non-decreasing")

        dt = 0.01
        t_interp = np.arange(t0, t1 + 1e-9, dt)

        # PCHIP supports vector-valued y; keep last axis as joints.
        p = scipy.interpolate.PchipInterpolator(times_s, trajectory, axis=0, extrapolate=True)
        trajectory_interp = p(t_interp)
        velocities_interp = p.derivative()(t_interp) * 0.1 # This is a hack to make the velocities more smooth.

        self.joint_space_trajectory_with_velocity(trajectory_interp, velocities_interp, t_interp)


if __name__ == "__main__":
    droid = DroidPlus()
    print("Camera service cameras:", droid.camera.list_cameras())

    # Try a single camera fetch (best-effort).
    try:
        img, ts = droid.get_wrist_image(return_timestamp=True)
        print("Wrist image:", img.shape, img.dtype, "timestamp_s:", ts)
    except Exception as e:
        print("Wrist image fetch failed:", type(e).__name__, e)

    try:
        dep, ts = droid.get_wrist_depth(return_timestamp=True)
        finite = np.isfinite(dep)
        print(
            "Wrist depth:",
            dep.shape,
            dep.dtype,
            "timestamp_s:",
            ts,
            "valid_frac:",
            float(np.mean(finite)) if dep.size else 0.0,
        )
    except Exception as e:
        print("Wrist depth fetch failed:", type(e).__name__, e)

    # Try a robot fetch (best-effort).
    try:
        js = droid.get_current_joint_state()
        print("Current joint state:", js)
    except Exception as e:
        print("Robot joint_state fetch failed:", type(e).__name__, e)


    print("Joint space interpolate and infer velocity")
    droid.set_target_joint_state(HOME_POSITION)
    time.sleep(1)
    waypoints = [ALT_POSITION_1, ALT_POSITION_2, ALT_POSITION_3, ALT_POSITION_4]
    N_repetitions = 100
    trajectory = []
    for i in range(N_repetitions):
        trajectory.extend(waypoints)
    times_s = np.array([i*2.0 for i in range(len(trajectory))])
    droid.joint_space_interpolate_and_infer_velocity(trajectory, times_s)
    time.sleep(0.1)
    droid.stop()
