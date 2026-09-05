#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Minimal inference server for a finetuned LeRobot pi0.5 checkpoint.

Runs on the GPU host (inside the lerobot conda env). The robot machine talks to
it over an SSH tunnel with msgpack + msgpack-numpy.

    GET  /health  -> {"ok": true, "checkpoint": "...", "device": "cuda", "action_dim": 8}
    POST /infer   -> msgpack in / msgpack out
        in : {"images": {"left": u8 HxWx3, "wrist": u8 HxWx3}, "state": f32[8], "prompt": str}
        out: {"actions": f32[chunk, 8]}   (7 joint-position targets + gripper)

Deps beyond `lerobot[pi]`:  pip install msgpack msgpack-numpy

    python serve_lerobot_policy.py \
        --checkpoint ~/lerobot_ft/outputs/pi05_fr3_lift/checkpoints/last/pretrained_model \
        --repo-id    droidplus/fr3_lift \
        --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import argparse
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import msgpack
import msgpack_numpy
import numpy as np
import torch

# left exterior camera -> model "base" slot; wrist -> wrist slot.
CAM_MAP = {
    "left": "observation.images.left",
    "wrist": "observation.images.wrist",
}


class Engine:
    def __init__(self, checkpoint: str, repo_id: str | None, device: str) -> None:
        from lerobot.policies.factory import make_pre_post_processors
        from lerobot.policies.pi05.modeling_pi05 import PI05Policy

        self.checkpoint = checkpoint
        self.device = device
        self.policy = PI05Policy.from_pretrained(checkpoint)
        self.policy.to(device).eval()
        self.action_dim = 8

        kw = dict(policy_cfg=self.policy.config, pretrained_path=checkpoint)
        try:
            self.pre, self.post = make_pre_post_processors(**kw)
        except Exception:
            # Older checkpoints don't bundle processor stats -- load them from the dataset.
            from lerobot.datasets.lerobot_dataset import LeRobotDataset

            if not repo_id:
                raise
            stats = LeRobotDataset(repo_id).meta.stats
            self.pre, self.post = make_pre_post_processors(**kw, dataset_stats=stats)

        try:
            self.policy.reset()
        except Exception:
            pass

    @torch.inference_mode()
    def infer(self, obs: dict) -> np.ndarray:
        batch: dict = {}
        for name, arr in obs["images"].items():
            img = torch.as_tensor(np.asarray(arr))
            if img.dtype == torch.uint8:
                img = img.to(torch.float32) / 255.0
            img = img.permute(2, 0, 1).unsqueeze(0).to(self.device)  # (1, C, H, W) in [0, 1]
            batch[CAM_MAP.get(name, f"observation.images.{name}")] = img

        state = np.asarray(obs["state"], dtype=np.float32).reshape(-1)
        batch["observation.state"] = torch.from_numpy(state).unsqueeze(0).to(self.device)
        batch["task"] = [str(obs.get("prompt", ""))]

        batch = self.pre(batch)
        chunk = self.policy.predict_action_chunk(batch)  # (1, T, Da)
        try:
            chunk = self.post(chunk)
        except Exception:
            chunk = self.post(chunk.squeeze(0)).unsqueeze(0)
        chunk = chunk.detach().to("cpu", torch.float32).numpy()
        if chunk.ndim == 3:
            chunk = chunk[0]
        return np.ascontiguousarray(chunk[:, : self.action_dim], dtype=np.float32)


def make_handler(engine: Engine):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quieter
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.rstrip("/") == "/health":
                import json

                self._send(
                    200,
                    json.dumps(
                        {
                            "ok": True,
                            "checkpoint": engine.checkpoint,
                            "device": engine.device,
                            "action_dim": engine.action_dim,
                        }
                    ).encode(),
                    "application/json",
                )
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path.rstrip("/") != "/infer":
                self._send(404, b"not found", "text/plain")
                return
            try:
                n = int(self.headers.get("Content-Length", 0))
                obs = msgpack.unpackb(
                    self.rfile.read(n), object_hook=msgpack_numpy.decode, raw=False
                )
                actions = engine.infer(obs)
                out = msgpack.packb(
                    {"actions": actions}, default=msgpack_numpy.encode, use_bin_type=True
                )
                self._send(200, out, "application/msgpack")
            except Exception:
                traceback.print_exc()
                self._send(500, traceback.format_exc().encode(), "text/plain")

    return H


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True, help="path to .../checkpoints/<step>/pretrained_model")
    ap.add_argument("--repo-id", default=None, help="dataset repo_id (fallback for processor stats)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()

    print(f"loading {args.checkpoint} on {args.device} ...")
    engine = Engine(args.checkpoint, args.repo_id, args.device)
    # warm up
    dummy = {
        "images": {"left": np.zeros((224, 224, 3), np.uint8), "wrist": np.zeros((224, 224, 3), np.uint8)},
        "state": np.zeros((8,), np.float32),
        "prompt": "warmup",
    }
    print("warmup chunk shape:", engine.infer(dummy).shape)

    srv = ThreadingHTTPServer((args.host, args.port), make_handler(engine))
    print(f"serving on {args.host}:{args.port}  (POST /infer, GET /health)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
