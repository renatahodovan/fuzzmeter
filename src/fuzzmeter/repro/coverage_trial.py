# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Bootstrap trial coverage state from seed baseline artifacts.'''

from __future__ import annotations

import shutil

from pathlib import Path

from ..trial.models import ActiveTrial
from .coverage_state import seed_coverage_root


def bootstrap_from_seed_baseline(
    *,
    run_dir: Path,
    trial: ActiveTrial,
    latest_root: Path,
    state_dir: Path,
) -> None:
    '''Copy seed baseline coverage state into an empty trial coverage state.'''
    base_root = seed_coverage_root(run_dir, trial.fuzzer, trial.benchmark, trial.fuzz_target)
    baseline_summary = base_root / 'summary.json'
    baseline_profdata = base_root / '_state' / 'merged.profdata'

    if not baseline_summary.exists():
        return

    if not (state_dir / 'merged.profdata').exists() and baseline_profdata.exists():
        state_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(baseline_profdata, state_dir / 'merged.profdata')

    latest_root.parent.mkdir(parents=True, exist_ok=True)
    for name in (
        'summary.json',
        'coverage-sets.json',
        'merge_run_diagnostics.txt',
        'input_exec_diagnostics.txt',
    ):
        src = base_root / name
        dst = latest_root / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
