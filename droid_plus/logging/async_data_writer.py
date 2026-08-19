# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path
from typing import Any, Optional


class AsyncJsonlWriter:
    """Background JSONL appender (one thread)."""

    def __init__(self, jsonl_path: str | os.PathLike[str], *, max_queue: int = 100000):
        self.path = Path(jsonl_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._q: queue.Queue[Optional[dict[str, Any]]] = queue.Queue(maxsize=int(max_queue))
        self._closed = False
        self._thread = threading.Thread(target=self._worker, name="AsyncJsonlWriter", daemon=True)
        self._thread.start()

    def append(self, obj: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("AsyncJsonlWriter is closed")
        # Enqueue a shallow copy so callers can reuse dicts safely.
        self._q.put(dict(obj))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._q.put(None)
        self._thread.join(timeout=10.0)

    def _worker(self) -> None:
        # Keep file open for throughput.
        with self.path.open("a", encoding="utf-8") as f:
            while True:
                item = self._q.get()
                if item is None:
                    self._q.task_done()
                    break
                try:
                    f.write(json.dumps(item, separators=(",", ":"), ensure_ascii=False) + "\n")
                    f.flush()
                finally:
                    self._q.task_done()
