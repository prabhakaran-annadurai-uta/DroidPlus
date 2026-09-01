# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Minimal Dynamixel Protocol 2.0 bus reader for GELLO leader arms.

Only the subset teleop needs: present positions and a torque switch. Polling
runs on a background thread because a sync-read over 8 servos at 57600 baud
costs ~20 ms, which would otherwise stall a 100 Hz control loop.
"""
from __future__ import annotations

import threading
import time
from typing import Sequence

import numpy as np

PROTOCOL_VERSION = 2.0
ADDR_TORQUE_ENABLE = 64
ADDR_PRESENT_POSITION = 132
LEN_PRESENT_POSITION = 4
PULSES_PER_REV = 4096
DEFAULT_BAUDRATE = 57600

_MIN_POLL_GAP_S = 0.002


def _pulses_to_rad(pulses: Sequence[int]) -> np.ndarray:
    signed = np.array([int(np.int32(np.uint32(p))) for p in pulses], dtype=np.float64)
    return signed * (2.0 * np.pi / PULSES_PER_REV)


class DynamixelBus:
    """Threaded present-position reader for one chain of Dynamixel servos."""

    def __init__(
        self,
        ids: Sequence[int],
        *,
        port: str,
        baudrate: int = DEFAULT_BAUDRATE,
        poll_hz: float = 100.0,
    ) -> None:
        # Lazy import: dynamixel-sdk is an optional extra (droid-plus[gello]).
        from dynamixel_sdk.group_sync_read import GroupSyncRead
        from dynamixel_sdk.packet_handler import PacketHandler
        from dynamixel_sdk.port_handler import PortHandler

        self.ids = tuple(int(i) for i in ids)
        self.port_name = str(port)

        self._port = PortHandler(self.port_name)
        self._packet = PacketHandler(PROTOCOL_VERSION)

        try:
            opened = self._port.openPort()
        except Exception as e:  # pyserial raises before openPort() can return False
            raise ConnectionError(f"Could not open Dynamixel port {self.port_name!r}: {e}") from e
        if not opened:
            raise ConnectionError(
                f"Could not open Dynamixel port {self.port_name!r}. Check the cable, that the "
                f"user is in the 'dialout' group, and that no other process holds the port."
            )
        if not self._port.setBaudRate(int(baudrate)):
            self._port.closePort()
            raise ConnectionError(f"Could not set baudrate {baudrate} on {self.port_name!r}")

        self._reader = GroupSyncRead(
            self._port, self._packet, ADDR_PRESENT_POSITION, LEN_PRESENT_POSITION
        )
        for dxl_id in self.ids:
            if not self._reader.addParam(dxl_id):
                self._port.closePort()
                raise ConnectionError(f"Failed to register servo id {dxl_id} for sync read")

        self._bus_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._positions: np.ndarray | None = None
        self._last_read_s: float = 0.0
        self._read_error: str | None = None
        self._stop = threading.Event()
        self._poll_dt = 1.0 / max(1e-3, float(poll_hz))

        try:
            self._read_once()  # fail fast on a powered-off or miswired chain
        except Exception:
            self.close()
            raise

        self._thread = threading.Thread(target=self._poll_loop, name="dynamixel-poll", daemon=True)
        self._thread.start()

    # ── Reading ──────────────────────────────────────────────────────────

    def _read_once(self) -> None:
        from dynamixel_sdk.robotis_def import COMM_SUCCESS

        with self._bus_lock:
            comm = self._reader.txRxPacket()
            if comm != COMM_SUCCESS:
                raise ConnectionError(
                    f"Dynamixel sync read failed on {self.port_name!r}: "
                    f"{self._packet.getTxRxResult(comm)}"
                )
            pulses = []
            for dxl_id in self.ids:
                if not self._reader.isAvailable(dxl_id, ADDR_PRESENT_POSITION, LEN_PRESENT_POSITION):
                    raise ConnectionError(
                        f"No response from Dynamixel id {dxl_id} on {self.port_name!r}. "
                        f"Check power, the servo id, and the baudrate ({self.ids} expected)."
                    )
                pulses.append(self._reader.getData(dxl_id, ADDR_PRESENT_POSITION, LEN_PRESENT_POSITION))

        with self._state_lock:
            self._positions = _pulses_to_rad(pulses)
            self._last_read_s = time.monotonic()
            self._read_error = None

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                self._read_once()
            except Exception as e:  # transient bus errors must not kill the thread
                with self._state_lock:
                    self._read_error = str(e)
            # dynamixel_sdk busy-waits inside txRxPacket, so always yield to the
            # control loop rather than re-reading back-to-back.
            elapsed = time.monotonic() - t0
            self._stop.wait(max(_MIN_POLL_GAP_S, self._poll_dt - elapsed))

    def read_positions(self, *, max_age_s: float = 0.5) -> np.ndarray:
        """Latest present positions (radians), one per configured servo id."""
        with self._state_lock:
            positions = self._positions
            age = time.monotonic() - self._last_read_s
            error = self._read_error
        if positions is None:
            raise ConnectionError(f"No Dynamixel reading yet from {self.port_name!r}: {error}")
        if age > max_age_s:
            raise ConnectionError(
                f"Stale Dynamixel reading from {self.port_name!r} ({age:.2f}s old): {error}"
            )
        return positions.copy()

    # ── Torque ───────────────────────────────────────────────────────────

    def set_torque(self, enable: bool) -> None:
        """Enable/disable torque on every servo. GELLO is driven with torque off."""
        from dynamixel_sdk.robotis_def import COMM_SUCCESS

        value = 1 if enable else 0
        with self._bus_lock:
            for dxl_id in self.ids:
                comm, err = self._packet.write1ByteTxRx(
                    self._port, dxl_id, ADDR_TORQUE_ENABLE, value
                )
                if comm != COMM_SUCCESS or err != 0:
                    raise ConnectionError(
                        f"Failed to set torque={enable} on Dynamixel id {dxl_id}: "
                        f"{self._packet.getTxRxResult(comm)} / {self._packet.getRxPacketError(err)}"
                    )

    # ── Lifecycle ────────────────────────────────────────────────────────

    def close(self) -> None:
        self._stop.set()
        thread = getattr(self, "_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        try:
            self._port.closePort()
        except Exception:
            pass
