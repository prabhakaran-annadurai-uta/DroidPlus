# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Global constants for the DROID+ system.

Set environment variables when configuring a new system or swapping hardware.
See docs/software-setup.md for details.
"""
from __future__ import annotations

import os


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _camera_serial(name: str) -> str:
    return os.getenv(name, "").strip()


# ── ZED Camera Serial Numbers ──
# Each ZED camera has a unique serial number burned into the hardware.
# To find yours: plug in the camera and run
#   python -c "import pyzed.sl as sl; print([(d.serial_number, d.camera_model) for d in sl.Camera.get_device_list()])"
WRIST_CAMERA_SERIAL = _camera_serial("WRIST_CAMERA_SERIAL")
LEFT_CAMERA_SERIAL = _camera_serial("LEFT_CAMERA_SERIAL")
RIGHT_CAMERA_SERIAL = _camera_serial("RIGHT_CAMERA_SERIAL")

ALL_CAMERA_SERIALS = [
    serial for serial in (WRIST_CAMERA_SERIAL, LEFT_CAMERA_SERIAL, RIGHT_CAMERA_SERIAL)
    if serial
]

CAMERA_SERIAL_NAMES = {
    serial: name
    for serial, name in (
        (WRIST_CAMERA_SERIAL, "wrist"),
        (LEFT_CAMERA_SERIAL, "left"),
        (RIGHT_CAMERA_SERIAL, "right"),
    )
    if serial
}

# ── Network ──
# NUC_IP: IP address of the Intel NUC running franky_service (Franka control).
NUC_IP = os.getenv("NUC_IP", "localhost").strip()

# SERVICES_IP: IP address of the machine running the services (franky_service, camera_service, gripper_service).
SERVICES_IP = os.getenv("SERVICES_IP", "127.0.0.1").strip()

# ── Policy Servers ──
# Each entry maps a policy name to its host and port.
# Override with POLICY_NAME, POLICY_HOST, and POLICY_PORT or pass CLI flags.
DEFAULT_POLICY = os.getenv("POLICY_NAME", "pi05").strip()
POLICIES = {
    DEFAULT_POLICY: {
        "host": os.getenv("POLICY_HOST", "127.0.0.1").strip(),
        "port": _env_int("POLICY_PORT", 8000),
    },
}

# ── Service URLs (derived from above) ──
FRANKY_SERVICE_URL = os.getenv("FRANKY_SERVICE_URL", f"http://{NUC_IP}:54321").strip()
CAMERA_SERVICE_URL = os.getenv("CAMERA_SERVICE_URL", f"http://{SERVICES_IP}:54322").strip()
GRIPPER_SERVICE_URL = os.getenv("GRIPPER_SERVICE_URL", f"http://{SERVICES_IP}:54323").strip()

# ── Recording ──
# JPEG quality used when persisting camera frames to disk (0–100).
# Q85 is perceptually indistinguishable from Q90 at typical ZED resolutions
# and yields ~11% smaller files; override per-run with --record-jpeg-quality.
RECORD_JPEG_QUALITY = 85
