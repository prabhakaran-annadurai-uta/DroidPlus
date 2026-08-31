"""
Intel RealSense camera snapshot service for Droid Plus.

Run:
  python realsense_camera_service.py

Endpoints:
  GET /health
  GET /cameras
  GET /camera/{camera_id}/calibration
  GET /camera/{camera_id}/rgb.jpg
  GET /camera/{camera_id}/depth.png?scale=10
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import pyrealsense2 as rs
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response

LOG = logging.getLogger("camera_service")

DEFAULT_SERVICE_PORT = 54322
DEFAULT_RGB_OUT_W = int(os.getenv("CAMERA_RGB_OUT_W", "0") or "0")
DEFAULT_RGB_OUT_H = int(os.getenv("CAMERA_RGB_OUT_H", "0") or "0")
DEFAULT_CORS_ALLOW_ORIGINS = os.getenv("CAMERA_CORS_ALLOW_ORIGINS", "*").strip()


LANDING_PAGE_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>camera_service (RealSense)</title>
    <style>
      :root { color-scheme: dark; }
      body { margin: 24px; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; background: #0b0f14; color: #e6edf3; }
      .row { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-start; }
      .card { background: #0f1620; border: 1px solid #223042; border-radius: 10px; padding: 14px 14px; min-width: 360px; flex: 1; }
      .title { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; font-size: 16px; font-weight: 700; margin: 0 0 8px; }
      .muted { color: #9fb2c8; }
      .kv { display: grid; grid-template-columns: 140px 1fr; gap: 6px 10px; font-size: 13px; }
      .ok { color: #3fb950; }
      .bad { color: #f85149; }
      .badge { display: inline-block; padding: 3px 10px; border-radius: 6px; font-size: 13px; font-weight: 700; letter-spacing: 0.3px; }
      .badge-ok { background: #0d2818; color: #3fb950; border: 1px solid #1a4028; }
      .badge-warn { background: #2d2000; color: #d29922; border: 1px solid #4a3500; }
      .badge-bad { background: #2d0a0a; color: #f85149; border: 1px solid #4a1414; }
      .card-ok { border-color: #1a4028; }
      .card-bad { border-color: #4a1414; }
      img { width: 100%; height: auto; border-radius: 10px; border: 1px solid #223042; background: #0b111a; }
      code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; font-size: 12px; }
      pre { margin: 8px 0 0; padding: 10px; background: #0b111a; border: 1px solid #223042; border-radius: 8px; overflow: auto; max-height: 300px; }
      button { background: #223042; color: #e6edf3; border: 1px solid #2b3b52; padding: 6px 10px; border-radius: 8px; cursor: pointer; }
      button.primary { background: #1f6feb; border-color: #1f6feb; }
      input { background: #0b111a; color: #e6edf3; border: 1px solid #223042; border-radius: 8px; padding: 6px 8px; width: 90px; }
      .controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 10px 0 0; }
    </style>
  </head>
  <body>
    <div class="row" style="align-items: center;">
      <div style="font-size: 18px; font-weight: 800;">camera_service</div>
      <span id="global_badge" class="badge badge-warn">...</span>
      <div class="muted">Live RGB preview + metadata (auto-refresh).</div>
    </div>

    <div class="controls">
      <button class="primary" onclick="refreshOnce()">Refresh now</button>
      <button class="secondary" onclick="doRescan()">Rescan cameras</button>
      <span class="muted">jpeg_quality</span><input id="jpeg_quality" type="number" min="1" max="100" step="1" value="90" />
      <span class="muted">fps</span><input id="ui_fps" type="number" min="1" max="60" step="1" value="15" />
      <span class="muted">manager_hz</span><code id="camera_hz">...</code>
      <span class="muted">num_cameras</span><code id="num_cameras">...</code>
      <span class="muted">manager_error</span><code id="manager_error">...</code>
    </div>

    <div style="height: 14px"></div>
    <div id="cards" class="row"></div>

    <div style="height: 14px"></div>
    <div class="card" style="min-width: 720px;">
      <div class="title"><div>raw_health</div><div class="muted">GET <code>/health</code></div></div>
      <pre><code id="raw_health">Loading...</code></pre>
    </div>

    <script>
      let cameraList = []; 
      let health = null;   

      function $(id) { return document.getElementById(id); }

      function setText(id, val, cls=null) {
        const el = $(id);
        if (!el) return;
        el.textContent = (val === undefined || val === null) ? "" : String(val);
        el.className = cls ? cls : "";
      }

      function setJson(id, obj) {
        const el = $(id);
        if (!el) return;
        el.textContent = JSON.stringify(obj, null, 2);
      }

      async function fetchJson(path) {
        const r = await fetch(path, { cache: "no-store" });
        const txt = await r.text();
        let data;
        try { data = JSON.parse(txt); } catch { data = { raw: txt }; }
        if (!r.ok) throw { status: r.status, data };
        return data;
      }

      function getUiParams() {
        const jq = Number(($("jpeg_quality") && $("jpeg_quality").value) ? $("jpeg_quality").value : 90);
        const fps = Number(($("ui_fps") && $("ui_fps").value) ? $("ui_fps").value : 5);
        return {
          jpeg_quality: (Number.isFinite(jq) && jq >= 1 && jq <= 100) ? jq : 85,
          ui_fps: (Number.isFinite(fps) && fps >= 1 && fps <= 60) ? fps : 5,
        };
      }

      function ensureCard(camera_id) {
        const root = $("cards");
        const existing = $("cam_" + camera_id);
        if (existing) return existing;

        const card = document.createElement("div");
        card.className = "card";
        card.id = "cam_" + camera_id;
        card.innerHTML = `
          <div class="title">
            <div>camera <code>${camera_id}</code></div>
            <div class="muted"><a href="/camera/${camera_id}/rgb.jpg" target="_blank">rgb.jpg</a> · <a href="/camera/${camera_id}/depth.png" target="_blank">depth.png</a> · <a href="/camera/${camera_id}/calibration" target="_blank">calibration</a></div>
          </div>
          <div class="kv">
            <div class="muted">model</div><div><code id="model_${camera_id}">...</code></div>
            <div class="muted">resolution</div><div><code id="res_${camera_id}">...</code></div>
            <div class="muted">fps</div><div><code id="fps_${camera_id}">...</code></div>
            <div class="muted">has_frame</div><div><code id="has_${camera_id}">...</code></div>
            <div class="muted">last_frame_age_s</div><div><code id="age_${camera_id}">...</code></div>
            <div class="muted">grab_count</div><div><code id="grab_${camera_id}">...</code></div>
            <div class="muted">last_error</div><div><code id="err_${camera_id}">...</code></div>
            <div class="muted">left_fx_fy</div><div><code id="intr_${camera_id}">...</code></div>
            <div class="muted">left_cx_cy</div><div><code id="pp_${camera_id}">...</code></div>
          </div>
          <div style="height: 10px"></div>
          <img id="img_${camera_id}" alt="rgb ${camera_id}" />
        `;
        root.appendChild(card);
        return card;
      }

      function updateCards() {
        const params = getUiParams();
        const perCam = (health && health.cameras) ? health.cameras : {};

        const knownIds = new Set(cameraList.map(c => c.camera_id));
        for (const cid of Object.keys(perCam)) knownIds.add(cid);

        for (const cid of knownIds) {
          ensureCard(cid);

          const cam = cameraList.find(c => c.camera_id === cid);
          const h = perCam[cid] || {};

          setText("model_" + cid, (cam && cam.model) || h.model || "");
          setText("res_" + cid, cam ? `${cam.resolution.width}x${cam.resolution.height}` : "");
          setText("fps_" + cid, cam ? cam.fps : "");

          const has = !!h.has_frame;
          const cardEl = $("cam_" + cid);
          if (cardEl) cardEl.className = "card " + (has ? "card-ok" : "card-bad");
          setText("has_" + cid, has, has ? "ok" : "bad");
          setText("age_" + cid, (h.last_frame_age_s === null || h.last_frame_age_s === undefined) ? "" : h.last_frame_age_s.toFixed(3));
          setText("grab_" + cid, (h.grab_count === undefined) ? "" : h.grab_count);
          setText("err_" + cid, h.last_error || "");

          const img = $("img_" + cid);
          if (img) {
            if (has) {
              img.src = `/camera/${cid}/rgb.jpg?jpeg_quality=${params.jpeg_quality}&t=${Date.now()}`;
            } else {
              img.removeAttribute("src");
            }
          }
        }
      }

      async function refreshOnce() {
        try {
          const [cams, h] = await Promise.all([
            fetchJson("/cameras"),
            fetchJson("/health"),
          ]);
          cameraList = (cams && cams.cameras) ? cams.cameras : [];
          health = h;

          setText("camera_hz", (h && h.camera_hz !== undefined) ? h.camera_hz : "");
          setText("num_cameras", (h && h.num_cameras !== undefined) ? h.num_cameras : cameraList.length);
          setText("manager_error", (h && h.manager_error) ? h.manager_error : "");
          setJson("raw_health", h);

          const perCamAll = (h && h.cameras) ? Object.values(h.cameras) : [];
          const nLive = perCamAll.filter(c => c.has_frame).length;
          const nTotal = perCamAll.length;
          const badge = $("global_badge");
          if (badge) {
            if (nTotal === 0) {
              badge.textContent = "NO CAMERAS";
              badge.className = "badge badge-bad";
            } else if (nLive === nTotal) {
              badge.textContent = "ALL CAMERAS LIVE";
              badge.className = "badge badge-ok";
            } else {
              badge.textContent = nLive + "/" + nTotal + " CAMERAS LIVE";
              badge.className = "badge badge-" + (nLive === 0 ? "bad" : "warn");
            }
          }

          updateCards();

          const perCam = cameraList.map(c => c.camera_id);
          await Promise.all(perCam.map(async (cid) => {
            try {
              const cal = await fetchJson(`/camera/${cid}/calibration`);
              const lc = (cal && cal.left_cam) ? cal.left_cam : null;
              if (lc) {
                setText("intr_" + cid, `${Number(lc.fx).toFixed(2)}  ${Number(lc.fy).toFixed(2)}`);
                setText("pp_" + cid, `${Number(lc.cx).toFixed(2)}  ${Number(lc.cy).toFixed(2)}`);
              } else {
                setText("intr_" + cid, "");
                setText("pp_" + cid, "");
              }
            } catch (e) {
              setText("intr_" + cid, "");
              setText("pp_" + cid, "");
            }
          }));
        } catch (e) {
          setText("manager_error", (e && e.data) ? JSON.stringify(e.data) : String(e), "bad");
        }
      }

      async function doRescan() {
        try {
          await fetch("/rescan", { method: "POST" });
        } finally {
          await refreshOnce();
        }
      }

      function startLoop() {
        refreshOnce();
        setInterval(refreshOnce, 1000);
        setInterval(updateCards, Math.floor(1000 / getUiParams().ui_fps));
      }

      startLoop();
    </script>
  </body>
</html>
"""


