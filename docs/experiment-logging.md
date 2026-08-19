# Experiment Logging

All entry points (`run_experiment_cli.py`, `run_experiment_ui.py`, `run_teleop_cli.py`, `run_teleop_ui.py`) share the same recording pipeline and data format via `EpisodeRecorder`. The run directory root is controlled by `--output-dir` (default `output/`).

## Directory Structure

```
{output-dir}/{run_name}_{timestamp}/
├── episode_000/
│   ├── meta.json              # Episode metadata and labels
│   ├── steps.jsonl            # Per-step state/action data
│   ├── ee_trajectory.json     # EE poses via FK (computed post-episode)
│   ├── left/000000000.jpg     # Left camera frames
│   ├── wrist/000000000.jpg    # Wrist camera frames
│   └── right/000000000.jpg    # Right camera frames (teleop only)
├── episode_001/
│   └── ...
└── ...
```

Run directory naming:

- Policy CLI: `{task}_{policy}_{timestamp}/`
- Policy UI: `ui_{policy}_{timestamp}/`
- Teleop CLI / UI: `{task_}teleop_{timestamp}/`

## Per-Step Data (steps.jsonl)

Each line is a JSON object:

```json
{
  "t_wall_s": 1737456789.123,
  "seq": 0,
  "images": {
    "left": "left/000000000.jpg",
    "wrist": "wrist/000000000.jpg",
    "right": "right/000000000.jpg"
  },
  "state": {
    "positions": [j0, j1, j2, j3, j4, j5, j6, gripper_frac],
    "velocities": [v0, v1, v2, v3, v4, v5, v6, 0.0]
  },
  "action": {
    "positions": [j0, j1, j2, j3, j4, j5, j6, gripper_cmd],
    "velocities": [v0, v1, v2, v3, v4, v5, v6, 0.0]
  }
}
```

| Field | Description |
|-------|-------------|
| `state.positions` | 7 joint positions + gripper fraction [0,1] |
| `state.velocities` | 7 joint velocities + 0.0 |
| `action.positions` | 7 commanded joint positions + gripper command |
| `action.velocities` | 7 commanded velocities + 0.0 |

For policy experiments, `action.positions[-1]` is binary {0,1}. For teleop, it's a continuous fraction [0,1].

## Episode Metadata (meta.json)

Written after each episode with configuration, timing, and user labels. Policy-episode example:

```json
{
  "t_start_wall_s": 1737456789.0,
  "t_end_wall_s": 1737456849.0,
  "duration_s": 60.0,
  "episode_idx": 0,
  "step_count": 900,
  "task": "BananaInBowlTask",
  "instruction": "Put the banana in the bowl",
  "valid": true,
  "success": true,
  "score": 0.95,
  "episode_notes": "good grasp, slight overshoot",
  "recording": { "format": "jsonl+jpg", "cameras": ["left", "wrist"], "jpeg_quality": 90 },
  "policy": { "name": "pi05", "host": "127.0.0.1", "port": 8000 },
  "control": { "rate_hz": 15.0, "action_step_limit": 900 },
  "inference_time": { "count": 90, "mean_s": 0.062, "min_s": 0.045, "max_s": 0.089 }
}
```

### Teleop variant

Teleop episodes differ in three blocks:

```json
{
  "recording": { "format": "jsonl+jpg", "cameras": ["left", "wrist", "right"], "jpeg_quality": 85 },
  "policy": { "name": "teleop_so101" },
  "control": { "rate_hz": 100.0, "record_rate_hz": 15.0, "min_z": 0.23, "action_step_limit": -1 }
}
```

- `recording.cameras` includes `right` (teleop records all three cameras).
- `policy.name = "teleop_so101"` is the provenance marker — no host/port, no inference times.
- `control` carries both the control-loop rate and the (sub-rate) record rate, plus the FK safety floor.

Labels (`valid`, `success`, `score`, `episode_notes`) are written the same way.

## Post-Episode Prompts

After each episode (ESC or step limit), the terminal prompts:

1. **valid?** `[y/n/enter=skip]` — Was the episode usable?
2. **success?** `[y/n/enter=skip]` — Did the robot complete the task?
3. **score?** `[number/enter=skip]` — Optional numeric score
4. **episode_notes?** `[text/enter=skip]` — Free-form notes for this episode

These are saved in `meta.json` as `valid`, `success`, `score`, `episode_notes`.

## EE Trajectory (ee_trajectory.json)

Computed post-episode via Pinocchio FK from recorded joint positions:

```json
{
  "t_wall_s": [...],
  "t_rel_s": [...],
  "position": [[x, y, z], ...],
  "quaternion": [[x, y, z, w], ...],
  "rpy": [[r, p, y], ...],
  "ee_frame": "panda_link8"
}
```

## Video Generation

```bash
make video RUN_DIR=output/run_20260118_123456/episode_000 FPS=10
make video RUN_DIR=output/run_20260118_123456 FPS=15
```

Requires `ffmpeg` in `PATH`. Install it as a system package, for example:

```bash
sudo apt install ffmpeg
```

## Data Export

### Parquet

```bash
make export_parquet RUN_DIR=output/run_20260118_123456
```

Creates `steps.parquet` per episode with columns: `t_wall_s`, `seq`, `state_positions`, `state_velocities`, `action_positions`, `action_velocities`, `episode_idx`, `instruction`.

### LeRobot v2.1

The exporter writes a local LeRobot dataset under
`<run_dir>/../lerobot/<run_name>/` by default.

```bash
# default: local export to <run_dir>/../lerobot/<run_name>/
make export_lerobot RUN_DIR=output/run_20260118_123456

# also push to the Hugging Face Hub (requires lerobot installed)
make export_lerobot RUN_DIR=output/run_20260118_123456 PUSH=hugo/banana_in_bowl PRIVATE=1
```

Or, after installation:

```bash
export-lerobot output/run_20260118_123456 --overwrite
```

Layout produced (LeRobot v2.1):

```
<out>/
├── meta/
│   ├── info.json                # codebase_version=v2.1, robot_type, fps, features, ...
│   ├── episodes.jsonl           # {"episode_index", "tasks", "length"} per episode
│   ├── tasks.jsonl              # {"task_index", "task"} (instruction strings, deduped)
│   ├── episodes_stats.jsonl     # per-episode mean/std/min/max for all features
│   └── stats.json               # aggregated global stats (v2.0 compat)
├── data/chunk-000/
│   └── episode_000000.parquet   # observation.state, action, timestamp, frame_index, episode_index, index, task_index
└── videos/chunk-000/
    ├── observation.images.left/episode_000000.mp4
    ├── observation.images.right/episode_000000.mp4
    └── observation.images.wrist/episode_000000.mp4
```

Mapping notes:

- `observation.state` and `action` are 8-D float32: 7 joint positions + gripper (state = fraction in [0,1], action = command). Velocities from `steps.jsonl` are dropped (they are zeros in the live recorder).
- `instruction` from each `meta.json` becomes a row in `tasks.jsonl`; identical instructions across episodes share a `task_index`.
- Cameras `left`, `right`, `wrist` are always emitted. If an episode is missing a camera (e.g. policy runs only record left+wrist), a black MP4 of the same length is written so the dataset has a uniform feature set.
- `fps` is read from `meta.control.record_rate_hz` (teleop) then `meta.control.rate_hz` (policy); override with `--fps`. All episodes in a single export must agree on H/W.
- Requires `ffmpeg` in `PATH`. DROID+ invokes the user-installed command-line
  tool and does not distribute ffmpeg or codec binaries.

### Python

```python
import json
from pathlib import Path

episode_dir = Path("output/run_20260118_123456/episode_000")
meta = json.loads((episode_dir / "meta.json").read_text())
steps = [json.loads(l) for l in open(episode_dir / "steps.jsonl")]
ee_traj = json.loads((episode_dir / "ee_trajectory.json").read_text())

# Or via Parquet
import pyarrow.parquet as pq
df = pq.read_table(episode_dir / "steps.parquet").to_pandas()
```

## Regenerating Derived Data

```bash
python scripts/regenerate_ee_trajectories.py output/run_20260118_123456
```
