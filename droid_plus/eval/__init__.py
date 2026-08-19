# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Evaluation: policy clients and episode execution."""

from droid_plus.eval.base_client import InferenceClient
from droid_plus.eval.episode_runner import (
    EpisodeConfig,
    EpisodeResult,
    SessionConfig,
    finalize_episode_recording,
    run_episode,
)

# Optional import — Pi0 client (and create_client) require openpi_client at runtime
try:
    from droid_plus.policies import POLICY_REGISTRY, Pi0DroidJointposClient, create_client
except ImportError:
    Pi0DroidJointposClient = None  # type: ignore
    POLICY_REGISTRY = {}  # type: ignore
    create_client = None  # type: ignore

__all__ = [
    "EpisodeConfig",
    "EpisodeResult",
    "SessionConfig",
    "run_episode",
    "finalize_episode_recording",
    "Pi0DroidJointposClient",
    "InferenceClient",
    "POLICY_REGISTRY",
    "create_client",
]