@dataclass
class RSFrame:
    timestamp_s: float
    rgb_rgba: np.ndarray
    depth_mm: np.ndarray

@dataclass
class RSCameraInfo:
    camera_id: str
    model: str
    resolution: tuple[int, int]
    fps: int

class RealsenseCameraManager:

    def __init__(self, camera_hz: int = 30):
        self.camera_hz = camera_hz
        self._lock = threading.Lock()
        self._running = False
        self._ctx = rs.context()
        
        self._pipelines: dict[str, rs.pipeline] = {}
        self._profiles: dict[str, rs.pipeline_profile] = {}
        self._aligns: dict[str, rs.align] = {}
        self._depth_scales: dict[str, float] = {}
        
        self._infos: dict[str, RSCameraInfo] = {}
        self._frames: dict[str, RSFrame] = {}
        self._cals: dict[str, dict] = {}
        self._health_stats: dict[str, dict] = {}
        
        self._manager_error = ""
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @staticmethod
    def default_camera_hz_from_env() -> int:
        return int(os.getenv("CAMERA_HZ", "30"))

    def start(self, allow_no_camera: bool = False):
        self._running = True
        self.rescan(force=True)
        if not self._infos and not allow_no_camera:
            raise RuntimeError("No RealSense cameras found")
            
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join()
            
        with self._lock:
            for pipe in self._pipelines.values():
                try: pipe.stop()
                except Exception: pass
            self._pipelines.clear()
            self._profiles.clear()

    def rescan(self, force: bool = False):
        devices = self._ctx.query_devices()
        new_devices = []
        for dev in devices:
            sn = dev.get_info(rs.camera_info.serial_number)
            with self._lock:
                if sn not in self._pipelines:
                    new_devices.append(dev)
                    
        for dev in new_devices:
            sn = dev.get_info(rs.camera_info.serial_number)
            model = dev.get_info(rs.camera_info.name)
            
            pipe = rs.pipeline(self._ctx)
            cfg = rs.config()
            cfg.enable_device(sn)
            
            cfg.enable_stream(rs.stream.color)
            
            cfg.enable_stream(rs.stream.depth)
            
            try:
                prof = pipe.start(cfg)
                align = rs.align(rs.stream.color)
                
                color_stream = prof.get_stream(rs.stream.color).as_video_stream_profile()
                intr = color_stream.get_intrinsics()
                depth_sensor = prof.get_device().first_depth_sensor()
                scale = depth_sensor.get_depth_scale()
                
                w, h = intr.width, intr.height
                fps = color_stream.fps()
                
                with self._lock:
                    self._pipelines[sn] = pipe
                    self._profiles[sn] = prof
                    self._aligns[sn] = align
                    self._depth_scales[sn] = scale
                    
                    self._infos[sn] = RSCameraInfo(
                        camera_id=sn, model=model, resolution=(w, h), fps=fps
                    )
                    self._cals[sn] = {
                        "left_cam": {
                            "fx": intr.fx, "fy": intr.fy,
                            "cx": intr.ppx, "cy": intr.ppy
                        }
                    }
                    self._health_stats[sn] = {
                        "grab_count": 0,
                        "last_error": "",
                        "last_timestamp_s": 0.0,
                    }
            except Exception as e:
                LOG.error(f"Failed to start realsense camera {sn}: {e}")
                self._manager_error = str(e)

    def _loop(self):
        while self._running:
            with self._lock:
                pipes = list(self._pipelines.items())
                
            for sn, pipe in pipes:
                try:
                    success, frames = pipe.try_wait_for_frames(timeout_ms=50)
                    if not success or not frames:
                        continue
                        
                    with self._lock:
                        align = self._aligns.get(sn)
                        scale = self._depth_scales.get(sn)
                    if align is None:
                        continue
                        
                    aligned = align.process(frames)
                    depth_fr = aligned.get_depth_frame()
                    color_fr = aligned.get_color_frame()
                    
                    if not depth_fr or not color_fr:
                        continue
                        
                    timestamp_s = color_fr.get_timestamp() / 1000.0  
                    
                    depth_u16 = np.asanyarray(depth_fr.get_data())
                    color_bgr = np.asanyarray(color_fr.get_data())
                    
                    depth_mm = (depth_u16.astype(np.float32) * (scale * 1000.0)).astype(np.float32)
                    depth_mm[depth_u16 == 0] = np.nan
                    
                    with self._lock:
                        self._frames[sn] = RSFrame(
                            timestamp_s=timestamp_s,
                            rgb_rgba=color_bgr,
                            depth_mm=depth_mm
                        )
                        stats = self._health_stats[sn]
                        stats["grab_count"] += 1
                        stats["last_timestamp_s"] = time.time()
                        stats["last_error"] = ""
                except Exception as e:
                    with self._lock:
                        if sn in self._health_stats:
                            self._health_stats[sn]["last_error"] = str(e)
            
            time.sleep(0.005)

    def list_cameras(self) -> list[RSCameraInfo]:
        with self._lock:
            return list(self._infos.values())

    def get_calibration(self, sn: str) -> dict:
        with self._lock:
            return self._cals.get(sn, {})

    def get_latest(self, sn: str) -> RSFrame | None:
        with self._lock:
            return self._frames.get(sn)

    def get_status(self) -> dict:
        with self._lock:
            now = time.time()
            cams = {}
            for sn, info in self._infos.items():
                st = self._health_stats.get(sn, {})
                last_ts = st.get("last_timestamp_s", 0)
                age = (now - last_ts) if last_ts > 0 else None
                cams[sn] = {
                    "model": info.model,
                    "has_frame": age is not None and age < 2.0,
                    "last_frame_age_s": age,
                    "grab_count": st.get("grab_count", 0),
                    "last_error": st.get("last_error", "")
                }
            
            return {
                "camera_hz": self.camera_hz,
                "num_cameras": len(self._infos),
                "manager_error": self._manager_error,
                "cameras": cams
            }


