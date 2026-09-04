# fix_stats_shape.py — run once against your already-exported v2.1 dataset
import json
from pathlib import Path

root = Path("/Users/prabhakaran_annadurai/Desktop/my_repo/DroidPlus/output/lerobot/teleop_20260902_194642")

info = json.loads((root / "meta" / "info.json").read_text())
image_keys = {k for k, ft in info["features"].items() if ft["dtype"] in ("image", "video")}

path = root / "meta" / "episodes_stats.jsonl"
lines = path.read_text().splitlines()
fixed_lines = []
for line in lines:
    rec = json.loads(line)
    stats = rec["stats"]
    for k in image_keys:
        if k not in stats:
            continue
        for stat_key in ("mean", "std", "min", "max"):
            v = stats[k][stat_key]
            if isinstance(v[0], list):  # already fixed
                continue
            stats[k][stat_key] = [[[x]] for x in v]  # (3,) -> (3,1,1)
    fixed_lines.append(json.dumps(rec))

path.write_text("\n".join(fixed_lines) + "\n")
print(f"patched {len(fixed_lines)} episodes")


"""
python -m lerobot.scripts.convert_dataset_v21_to_v30 \
    --repo-id=prabhakaran-a-uta/fr3_lift_task \
    --root=/Users/prabhakaran_annadurai/Desktop/my_repo/DroidPlus/output/lerobot/teleop_20260902_194642 \
    --push-to-hub=false

"""