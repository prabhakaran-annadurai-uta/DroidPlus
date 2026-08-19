# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
DROID+ - Franka robot control services, clients, and utilities.

Quick start:
    from droid_plus.robot import DroidPlus
    from droid_plus.services import FrankyClient, CameraClient, GripperClient
"""

__version__ = "0.1.0"

# Convenience imports
from droid_plus.robot.droid_plus import DroidPlus
from droid_plus.services.camera_client import CameraClient
from droid_plus.services.franky_client import HOME_POSITION, FrankyClient
from droid_plus.services.gripper_client import GripperClient

__all__ = [
    "DroidPlus",
    "FrankyClient",
    "CameraClient",
    "GripperClient",
    "HOME_POSITION",
    "__version__",
]
