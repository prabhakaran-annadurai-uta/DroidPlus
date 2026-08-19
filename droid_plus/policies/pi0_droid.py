# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import numpy as np
from openpi_client import image_tools, websocket_client_policy

from droid_plus.eval.base_client import InferenceClient

__all__ = ["Pi0DroidJointposClient"]


class Pi0DroidJointposClient(InferenceClient):
    DEFAULT_HORIZON: int = 10

    def __init__(
        self,
        remote_host: str = "localhost",
        remote_port: int = 8000,
        open_loop_horizon: int | None = None,
    ) -> None:
        super().__init__()
        self.open_loop_horizon = (
            int(open_loop_horizon) if open_loop_horizon is not None else int(self.DEFAULT_HORIZON)
        )
        print(f"[{self.__class__.__name__}] Awaiting for server on {remote_host}:{remote_port} to be ready...")
        self.client = websocket_client_policy.WebsocketClientPolicy(remote_host, remote_port)
        print(f"[{self.__class__.__name__}] Server on {remote_host}:{remote_port} is ready.")

    # ---- required hooks -----------------------------------------------

    def _extract_observation(self, raw_obs: dict, *, env_id: int = 0) -> dict:
        left_image = np.asarray(raw_obs["left_image"], dtype=np.uint8)
        wrist_image = np.asarray(raw_obs["wrist_image"], dtype=np.uint8)

        joint_position = np.asarray(raw_obs["joint_position"], dtype=np.float32).reshape(-1)
        if joint_position.shape[0] != 7:
            raise ValueError(f"joint_position must have length 7, got shape {joint_position.shape}")

        gp = raw_obs.get("gripper_position", 0.0)
        gripper_position = (
            float(np.asarray(gp, dtype=np.float32).reshape(-1)[0]) if gp is not None else 0.0
        )

        return {
            "left_image": left_image,
            "wrist_image": wrist_image,
            "joint_position": joint_position,
            "gripper_position": gripper_position,
        }

    def _pack_request(self, extracted_obs: dict, instruction: str) -> dict:
        return {
            "observation/exterior_image_1_left": image_tools.resize_with_pad(
                extracted_obs["left_image"], 224, 224
            ),
            "observation/wrist_image_left": image_tools.resize_with_pad(
                extracted_obs["wrist_image"], 224, 224
            ),
            "observation/joint_position": extracted_obs["joint_position"],
            "observation/gripper_position": extracted_obs["gripper_position"],
            "prompt": instruction,
        }

    def _query_server(self, request: dict) -> dict:
        return self.client.infer(request)

    def _unpack_response(self, response: dict) -> np.ndarray:
        if "actions" not in response:
            raise KeyError("Policy response missing 'actions' field")

        chunk = np.asarray(response["actions"], dtype=np.float32)
        if chunk.ndim == 1:
            chunk = chunk.reshape(1, -1)
        if chunk.ndim != 2:
            raise ValueError(f"Expected actions chunk with 2 dims, got shape {chunk.shape}")
        if int(chunk.shape[0]) < int(self.open_loop_horizon):
            raise ValueError(
                f"Expected actions chunk length >= {int(self.open_loop_horizon)}, got {int(chunk.shape[0])}"
            )
        if int(chunk.shape[1]) < 7:
            raise ValueError(f"Expected action_dim >= 7, got {int(chunk.shape[1])}")
        return chunk[: int(self.open_loop_horizon)]

    # ---- optional hooks -----------------------------------------------

    def _postprocess_chunk(self, chunk: np.ndarray) -> np.ndarray:
        # Binarize gripper column for chunks served via infer() (per-step).
        chunk = chunk.copy()
        chunk[..., -1] = (chunk[..., -1] > 0.5).astype(chunk.dtype)
        return chunk

    def _build_visualization(self, extracted_obs: dict) -> np.ndarray:
        img1 = image_tools.resize_with_pad(extracted_obs["left_image"], 224, 224)
        img2 = image_tools.resize_with_pad(extracted_obs["wrist_image"], 224, 224)
        return np.concatenate([img1, img2], axis=1)

    # ---- droid-plus specific extension --------------------------------

    def infer_chunk(self, obs: dict, instruction: str, *, env_id: int = 0) -> np.ndarray:
        """Query the server and return the *raw* action chunk.

        The chunk is NOT passed through ``_postprocess_chunk``; the caller is
        responsible for interpreting the gripper column (episode_runner does
        its own binarization). No internal chunk state is modified, so this
        method does not interfere with a later ``infer()`` call.
        """
        extracted = self._extract_observation(obs, env_id=env_id)
        request = self._pack_request(extracted, instruction)
        response = self._query_server(request)
        return self._unpack_response(response)


if __name__ == "__main__":
    fake_obs = {
        "left_image": np.zeros((224, 224, 3), dtype=np.uint8),
        "wrist_image": np.zeros((224, 224, 3), dtype=np.uint8),
        "joint_position": np.zeros((7,), dtype=np.float32),
        "gripper_position": 0.0,
    }
    fake_instruction = "pick up the object"

    import time

    start = time.time()
    client = Pi0DroidJointposClient()
    client.infer(fake_obs, fake_instruction)  # warm up
    num = 20
    for _ in range(num):
        ret = client.infer(fake_obs, fake_instruction)
        print(ret["action"].shape)
    end = time.time()

    print(f"Average inference time: {(end - start) / num}")
