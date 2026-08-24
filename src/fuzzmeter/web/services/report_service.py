# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Adapt reporting payload and export helpers for live web runs.'''

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ...reporting import build_payload, write_report
from .file_service import require_run_dir


def load_report_payload(run_dirs: Iterable[Path], run_id: str) -> dict[str, Any]:
    '''Build the live report payload for one existing run.'''

    run_dir = require_run_dir(run_dirs, run_id)
    return build_payload(run_dir, file_url_prefix=f'/file/{run_id}/')


def export_static_report(run_dirs: Iterable[Path], run_id: str) -> Path:
    '''Write a static report for one existing run and return its directory.'''

    run_dir = require_run_dir(run_dirs, run_id)
    return write_report(run_dir, out_dir=run_dir / 'report')
