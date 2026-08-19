# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pyzed.sl as sl

from droid_plus.constants import ALL_CAMERA_SERIALS


@dataclass(frozen=True)
class CameraInfo:
    camera_id: str  # typically the ZED serial number as a string
    model: str
    resolution: tuple[int, int]  # (width, height)
    fps: int


@dataclass
class LatestFrames:
    timestamp_s: float
    rgb_rgba: np.ndarray  # HxWx4 uint8 (BGRA from ZED/OpenCV conventions)
    depth_mm: np.ndarray  # HxW float32 (millimeters); invalid may be NaN/Inf


class ZedCameraManager:
    """
    Owns ZED camera handles and background grab threads.

    Design goal: open each camera exactly once, keep the newest RGB+Depth in RAM,
    and let HTTP handlers read the latest buffer without touching the camera.
    """

    @staticmethod
    def _expected_serials_from_env() -> list[str]:
        """
        Comma-separated list of camera serial numbers that are expected to be present.

        When set, ``get_status()`` will include a placeholder entry for any expected
        camera that is not currently detected, making it visible in the dashboard as
        missing. Set via ``EXPECTED_CAMERA_SERIALS`` env var.
        """
        raw = os.getenv("EXPECTED_CAMERA_SERIALS", "")
        if raw.strip():
            return [str(int(s.strip())) for s in raw.split(",") if s.strip()]
        return list(ALL_CAMERA_SERIALS)

    def __init__(self, *, camera_hz: float = 30.0, expected_serials: list[str] | None = None):
        self._camera_hz = float(camera_hz)
        if not np.isfinite(self._camera_hz) or self._camera_hz <= 0:
            raise ValueError("camera_hz must be > 0")

        self._expected_serials: list[str] = expected_serials if expected_serials is not None else self._expected_serials_from_env()

        self._shutdown = threading.Event()
        self._lock = threading.Lock()

        self._cameras: dict[str, sl.Camera] = {}
        self._camera_infos: dict[str, CameraInfo] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._latest: dict[str, LatestFrames] = {}
        self._errors: dict[str, str] = {}
        self._manager_error: str | None = None
        # Throttle repeated open() attempts for cameras that are present but failing to init.
        self._last_open_attempt_ts: dict[str, float] = {}

        # Stats
        self._grab_count: dict[str, int] = {}
        self._last_grab_ts: dict[str, float] = {}

    @staticmethod
    def default_camera_hz_from_env() -> float:
        raw = os.getenv("ZED_CAMERA_HZ", "30")
        try:
            return float(raw)
        except ValueError:
            return 30.0

    @staticmethod
    def _resolution_from_env() -> sl.RESOLUTION:
        """
        Map ZED_CAMERA_RESOLUTION env var to sl.RESOLUTION.

        Supported values (case-insensitive): AUTO, HD2K, HD1080, HD720, SVGA, VGA.
        """
        # Default to VGA to reduce bandwidth/compute unless the user overrides it.
        raw = (os.getenv("ZED_CAMERA_RESOLUTION", "VGA") or "VGA").strip().upper()
        mapping = {
            "AUTO": sl.RESOLUTION.AUTO,
            "HD2K": sl.RESOLUTION.HD2K,
            "HD1080": sl.RESOLUTION.HD1080,
            "HD720": sl.RESOLUTION.HD720,
            "SVGA": sl.RESOLUTION.SVGA,
            "VGA": sl.RESOLUTION.VGA,
        }
        return mapping.get(raw, sl.RESOLUTION.AUTO)

    @staticmethod
    def _fps_from_env() -> int | None:
        raw = os.getenv("ZED_CAMERA_FPS")
        if raw is None or raw.strip() == "":
            return None
        try:
            v = int(raw)
        except ValueError:
            return None
        return v if v > 0 else None

    @staticmethod
    def default_open_retry_s_from_env() -> float:
        """
        Minimum time between consecutive open() retries for the same camera_id.

        This prevents periodic stalls when a camera is detected by USB but cannot be initialized.
        """
        raw = os.getenv("ZED_OPEN_RETRY_S", "10.0")
        try:
            return float(raw)
        except ValueError:
            return 10.0

    def list_cameras(self) -> list[CameraInfo]:
        with self._lock:
            return list(self._camera_infos.values())

    def get_latest(self, camera_id: str) -> LatestFrames | None:
        with self._lock:
            fr = self._latest.get(camera_id)
            return fr

    def get_error(self, camera_id: str) -> str | None:
        with self._lock:
            return self._errors.get(camera_id)

    # A camera is considered "live" only if its most recent frame is younger than
    # this many seconds. Anything older is treated as stale (camera unplugged,
    # grab failures, etc.).
    _FRAME_STALE_S = 2.0

    def get_status(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            cams = list(self._camera_infos.values())
            latest = {cid: self._latest[cid].timestamp_s for cid in self._latest.keys()}
            errors = dict(self._errors)
            grab_count = dict(self._grab_count)
            last_grab_ts = dict(self._last_grab_ts)
            manager_error = self._manager_error

        per_cam: dict[str, Any] = {}
        for c in cams:
            ts = latest.get(c.camera_id)
            age = (now - ts) if ts is not None else None
            per_cam[c.camera_id] = {
                "model": c.model,
                "resolution": {"width": c.resolution[0], "height": c.resolution[1]},
                "fps": c.fps,
                "has_frame": ts is not None and age is not None and age < self._FRAME_STALE_S,
                "last_frame_age_s": age,
                "last_error": errors.get(c.camera_id),
                "grab_count": grab_count.get(c.camera_id, 0),
                "last_grab_age_s": (now - last_grab_ts[c.camera_id]) if c.camera_id in last_grab_ts else None,
            }

        # Include placeholder entries for expected cameras that are not currently detected.
        for serial in self._expected_serials:
            if serial not in per_cam:
                per_cam[serial] = {
                    "model": "unknown",
                    "resolution": {"width": 0, "height": 0},
                    "fps": 0,
                    "has_frame": False,
                    "last_frame_age_s": None,
                    "last_error": "not detected",
                    "grab_count": 0,
                    "last_grab_age_s": None,
                }

        return {
            "camera_hz": self._camera_hz,
            "open_retry_s": self.default_open_retry_s_from_env(),
            "auto_rescan_enabled": bool(self._expected_serials),
            "num_cameras": len(cams),
            "num_expected": len(self._expected_serials) if self._expected_serials else len(cams),
            "manager_error": manager_error,
            "cameras": per_cam,
        }

    def get_calibration(self, camera_id: str) -> dict[str, Any]:
        """
        Return best-effort calibration/intrinsics for an opened ZED camera.

        Uses `pyzed.sl.Camera.get_camera_information()` and returns a JSON-serializable dict.
        """

        def _vec(x: Any) -> list[float]:
            try:
                return [float(v) for v in x]
            except Exception:
                return []

        def _size(s: Any) -> dict[str, int] | None:
            try:
                return {"width": int(s.width), "height": int(s.height)}
            except Exception:
                return None

        def _cam_params(p: Any) -> dict[str, Any]:
            return {
                "fx": float(getattr(p, "fx")),
                "fy": float(getattr(p, "fy")),
                "cx": float(getattr(p, "cx")),
                "cy": float(getattr(p, "cy")),
                "disto": _vec(getattr(p, "disto", [])),
                "image_size": _size(getattr(p, "image_size", None)),
            }

        with self._lock:
            cam = self._cameras.get(camera_id)
            info_cached = self._camera_infos.get(camera_id)

        if cam is None:
            return {"ok": False, "camera_id": camera_id, "error": "camera not opened"}

        try:
            info = cam.get_camera_information()
            cfg = info.camera_configuration
            calib = cfg.calibration_parameters

            left = _cam_params(getattr(calib, "left_cam"))
            right = _cam_params(getattr(calib, "right_cam"))

            return {
                "ok": True,
                "camera_id": camera_id,
                "serial_number": int(getattr(info, "serial_number", int(camera_id))),
                "model": str(getattr(info, "camera_model", info_cached.model if info_cached else "unknown")),
                "resolution": {
                    "width": int(getattr(cfg.resolution, "width", (info_cached.resolution[0] if info_cached else 0))),
                    "height": int(getattr(cfg.resolution, "height", (info_cached.resolution[1] if info_cached else 0))),
                },
                "fps": int(getattr(cfg, "fps", info_cached.fps if info_cached else 0)),
                "left_cam": left,
                "right_cam": right,
            }
        except Exception as e:
            with self._lock:
                self._errors[camera_id] = f"calibration: {type(e).__name__}: {e}"
            return {"ok": False, "camera_id": camera_id, "error": f"{type(e).__name__}: {e}"}

    def _start_grab_thread(self, *, camera_id: str) -> None:
        t = threading.Thread(target=self._grab_loop, kwargs={"camera_id": camera_id}, daemon=True)
        with self._lock:
            self._threads[camera_id] = t
        t.start()

    def _try_open_camera(self, *, sn: int, force: bool = False) -> bool:
        """
        Best-effort open. Returns True if opened successfully, else records an error and returns False.
        """
        if sn <= 0:
            return False
        camera_id = str(int(sn))
        with self._lock:
            if camera_id in self._cameras:
                return True
            if not force:
                now = time.time()
                last = self._last_open_attempt_ts.get(camera_id)
                retry_s = float(self.default_open_retry_s_from_env())
                if last is not None and np.isfinite(retry_s) and retry_s > 0 and (now - last) < retry_s:
                    return False
                self._last_open_attempt_ts[camera_id] = now

        def _open_with(resolution: sl.RESOLUTION) -> tuple[sl.Camera, sl.ERROR_CODE]:
            z = sl.Camera()
            init_params = sl.InitParameters()
            init_params.depth_mode = sl.DEPTH_MODE.NEURAL
            init_params.coordinate_units = sl.UNIT.MILLIMETER
            init_params.camera_resolution = resolution
            init_params.set_from_serial_number(int(sn))
            fps = self._fps_from_env()
            if fps is not None:
                try:
                    init_params.camera_fps = int(fps)
                except Exception:
                    pass
            return z, z.open(init_params)

        requested_res = self._resolution_from_env()
        zed, open_err = _open_with(requested_res)
        if open_err != sl.ERROR_CODE.SUCCESS:
            # Fallback: if a specific resolution was requested, retry AUTO.
            try:
                zed.close()
            except Exception:
                pass

            if requested_res != sl.RESOLUTION.AUTO:
                zed2, open_err2 = _open_with(sl.RESOLUTION.AUTO)
                if open_err2 == sl.ERROR_CODE.SUCCESS:
                    zed = zed2
                    open_err = open_err2
                else:
                    try:
                        zed2.close()
                    except Exception:
                        pass

            if open_err != sl.ERROR_CODE.SUCCESS:
                with self._lock:
                    self._errors[camera_id] = f"open: {open_err}"
                return False

        info = zed.get_camera_information()
        cam_info = CameraInfo(
            camera_id=camera_id,
            model=str(info.camera_model),
            resolution=(int(info.camera_configuration.resolution.width), int(info.camera_configuration.resolution.height)),
            fps=int(info.camera_configuration.fps),
        )

        with self._lock:
            self._cameras[camera_id] = zed
            self._camera_infos[camera_id] = cam_info
            self._grab_count.setdefault(camera_id, 0)
            self._errors.pop(camera_id, None)
            self._manager_error = None

        self._start_grab_thread(camera_id=camera_id)
        return True

    def rescan(self, *, force: bool = False) -> dict[str, Any]:
        """
        One-shot discovery pass for newly plugged cameras.

        This is intentionally NOT periodic; callers (e.g., HTTP endpoint /rescan)
        should trigger it explicitly.
        """
        t0 = time.time()
        attempted = 0
        opened = 0
        try:
            devs = sl.Camera.get_device_list()
            for dev in devs:
                try:
                    sn = int(dev.serial_number)
                except Exception:
                    continue
                attempted += 1
                if self._try_open_camera(sn=sn, force=force):
                    opened += 1
        except Exception as e:
            with self._lock:
                self._manager_error = f"rescan: {type(e).__name__}: {e}"
            return {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "attempted": attempted,
                "opened": opened,
                "dt_s": time.time() - t0,
            }

        return {"ok": True, "attempted": attempted, "opened": opened, "dt_s": time.time() - t0}

    def start(self, *, allow_no_camera: bool = True) -> None:
        """
        Discover and open cameras, then start per-camera grab threads.
        """
        devs = sl.Camera.get_device_list()
        if not devs:
            msg = "No ZED cameras detected (sl.Camera.get_device_list returned empty)."
            with self._lock:
                self._manager_error = msg
            if allow_no_camera:
                return
            raise RuntimeError(msg)

        # Open all detected stereo ZED cameras.
        opened_any = False
        for dev in devs:
            sn = int(dev.serial_number)
            camera_id = str(sn)

            if self._try_open_camera(sn=sn, force=True):
                opened_any = True
            else:
                # Keep placeholder metadata if we have it from the device list.
                with self._lock:
                    self._camera_infos.setdefault(
                        camera_id,
                        CameraInfo(
                            camera_id=camera_id,
                            model=str(getattr(dev, "camera_model", "unknown")),
                            resolution=(0, 0),
                            fps=0,
                        ),
                    )

        if not opened_any:
            msg = "Failed to open any ZED cameras."
            with self._lock:
                self._manager_error = msg
            if not allow_no_camera:
                raise RuntimeError(msg)
            # Cameras may appear later; auto-rescan will pick them up.

        # Start auto-rescan thread if there are expected cameras to watch for.
        self._rescan_thread: threading.Thread | None = None
        if self._expected_serials:
            self._rescan_thread = threading.Thread(target=self._auto_rescan_loop, daemon=True)
            self._rescan_thread.start()

    _AUTO_RESCAN_INTERVAL_S = 5.0

    def _auto_rescan_loop(self) -> None:
        """Background thread: periodically rescan when expected cameras are missing."""
        while not self._shutdown.is_set():
            self._shutdown.wait(self._AUTO_RESCAN_INTERVAL_S)
            if self._shutdown.is_set():
                break
            # Only rescan if some expected cameras are not yet opened.
            with self._lock:
                opened = set(self._cameras.keys())
            missing = [s for s in self._expected_serials if s not in opened]
            if missing:
                self.rescan(force=True)

    def stop(self) -> None:
        self._shutdown.set()

        threads: list[threading.Thread] = []
        with self._lock:
            threads = list(self._threads.values())
        for t in threads:
            t.join(timeout=2.0)
        if hasattr(self, "_rescan_thread") and self._rescan_thread is not None:
            self._rescan_thread.join(timeout=2.0)

        with self._lock:
            cams = list(self._cameras.values())
            self._cameras.clear()
            self._threads.clear()
        for cam in cams:
            try:
                cam.close()
            except Exception:
                pass

    # After this many seconds of continuous grab errors, the grab loop exits and
    # releases the camera handle so auto-rescan can reopen it.
    _GRAB_ERROR_BAIL_S = 5.0

    def _grab_loop(self, *, camera_id: str) -> None:
        period_s = 1.0 / self._camera_hz
        runtime = sl.RuntimeParameters()
        image = sl.Mat()
        depth = sl.Mat()

        with self._lock:
            cam = self._cameras.get(camera_id)
        if cam is None:
            return

        error_since: float | None = None

        while not self._shutdown.is_set():
            t0 = time.time()
            try:
                err = cam.grab(runtime)
                if err != sl.ERROR_CODE.SUCCESS:
                    with self._lock:
                        self._errors[camera_id] = f"grab: {err}"
                    if error_since is None:
                        error_since = time.time()
                    elif (time.time() - error_since) > self._GRAB_ERROR_BAIL_S:
                        # Persistent errors: close handle and let auto-rescan reopen.
                        try:
                            cam.close()
                        except Exception:
                            pass
                        with self._lock:
                            self._cameras.pop(camera_id, None)
                            self._threads.pop(camera_id, None)
                        return
                    time.sleep(min(0.1, period_s))
                    continue

                error_since = None  # reset on successful grab

                cam.retrieve_image(image, sl.VIEW.LEFT)  # BGRA8 (ZED image buffers)
                cam.retrieve_measure(depth, sl.MEASURE.DEPTH)  # float32 in mm (per coordinate_units)

                rgb = image.get_data()
                dep = depth.get_data()

                # Defensive copies: pyzed buffers are reused; we want stable snapshots.
                rgb_copy = np.array(rgb, copy=True)
                dep_copy = np.array(dep, copy=True)

                now = time.time()
                with self._lock:
                    self._latest[camera_id] = LatestFrames(timestamp_s=now, rgb_rgba=rgb_copy, depth_mm=dep_copy)
                    self._errors.pop(camera_id, None)
                    self._grab_count[camera_id] = self._grab_count.get(camera_id, 0) + 1
                    self._last_grab_ts[camera_id] = now
            except Exception as e:
                with self._lock:
                    self._errors[camera_id] = f"{type(e).__name__}: {e}"
                if error_since is None:
                    error_since = time.time()
                elif (time.time() - error_since) > self._GRAB_ERROR_BAIL_S:
                    try:
                        cam.close()
                    except Exception:
                        pass
                    with self._lock:
                        self._cameras.pop(camera_id, None)
                        self._threads.pop(camera_id, None)
                    return

            dt = time.time() - t0
            if dt < period_s:
                time.sleep(period_s - dt)
