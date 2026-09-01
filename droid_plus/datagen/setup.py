# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Teleop session bootstrap: FK model, leader-arm connection, run dir.

Parallels ``droid_plus.eval.experiment_setup`` but for data-generation flows.
"""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

from droid_plus.analysis.end_effector_pose import build_model_from_urdf, get_urdf
from droid_plus.constants import FRANKY_SERVICE_URL
from droid_plus.datagen.gello import DEFAULT_GELLO_PORT
from droid_plus.datagen.leader import LEADER_KINDS, LeaderArm, So101Leader

if TYPE_CHECKING:
    from droid_plus.datagen.gello import GelloLeader
    from droid_plus.robot import DroidPlus


_YELLOW = "\033[93m"
_RESET = "\033[0m"


# ── FK model ─────────────────────────────────────────────────────────────────

def build_fk_model(franky_service_url: str = FRANKY_SERVICE_URL) -> tuple[Any, Any, str]:
    """Fetch the URDF from franky_service and build a Pinocchio FK model.

    Returns ``(pin_model, pin_data, ee_frame)`` ready for
    :func:`droid_plus.datagen.safety.enforce_min_z`.
    """
    print("Fetching URDF for FK safety checks...")
    urdf_xml = get_urdf(franky_service_url)
    pin_model, pin_data, ee_frame = build_model_from_urdf(urdf_xml)
    print(f"FK model ready (ee_frame={ee_frame!r})")
    return pin_model, pin_data, ee_frame


# ── Gripper ──────────────────────────────────────────────────────────────────

def init_gripper(droid: "DroidPlus") -> bool:
    """Best-effort connect + activate of the Robotiq gripper.

    Returns ``True`` if initialization succeeded, else ``False`` (so the
    caller can decide whether to proceed without gripper control).
    """
    try:
        print("Initializing gripper...")
        droid.connect_gripper()
        droid.activate_gripper()
        print("Gripper initialized successfully")
        return True
    except Exception as e:
        print(f"{_YELLOW}Warning: Could not initialize gripper: {e}{_RESET}")
        print("Continuing without gripper control...")
        return False


# ── Leader arms ──────────────────────────────────────────────────────────────

DEFAULT_LEADER_PORTS = {"so101": "/dev/ttyACM0", "gello": DEFAULT_GELLO_PORT}


def connect_so101(port: str = "/dev/ttyACM0", *, id: str = "main_leader", settle_s: float = 2.0) -> Any:
    """Connect to the SO-101 leader arm.

    ``settle_s`` sleeps between gripper init and SO-101 handshake — the
    gripper USB initialization can otherwise interfere with the SO-101 serial
    handshake when they share a hub. Callers that don't init the gripper can
    pass ``settle_s=0.0``.
    """
    if settle_s > 0:
        print(f"Waiting {settle_s}s before initializing SO-101...")
        time.sleep(settle_s)
    # Lazy import: lerobot is an optional extra.
    from lerobot.teleoperators.so_leader.config_so_leader import SO101LeaderConfig
    from lerobot.teleoperators.so_leader.so_leader import SO101Leader

    print(f"Connecting to SO-101 on {port}...")
    teleop = SO101Leader(SO101LeaderConfig(port=port, id=id))
    teleop.connect()
    print("SO-101 connected successfully")
    return teleop


def connect_gello(
    port: str | None = None,
    *,
    config_path: str | None = None,
    max_joint_speed_rad_s: float | None = None,
    settle_s: float = 0.0,
) -> "GelloLeader":
    """Connect to a 7-DoF GELLO leader arm."""
    from droid_plus.datagen.gello import GelloLeader, load_gello_config

    if settle_s > 0:
        print(f"Waiting {settle_s}s before initializing GELLO...")
        time.sleep(settle_s)

    config = load_gello_config(
        config_path, port=port, max_joint_speed_rad_s=max_joint_speed_rad_s
    )
    print(f"Connecting to GELLO on {config.port}...")
    leader = GelloLeader(config)
    print(f"GELLO connected successfully (slew limit {config.max_joint_speed_rad_s} rad/s, "
          f"gripper {'on' if config.gripper else 'off'})")
    return leader


def connect_leader(
    kind: str,
    port: str | None = None,
    *,
    settle_s: float = 0.0,
    gello_config_path: str | None = None,
    gello_max_joint_speed_rad_s: float | None = None,
) -> LeaderArm:
    """Connect the requested leader device and return it as a ``LeaderArm``."""
    kind = kind.strip().lower()
    if kind not in LEADER_KINDS:
        raise ValueError(f"Unknown leader {kind!r}; expected one of {LEADER_KINDS}")

    if kind == "so101":
        return So101Leader(connect_so101(port or DEFAULT_LEADER_PORTS["so101"], settle_s=settle_s))

    return connect_gello(
        port,
        config_path=gello_config_path,
        max_joint_speed_rad_s=gello_max_joint_speed_rad_s,
        settle_s=settle_s,
    )


# ── Run directory ────────────────────────────────────────────────────────────

def make_teleop_run_dir(task: str = "", *, parent: str = "output") -> str:
    """Build ``{task_}teleop_{timestamp}`` under ``parent/`` and create it."""
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    task_str = f"{task}_" if task else ""
    run_name = f"{task_str}teleop_{ts}"
    path = os.path.join(parent, run_name)
    os.makedirs(path, exist_ok=True)
    return path


# ── Rate helpers ─────────────────────────────────────────────────────────────

def compute_record_every_n(rate_hz: float, record_rate_hz: float) -> int:
    """Control ticks per recorded frame: ``max(1, round(rate / record_rate))``."""
    return max(1, round(float(rate_hz) / float(record_rate_hz)))