@dataclass
class AppState:
    mgr: RealsenseCameraManager
    encode_locks: dict[str, threading.Lock]
    rescan_lock: threading.Lock

def _get_state(request: Request) -> AppState:
    return request.app.state.camera_state

def _require_camera(state: AppState, camera_id: str) -> None:
    cams = {c.camera_id for c in state.mgr.list_cameras()}
    if camera_id not in cams:
        raise HTTPException(status_code=404, detail=f"Unknown camera_id {camera_id}. Use /cameras.")

@asynccontextmanager
async def _lifespan(app: FastAPI):
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

    camera_hz = RealsenseCameraManager.default_camera_hz_from_env()
    mgr = RealsenseCameraManager(camera_hz=camera_hz)
    
    try:
        mgr.start(allow_no_camera=True)
    except Exception as e:
        LOG.exception("RealsenseCameraManager.start failed; continuing with no cameras.")
        try:
            with mgr._lock:  
                mgr._manager_error = f"{type(e).__name__}: {e}"
        except Exception:
            pass

    encode_locks = {c.camera_id: threading.Lock() for c in mgr.list_cameras()}
    app.state.camera_state = AppState(mgr=mgr, encode_locks=encode_locks, rescan_lock=threading.Lock())

    try:
        yield
    finally:
        mgr.stop()


