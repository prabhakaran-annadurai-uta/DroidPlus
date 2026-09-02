# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Teleop episode runner: streams leader-arm actions to the Franka while
recording observations at a configurable sub-rate.

UI- and device-agnostic — mirrors ``droid_plus.eval.episode_runner.run_episode``.
The caller supplies a :class:`~droid_plus.datagen.leader.LeaderArm` (SO-101,
GELLO, ...), a ``should_stop`` callable (KeyPoller closure for CLI,
``threading.Event.is_set`` for the web UI) and constructs the
``EpisodeRecorder``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from droid_plus.datagen.leader import LeaderArm
from droid_plus.datagen.safety import DEFAULT_MIN_EE_Z, enforce_min_z
from droid_plus.eval.episode_runner import EpisodeConfig, EpisodeResult
from droid_plus.logging import EpisodeRecorder
from droid_plus.robot.observations import pack_state_action
from droid_plus.services.franky_client import HOME_POSITION

if TYPE_CHECKING:
    from droid_plus.robot import DroidPlus


# ── Dataclass ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TeleopSessionConfig:
    """Session-level parameters for a teleop run (constant across episodes).

    Kept separate from ``eval.episode_runner.SessionConfig`` because teleop has
    no policy host/port, carries a control-vs-record rate split, and owns a
    safety knob (``min_z``).
    """
    rate_hz: float = 100.0
    record_rate_hz: float = 15.0
    jpeg_quality: int = 90
    record_jpeg_quality: int = 90
    min_z: float = DEFAULT_MIN_EE_Z
    dry_run: bool = False
    record: bool = True
    policy_name: str = "teleop_so101"


# ── Episode runner ───────────────────────────────────────────────────────────

