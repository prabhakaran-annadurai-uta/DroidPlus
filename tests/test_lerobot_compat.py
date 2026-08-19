# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Compatibility tests for the supported LeRobot 0.4.x API."""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from droid_plus.datagen.setup import connect_so101
from droid_plus.logging.lerobot_export import push_to_hub


def _package(name: str) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = []  # type: ignore[attr-defined]
    return module


def test_connect_so101_uses_lerobot_04_api(monkeypatch: Any) -> None:
    config_args: dict[str, Any] = {}

    class FakeConfig:
        def __init__(self, **kwargs: Any) -> None:
            config_args.update(kwargs)

    class FakeLeader:
        def __init__(self, config: FakeConfig) -> None:
            self.config = config
            self.connected = False

        def connect(self) -> None:
            self.connected = True

    config_module = ModuleType("lerobot.teleoperators.so_leader.config_so_leader")
    config_module.SO101LeaderConfig = FakeConfig  # type: ignore[attr-defined]
    leader_module = ModuleType("lerobot.teleoperators.so_leader.so_leader")
    leader_module.SO101Leader = FakeLeader  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "lerobot", _package("lerobot"))
    monkeypatch.setitem(sys.modules, "lerobot.teleoperators", _package("lerobot.teleoperators"))
    monkeypatch.setitem(sys.modules, "lerobot.teleoperators.so_leader", _package("lerobot.teleoperators.so_leader"))
    monkeypatch.setitem(sys.modules, config_module.__name__, config_module)
    monkeypatch.setitem(sys.modules, leader_module.__name__, leader_module)

    leader = connect_so101(port="/dev/test-so101", id="test_leader", settle_s=0)

    assert config_args == {"port": "/dev/test-so101", "id": "test_leader"}
    assert leader.connected


def test_push_to_hub_uses_lerobot_04_dataset_api(monkeypatch: Any, tmp_path: Path) -> None:
    calls: dict[str, Any] = {}

    class FakeDataset:
        def __init__(self, **kwargs: Any) -> None:
            calls["init"] = kwargs

        def push_to_hub(self, **kwargs: Any) -> None:
            calls["push"] = kwargs

    dataset_module = ModuleType("lerobot.datasets.lerobot_dataset")
    dataset_module.LeRobotDataset = FakeDataset  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "lerobot", _package("lerobot"))
    monkeypatch.setitem(sys.modules, "lerobot.datasets", _package("lerobot.datasets"))
    monkeypatch.setitem(sys.modules, dataset_module.__name__, dataset_module)

    push_to_hub(tmp_path, "nvidia/test-dataset", private=True, tags=["robotics"])

    assert calls["init"] == {"repo_id": "nvidia/test-dataset", "root": str(tmp_path)}
    assert calls["push"] == {"private": True, "tags": ["robotics"]}