app = FastAPI(lifespan=_lifespan)
_cors_origins = [o.strip() for o in DEFAULT_CORS_ALLOW_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins if _cors_origins else ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Frame-Timestamp-S", "X-Depth-Unit", "X-Depth-Scale"],
)

@app.get("/")
def root():
    return HTMLResponse(content=LANDING_PAGE_HTML)

@app.post("/rescan")
def rescan(request: Request):
    st = _get_state(request)
    if not st.rescan_lock.acquire(blocking=False):
        return {"started": False, "detail": "rescan already running"}
    def _run():
        try:
            st.mgr.rescan(force=True)
        finally:
            st.rescan_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}

@app.get("/health")
def health(request: Request):
    st = _get_state(request)
    return st.mgr.get_status()

@app.get("/cameras")
def cameras(request: Request):
    st = _get_state(request)
    cams = st.mgr.list_cameras()
    return {
        "cameras": [
            {
                "camera_id": c.camera_id,
                "model": c.model,
                "resolution": {"width": c.resolution[0], "height": c.resolution[1]},
                "fps": c.fps,
            }
            for c in cams
        ]
    }

@app.get("/camera/{camera_id}/calibration")
def calibration(camera_id: str, request: Request):
    st = _get_state(request)
    _require_camera(st, camera_id)
    return st.mgr.get_calibration(camera_id)

