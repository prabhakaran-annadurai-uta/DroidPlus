# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Plot simple tracking diagnostics from a recorded run/episode.

This reads the JSONL stream written via `AsyncJsonlWriter`:

  episode_dir/
    steps.jsonl
    meta.json (optional)
    left/000000123.jpg
    wrist/000000123.jpg

Usage:
  python analysis/tracking.py runs/recordings/20260114_162044/episode_000
  python analysis/tracking.py runs/recordings/20260114_162044 --episode 0

By default it opens interactive matplotlib windows. Use --no-show and --out to save figures.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable

import matplotlib as mpl
import numpy as np

try:  # optional convenience
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]


def _iter_steps(jsonl_path: Path) -> Iterable[dict[str, Any]]:
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                # Best-effort: skip malformed lines.
                continue


def _find_episode_dirs(run_dir: Path) -> list[Path]:
    # If run_dir itself looks like an episode dir, just return it.
    if (run_dir / "steps.jsonl").exists():
        return [run_dir]
    eps = sorted([p for p in run_dir.glob("episode_*") if p.is_dir()])
    return [p for p in eps if (p / "steps.jsonl").exists()]


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _coerce_vec(xs: Any, *, n: int, fill: float = float("nan")) -> np.ndarray:
    arr = np.asarray(xs if xs is not None else [], dtype=np.float64).reshape(-1)
    if arr.size >= n:
        return arr[:n].copy()
    out = np.full((n,), float(fill), dtype=np.float64)
    if arr.size:
        out[: arr.size] = arr
    return out


def load_episode(episode_dir: Path) -> dict[str, Any]:
    steps_path = episode_dir / "steps.jsonl"
    if not steps_path.exists():
        raise FileNotFoundError(f"Missing {steps_path}")

    meta = _safe_read_json(episode_dir / "meta.json")

    rows: list[dict[str, Any]] = []
    for step in _iter_steps(steps_path):
        st = step.get("state") or {}
        ac = step.get("action") or {}
        imgs = step.get("images") or {}

        rows.append(
            {
                "t_wall_s": float(step.get("t_wall_s", 0.0)),
                "seq": int(step.get("seq", len(rows))),
                "state_pos8": _coerce_vec(st.get("positions"), n=8),
                "state_vel8": _coerce_vec(st.get("velocities"), n=8),
                "action_pos8": _coerce_vec(ac.get("positions"), n=8),
                "action_vel8": _coerce_vec(ac.get("velocities"), n=8),
                "left_rel": str(imgs.get("left", "")) if "left" in imgs else "",
                "wrist_rel": str(imgs.get("wrist", "")) if "wrist" in imgs else "",
            }
        )

    if not rows:
        raise RuntimeError(f"No steps found in {steps_path}")

    t_wall_s = np.array([r["t_wall_s"] for r in rows], dtype=np.float64)
    seq = np.array([r["seq"] for r in rows], dtype=np.int64)
    state_pos8 = np.stack([r["state_pos8"] for r in rows], axis=0)
    action_pos8 = np.stack([r["action_pos8"] for r in rows], axis=0)
    state_vel8 = np.stack([r["state_vel8"] for r in rows], axis=0)
    action_vel8 = np.stack([r["action_vel8"] for r in rows], axis=0)

    # Relative time for plots.
    t0 = float(t_wall_s[0])
    t_s = t_wall_s - t0
    dt_s = np.diff(t_s, prepend=t_s[0])

    return {
        "episode_dir": episode_dir,
        "meta": meta,
        "rows": rows,
        "t_wall_s": t_wall_s,
        "t_s": t_s,
        "dt_s": dt_s,
        "seq": seq,
        "state_pos8": state_pos8,
        "state_vel8": state_vel8,
        "action_pos8": action_pos8,
        "action_vel8": action_vel8,
    }


def _maybe_load_frame(episode_dir: Path, rel_path: str) -> np.ndarray | None:
    rel_path = str(rel_path or "")
    if not rel_path:
        return None
    img_path = (episode_dir / rel_path).resolve()
    if not img_path.exists():
        return None
    if cv2 is None:
        return None
    bgr = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return rgb


