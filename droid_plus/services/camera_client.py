# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import requests

from droid_plus.constants import CAMERA_SERVICE_URL


@dataclass(frozen=True)
class CameraInfo:
    camera_id: str
    model: str
    resolution: tuple[int, int]  # (width, height)
    fps: int


@dataclass(frozen=True)
class Frame:
    timestamp_s: float | None
    image: np.ndarray


class CameraClient:
    """
    Thin HTTP client for `camera_service.py`.

    Endpoints used:
      - GET /cameras
      - GET /camera/{camera_id}/calibration
      - GET /camera/{camera_id}/rgb.jpg
      - GET /camera/{camera_id}/depth.png?scale=...&max_value=...
    """

    def __init__(self, base_url: str | None = None, *, timeout_s: float = 5.0):
        self.base_url = (base_url or CAMERA_SERVICE_URL).rstrip("/")
        self.timeout_s = float(timeout_s)

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def list_cameras(self) -> list[CameraInfo]:
        r = requests.get(self._url("/cameras"), timeout=self.timeout_s)
        r.raise_for_status()
        payload = r.json()

        cams: list[CameraInfo] = []
        for c in payload.get("cameras", []):
            res = c.get("resolution") or {}
            cams.append(
                CameraInfo(
                    camera_id=str(c["camera_id"]),
                    model=str(c.get("model", "")),
                    resolution=(int(res.get("width", 0)), int(res.get("height", 0))),
                    fps=int(c.get("fps", 0)),
                )
            )
        return cams

    def health(self) -> dict[str, Any]:
        """Return `camera_service` health/status payload (GET /health)."""
        r = requests.get(self._url("/health"), timeout=self.timeout_s)
        r.raise_for_status()
        return r.json()

    def rescan(self) -> dict[str, Any]:
        """
        Trigger a one-shot camera discovery pass (POST /rescan).

        Note: the server runs the scan in a background thread; call `list_cameras()`
        or `health()` after a short delay to see newly opened devices.
        """
        r = requests.post(self._url("/rescan"), timeout=self.timeout_s)
        r.raise_for_status()
        return r.json()

    def get_rgb_jpeg(
        self,
        camera_id: str,
        *,
        jpeg_quality: int = 90,
        out_w: int | None = None,
        out_h: int | None = None,
    ) -> tuple[bytes, float | None]:
        r = requests.get(
            self._url(f"/camera/{camera_id}/rgb.jpg"),
            params={
                "jpeg_quality": int(jpeg_quality),
                **({"out_w": int(out_w)} if out_w is not None else {}),
                **({"out_h": int(out_h)} if out_h is not None else {}),
            },
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        ts = r.headers.get("X-Frame-Timestamp-S")
        return r.content, (float(ts) if ts is not None else None)

    def get_calibration(self, camera_id: str) -> dict[str, Any]:
        """Return calibration/intrinsics for a camera (GET /camera/{camera_id}/calibration)."""
        r = requests.get(self._url(f"/camera/{camera_id}/calibration"), timeout=self.timeout_s)
        r.raise_for_status()
        return r.json()

    def get_rgb(self, camera_id: str, *, jpeg_quality: int = 90, out_w: int | None = None, out_h: int | None = None) -> Frame:
        jpg, ts = self.get_rgb_jpeg(camera_id, jpeg_quality=jpeg_quality, out_w=out_w, out_h=out_h)
        arr = np.frombuffer(jpg, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise RuntimeError("Failed to decode JPEG")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return Frame(timestamp_s=ts, image=rgb)

    def get_depth_png(
        self, camera_id: str, *, scale: float = 1.0, max_value: int = 65535
    ) -> tuple[bytes, float | None, dict[str, Any]]:
        r = requests.get(
            self._url(f"/camera/{camera_id}/depth.png"),
            params={"scale": float(scale), "max_value": int(max_value)},
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        ts = r.headers.get("X-Frame-Timestamp-S")
        meta = {
            "depth_unit": r.headers.get("X-Depth-Unit"),
            "depth_scale": r.headers.get("X-Depth-Scale"),
        }
        return r.content, (float(ts) if ts is not None else None), meta

    def get_depth_mm(self, camera_id: str, *, scale: float = 1.0, max_value: int = 65535) -> Frame:
        """
        Returns depth in millimeters as float32 with invalid pixels as NaN.

        Note: `camera_service` encodes uint16 as round(depth_mm * scale). We invert that:
          depth_mm = u16 / scale
        """
        if not np.isfinite(scale) or float(scale) <= 0:
            raise ValueError("scale must be finite and > 0")

        png, ts, _meta = self.get_depth_png(camera_id, scale=scale, max_value=max_value)
        arr = np.frombuffer(png, dtype=np.uint8)
        u16 = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if u16 is None:
            raise RuntimeError("Failed to decode PNG")
        if u16.dtype != np.uint16:
            # Defensive: ensure we got the expected 16-bit depth.
            u16 = np.asarray(u16, dtype=np.uint16)

        depth = (u16.astype(np.float32) / float(scale)).astype(np.float32, copy=False)
        depth[u16 == 0] = np.nan
        return Frame(timestamp_s=ts, image=depth)
