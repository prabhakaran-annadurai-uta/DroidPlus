#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Debug helper for "joints stick for a fraction of a second then jump" during
GELLO -> FR3 teleop.

It records three time-aligned streams and, on exit, prints a report that tries
to attribute each freeze to one of:

  * leader-side   : the GELLO Dynamixel poll thread went stale / errored, so the
                    same target was streamed until it caught up, then jumped
  * comms         : the HTTP POST /target_joint_state (or the loop itself) blew
                    past the control period, leaving a gap in the target stream
  * robot-side    : target stream was smooth and on-time but the arm did not
                    move (Ruckig re-planning / zero-velocity waypoints /
                    dynamics limits)

Two modes:

  drive  (default)  This script *is* the teleop loop (no cameras, no gripper).
                    Move the GELLO as usual; the FR3 mirrors it. Full
                    instrumentation: leader read latency, Dynamixel bus health,
                    POST latency, target-vs-actual tracking.
                    Do NOT run the normal teleop at the same time.

  observe           Run your normal teleop (CLI or UI) in another terminal.
                    This only polls /target_joint_state and /joint_state and
                    analyses target-vs-actual tracking + robot-side freezes.
                    (Can't touch the GELLO serial port while teleop holds it.)

Examples:
  python scripts/debug_teleop_timing.py --gello-config gello_config.json
  python scripts/debug_teleop_timing.py --mode observe
  python scripts/debug_teleop_timing.py --gello-config gello_config.json --rate 100 --secs 60

Stop with Ctrl+C (or --secs). CSVs + a report are written next to --out.
"""
from __future__ import annotations

import argparse
import csv
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field

import numpy as np
import requests

from droid_plus.constants import FRANKY_SERVICE_URL

MONO = time.monotonic


# ─────────────────────────── shared recording buffers ───────────────────────

@dataclass
class Buffers:
    loop: list = field(default_factory=list)      # t, seq, read_ms, send_ms, loop_ms, q_target[7]
    bus: list = field(default_factory=list)       # t, age_ms, err(0/1), raw[7]
    robot: list = field(default_factory=list)     # t, req_ms, q[7], dq[7]
    target: list = field(default_factory=list)    # t, req_ms, seq, q[7]  (observe mode)
    health: list = field(default_factory=list)    # t, req_ms, stop_latched, has_target, robot_connected, last_error
    stop: threading.Event = field(default_factory=threading.Event)


# ─────────────────────────── probe threads ──────────────────────────────────

def bus_probe(leader, buf: Buffers, hz: float) -> None:
    """Sample the GELLO Dynamixel bus's internal freshness at high rate."""
    bus = getattr(leader, "_bus", None)
    if bus is None:
        print("[bus_probe] leader has no _bus attribute; skipping")
        return
    dt = 1.0 / hz
    while not buf.stop.is_set():
        t = MONO()
        try:
            with bus._state_lock:                       # noqa: SLF001
                pos = None if bus._positions is None else np.asarray(bus._positions, float).copy()
                last = bus._last_read_s
                err = bus._read_error
            age_ms = (time.monotonic() - last) * 1e3 if last else -1.0
            raw = pos.tolist() if pos is not None else [float("nan")] * 8
            buf.bus.append((t, age_ms, 1 if err else 0, raw))
        except Exception as e:  # pragma: no cover
            buf.bus.append((t, -1.0, 1, [float("nan")] * 8))
        time.sleep(dt)


def robot_probe(url: str, buf: Buffers, hz: float, timeout_s: float) -> None:
    s = requests.Session()
    ep = url.rstrip("/") + "/joint_state"
    dt = 1.0 / hz
    while not buf.stop.is_set():
        t = MONO()
        try:
            r = s.get(ep, timeout=timeout_s)
            req_ms = (MONO() - t) * 1e3
            j = r.json()
            buf.robot.append((t, req_ms,
                              [float(x) for x in j["positions"]],
                              [float(x) for x in j.get("velocities", [0] * 7)]))
        except Exception:
            buf.robot.append((t, (MONO() - t) * 1e3, [float("nan")] * 7, [float("nan")] * 7))
        time.sleep(dt)


def target_probe(url: str, buf: Buffers, hz: float, timeout_s: float) -> None:
    """observe mode only: watch the target stream someone else is producing."""
    s = requests.Session()
    ep = url.rstrip("/") + "/target_joint_state"
    dt = 1.0 / hz
    while not buf.stop.is_set():
        t = MONO()
        try:
            r = s.get(ep, timeout=timeout_s)
            req_ms = (MONO() - t) * 1e3
            j = r.json()
            buf.target.append((t, req_ms, j.get("seq"),
                               [float(x) for x in j["positions"]]))
        except Exception:
            buf.target.append((t, (MONO() - t) * 1e3, None, [float("nan")] * 7))
        time.sleep(dt)


def health_probe(url: str, buf: Buffers, hz: float, timeout_s: float) -> None:
    """Poll /health so freezes can be cross-checked against franky stop-latches / control errors."""
    s = requests.Session()
    ep = url.rstrip("/") + "/health"
    dt = 1.0 / hz
    while not buf.stop.is_set():
        t = MONO()
        try:
            r = s.get(ep, timeout=timeout_s)
            req_ms = (MONO() - t) * 1e3
            j = r.json()
            buf.health.append((t, req_ms,
                               1 if j.get("stop_latched") else 0,
                               1 if j.get("has_target") else 0,
                               1 if j.get("robot_connected") else 0,
                               str(j.get("last_control_error") or ""),
                               j.get("control_hz"),
                               j.get("control_deadband_rad"),
                               ",".join(f"{x:g}" for x in j["relative_dynamics"])
                               if isinstance(j.get("relative_dynamics"), (list, tuple)) else None,
                               j.get("control_mode")))
        except Exception as e:
            buf.health.append((t, (MONO() - t) * 1e3, -1, -1, -1, f"probe_error: {e}", None, None, None, None))
        time.sleep(dt)


# ─────────────────────────── drive loop ─────────────────────────────────────

def drive_loop(leader, url: str, buf: Buffers, rate_hz: float, timeout_s: float,
               use_min_z: bool, min_z: float, ff_vel: bool = False,
               ff_alpha: float = 0.4, ff_clamp: float = 3.0) -> None:
    from droid_plus.services.franky_client import FrankyClient

    client = FrankyClient(url, timeout_s=timeout_s)
    print(f"[drive] feed-forward velocity: {'ON' if ff_vel else 'OFF (zeros)'}"
          + (f"  (ema alpha={ff_alpha}, clamp=±{ff_clamp} rad/s)" if ff_vel else ""))

    pin_model = pin_data = ee_frame = None
    q_prev_safe = None
    if use_min_z:
        from droid_plus.datagen.setup import build_fk_model
        from droid_plus.datagen.safety import enforce_min_z  # noqa: F401
        pin_model, pin_data, ee_frame = build_fk_model(url)

    # Align: seed the leader from the robot's current pose so we don't jump.
    try:
        q_now = np.asarray(client.get_current_joint_state()["positions"], float)
        leader.sync_to(q_now)
        q_prev_safe = q_now.copy()
        print(f"[drive] seeded from robot pose {np.round(q_now, 3).tolist()}")
        print("[drive] move the GELLO to match, then teleop as usual. Ctrl+C to stop.")
    except Exception as e:
        print(f"[drive] WARNING could not read robot pose ({e}); NOT seeding")

    dt = 1.0 / rate_hz
    seq = 0
    q_prev: np.ndarray | None = None
    t_prev: float | None = None
    v_ema = np.zeros(7)
    while not buf.stop.is_set():
        t0 = MONO()

        tr = MONO()
        cmd = leader.read()
        q = np.asarray(cmd.q_franka, float)
        read_ms = (MONO() - tr) * 1e3

        if use_min_z and pin_model is not None:
            from droid_plus.datagen.safety import enforce_min_z
            q, _ = enforce_min_z(q, q_prev_safe, pin_model, pin_data, ee_frame, min_z)
            q_prev_safe = q.copy()

        if ff_vel and q_prev is not None and t_prev is not None:
            dts = max(1e-3, t0 - t_prev)
            v_raw = (q - q_prev) / dts
            v_ema = ff_alpha * v_raw + (1.0 - ff_alpha) * v_ema
            v_cmd = np.clip(v_ema, -ff_clamp, ff_clamp)
        else:
            v_cmd = np.zeros(7)
        q_prev = q.copy()
        t_prev = t0

        ts = MONO()
        try:
            client.set_target_joint_state(q, v_cmd.tolist(), seq=seq)
            send_ms = (MONO() - ts) * 1e3
        except Exception as e:
            send_ms = (MONO() - ts) * 1e3
            print(f"[drive] POST failed seq={seq}: {e}")

        loop_ms = (MONO() - t0) * 1e3
        buf.loop.append((t0, seq, read_ms, send_ms, loop_ms, q.tolist(), v_cmd.tolist()))
        seq += 1

        rem = dt - (MONO() - t0)
        if rem > 0:
            time.sleep(rem)

    # leave the robot where it is; caller sends /stop
    try:
        client.stop()
    except Exception:
        pass


# ─────────────────────────── analysis ───────────────────────────────────────

def _pct(a, q):
    return float(np.percentile(a, q)) if len(a) else float("nan")


def _longest_true_run_s(t, mask) -> float:
    """Longest contiguous span (seconds) where mask is True, measured with timestamps t."""
    longest = 0.0
    run_start = None
    for i in range(len(mask)):
        if mask[i]:
            run_start = t[i] if run_start is None else run_start
            longest = max(longest, t[i] - run_start)
        else:
            run_start = None
    return longest


def analyse(buf: Buffers, rate_hz: float, mode: str) -> str:
    L = []
    dt_ms = 1000.0 / rate_hz
    out = L.append
    out("=" * 72)
    out(f"REPORT  (mode={mode}, nominal {rate_hz:.0f} Hz -> {dt_ms:.1f} ms period)")
    out("=" * 72)

    # ---- loop timing (drive only) ----
    if buf.loop:
        arr = buf.loop
        t = np.array([r[0] for r in arr])
        read = np.array([r[2] for r in arr])
        send = np.array([r[3] for r in arr])
        loop = np.array([r[4] for r in arr])
        gaps = np.diff(t) * 1e3
        dur = t[-1] - t[0]
        out("")
        out(f"-- control loop --   iters={len(arr)}  duration={dur:.1f}s  "
            f"achieved={len(arr)/dur:.1f} Hz")
        out(f"   inter-iter gap ms : p50={_pct(gaps,50):.1f}  p95={_pct(gaps,95):.1f}  "
            f"p99={_pct(gaps,99):.1f}  max={gaps.max():.1f}")
        out(f"   leader.read()  ms : p50={_pct(read,50):.2f}  p95={_pct(read,95):.2f}  "
            f"p99={_pct(read,99):.2f}  max={read.max():.2f}")
        out(f"   POST target    ms : p50={_pct(send,50):.2f}  p95={_pct(send,95):.2f}  "
            f"p99={_pct(send,99):.2f}  max={send.max():.2f}")
        stall = np.where(gaps > 1.8 * dt_ms)[0]
        out(f"   loop stalls (>1.8x period): {len(stall)}")
        for i in stall[:12]:
            out(f"      t+{t[i]-t[0]:7.2f}s  gap={gaps[i]:6.1f}ms  "
                f"read={read[i+1]:.1f}  send={send[i+1]:.1f}")

    # ---- Dynamixel bus health (drive only) ----
    if buf.bus:
        arr = buf.bus
        t = np.array([r[0] for r in arr])
        age = np.array([r[1] for r in arr])
        err = np.array([r[2] for r in arr])
        valid = age >= 0
        out("")
        out(f"-- GELLO Dynamixel bus --   samples={len(arr)}")
        out(f"   read age ms       : p50={_pct(age[valid],50):.1f}  p95={_pct(age[valid],95):.1f}  "
            f"p99={_pct(age[valid],99):.1f}  max={age[valid].max():.1f}")
        out(f"   samples w/ age>20ms : {int((age>20).sum())} "
            f"({100*(age>20).mean():.1f}%)   age>50ms: {int((age>50).sum())}")
        out(f"   samples w/ read_error flag : {int(err.sum())} "
            f"({100*err.mean():.1f}%)")
        # longest continuous stale window
        stale = age > 20
        longest = cur = 0.0
        run_start = None
        for i in range(len(stale)):
            if stale[i]:
                run_start = t[i] if run_start is None else run_start
                cur = t[i] - run_start
                longest = max(longest, cur)
            else:
                run_start = None
        out(f"   longest continuous stale (>20ms) window : {longest*1e3:.0f} ms")
        # raw jumps between consecutive distinct samples
        raw = np.array([r[3][:7] for r in arr], float)
        if raw.shape[0] > 2:
            draw = np.abs(np.diff(raw, axis=0))
            out(f"   max raw jump per joint (rad)  : "
                + " ".join(f"j{k}:{draw[:,k].max():.3f}" for k in range(7)))

    # ---- franky /health (stop latches + control errors) ----
    if buf.health:
        arr = buf.health
        hstop = np.array([r[2] for r in arr])
        hconn = np.array([r[4] for r in arr])
        herr = [r[5] for r in arr]
        edges = int(np.sum((hstop[1:] == 1) & (hstop[:-1] == 0))) if len(hstop) > 1 else 0
        distinct: list[str] = []
        for e in herr:
            if e and e not in distinct:
                distinct.append(e)
        chz = {r[6] for r in arr if r[6] is not None}
        dbs = {round(r[7], 4) for r in arr if len(r) > 7 and r[7] is not None}
        rds = {r[8] for r in arr if len(r) > 8 and r[8] is not None}
        mds = {r[9] for r in arr if len(r) > 9 and r[9] is not None}
        out("")
        out(f"-- franky /health --   samples={len(arr)}")
        out(f"   service control_mode : {sorted(mds) if mds else 'unknown (old service?)'}")
        out(f"   service control_hz : {sorted(chz) if chz else 'unknown (old service?)'}")
        out(f"   service deadband   : {sorted(dbs) if dbs else 'unknown (old service?)'} rad")
        out(f"   relative_dynamics  : {sorted(rds) if rds else 'unknown (old service?)'} (v,a,j)")
        out(f"   stop_latched     : {100*(hstop == 1).mean():.1f}% of samples, {edges} latch event(s)")
        out(f"   robot_connected  : {100*(hconn == 1).mean():.1f}% of samples")
        out(f"   distinct last_control_error : {len(distinct)}")
        for e in distinct[:8]:
            out(f"      {e[:200]}")

    # ---- robot tracking + freeze attribution ----
    if buf.robot and (buf.loop or buf.target):
        rt = np.array([r[0] for r in buf.robot])
        rq = np.array([r[2] for r in buf.robot], float)
        rdq = np.array([r[3] for r in buf.robot], float)
        rreq = np.array([r[1] for r in buf.robot])

        if buf.loop:
            tt = np.array([r[0] for r in buf.loop])
            tq = np.array([r[5] for r in buf.loop], float)
        else:
            tt = np.array([r[0] for r in buf.target])
            tq = np.array([r[3] for r in buf.target], float)

        # interpolate target onto robot timestamps
        tq_i = np.zeros_like(rq)
        for k in range(7):
            tq_i[:, k] = np.interp(rt, tt, tq[:, k])
        trk = np.abs(tq_i - rq)
        out("")
        out(f"-- robot tracking --   /joint_state req ms p95={_pct(rreq,95):.1f} max={rreq.max():.1f}")
        out(f"   |target-actual| per joint (rad) p95 : "
            + " ".join(f"j{k}:{_pct(trk[:,k],95):.3f}" for k in range(7)))
        out(f"   |target-actual| per joint (rad) max : "
            + " ".join(f"j{k}:{trk[:,k].max():.3f}" for k in range(7)))

        # freeze events: actual barely moving while target moved
        speed = np.linalg.norm(rdq, axis=1)
        win = max(3, int(0.08 * len(rt) / max(1e-6, (rt[-1] - rt[0]))))  # ~80ms in samples
        events = []
        i = 0
        n = len(rt)
        while i < n - win:
            seg = slice(i, i + win)
            if np.nanmax(speed[seg]) < 0.03:
                tgt_disp = np.nanmax(np.abs(tq_i[i + win - 1] - tq_i[i]))
                if tgt_disp > 0.02:
                    j = i + win
                    while j < n and speed[j] < 0.03:
                        j += 1
                    events.append((rt[i], rt[min(j, n - 1)], tgt_disp))
                    i = j
                    continue
            i += 1

        out("")
        out(f"-- freeze events (arm still >~80ms while target moving) : {len(events)} --")
        cats = {"robot_stop": 0, "leader_stale": 0, "comms_slow": 0, "robot_side": 0}
        bus_t = np.array([r[0] for r in buf.bus]) if buf.bus else None
        bus_age = np.array([r[1] for r in buf.bus]) if buf.bus else None
        bus_err = np.array([r[2] for r in buf.bus]) if buf.bus else None
        loop_t = np.array([r[0] for r in buf.loop]) if buf.loop else None
        loop_send = np.array([r[3] for r in buf.loop]) if buf.loop else None
        loop_dur = np.array([r[4] for r in buf.loop]) if buf.loop else None
        hlth_t = np.array([r[0] for r in buf.health]) if buf.health else None
        hlth_stop = np.array([r[2] for r in buf.health]) if buf.health else None
        hlth_err = [r[5] for r in buf.health] if buf.health else None
        t0 = rt[0]
        for (a, b, disp) in events:
            tag = "robot_side"
            note = ""
            # 1) franky latched stop / reported a control error across the freeze?
            if hlth_t is not None:
                mi = np.where((hlth_t >= a - 0.05) & (hlth_t <= b + 0.05))[0]
                if len(mi):
                    if (hlth_stop[mi] == 1).any():
                        tag, note = "robot_stop", " [stop_latched]"
                    else:
                        es = [hlth_err[i] for i in mi if hlth_err[i]]
                        if es:
                            tag, note = "robot_stop", f" [{es[0][:80]}]"
            # 2) leader stale: require a *sustained* stale run, not one unlucky sample
            if tag == "robot_side" and bus_t is not None:
                m = (bus_t >= a - 0.03) & (bus_t <= b)
                if m.any():
                    if bus_err[m].any():
                        tag, note = "leader_stale", " [read_error]"
                    else:
                        run_s = _longest_true_run_s(bus_t[m], bus_age[m] > 20)
                        if run_s > 0.05 and run_s > 0.4 * (b - a):
                            tag, note = "leader_stale", f" [stale {run_s*1e3:.0f}ms]"
            # 3) comms / loop overran the control period
            if tag == "robot_side" and loop_t is not None:
                m = (loop_t >= a - 0.03) & (loop_t <= b)
                if m.any() and (np.nanmax(loop_send[m]) > 15 or np.nanmax(loop_dur[m]) > 1.8 * dt_ms):
                    tag = "comms_slow"
            cats[tag] += 1
            if cats[tag] <= 12:
                out(f"   t+{a-t0:7.2f}s  dur={ (b-a)*1e3:6.0f}ms  tgtΔ={disp:.3f}rad  -> {tag}{note}")
        out("")
        out(f"   attribution: robot_stop={cats['robot_stop']}  leader_stale={cats['leader_stale']}  "
            f"comms_slow={cats['comms_slow']}  robot_side={cats['robot_side']}")

    out("")
    out("Interpretation:")
    out("  robot_stop dominates   -> franky latched stop / raised a control error mid-freeze")
    out("        (see last_control_error above). Usually per-tick JointMotion preemption in")
    out("        franky_service._control_loop: raise CONTROL_HZ, send feed-forward velocities,")
    out("        and don't re-issue robot.move() when the target is unchanged.")
    out("  leader_stale dominates -> GELLO serial: set FTDI latency_timer=1, check")
    out("        connectors/power; poll thread is dropping sync-reads.")
    out("  comms_slow dominates  -> network / uvicorn / GC on the POST path.")
    out("  robot_side dominates  -> Ruckig: zero-velocity waypoints + per-tick")
    out("        JointMotion preemption. Try velocity feed-forward, lower CONTROL_HZ,")
    out("        keep jerk low, or don't re-send an unchanged target.")
    out("=" * 72)
    return "\n".join(L)


def _write_csv(path: str, header: list, rows: list) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  wrote {path}  ({len(rows)} rows)")


def write_csvs(buf: Buffers, base: str) -> None:
    if buf.loop:
        _write_csv(f"{base}.loop.csv",
                   ["t", "seq", "read_ms", "send_ms", "loop_ms"]
                   + [f"qt{k}" for k in range(7)] + [f"vt{k}" for k in range(7)],
                   [[t, sq, rm, sm, lm, *q, *v] for (t, sq, rm, sm, lm, q, v) in buf.loop])
    if buf.bus:
        _write_csv(f"{base}.bus.csv",
                   ["t", "age_ms", "err"] + [f"raw{k}" for k in range(8)],
                   [[t, a, e, *raw] for (t, a, e, raw) in buf.bus])
    if buf.target:
        _write_csv(f"{base}.target.csv",
                   ["t", "req_ms", "seq"] + [f"q{k}" for k in range(7)],
                   [[t, rq, sq, *q] for (t, rq, sq, q) in buf.target])
    if buf.robot:
        _write_csv(f"{base}.robot.csv",
                   ["t", "req_ms"] + [f"q{k}" for k in range(7)] + [f"dq{k}" for k in range(7)],
                   [[t, rq, *q, *dq] for (t, rq, q, dq) in buf.robot])
    if buf.health:
        _write_csv(f"{base}.health.csv",
                   ["t", "req_ms", "stop_latched", "has_target", "robot_connected",
                    "last_control_error", "control_hz", "control_deadband_rad", "relative_dynamics", "control_mode"],
                   [[t, rq, sl, ht, rc, err, chz, db, rd, md]
                    for (t, rq, sl, ht, rc, err, chz, db, rd, md) in buf.health])


# ─────────────────────────── main ───────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=("drive", "observe"), default="drive")
    p.add_argument("--franky-service-url", default=FRANKY_SERVICE_URL)
    p.add_argument("--gello-config", default=None, help="GELLO config JSON (drive mode)")
    p.add_argument("--port", default=None, help="GELLO serial port override")
    p.add_argument("--rate", type=float, default=100.0, help="drive loop rate (Hz)")
    p.add_argument("--robot-probe-hz", type=float, default=60.0)
    p.add_argument("--health-probe-hz", type=float, default=20.0)
    p.add_argument("--bus-probe-hz", type=float, default=300.0)
    p.add_argument("--secs", type=float, default=0.0, help="auto-stop after N s (0 = until Ctrl+C)")
    p.add_argument("--min-z", type=float, default=None, help="also run enforce_min_z with this floor")
    p.add_argument("--http-timeout", type=float, default=2.0)
    p.add_argument("--ff-vel", action="store_true",
                   help="EXPERIMENT: send finite-difference feed-forward velocities instead of zeros")
    p.add_argument("--ff-alpha", type=float, default=0.4, help="EMA smoothing for --ff-vel (0..1)")
    p.add_argument("--ff-clamp", type=float, default=3.0, help="clamp for --ff-vel (rad/s)")
    p.add_argument("--out", default=None, help="output path prefix for CSVs + report")
    args = p.parse_args()

    base = args.out or os.path.join(
        os.getcwd(), "teleop_debug", time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(base) or ".", exist_ok=True)

    buf = Buffers()
    threads: list[threading.Thread] = []
    leader = None

    if args.mode == "drive":
        from droid_plus.datagen.setup import connect_gello
        leader = connect_gello(port=args.port, config_path=args.gello_config)
        threads.append(threading.Thread(
            target=bus_probe, args=(leader, buf, args.bus_probe_hz), daemon=True))
    else:
        threads.append(threading.Thread(
            target=target_probe,
            args=(args.franky_service_url, buf, args.rate, args.http_timeout), daemon=True))

    threads.append(threading.Thread(
        target=robot_probe,
        args=(args.franky_service_url, buf, args.robot_probe_hz, args.http_timeout), daemon=True))

    threads.append(threading.Thread(
        target=health_probe,
        args=(args.franky_service_url, buf, args.health_probe_hz, args.http_timeout), daemon=True))

    def handle_sigint(*_):
        buf.stop.set()
    signal.signal(signal.SIGINT, handle_sigint)

    for t in threads:
        t.start()

    t_start = MONO()
    try:
        if args.mode == "drive":
            if args.secs > 0:
                threading.Thread(
                    target=lambda: (time.sleep(args.secs), buf.stop.set()), daemon=True).start()
            drive_loop(leader, args.franky_service_url, buf, args.rate, args.http_timeout,
                       use_min_z=args.min_z is not None, min_z=(args.min_z or 0.0),
                       ff_vel=args.ff_vel, ff_alpha=args.ff_alpha, ff_clamp=args.ff_clamp)
        else:
            print("[observe] polling /target_joint_state + /joint_state. "
                  "Run your teleop now. Ctrl+C to stop.")
            while not buf.stop.is_set():
                if args.secs > 0 and MONO() - t_start > args.secs:
                    break
                time.sleep(0.2)
    finally:
        buf.stop.set()
        for t in threads:
            t.join(timeout=1.0)
        if leader is not None:
            try:
                leader.close()
            except Exception:
                pass

    print("\nwriting data...")
    write_csvs(buf, base)

    report = analyse(buf, args.rate, args.mode)
    print("\n" + report)
    rp = f"{base}.report.txt"
    with open(rp, "w") as f:
        f.write(report + "\n")
    print(f"\nreport saved to {rp}")
    print(f"\n>>> send me: {rp}  (and the .csv files if you can)")


if __name__ == "__main__":
    main()
