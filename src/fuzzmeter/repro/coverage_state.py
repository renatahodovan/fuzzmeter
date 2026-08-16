# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Manage coverage output locations and apply coverage summaries to snapshots.'''

from __future__ import annotations

import json

from pathlib import Path

from ..db.base import DB
from ..db.snapshot import CoverageSummary, set_snapshot_coverage_fields


def trial_coverage_root(run_dir: Path, fuzzer: str, benchmark: str, fuzz_target: str) -> Path:
    '''Return the latest trial coverage output root for a target.'''
    return run_dir / 'coverage' / fuzzer / benchmark / fuzz_target


def seed_coverage_root(run_dir: Path, fuzzer: str, benchmark: str, fuzz_target: str) -> Path:
    '''Return the seed baseline coverage output root for a target.'''
    return run_dir / 'coverage_seed' / fuzzer / benchmark / fuzz_target


def collect_inputs(corpus_dir: Path) -> list[Path]:
    '''Collect all regular files under corpus_dir, sorted by path.'''
    return sorted(path for path in corpus_dir.rglob('*') if path.is_file())


def load_coverage_summary(summary_path: Path) -> dict:
    '''Load a coverage summary, returning an empty summary when unavailable.'''
    if not summary_path.exists():
        return {}

    try:
        summary_text = summary_path.read_text(encoding='utf-8', errors='replace')
        return json.loads(summary_text or '{}')
    except Exception:
        return {}


def load_measurement_provenance(path: Path, *, carried_forward: bool = False) -> dict:
    '''Load measurement provenance and optionally mark reused coverage sets.'''

    provenance = load_coverage_summary(path)
    if not isinstance(provenance, dict):
        return {}
    if carried_forward and provenance:
        provenance = dict(provenance)
        coverage_sets = dict(provenance.get('coverage_sets') or {})
        coverage_sets['freshness'] = 'carried_forward'
        provenance['coverage_sets'] = coverage_sets
    return provenance


def apply_snapshot_summary(
    *,
    db: DB,
    run_dir: Path,
    snapshot_id: int,
    out_root: Path,
    summary: dict,
    carried_forward: bool = False,
) -> None:
    '''Store coverage summary fields for one snapshot.'''
    idx_path = out_root / 'html' / 'index.html'
    coverage_sets_path = out_root / 'coverage-sets.json'
    rel_html = str(idx_path.relative_to(run_dir)) if idx_path.exists() else None
    coverage_sets_json_rel = (
        str(coverage_sets_path.relative_to(run_dir)) if coverage_sets_path.exists() else None
    )
    set_snapshot_coverage_fields(
        db=db,
        snapshot_id=snapshot_id,
        coverage=CoverageSummary.from_mapping(coverage_html_dir=rel_html, summary=summary),
        coverage_sets_json_rel=coverage_sets_json_rel,
        measurement_provenance=load_measurement_provenance(
            out_root / 'measurement-provenance.json',
            carried_forward=carried_forward,
        ),
    )
