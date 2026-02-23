# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import json
from pathlib import Path

from ..db.base import DB
from ..db.snapshot import set_snapshot_coverage_fields


def trial_coverage_root(run_dir: Path, fuzzer: str, benchmark: str, fuzz_target: str) -> Path:
    '''Return the latest trial coverage output root for a target.'''
    return Path(run_dir) / 'coverage' / fuzzer / benchmark / fuzz_target


def seed_coverage_root(run_dir: Path, fuzzer: str, benchmark: str, fuzz_target: str) -> Path:
    '''Return the seed baseline coverage output root for a target.'''
    return Path(run_dir) / 'coverage_seed' / fuzzer / benchmark / fuzz_target


def collect_inputs(corpus_dir: Path, seen: set[str] | None = None) -> tuple[list[Path], list[str]]:
    '''Collect corpus files whose content hash is not in the seen set.'''
    return sorted(path for path in corpus_dir.rglob('*') if path.is_file())


def load_coverage_summary(summary_path: Path) -> dict:
    '''Load a coverage summary, returning an empty summary when unavailable.'''
    if not summary_path.exists():
        return {}

    try:
        return json.loads(summary_path.read_text(encoding='utf-8', errors='replace') or '{}')
    except Exception:
        return {}


def apply_snapshot_summary(*, db: DB, run_dir: Path, snapshot_id: int, out_root: Path, summary: dict) -> None:
    '''Store coverage summary fields for one snapshot.'''
    idx_path = out_root / 'html' / 'index.html'
    rel_html = str(idx_path.relative_to(run_dir)) if idx_path.exists() else None
    set_snapshot_coverage_fields(
        db=db,
        snapshot_id=int(snapshot_id),
        coverage_html_dir=rel_html,
        cov_lines_covered=summary.get('cov_lines_covered'),
        cov_lines_total=summary.get('cov_lines_total'),
        cov_branches_covered=summary.get('cov_branches_covered'),
        cov_branches_total=summary.get('cov_branches_total'),
        cov_regions_covered=summary.get('cov_regions_covered'),
        cov_regions_total=summary.get('cov_regions_total'),
        cov_functions_covered=summary.get('cov_functions_covered'),
        cov_functions_total=summary.get('cov_functions_total'),
    )
