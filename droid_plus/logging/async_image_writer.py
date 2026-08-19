# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class ImageWriteJob:
    camera: str
    frame_idx: int
    rgb: np.ndarray
    jpeg_quality: int
    rel_path: str


class AsyncImageWriter:
    """
    Background image writer (one thread) to avoid blocking control loops.

    Layout:
      run_dir/
        right/000000123.jpg
        wrist/000000123.jpg
        ...
    """

    def __init__(self, run_dir: str | os.PathLike[str], *, max_queue: int = 2048):
        self.run_dir = Path(run_dir)
        self._q: queue.Queue[Optional[ImageWriteJob]] = queue.Queue(maxsize=int(max_queue))
        self._closed = False
        self._thread = threading.Thread(target=self._worker, name="AsyncImageWriter", daemon=True)
        self._thread.start()

    def ensure_camera_dir(self, camera: str) -> Path:
        d = self.run_dir / str(camera)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write(self, camera: str, frame_idx: int, rgb: np.ndarray, *, jpeg_quality: int = 90) -> str:
        """
        Enqueue an RGB image for writing and return the relative path (within run_dir).

        Note: This enqueues the numpy array; for maximum safety, pass a contiguous array
        that won't be mutated after enqueueing (we defensively copy if needed).
        """
        if self._closed:
            raise RuntimeError("AsyncImageWriter is closed")

        camera = str(camera)
        self.ensure_camera_dir(camera)

        rel_path = f"{camera}/{int(frame_idx):09d}.jpg"

        arr = np.asarray(rgb)
        if arr.dtype != np.uint8:
            arr = arr.astype(np.uint8, copy=False)
        if not arr.flags["C_CONTIGUOUS"]:
            arr = np.ascontiguousarray(arr)
        # Defensive copy to prevent caller mutation affecting async write.
        arr = arr.copy()

        job = ImageWriteJob(
            camera=camera,
            frame_idx=int(frame_idx),
            rgb=arr,
            jpeg_quality=int(jpeg_quality),
            rel_path=rel_path,
        )
        self._q.put(job)
        return rel_path

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._q.put(None)
        self._thread.join(timeout=10.0)

    def _worker(self) -> None:
        while True:
            job = self._q.get()
            if job is None:
                self._q.task_done()
                break
            try:
                self._write_one(job)
            finally:
                self._q.task_done()

    def _write_one(self, job: ImageWriteJob) -> None:
        out_path = self.run_dir / job.rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # OpenCV encodes BGR; inputs are RGB.
        rgb = job.rgb
        if rgb.ndim == 3 and rgb.shape[2] == 3:
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        else:
            # Fallback: write as-is (e.g., already BGR or grayscale)
            bgr = rgb

        params = [int(cv2.IMWRITE_JPEG_QUALITY), int(job.jpeg_quality)]
        ok, buf = cv2.imencode(".jpg", bgr, params)
        if not ok:
            raise RuntimeError("cv2.imencode failed")

        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp.write_bytes(buf.tobytes())
        tmp.replace(out_path)