def _encode_rgb_jpeg(
    rgb_rgba: np.ndarray,
    *,
    jpeg_quality: int = 90,
    out_w: int | None = None,
    out_h: int | None = None,
) -> bytes:
    if len(rgb_rgba.shape) == 3 and rgb_rgba.shape[2] == 4:
        bgr = cv2.cvtColor(rgb_rgba, cv2.COLOR_BGRA2BGR)
    elif len(rgb_rgba.shape) == 3 and rgb_rgba.shape[2] == 3:
        #bgr = rgb_rgba 
        bgr = cv2.cvtColor(rgb_rgba, cv2.COLOR_RGB2BGR)
    else:
        bgr = rgb_rgba

    if out_w is None:
        out_w = DEFAULT_RGB_OUT_W if DEFAULT_RGB_OUT_W > 0 else None
    if out_h is None:
        out_h = DEFAULT_RGB_OUT_H if DEFAULT_RGB_OUT_H > 0 else None
        
    if out_w is not None and out_h is not None:
        ow = int(out_w)
        oh = int(out_h)
        if ow > 0 and oh > 0 and (bgr.shape[1] != ow or bgr.shape[0] != oh):
            bgr = cv2.resize(bgr, (ow, oh), interpolation=cv2.INTER_AREA if (ow < bgr.shape[1] or oh < bgr.shape[0]) else cv2.INTER_LINEAR)
            
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
    if not ok:
        raise RuntimeError("Failed to encode JPEG")
    return bytes(buf)

