# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CampaignCase:
    '''Describe one fuzzer-target combination in a campaign.'''

    fuzzer_base: str
    fuzzer_name: str
    fuzzer_chain: tuple[str, ...]
    benchmark: str
    fuzz_target: str
    target_id: str
    input_mode: str
    build_config: dict[str, Any] = field(default_factory=dict)
    runtime_config: dict[str, Any] = field(default_factory=dict)
    replay_trials: tuple[Path, ...] = ()


@dataclass(frozen=True)
class CampaignSettings:
    '''Describe campaign-level runtime settings.'''

    time_seconds: int = 3600
    repetitions: int = 1
    parallel_jobs: int = 1
    snapshot_jobs: int | None = None
    snapshot_every_seconds: int = 1800
    snapshot_export_every_ticks: int = 1
    memory: str | None = None
    memory_swap: str | None = None


@dataclass(frozen=True)
class CampaignConfig:
    '''Describe the full fuzzing campaign loaded from YAML.'''

    settings: CampaignSettings
    cases: list[CampaignCase]
