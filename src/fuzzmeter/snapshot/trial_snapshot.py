# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Define immutable models used by snapshot processing steps.'''

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..repro import ingest as repro_ingest
from ..trial.models import TrialInstance


@dataclass(frozen=True)
class TrialCoverageSnapshot:
    '''Describe coverage processing work for one trial snapshot.'''

    trial: TrialInstance
    snapshot_id: int
    snapshot_dir: Path
    tick_idx: int


@dataclass(frozen=True)
class TrialCrashSnapshot:
    '''Describe crash reproduction work for one trial snapshot.'''

    trial: TrialInstance
    snapshot_id: int
    snapshot_dir: Path
    tick_idx: int
    crash_files: list[repro_ingest.DetectedFile]
