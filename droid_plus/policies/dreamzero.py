# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""DreamZero VLA client for droid-plus.

Mirrors ``robolab/robolab_policy_client/dreamzero.py`` so the real-robot
stack speaks the same wire protocol as the sim stack. The only piece that
differs is ``_extract_observation``, which consumes the flat numpy dict
produced by the DROID robot (left_image / wrist_image / joint_position /
gripper_position) rather than the nested torch-batched dict from IsaacLab.

DreamZero is a world model that predicts future observations while predicting
actions. It uses the roboarena WebSocket protocol, with:
  - Support for multiple external cameras (2 for DROID)
  - Temporal frame input (can send multiple frames for temporal context)
  - Session ID tracking for episode-level history
  - Action chunks output (N, 8)
"""

import logging
import time
import uuid

import numpy as np
import websockets.sync.client

from droid_plus.eval.base_client import InferenceClient

logger = logging.getLogger(__name__)

# Increase timeouts for DreamZero's longer inference times (world model prediction)
PING_INTERVAL_SECS = 60
PING_TIMEOUT_SECS = 600

# Connection safeguards
CONNECT_TIMEOUT_SECS = 300
RECV_TIMEOUT_SECS = 300
MAX_CONNECT_RETRIES = 5
MAX_INFER_RETRIES = 3
RETRY_BACKOFF_BASE_SECS = 2


class MsgPackNumpy:
    """Simple msgpack wrapper with numpy support.

    Mirrors the client_lib.msgpack_numpy from dreamzero.
    """

    def __init__(self):
        import msgpack
        self._msgpack = msgpack

    def pack(self, obj):
        # Don't use strict_types=True - it breaks tuple serialization
        return self._msgpack.packb(obj, default=self._encode_numpy)

    def unpack(self, data):
        return self._msgpack.unpackb(data, object_hook=self._decode_numpy, strict_map_key=False)

    def _encode_numpy(self, obj):
        if isinstance(obj, np.ndarray):
            if obj.dtype.kind in ("V", "O", "c"):
                raise ValueError(f"Unsupported dtype: {obj.dtype}")
            return {
                b"__ndarray__": True,
                b"data": obj.tobytes(),
                b"dtype": obj.dtype.str,
                b"shape": obj.shape,
            }

        if isinstance(obj, np.generic):
            return {
                b"__npgeneric__": True,
                b"data": obj.item(),
                b"dtype": obj.dtype.str,
            }

        return obj

    def _decode_numpy(self, obj):
        if b"__ndarray__" in obj:
            return np.ndarray(buffer=obj[b"data"], dtype=np.dtype(obj[b"dtype"]), shape=obj[b"shape"])
        if b"__npgeneric__" in obj:
            return np.dtype(obj[b"dtype"]).type(obj[b"data"])
        return obj


class DreamZeroClient(InferenceClient):
    """Inference client for DreamZero VLA model driving the real DROID.

    DreamZero uses the roboarena WebSocket protocol with:
      - 2 external cameras + 1 wrist camera
      - Image resolution: 180x320 (H x W) for DROID config
      - Joint position action space (7 DoF + gripper)
      - Session ID for episode tracking
      - Action chunks output
    """

    def __init__(
        self,
        remote_host: str = "localhost",
        remote_port: int = 5000,
        open_loop_horizon: int = 8,
        image_height: int = 180,
        image_width: int = 320,
    ) -> None:
        super().__init__()
        self.host = remote_host
        self.port = remote_port
        self.open_loop_horizon = int(open_loop_horizon)
        self.image_height = image_height
        self.image_width = image_width

        # Per-env session IDs. The server uses session_id to track temporal
        # history. Droid-plus runs one env at a time in practice, but keeping
        # the dict mirrors the sim side and costs nothing.
        self._env_session_id: dict[int, str] = {}

        # MsgPack for numpy serialization
        self._packer = MsgPackNumpy()

        # Connect to server
        self._uri = f"ws://{remote_host}:{remote_port}"
        self._ws = None
        self._connect_with_retries()

    # ---- required hooks -----------------------------------------------

    def _extract_observation(self, raw_obs: dict, *, env_id: int = 0) -> dict:
        """Flatten the real-robot obs dict into DZ's expected shape.

        Expected input:
          - raw_obs["left_image"]:      (H, W, 3) uint8
          - raw_obs["wrist_image"]:     (H, W, 3) uint8
          - raw_obs["joint_position"]:  (7,) float
          - raw_obs["gripper_position"]: scalar or (1,) float (optional; default 0.0)

        DROID has one external camera (left_image); DZ expects two
        external feeds, so _pack_request duplicates this image into both
        exterior_image_0_left and exterior_image_1_left on the wire.
        """
        left_image = np.asarray(raw_obs["left_image"], dtype=np.uint8)
        wrist_image = np.asarray(raw_obs["wrist_image"], dtype=np.uint8)

        joint_position = np.asarray(raw_obs["joint_position"], dtype=np.float32).reshape(-1)
        if joint_position.shape[0] != 7:
            raise ValueError(f"joint_position must have length 7, got shape {joint_position.shape}")

        gp = raw_obs.get("gripper_position", 0.0)
        gripper_position = np.array(
            [float(np.asarray(gp, dtype=np.float32).reshape(-1)[0]) if gp is not None else 0.0],
            dtype=np.float32,
        )

        # Lazy-init a stable session_id per env so the server can thread
        # temporal history correctly across parallel envs (or across sequential
        # episodes if reset() isn't called).
        if env_id not in self._env_session_id:
            self._env_session_id[env_id] = str(uuid.uuid4())

        return {
            "right_image": left_image,   # DZ wire keys use 'right_image' internally; DROID only has one external cam
            "wrist_image": wrist_image,
            "joint_position": joint_position,
            "gripper_position": gripper_position,
            "session_id": self._env_session_id[env_id],
        }

    def _pack_request(self, extracted_obs: dict, instruction: str) -> dict:
        right_resized = self._resize_image(extracted_obs["right_image"], self.image_height, self.image_width)
        wrist_resized = self._resize_image(extracted_obs["wrist_image"], self.image_height, self.image_width)
        return {
            "observation/exterior_image_0_left": right_resized,
            # Using same image for both when only one external camera is available
            "observation/exterior_image_1_left": right_resized,
            "observation/wrist_image_left": wrist_resized,
            "observation/joint_position": extracted_obs["joint_position"],
            "observation/cartesian_position": np.zeros(6, dtype=np.float32),
            "observation/gripper_position": extracted_obs["gripper_position"],
            "prompt": instruction,
            "session_id": extracted_obs["session_id"],
            "endpoint": "infer",
        }

    def _query_server(self, request: dict):
        raw = self._send_recv(self._packer.pack(request))
        if isinstance(raw, str):
            raise RuntimeError(f"DreamZero server error:\n{raw}")
        return self._packer.unpack(raw)

    def _unpack_response(self, response) -> np.ndarray:
        if isinstance(response, dict):
            response = response.get("actions", response)
        chunk = np.asarray(response)
        if chunk.ndim == 1:
            chunk = chunk.reshape(1, -1)
        return chunk

    # ---- optional hooks -----------------------------------------------

    def _postprocess_chunk(self, chunk: np.ndarray) -> np.ndarray:
        # DreamZero emits continuous gripper values that the downstream
        # controller interprets directly. Do not binarize here.
        chunk = chunk.copy()
        if chunk.shape[-1] == 7:
            pad = np.zeros((*chunk.shape[:-1], 1), dtype=chunk.dtype)
            chunk = np.concatenate([chunk, pad], axis=-1)
        return chunk

    def _build_visualization(self, extracted_obs: dict) -> np.ndarray:
        img1 = self._resize_image(extracted_obs["right_image"], self.image_height, self.image_width)
        img2 = self._resize_image(extracted_obs["wrist_image"], self.image_height, self.image_width)
        return np.concatenate([img1, img2], axis=1)

    # ---- lifecycle overrides ------------------------------------------

    def reset(self, *, env_id: int | None = None) -> None:
        """Notify server, clear per-env session ids, then clear chunk state."""
        self._send_recv(self._packer.pack({"endpoint": "reset"}))
        if env_id is None:
            self._env_session_id.clear()
        else:
            self._env_session_id.pop(env_id, None)
        super().reset(env_id=env_id)
        print(f"[{self.__class__.__name__}] Reset complete (env_id={env_id}).")

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    # ---- connection internals -----------------------------------------

    @staticmethod
    def _wait_with_progress(tag: str, label: str, duration: float, interval: float = 5.0):
        """Sleep for *duration* seconds, printing a progress bar to stdout."""
        elapsed = 0.0
        width = 30
        while elapsed < duration:
            step = min(interval, duration - elapsed)
            time.sleep(step)
            elapsed += step
            frac = elapsed / duration
            filled = int(width * frac)
            bar = "=" * filled + "-" * (width - filled)
            mins_left = (duration - elapsed) / 60
            print(f"\r{tag} {label} [{bar}] {frac*100:5.1f}%  {mins_left:.1f}m left", end="", flush=True)
        print()

    def _connect_with_retries(self):
        """Establish WebSocket connection with retries and exponential backoff."""
        tag = f"[{self.__class__.__name__}]"
        print(f"{tag} Connecting to DreamZero server at {self._uri}...")

        for attempt in range(1, MAX_CONNECT_RETRIES + 1):
            if attempt > 1:
                print(f"{tag} Connection attempt {attempt}/{MAX_CONNECT_RETRIES}...")
            try:
                try:
                    self._ws = websockets.sync.client.connect(
                        self._uri,
                        compression=None,
                        max_size=None,
                        open_timeout=CONNECT_TIMEOUT_SECS,
                        ping_interval=PING_INTERVAL_SECS,
                        ping_timeout=PING_TIMEOUT_SECS,
                    )
                except TypeError:
                    # Older websockets lacks ping_interval/ping_timeout kwargs
                    self._ws = websockets.sync.client.connect(
                        self._uri,
                        compression=None,
                        max_size=None,
                        open_timeout=CONNECT_TIMEOUT_SECS,
                    )

                self._server_metadata = self._packer.unpack(
                    self._ws.recv(timeout=RECV_TIMEOUT_SECS)
                )
                print(f"{tag} Server metadata: {self._server_metadata}")
                print(f"{tag} Connected successfully.")
                return

            except Exception as e:
                if self._ws is not None:
                    try:
                        self._ws.close()
                    except Exception:
                        pass
                    self._ws = None

                if attempt == MAX_CONNECT_RETRIES:
                    raise ConnectionError(
                        f"{tag} Failed to connect after {MAX_CONNECT_RETRIES} attempts. "
                        f"Last error: {e}"
                    ) from e

                wait = RETRY_BACKOFF_BASE_SECS ** attempt
                logger.warning(
                    "%s Connection attempt %d/%d failed (%s). Retrying in %.1fs...",
                    tag, attempt, MAX_CONNECT_RETRIES, e, wait,
                )
                print(f"{tag} Connection attempt {attempt}/{MAX_CONNECT_RETRIES} failed ({e}).")
                self._wait_with_progress(tag, "Waiting to retry", wait)

    def _ensure_connected(self):
        """Reconnect if the WebSocket has been closed or lost."""
        try:
            if self._ws is not None and self._ws.socket is not None:
                return
        except Exception:
            pass
        tag = f"[{self.__class__.__name__}]"
        print(f"{tag} Connection lost. Reconnecting...")
        self._connect_with_retries()

    def _send_recv(self, data: bytes, *, timeout: float = RECV_TIMEOUT_SECS) -> bytes:
        """Send packed data and receive response with timeout and auto-reconnect."""
        tag = f"[{self.__class__.__name__}]"
        last_exc = None

        for attempt in range(1, MAX_INFER_RETRIES + 1):
            if attempt > 1:
                print(f"{tag} send/recv attempt {attempt}/{MAX_INFER_RETRIES}...")
            try:
                self._ensure_connected()
                assert self._ws is not None
                self._ws.send(data)
                return self._ws.recv(timeout=timeout)
            except Exception as e:
                last_exc = e
                if self._ws is not None:
                    try:
                        self._ws.close()
                    except Exception:
                        pass
                    self._ws = None

                if attempt == MAX_INFER_RETRIES:
                    break

                wait = RETRY_BACKOFF_BASE_SECS * attempt
                logger.warning(
                    "%s send/recv attempt %d/%d failed (%s). Reconnecting in %.1fs...",
                    tag, attempt, MAX_INFER_RETRIES, e, wait,
                )
                print(f"{tag} send/recv attempt {attempt}/{MAX_INFER_RETRIES} failed ({e}).")
                self._wait_with_progress(tag, "Waiting to reconnect", wait)

        raise ConnectionError(
            f"{tag} send/recv failed after {MAX_INFER_RETRIES} attempts. "
            f"Last error: {last_exc}"
        ) from last_exc

    def _resize_image(self, image: np.ndarray, height: int, width: int) -> np.ndarray:
        # Aspect-preserving resize to (height, width), padded with zeros.
        # Replicates tf.image.resize_with_pad (what the DreamZero training
        # pipeline uses); see droid_plus/policies/image_tools.py.
        from .image_tools import resize_with_pad
        return resize_with_pad(image, height, width)


if __name__ == "__main__":
    client = DreamZeroClient(remote_host="localhost", remote_port=5000)

    fake_obs = {
        "left_image": np.zeros((180, 320, 3), dtype=np.uint8),
        "wrist_image": np.zeros((180, 320, 3), dtype=np.uint8),
        "joint_position": np.zeros((7,), dtype=np.float32),
        "gripper_position": 0.0,
    }
    fake_instruction = "pick up the object"

    print("Testing inference...")
    ret = client.infer(fake_obs, fake_instruction)
    print(f"Action shape: {ret['action'].shape}")
    print(f"Action: {ret['action']}")

    print("\nTesting reset...")
    client.reset()
    print("Done.")
