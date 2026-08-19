#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Thin shell over ``droid_plus.logging.lerobot_export_cli`` so it works without
the package being installed (matches the pattern of other scripts/ entry points).

Usage:
    python scripts/export_lerobot.py output/BananaInBowl_pi0_20260118_123456
    python scripts/export_lerobot.py output/run --out-dir output/lerobot/run --overwrite
    python scripts/export_lerobot.py output/run --push hugo/banana_in_bowl --private

See ``export-lerobot --help`` (after ``pip install -e .``) for the full flag list.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from droid_plus.logging.lerobot_export_cli import main  # noqa: E402

if __name__ == "__main__":
    main()
