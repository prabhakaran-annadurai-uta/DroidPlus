# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Experiment configuration loading utilities.
"""
from __future__ import annotations

import json
import os
from typing import Any


def find_experiments_file(search_paths: list[str] | None = None) -> str:
    """
    Find experiments.json in common locations.

    Args:
        search_paths: Optional list of paths to search. If None, uses defaults.

    Returns:
        Path to experiments.json

    Raises:
        FileNotFoundError: If experiments.json is not found in any search path
    """
    if search_paths is None:
        # Default search paths relative to common locations
        search_paths = [
            os.path.join(os.getcwd(), "experiments", "experiments.json"),
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "experiments", "experiments.json"),
        ]

    for path in search_paths:
        normalized = os.path.normpath(path)
        if os.path.exists(normalized):
            return normalized

    raise FileNotFoundError(f"experiments.json not found in: {search_paths}")


def load_experiments_file(path: str | None = None) -> list[dict[str, Any]]:
    """
    Load all experiments from experiments.json.

    Args:
        path: Path to experiments.json. If None, searches default locations.

    Returns:
        List of experiment dictionaries
    """
    if path is None:
        path = find_experiments_file()

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_experiment(experiment_name: str, path: str | None = None) -> dict[str, Any]:
    """
    Load a specific experiment by name from experiments.json.

    Args:
        experiment_name: Name of the experiment to load
        path: Path to experiments.json. If None, searches default locations.

    Returns:
        Experiment configuration dictionary

    Raises:
        FileNotFoundError: If experiments.json is not found
        ValueError: If experiment_name is not found in the file
    """
    experiments = load_experiments_file(path)

    for exp in experiments:
        if exp.get("experiment") == experiment_name:
            return exp

    available = [e.get("experiment") for e in experiments if e.get("experiment")]
    raise ValueError(f"Experiment '{experiment_name}' not found. Available: {available}")


def list_experiments(path: str | None = None) -> list[str]:
    """
    List all available experiment names.

    Args:
        path: Path to experiments.json. If None, searches default locations.

    Returns:
        List of experiment names
    """
    experiments = load_experiments_file(path)
    return [e.get("experiment") for e in experiments if e.get("experiment")]
