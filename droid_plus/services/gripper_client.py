from __future__ import annotations

import os
import threading
import time
import urllib.parse
from typing import Any, Callable
import franky



class GripperClient:
    """
    Direct client for Franka FR3 Gripper
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout_s: float = 5.0,
        async_timeout_s: float = 0.35,
        async_busy_backoff_s: float = 0.05,
    ):
        
        self.franka_ip = os.getenv("FRANKY_ROBOT_IP")
        #self.franka_ip = "172.16.0.3" #hardcoded for now
        self.timeout_s = float(timeout_s)
        self.async_timeout_s = float(async_timeout_s)
        self.async_busy_backoff_s = float(async_busy_backoff_s)

        self.gripper = None
        self._max_width_m = 0.08  # Default FR3 max width (~80mm)

        self._async_lock = threading.RLock()
        self._async_cv = threading.Condition(self._async_lock)
        self._async_thread: threading.Thread | None = None
        self._async_stop = False
        
        self._async_latest: tuple[Callable, tuple, dict] | None = None
        self._async_last_error: str | None = None
        self._async_last_status_code: int | None = None

        try:
            self.connect()
        except Exception:
            pass


    def _speed_ms(self, speed_bits: int) -> float:
        return (max(0, min(255, speed_bits)) / 255.0) * 0.1

    def _force_n(self, force_bits: int) -> float:
        return (max(0, min(255, force_bits)) / 255.0) * 50.0

    def _pos_m(self, pos_bits: int) -> float:
        frac = max(0.0, min(1.0, pos_bits / 255.0))
        return self._max_width_m * (1.0 - frac)

    def _pos_to_bits(self, width_m: float) -> int:
        frac = max(0.0, min(1.0, 1.0 - (width_m / self._max_width_m)))
        return int(frac * 255)

    def _require_gripper(self):
        if self.gripper is None:
            raise RuntimeError("Gripper not connected. Call connect() first.")
        return self.gripper

    def _ensure_async_worker(self) -> None:
        with self._async_lock:
            if self._async_thread is not None and self._async_thread.is_alive():
                return
            self._async_stop = False
            t = threading.Thread(target=self._async_loop, name="GripperClientAsync", daemon=True)
            self._async_thread = t
            t.start()

    def _async_submit(self, func: Callable, args: tuple = (), kwargs: dict = None) -> None:
        """Submit a direct function call to the async worker."""
        if kwargs is None:
            kwargs = {}
        self._ensure_async_worker()
        with self._async_lock:
            self._async_latest = (func, args, kwargs)
            self._async_cv.notify()

    def shutdown_async(self, *, join_timeout_s: float = 0.5) -> None:
        with self._async_lock:
            self._async_stop = True
            self._async_cv.notify_all()
            t = self._async_thread
        if t is not None:
            try:
                t.join(timeout=float(join_timeout_s))
            except Exception:
                pass

    def async_last_error(self) -> dict[str, Any]:
        with self._async_lock:
            return {
                "last_error": self._async_last_error,
                "last_status_code": self._async_last_status_code,
                "worker_alive": bool(self._async_thread.is_alive()) if self._async_thread is not None else False,
            }

    def _async_loop(self) -> None:
        while True:
            with self._async_lock:
                while not self._async_stop and self._async_latest is None:
                    self._async_cv.wait(timeout=0.5)
                if self._async_stop:
                    return
                item = self._async_latest
                self._async_latest = None

            if item is None:
                continue

            func, args, kwargs = item

            try:
                func(*args, **kwargs)
                
                with self._async_lock:
                    self._async_last_status_code = 200
                    self._async_last_error = None
            except Exception as e:
                print(f"gripper thread movement rejected {type(e).__name__} : {e}\n")
                with self._async_lock:
                    self._async_last_status_code = 500
                    self._async_last_error = f"{type(e).__name__}: {repr(e)}"

    def health(self) -> dict[str, Any]:
        connected = self.gripper is not None
        return {"ok": connected, "connected": connected, "is_activated": connected, "is_calibrated": connected}

    def connect(self) -> dict[str, Any]:
        if franky is None:
            raise RuntimeError("The 'franky' library is not installed in this Python environment! Please run 'pip install franky'.")
        
        try:
            self.gripper = franky.Gripper(self.franka_ip)
            try:
                self._max_width_m = getattr(self.gripper, "max_width", 0.08)
            except Exception:
                pass
            return {"connected": True, "last_connect_error": None}
        except Exception as e:
            self.gripper = None
            raise RuntimeError(f"Could not connect to Franka Gripper at IP {self.franka_ip}. Hardware error: {e}")

    def reset(self) -> dict[str, Any]:
        return {"ok": True}

    def activate(self) -> dict[str, Any]:
        return {"ok": True, "is_activated": True}

    def reset_activate(self) -> dict[str, Any]:
        return {"ok": True, "is_activated": True}

    def open(self, *, speed: int = 255, force: int = 255, wait: bool = True) -> dict[str, Any]:
        g = self._require_gripper()
        s_ms = self._speed_ms(speed)
        
        if not wait:
            self._async_submit(g.open, (s_ms,))
            return {"ok": True, "position": 0, "object_detected": False, "accepted": True}
        
        success = g.open(s_ms)
        return {"ok": True, "position": self.position()["position"], "object_detected": False, "accepted": False}

    def open_async(self, *, speed: int = 255, force: int = 255, wait: bool = False) -> None:
        g = self._require_gripper()
        self._async_submit(g.open, (self._speed_ms(speed),))

    def close(self, *, speed: int = 255, force: int = 255, wait: bool = True) -> dict[str, Any]:
        g = self._require_gripper()
        s_ms = self._speed_ms(speed)
        f_n = self._force_n(force)

        if not wait:
            self._async_submit(g.grasp, (0.0, s_ms, f_n))
            return {"ok": True, "position": 255, "object_detected": False, "accepted": True}
            
        success = g.grasp(0.0, s_ms, f_n)
        return {"ok": True, "position": self.position()["position"], "object_detected": success, "accepted": False}

    def close_async(self, *, speed: int = 255, force: int = 255, wait: bool = False) -> None:
        g = self._require_gripper()
        self._async_submit(g.grasp, (0.0, self._speed_ms(speed), self._force_n(force)))

    def go_to(self, position: int, *, speed: int = 255, force: int = 255, wait: bool = True) -> dict[str, Any]:
        g = self._require_gripper()
        s_ms = self._speed_ms(speed)
        w_m = self._pos_m(position)

        if not wait:
            self._async_submit(g.move, (w_m, s_ms))
            return {"ok": True, "position": position, "object_detected": False, "accepted": True}
            
        success = g.move(w_m, s_ms)
        return {"ok": True, "position": self.position()["position"], "object_detected": False, "accepted": False}

    def go_to_async(self, position: int, *, speed: int = 255, force: int = 255, wait: bool = False) -> None:
        g = self._require_gripper()
        width_m = self._pos_m(position)
        #print(f"Franka In: {width_m:.5f} meters")
        self._async_submit(g.move, (self._pos_m(position), self._speed_ms(speed)))

    def go_to_mm(self, position_mm: float, *, speed: int = 255, force: int = 255, wait: bool = True) -> dict[str, Any]:
        g = self._require_gripper()
        s_ms = self._speed_ms(speed)
        w_m = float(position_mm) / 1000.0

        if not wait:
            self._async_submit(g.move, (w_m, s_ms))
            return {"ok": True, "position_mm": position_mm, "accepted": True}
            
        g.move(w_m, s_ms)
        return {"ok": True, "position_mm": self.position_mm()["position_mm"], "accepted": False}

    def go_to_mm_async(self, position_mm: float, *, speed: int = 255, force: int = 255, wait: bool = False) -> None:
        g = self._require_gripper()
        self._async_submit(g.move, (float(position_mm) / 1000.0, self._speed_ms(speed)))

    def calibrate(self, *, close_mm: float, open_mm: float) -> dict[str, Any]:
        g = self._require_gripper()
        if hasattr(g, "homing"):
            g.homing()
        return {"ok": True, "is_calibrated": True}

    def is_activated(self) -> dict[str, Any]:
        return {"is_activated": self.gripper is not None, "busy": False}

    def is_calibrated(self) -> dict[str, Any]:
        return {"is_calibrated": self.gripper is not None, "busy": False}

    def position(self) -> dict[str, Any]:
        g = self._require_gripper()
        try:
            w = g.width
            return {"position": self._pos_to_bits(w), "busy": False}
        except Exception:
            return {"position": None, "busy": False}

    def position_mm(self) -> dict[str, Any]:
        g = self._require_gripper()
        try:
            return {"position_mm": g.width * 1000.0, "calibrated": True, "busy": False}
        except Exception:
            return {"position_mm": None, "calibrated": True, "busy": False}

    def status(self) -> dict[str, Any]:
        # Returns a mock structure to prevent KeyError in downstream code
        return {"param": {}, "decoded": {}, "motion": {"busy": False}}

    def gripper_state(self, *, closed_threshold: int = 128) -> dict[str, Any]:
        pos = self.position().get("position", 0)
        pos_frac = max(0.0, min(1.0, pos / 255.0))
        return {
            "connected": self.gripper is not None,
            "position_bits": pos,
            "max_position_bits": 255,
            "position_frac": pos_frac,
            "is_closed": pos >= closed_threshold,
            "is_open": pos < closed_threshold,
            "is_activated": self.gripper is not None,
            "is_calibrated": self.gripper is not None,
            "busy": False,
        }

    def gripper_position_frac(self) -> float:
        st = self.gripper_state()
        if "position_frac" in st and st["position_frac"] is not None:
            return float(st["position_frac"])
        pos = float(st.get("position_bits", 0.0) or 0.0)
        return max(0.0, min(1.0, pos / 255.0))


if __name__ == "__main__":
    c = GripperClient(base_url="10.90.90.1")
    print("health:", c.health())
    print("open:", c.open())
    print("close:", c.close())
    print("status:", c.status())