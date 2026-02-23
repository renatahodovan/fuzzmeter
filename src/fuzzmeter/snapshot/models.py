# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..repro import ingest as repro_ingest
from ..trial.models import ActiveTrial


DEFAULT_COVERAGE_BATCH_SIZE = 256
DEFAULT_CRASH_BATCH_SIZE = 64


@dataclass(frozen=True)
class CoverageTask:
    '''Describe one trial coverage task for a snapshot tick.'''

    trial: ActiveTrial
    snap_dir: Path
    snapshot_id: int
    tick_idx: int
    render_heavy: bool = False


@dataclass(frozen=True)
class CrashTask:
    '''Describe one crash reproduction task for a snapshot tick.'''

    trial: ActiveTrial
    snapshot_id: int
    ts: int
    snapshot_crashes_dir: Path
    new_crash_files: list[repro_ingest.DetectedFile]


@dataclass(frozen=True)
class CoverageInprocessTask:
    '''Describe one libFuzzer in-process coverage replay batch.'''

    trial: ActiveTrial
    snapshot_id: int
    inputs: list[Path]
    batch_index: int
    batch_profdata_path: Path
    diagnostics_dir: Path


@dataclass(frozen=True)
class CoverageBatchTask:
    '''Describe one regular coverage replay batch run in one container.'''

    trial: ActiveTrial
    snapshot_id: int
    inputs: list[Path]
    batch_index: int
    batch_profdata_path: Path
    diagnostics_dir: Path


@dataclass(frozen=True)
class CrashBatchTask:
    '''Describe one crash replay batch run sequentially in one container.'''

    trial: ActiveTrial
    snapshot_id: int
    ts: int
    snapshot_crashes_dir: Path
    new_crash_files: list[repro_ingest.DetectedFile]
    batch_index: int


@dataclass(frozen=True)
class SnapshotTickPlan:
    '''Group all snapshot work selected for one tick.'''

    active_trials: list[ActiveTrial] = field(default_factory=list)
    coverage_tasks: list[CoverageTask] = field(default_factory=list)
    crash_tasks: list[CrashTask] = field(default_factory=list)