@app.get("/camera/{camera_id}/rgb.jpg")
def rgb_jpg(camera_id: str, request: Request, jpeg_quality: int = 90, out_w: int | None = None, out_h: int | None = None):
    st = _get_state(request)
    _require_camera(st, camera_id)

    if jpeg_quality < 1 or jpeg_quality > 100:
        raise HTTPException(status_code=400, detail="jpeg_quality must be in [1,100]")
    if out_w is not None and int(out_w) <= 0:
        raise HTTPException(status_code=400, detail="out_w must be > 0")
    if out_h is not None and int(out_h) <= 0:
        raise HTTPException(status_code=400, detail="out_h must be > 0")

    fr = st.mgr.get_latest(camera_id)
    if fr is None:
        raise HTTPException(status_code=503, detail="No frames yet")

    lock = st.encode_locks.setdefault(camera_id, threading.Lock())
    with lock:
        jpg = _encode_rgb_jpeg(fr.rgb_rgba, jpeg_quality=jpeg_quality, out_w=out_w, out_h=out_h)

    headers = {"X-Frame-Timestamp-S": str(fr.timestamp_s)}
    return Response(content=jpg, media_type="image/jpeg", headers=headers)

def _depth_to_u16_png(depth_mm: np.ndarray, *, scale: float, max_value: int = 65535) -> bytes:
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be finite and > 0")
    if max_value < 1 or max_value > 65535:
        raise ValueError("max_value must be in [1,65535]")

    d = np.asarray(depth_mm, dtype=np.float32)
    valid = np.isfinite(d) & (d > 0.0)

    out = np.zeros(d.shape, dtype=np.uint16)
    if np.any(valid):
        scaled = np.rint(d[valid] * float(scale))
        scaled = np.clip(scaled, 0, max_value).astype(np.uint16, copy=False)
        out[valid] = scaled

    ok, buf = cv2.imencode(".png", out)
    if not ok:
        raise RuntimeError("Failed to encode depth PNG")
    return bytes(buf)

@app.get("/camera/{camera_id}/depth.png")
def depth_png(camera_id: str, request: Request, scale: float = 1.0, max_value: int = 65535):
    st = _get_state(request)
    _require_camera(st, camera_id)

    fr = st.mgr.get_latest(camera_id)
    if fr is None:
        raise HTTPException(status_code=503, detail="No frames yet")

    try:
        lock = st.encode_locks.setdefault(camera_id, threading.Lock())
        with lock:
            png = _depth_to_u16_png(fr.depth_mm, scale=scale, max_value=max_value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    headers = {
        "X-Frame-Timestamp-S": str(fr.timestamp_s),
        "X-Depth-Unit": "mm",
        "X-Depth-Scale": str(scale),
    }
    return Response(content=png, media_type="image/png", headers=headers)

def main():
    import uvicorn
    host = "0.0.0.0"
    port = int(os.getenv("PORT", DEFAULT_SERVICE_PORT))
    
    # We pass the application instance directly to allow this standalone drop-in functionality
    uvicorn.run(app, host=host, port=port, workers=1, access_log=False)

if __name__ == "__main__":
    main()