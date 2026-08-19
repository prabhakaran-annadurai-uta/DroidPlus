# Adding New Experiments

## Experiment Configuration

Experiments are defined in `experiments/experiments.json`. Each entry specifies:

| Field | Type | Description |
|-------|------|-------------|
| `experiment` | string | Unique name (used with `--experiment` flag) |
| `task` | string | Task name for output directory and metadata |
| `instruction` | string | Natural language instruction for the policy |
| `action_step_limit` | integer | Max action steps per episode (-1 = unlimited) |

Example:

```json
{
    "experiment": "banana_in_bowl",
    "task": "BananaInBowlTask",
    "instruction": "Put the banana in the bowl",
    "action_step_limit": 900
}
```

## Running Experiments

### From a preset

```bash
python scripts/run_experiment_cli.py --exp banana_in_bowl
python scripts/run_experiment_cli.py --exp banana_in_bowl --action-step-limit 450
```

### From CLI arguments

```bash
python scripts/run_experiment_cli.py \
    --task "CustomTask" \
    --instruction "Move the cup to the left" \
    --action-step-limit 600
```

### Batch mode

```bash
python scripts/run_experiment_cli.py --exp-file experiments/experiments.json
```

### Make targets

```bash
make run_experiment_900 INSTRUCTION="pick up the can" NOTES="testing new grasp"
```

### Web UI

For an interactive browser-based runner (select policy at runtime, edit labels inline), see the Web UI Workflow section of [Policy Evaluation](eval.md).

## CLI Reference

| Argument | Default | Description |
|----------|---------|-------------|
| `--experiment`, `--exp` | None | Load from experiments.json |
| `--experiment-file`, `--exp-file` | None | Batch: run all experiments in file |
| `--task` | "" | Task name (overrides experiment) |
| `--instruction` | "" | Policy instruction (overrides experiment) |
| `--action-step-limit` | -1 | Max steps per episode (overrides experiment) |
| `--notes` | "" | Free-form notes saved to metadata |
| `--policy` | "pi05" | Policy name |
| `--policy-host` | from constants | Policy server host |
| `--policy-port` | 8000 | Policy server port |
| `--rate-hz` | 15.0 | Control loop rate (Hz) |
| `--output-dir` | `output` | Base output directory for recordings |
| `--dry-run` | off | Run policy without commanding robot |
| `--no-record` | off | Disable recording (records by default) |

## Action Step Limits

| Task Type | Recommended Limit | Duration at 15Hz |
|-----------|-------------------|------------------|
| Simple pick-and-place | 450 | ~30s |
| Standard manipulation | 900 | ~60s |
| Multi-step tasks | 1200 | ~80s |
| Complex sequences | 1800 | ~120s |

## Output Structure

```
{output-dir}/{task}_{policy}_{timestamp}/
├── episode_000/
│   ├── meta.json
│   ├── steps.jsonl
│   ├── ee_trajectory.json
│   ├── left/000000000.jpg, ...
│   └── wrist/000000000.jpg, ...
├── episode_001/
│   └── ...
└── ...
```

`{output-dir}` defaults to `output/`; override with `--output-dir`. See [Experiment Logging](experiment-logging.md) for full data format details.
