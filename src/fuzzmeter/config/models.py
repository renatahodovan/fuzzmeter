# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Define normalized campaign configuration models."""

from __future__ import annotations

import os

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def target_key(benchmark: str, fuzz_target: str) -> str:
    '''Return the internal key used for fuzz-target-specific artifacts.'''
    return f'{benchmark}-{fuzz_target}'


@dataclass(frozen=True)
class CampaignCase:
    '''Describe one fuzzer/fuzz-target combination in a campaign.'''

    fuzzer_id: str
    fuzzer_name: str
    fuzzer_chain: tuple[str, ...]
    benchmark: str
    fuzz_target: str
    input_mode: str
    target_timeout_s: float = 1.0
    build_config: dict[str, Any] = field(default_factory=dict)
    runtime_config: dict[str, Any] = field(default_factory=dict)
    replay_trials: tuple[Path, ...] = ()


@dataclass(frozen=True)
class CampaignSettings:
    '''Describe campaign-level runtime settings.'''

    time_seconds: int = 3600
    repetitions: int = 1
    parallel_jobs: int = os.cpu_count() or 2
    snapshot_jobs: int = 1
    snapshot_every_seconds: int = 900
    snapshot_export_every_ticks: int = 1
    memory: str | None = None
    memory_swap: str | None = None


@dataclass(frozen=True)
class CampaignConfig:
    '''Describe the full fuzzing campaign loaded from YAML.'''

    settings: CampaignSettings
    cases: list[CampaignCase]
    fuzzer_dirs: dict[str, Path] = field(default_factory=dict)
    fuzzer_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    benchmark_dirs: dict[str, Path] = field(default_factory=dict)