def run_teleop_episode(
    *,
    config: EpisodeConfig,
    session: TeleopSessionConfig,
    droid: "DroidPlus",
    leader: LeaderArm,
    gripper_initialized: bool,
    pin_model: Any,
    pin_data: Any,
    ee_frame: str,
    recorder: EpisodeRecorder | None,
    should_stop: Callable[[], bool],
) -> EpisodeResult:
    """Run a single teleop episode.

    Streams leader-arm joint targets to the Franka at ``session.rate_hz``, with
    FK-based table-safety clamping. Records images + state/action at the
    configured sub-rate. Returns an :class:`EpisodeResult` with the recorder
    **un-finalized** (the caller finalizes after collecting labels).
    """
    dt = 1.0 / float(session.rate_hz)
    record_every_n = max(1, round(float(session.rate_hz) / float(session.record_rate_hz)))

    seq = 0
    rec_seq = 0
    last_gripper_cmd_frac: float = 0.0

    # Franka Hand can't be streamed a continuous width like a Robotiq — every
    # move()/grasp() is a discrete command that libfranka rejects while another
    # runs, and move() throws once the fingers hit an object. Hybrid scheme:
    #   trigger < GRASP_OFF ......... proportional move() to the mapped width
    #                                 (approach / hover / release to a gap)
    #   trigger >= GRASP_ON ......... latch a force-controlled grasp()
    #   GRASP_OFF..GRASP_ON ......... hysteresis band, hold whatever we're doing
    # The pre-grasp trigger travel [0, GRASP_OFF] is rescaled to the full width
    # range so the whole finger span is reachable before the grasp latches.
    GRIPPER_GRASP_ON = 0.70        # closed-fraction that latches a grasp
    GRIPPER_GRASP_OFF = 0.55       # closed-fraction that drops back to move()
    GRIPPER_MOVE_DEADBAND = 0.05   # min frac change before re-sending a move()
    GRIPPER_MIN_CMD_INTERVAL_S = 0.15
    # Grasp force, in client "bits" (255 -> ~50 N). ~90 -> ~18 N: gentle enough
    # for a sponge without crushing it. Raise for heavier / more slippery objects.
    GRIPPER_GRASP_FORCE_BITS = 90
    gripper_grasping = False
    last_move_frac: float | None = None
    last_gripper_cmd_t = 0.0

    # Seed the safety fallback from where the robot actually is: enforce_min_z
    # reverts to this pose, so a stale value would command a large step.
    try:
        q_prev_safe = np.asarray(droid.get_current_joint_state()["positions"], dtype=float)
    except Exception:
        q_prev_safe = np.array(HOME_POSITION, dtype=float)

    step_limit = config.action_step_limit if config.action_step_limit > 0 else None

    _stopped_by_caller = False
    _stopped_by_limit = False
    t_episode_start = time.time()

    try:
        while True:
            if should_stop():
                _stopped_by_caller = True
                break
            if step_limit is not None and seq >= step_limit:
                _stopped_by_limit = True
                break

            t0 = time.time()

            command = leader.read()
            q_franka = np.asarray(command.q_franka, dtype=float)

            q_franka, _ = enforce_min_z(
                q_franka, q_prev_safe, pin_model, pin_data, ee_frame, session.min_z,
            )
            q_prev_safe = q_franka.copy()

            if not session.dry_run:
                droid.set_target_joint_state(q_franka, velocities=[0.0] * 7, seq=seq)

            # Gripper — proportional move() below the band, force grasp() above it.
            gripper_cmd_frac = last_gripper_cmd_frac
            if gripper_initialized and not session.dry_run and command.gripper_bits is not None:
                close_frac = float(command.gripper_bits) / 255.0  # 0 = open, 1 = closed
                gripper_cmd_frac = close_frac

                if not gripper_grasping and close_frac >= GRIPPER_GRASP_ON:
                    try:
                        droid.gripper.close_async(force=GRIPPER_GRASP_FORCE_BITS, wait=False)
                        gripper_grasping = True
                        last_move_frac = None
                        last_gripper_cmd_t = t0
                    except Exception as e:
                        print(f"[gripper] {type(e).__name__}: {e}")
                elif gripper_grasping and close_frac <= GRIPPER_GRASP_OFF:
                    gripper_grasping = False
                    last_move_frac = None  # reposition on the next eligible tick

                if not gripper_grasping:
                    move_frac = min(close_frac / GRIPPER_GRASP_OFF, 1.0)
                    moved_enough = (
                        last_move_frac is None
                        or abs(move_frac - last_move_frac) >= GRIPPER_MOVE_DEADBAND
                    )
                    if moved_enough and (t0 - last_gripper_cmd_t) >= GRIPPER_MIN_CMD_INTERVAL_S:
                        try:
                            droid.gripper.go_to_async(int(round(move_frac * 255)), wait=False)
                            last_move_frac = move_frac
                            last_gripper_cmd_t = t0
                        except Exception as e:
                            print(f"[gripper] {type(e).__name__}: {e}")
                last_gripper_cmd_frac = gripper_cmd_frac

            # Sub-rate recording.
            if recorder is not None and session.record and seq % record_every_n == 0:
                try:
                    left_rgb = droid.get_left_image(jpeg_quality=session.record_jpeg_quality)
                    wrist_rgb = droid.get_wrist_image(jpeg_quality=session.record_jpeg_quality)
                    right_rgb = droid.get_right_image(jpeg_quality=session.record_jpeg_quality)

                    js = droid.get_current_joint_state()
                    q_state = np.asarray(js["positions"], dtype=np.float64)
                    dq_state = np.asarray(js.get("velocities", [0.0] * 7), dtype=np.float64).reshape(-1)
                    if dq_state.shape != (7,):
                        dq_state = np.zeros((7,), dtype=np.float64)

                    gripper_obs = 0.0
                    if gripper_initialized:
                        try:
                            gripper_obs = float(droid.get_gripper_obs_value())
                        except Exception:
                            pass

                    state_pos, state_vel = pack_state_action(q_state, dq_state, gripper_obs)
                    action_pos, action_vel = pack_state_action(
                        q_franka, np.zeros((7,), dtype=np.float64), gripper_cmd_frac,
                    )

                    recorder.record_step(
                        seq=rec_seq,
                        left_rgb=left_rgb,
                        wrist_rgb=wrist_rgb,
                        right_rgb=right_rgb,
                        state_positions=state_pos,
                        state_velocities=state_vel,
                        action_positions=action_pos,
                        action_velocities=action_vel,
                        t_wall_s=t0,
                    )
                    rec_seq += 1
                except Exception as e:
                    print(f"[record] Warning: {e}")

            seq += 1

            elapsed = time.time() - t0
            if elapsed < dt:
                time.sleep(dt - elapsed)
    finally:
        if not session.dry_run:
            try:
                droid.stop()
            except Exception:
                pass

    return EpisodeResult(
        episode_idx=recorder.episode_idx if recorder is not None else 0,
        seq=rec_seq,
        t_start=t_episode_start,
        t_end=time.time(),
        inference_times=[],
        recorder=recorder,
        stopped_by_limit=_stopped_by_limit,
        stopped_by_caller=_stopped_by_caller,
    )


# ── Recording finalization ───────────────────────────────────────────────────

def finalize_teleop_episode_recording(
    *,
    result: EpisodeResult,
    config: EpisodeConfig,
    session: TeleopSessionConfig,
    episode_valid: bool | None = None,
    episode_success: bool | None = None,
    episode_score: float | None = None,
    episode_notes: str | None = None,
) -> None:
    """Finalize a teleop episode recording: close writers, write meta.json.

    Mirrors ``eval.episode_runner.finalize_episode_recording`` but emits
    teleop-shaped ``policy`` and ``control`` meta blocks.
    """
    if result.recorder is None:
        return
    try:
        result.recorder.finalize(
            experiment=config.experiment,
            task=config.task,
            instruction=config.instruction,
            notes=config.notes,
            policy_info={"name": session.policy_name},
            control_info={
                "rate_hz": session.rate_hz,
                "record_rate_hz": session.record_rate_hz,
                "min_z": session.min_z,
                "action_step_limit": config.action_step_limit,
            },
            extra_meta={
                "valid": episode_valid,
                "success": episode_success,
                "score": episode_score,
                "episode_notes": episode_notes,
            },
        )
    except Exception:
        result.recorder.close()
