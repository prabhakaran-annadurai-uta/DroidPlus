# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Franky services and clients.

Services are FastAPI applications for robot, camera, and gripper control.
Clients are HTTP clients for communicating with these services.
"""

from droid_plus.services.camera_client import CameraClient, CameraInfo, Frame
from droid_plus.services.franky_client import (
    ALT_POSITION_1,
    ALT_POSITION_2,
    ALT_POSITION_3,
    ALT_POSITION_4,
    HOME_POSITION,
    FrankyClient,
)
from droid_plus.services.gripper_client import GripperClient

__all__ = [
    # Clients
    "FrankyClient",
    "CameraClient",
    "GripperClient",
    # Data classes
    "CameraInfo",
    "Frame",
    # Constants
    "HOME_POSITION",
    "ALT_POSITION_1",
    "ALT_POSITION_2",
    "ALT_POSITION_3",
    "ALT_POSITION_4",
]
