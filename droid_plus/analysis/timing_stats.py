# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Timing statistics utilities for experiment analysis.
"""
from __future__ import annotations

from typing import Any


def compute_timing_stats(times: list[float]) -> dict[str, Any]:
    """
    Compute timing statistics from a list of duration values.

    Args:
        times: List of timing values (e.g., inference times in seconds)

    Returns:
        Dictionary with count, min_s, max_s, mean_s, stddev_s, total_s
    """
    stats: dict[str, Any] = {"count": len(times)}

    if not times:
        return stats

    mean_t = sum(times) / len(times)
    variance = sum((t - mean_t) ** 2 for t in times) / len(times)

    stats["min_s"] = float(min(times))
    stats["max_s"] = float(max(times))
    stats["mean_s"] = float(mean_t)
    stats["stddev_s"] = float(variance ** 0.5)
    stats["total_s"] = float(sum(times))

    return stats


def format_timing_stats(stats: dict[str, Any], unit: str = "ms") -> str:
    """
    Format timing statistics as a human-readable string.

    Args:
        stats: Dictionary from compute_timing_stats
        unit: Display unit - "ms" (milliseconds) or "s" (seconds)

    Returns:
        Formatted string like "mean=45.2ms, std=3.1ms, min=40.1ms, max=52.3ms (n=100)"
    """
    if stats.get("count", 0) == 0:
        return "no samples"

    scale = 1000.0 if unit == "ms" else 1.0

    return (
        f"mean={stats['mean_s'] * scale:.1f}{unit}, "
        f"std={stats['stddev_s'] * scale:.1f}{unit}, "
        f"min={stats['min_s'] * scale:.1f}{unit}, "
        f"max={stats['max_s'] * scale:.1f}{unit} "
        f"(n={stats['count']})"
    )