def plot_tracking(
    ep: dict[str, Any],
    *,
    out_dir: Path | None,
    show: bool,
    title_prefix: str = "",
    preview_seq: int | None = None,
    preview_camera: str = "wrist",
) -> None:
    import matplotlib.pyplot as plt

    episode_dir: Path = ep["episode_dir"]
    meta: dict[str, Any] = ep["meta"]

    t_s: np.ndarray = ep["t_s"]
    state_pos8: np.ndarray = ep["state_pos8"]
    action_pos8: np.ndarray = ep["action_pos8"]

    # Window by seq if requested.
    sel = slice(None)
    if preview_seq is not None:
        # still plot full timeline; preview is independent.
        pass

    t = t_s[sel]
    s_pos = state_pos8[sel]
    a_pos = action_pos8[sel]

    # Convert joint angles (first 7 dims) to degrees for plotting.
    rad2deg = 180.0 / float(np.pi)
    s_pos_plot = s_pos.copy()
    a_pos_plot = a_pos.copy()
    s_pos_plot[:, :7] *= rad2deg
    a_pos_plot[:, :7] *= rad2deg

    # Meta banner.
    instruction = str(meta.get("instruction", "") or "")
    notes = str(meta.get("notes", "") or "")
    rate_hz = meta.get("control", {}).get("rate_hz", None) if isinstance(meta.get("control"), dict) else None
    banner = " | ".join([x for x in [notes, instruction] if x])
    if rate_hz is not None:
        banner = (banner + " | " if banner else "") + f"rate_hz={float(rate_hz):g}"

    fig = plt.figure(figsize=(14, 9), constrained_layout=True)
    gs = fig.add_gridspec(2, 2, height_ratios=[2.4, 1.2])

    ax_q = fig.add_subplot(gs[0, 0])
    ax_g = fig.add_subplot(gs[1, 0], sharex=ax_q)

    # Joint positions (7): fixed color per joint, solid=state, dashed=cmd.
    colors = list(plt.get_cmap("tab10").colors)
    for j in range(7):
        c = colors[j % len(colors)]
        ax_q.plot(t, s_pos_plot[:, j], lw=1.6, color=c, ls="-", label=f"q{j+1} state")
        ax_q.plot(t, a_pos_plot[:, j], lw=1.4, color=c, ls="--", alpha=0.9, label=f"q{j+1} cmd")

    # Print average tracking error (deg) per joint.
    tracking_err_deg = a_pos_plot[:, :7] - s_pos_plot[:, :7]  # cmd - state
    print("Average tracking error (cmd - state) per joint:")
    for j in range(7):
        err_j = tracking_err_deg[:, j]
        mean_err = float(np.mean(err_j))
        mean_abs_err = float(np.mean(np.abs(err_j)))
        std_err = float(np.std(err_j))
        print(f"  q{j+1}: mean={mean_err:+.4f}°  |mean|={mean_abs_err:.4f}°  std={std_err:.4f}°")

    ax_q.set_ylabel("joint position (deg)")
    ax_q.set_title((title_prefix + " " if title_prefix else "") + "Joint tracking" + (f"\n{banner}" if banner else ""))
    ax_q.grid(True, which="major", alpha=0.25)
    ax_q.minorticks_on()
    ax_q.grid(True, which="minor", alpha=0.1, linestyle=":")
    ax_q.legend(ncol=2, fontsize=8, loc="upper right")

    # Gripper: state is frac in [0,1], action is binary {0,1}.
    ax_g.plot(t, s_pos[:, 7], lw=1.5, label="gripper state frac")
    ax_g.step(t, a_pos[:, 7], where="post", lw=1.5, label="gripper cmd (sent)")
    ax_g.set_ylim(-0.05, 1.05)
    ax_g.set_ylabel("gripper")
    ax_g.set_xlabel("t since first step (s)")
    ax_g.grid(True, which="major", alpha=0.25)
    ax_g.minorticks_on()
    ax_g.grid(True, which="minor", alpha=0.1, linestyle=":")
    ax_g.legend(fontsize=9, loc="upper right")

    # Timing histogram: step interval Δt = t_{i+1} - t_i.
    ax_dt = fig.add_subplot(gs[:, 1])
    t_wall_s_full: np.ndarray = ep["t_wall_s"]
    dt = np.diff(t_wall_s_full.astype(np.float64, copy=False))
    dt = dt[np.isfinite(dt)]
    dt = dt[dt > 0]

    x_ms = dt * 1000.0
    # Display 0..1000ms but include all tails by folding out-of-range values into the edge bins.
    lo_ms, hi_ms = 0.0, 1000.0
    x_ms_clip = np.clip(x_ms, lo_ms, hi_ms)
    ax_dt.hist(x_ms_clip, bins=20, range=(lo_ms, hi_ms), alpha=0.9)
    ax_dt.set_title("Step interval histogram")
    ax_dt.set_xlabel(r"\(t_{i+1} - t_i\) (ms)")
    ax_dt.set_ylabel("count")
    ax_dt.set_xlim(lo_ms, hi_ms)
    ax_dt.grid(True, alpha=0.25)

    # Optional image preview.
    if preview_seq is not None:
        # Find row with matching seq (best-effort).
        rows = ep["rows"]
        rel_key = "wrist_rel" if str(preview_camera).lower().startswith("w") else "left_rel"
        rel_path = ""
        for r in rows:
            if int(r["seq"]) == int(preview_seq):
                rel_path = str(r.get(rel_key, "") or "")
                break
        img = _maybe_load_frame(episode_dir, rel_path)
        if img is not None:
            # Put it as an inset on the timing axis.
            ax_in = ax_dt.inset_axes([0.55, 0.55, 0.43, 0.43])
            ax_in.imshow(img)
            ax_in.set_title(f"{preview_camera} seq={int(preview_seq)}", fontsize=9)
            ax_in.axis("off")

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "tracking.png"
        fig.savefig(out_path, dpi=150)
        print(f"Wrote {out_path}")

    if show:
        # If user asked to show but we are on a non-interactive backend, make it obvious why.
        backend = str(mpl.get_backend() or "").lower()
        if "agg" in backend:
            print(
                "WARNING: matplotlib backend is non-interactive (Agg), so no window can be shown.\n"
                "  Fix: install an interactive backend (e.g. python3-tk / PyQt) or run with --backend TkAgg.\n"
                "  Current backend:",
                mpl.get_backend(),
            )
        plt.show()
    else:
        plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description="Plot tracking diagnostics from a recorded run/episode.")
    p.add_argument("run_dir", help="Run dir (contains episode_*/ ) or episode dir (contains steps.jsonl)")
    p.add_argument("--episode", type=int, default=None, help="Episode index (when run_dir contains episode_*/)")
    p.add_argument("--list", action="store_true", help="List episodes under run_dir and exit")
    p.add_argument("--out", default=None, help="Output directory for plots (default: none)")
    p.add_argument("--no-show", action="store_true", help="Do not open interactive windows (useful on headless machines)")
    p.add_argument(
        "--backend",
        default=None,
        help="Force a matplotlib backend (e.g. TkAgg, Qt5Agg). Must be available in your environment.",
    )
    p.add_argument("--title", default="", help="Optional title prefix")
    p.add_argument("--preview-seq", type=int, default=None, help="Overlay an image preview for this seq (requires opencv-python)")
    p.add_argument("--preview-camera", default="wrist", choices=["wrist", "left"], help="Camera to preview")
    args = p.parse_args()

    # Must happen before importing pyplot; we only import pyplot inside plot_tracking.
    if args.backend:
        try:
            mpl.use(str(args.backend), force=True)
        except Exception as e:
            raise RuntimeError(f"Failed to set matplotlib backend to {args.backend!r}: {type(e).__name__}: {e}") from e

    run_dir = Path(os.path.expanduser(args.run_dir)).resolve()
    if not run_dir.exists():
        raise FileNotFoundError(str(run_dir))

    eps = _find_episode_dirs(run_dir)
    if not eps:
        raise RuntimeError(f"No episodes found under {run_dir} (expected episode_*/steps.jsonl)")

    if args.list and (run_dir / "steps.jsonl").exists() is False:
        for ep in eps:
            meta = _safe_read_json(ep / "meta.json")
            instruction = str(meta.get("instruction", "") or "")
            notes = str(meta.get("notes", "") or "")
            print(f"{ep.name}: notes={notes!r} instruction={instruction!r}")
        return

    # Select an episode dir.
    if (run_dir / "steps.jsonl").exists():
        episode_dir = run_dir
    else:
        if args.episode is None:
            # Default to the highest episode index for "latest" behavior.
            def _ep_idx(pth: Path) -> int:
                name = pth.name
                try:
                    return int(name.split("_")[-1])
                except Exception:
                    return -1

            episode_dir = sorted(eps, key=_ep_idx)[-1]
        else:
            wanted = f"episode_{int(args.episode):03d}"
            cand = [p for p in eps if p.name == wanted]
            if not cand:
                raise RuntimeError(f"Episode {wanted} not found under {run_dir}")
            episode_dir = cand[0]

    ep = load_episode(episode_dir)

    out_dir = Path(os.path.expanduser(args.out)).resolve() if args.out else None
    show = not bool(args.no_show)
    plot_tracking(
        ep,
        out_dir=out_dir,
        show=show,
        title_prefix=str(args.title or ""),
        preview_seq=args.preview_seq,
        preview_camera=str(args.preview_camera),
    )


if __name__ == "__main__":
    main()

