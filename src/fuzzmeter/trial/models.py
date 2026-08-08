# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Describe trial configuration, filesystem layout, and concrete run instances.'''

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..fuzzers import OutputPaths

FUZZ_DIR = Path('work')
SNAPSHOTS_DIR = Path('snapshots')
LOGS_DIR = Path('logs')
FUZZER_LOG = Path('logs/fuzzer.log')


class TrialImages:
    '''Build docker image names for one fuzzer and target pair.'''

    def __init__(self, *, fuzzer_name: str, target_key: str) -> None:
        self.runner = f'fuzzmeter/runner-{fuzzer_name}-{target_key}:dev'
        self.coverage = f'fuzzmeter/coverage-runner-{target_key}:dev'
        self.asan = f'fuzzmeter/asan-runner-{target_key}:dev'


@dataclass(frozen=True)
class TrialConfig:
    '''Describe one logical trial independent of its run directory.'''

    fuzzer: str
    fuzzer_impl: str
    benchmark: str
    fuzz_target: str
    fuzz_target_bin: Path
    fuzz_target_input_mode: str
    fuzz_target_timeout: float
    rep_idx: int
    trial_key: str
    output_paths: OutputPaths
    trial_timeout: int
    snapshot_preprocess: Path | None
    images: TrialImages
    replay_dir: Path | None = None
    build_config: dict[str, Any] = field(default_factory=dict)
    runtime_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TrialLayout:
    '''Describe host-side paths for one concrete trial.'''

    trial_dir: Path
    fuzz_dir: Path
    corpus_dir: Path
    crashes_dir: Path
    snapshots_dir: Path
    logs_dir: Path
    fuzzer_log: Path
    hangs_dir: Path | None = None

    @classmethod
    def from_config(cls, *, trial_dir: Path, cfg: TrialConfig) -> TrialLayout:
        '''Resolve the host-side filesystem layout for one trial config.'''
        fuzz_dir = trial_dir / FUZZ_DIR
        corpus_dir = fuzz_dir / cfg.output_paths.corpus_root
        crashes_dir = fuzz_dir / cfg.output_paths.crashes_root
        hangs_dir = None
        if cfg.output_paths.hangs_root is not None:
            hangs_dir = fuzz_dir / cfg.output_paths.hangs_root

        return cls(
            trial_dir=trial_dir,
            fuzz_dir=fuzz_dir,
            corpus_dir=corpus_dir,
            crashes_dir=crashes_dir,
            hangs_dir=hangs_dir,
            snapshots_dir=trial_dir / SNAPSHOTS_DIR,
            logs_dir=trial_dir / LOGS_DIR,
            fuzzer_log=trial_dir / FUZZER_LOG,
        )


@dataclass(frozen=True)
class TrialInstance:
    '''Bind a trial config and layout to one concrete database/run instance.'''

    db_id: int
    config: TrialConfig
    layout: TrialLayout
    container_name: str
    fuzzers_root: Path
    start_ts: int


@dataclass(frozen=True)
class ReplayTrialInstance(TrialInstance):
    '''Extend a trial instance with the fixed replay end timestamp.'''

    end_ts: int
