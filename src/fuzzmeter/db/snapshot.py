# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Store and update snapshot coverage rows in the run database.'''

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .base import DB

LOG = logging.getLogger(__name__)
SEED_BASELINE_IDX = 0


@dataclass(frozen=True)
class CoverageSummary:
    '''Describe coverage fields stored on snapshot and aggregate rows.'''

    coverage_html_dir: str | None
    cov_lines_covered: int | None
    cov_lines_total: int | None
    cov_branches_covered: int | None
    cov_branches_total: int | None
    cov_regions_covered: int | None
    cov_regions_total: int | None
    cov_functions_covered: int | None
    cov_functions_total: int | None

    @classmethod
    def from_mapping(cls, *, coverage_html_dir: str | None, summary: dict[str, Any]) -> 'CoverageSummary':
        '''Create coverage fields from a coverage summary mapping.'''

        return cls(
            coverage_html_dir=coverage_html_dir,
            cov_lines_covered=summary.get('cov_lines_covered'),
            cov_lines_total=summary.get('cov_lines_total'),
            cov_branches_covered=summary.get('cov_branches_covered'),
            cov_branches_total=summary.get('cov_branches_total'),
            cov_regions_covered=summary.get('cov_regions_covered'),
            cov_regions_total=summary.get('cov_regions_total'),
            cov_functions_covered=summary.get('cov_functions_covered'),
            cov_functions_total=summary.get('cov_functions_total'),
        )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> 'CoverageSummary':
        '''Create coverage fields from a database row.'''

        return cls(
            coverage_html_dir=row.get('coverage_html_dir'),
            cov_lines_covered=row.get('cov_lines_covered'),
            cov_lines_total=row.get('cov_lines_total'),
            cov_branches_covered=row.get('cov_branches_covered'),
            cov_branches_total=row.get('cov_branches_total'),
            cov_regions_covered=row.get('cov_regions_covered'),
            cov_regions_total=row.get('cov_regions_total'),
            cov_functions_covered=row.get('cov_functions_covered'),
            cov_functions_total=row.get('cov_functions_total'),
        )

    def values(self) -> tuple[Any, ...]:
        '''Return coverage field values in database column order.'''

        return (
            self.coverage_html_dir,
            self.cov_lines_covered,
            self.cov_lines_total,
            self.cov_branches_covered,
            self.cov_branches_total,
            self.cov_regions_covered,
            self.cov_regions_total,
            self.cov_functions_covered,
            self.cov_functions_total,
        )


@dataclass(frozen=True)
class SnapshotRecord:
    '''Describe one trial snapshot row to persist.'''

    trial_db_id: int
    tick_idx: int
    end_ts: int
    corpus_files: int
    execs_done: int | None
    stats: dict[str, Any] | None
    crashes: int | None
    hangs: int | None
    coverage: CoverageSummary | None = None


def insert_tick(db: DB, *, run_id: str, idx: int, ts: int) -> None:
    '''Insert one snapshot tick for a run when missing.'''

    db.exec(
        'INSERT OR IGNORE INTO snapshot_ticks(run_id, idx, ts) VALUES(?,?,?)',
        (str(run_id), int(idx), int(ts)),
    )


def mark_tick_completed(db: DB, *, run_id: str, idx: int) -> None:
    '''Mark a snapshot tick as processed successfully.'''

    db.exec(
        "UPDATE snapshot_ticks SET status='completed', error=NULL WHERE run_id=? AND idx=?",
        (str(run_id), int(idx)),
    )


def mark_tick_failed(db: DB, *, run_id: str, idx: int, error: str) -> None:
    '''Record a snapshot tick processing failure.'''

    db.exec(
        "UPDATE snapshot_ticks SET status='failed', error=? WHERE run_id=? AND idx=?",
        (str(error), str(run_id), int(idx)),
    )


def get_latest_tick_idx(db: DB, *, run_id: str) -> int:
    '''Return the latest recorded snapshot tick index for a run.'''

    return int(db.scalar('SELECT COALESCE(MAX(idx), 0) FROM snapshot_ticks WHERE run_id=?', (str(run_id),)) or 0)


def get_next_tick_idx(db: DB, *, run_id: str) -> int:
    '''Return the next snapshot tick index for a run.'''

    return get_latest_tick_idx(db, run_id=run_id) + 1


def list_ticks(db: DB, *, run_id: str) -> list[dict[str, Any]]:
    '''Return snapshot ticks for a run ordered by tick index.'''
    return db.q(
        """
        SELECT run_id, idx, ts, status, error
          FROM snapshot_ticks
         WHERE run_id=?
         ORDER BY idx
        """,
        (str(run_id),),
    )


def list_trial_snapshots(db: DB, *, trial_row_id: int) -> list[dict[str, Any]]:
    '''Return snapshot rows for a trial ordered by tick index.'''
    return db.q(
        """
        SELECT *
          FROM snapshots
         WHERE trial_id=?
         ORDER BY idx
        """,
        (int(trial_row_id),),
    )


def save_snapshot_data(db: DB, record: SnapshotRecord) -> int:
    '''Insert one snapshot row and return its database id.'''

    stats_json = None
    if isinstance(record.stats, dict) and record.stats:
        stats_json = json.dumps(record.stats, sort_keys=True, separators=(',', ':'), default=str)
    db.exec(
        """
        INSERT OR IGNORE INTO snapshots(trial_id, idx, ts, corpus_files, execs_done, stats_json, crashes, hangs)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            int(record.trial_db_id),
            int(record.tick_idx),
            int(record.end_ts),
            int(record.corpus_files),
            None if record.execs_done is None else int(record.execs_done),
            stats_json,
            record.crashes,
            record.hangs,
        ),
    )
    sid = db.scalar(
        'SELECT snapshot_id FROM snapshots WHERE trial_id=? AND idx=?',
        (int(record.trial_db_id), int(record.tick_idx)),
    )
    snapshot_id = int(sid or 0)
    if record.coverage is not None and snapshot_id > 0:
        set_snapshot_coverage_fields(db, snapshot_id=snapshot_id, coverage=record.coverage)
    return snapshot_id


def latest_trial_snapshot(db: DB, *, trial_row_id: int) -> dict[str, Any] | None:
    '''Return the newest snapshot row of a trial, if any.'''

    rows = db.q(
        """
        SELECT *
          FROM snapshots
         WHERE trial_id=?
         ORDER BY idx DESC
         LIMIT 1
        """,
        (int(trial_row_id),),
    )
    return rows[0] if rows else None


def copy_previous_coverage_fields(db: DB, *, trial_row_id: int, snapshot_id: int) -> None:
    '''Copy the latest known coverage fields into a newer snapshot row.'''

    previous = db.q(
        """
        SELECT coverage_html_dir,
               cov_lines_covered,
               cov_lines_total,
               cov_branches_covered,
               cov_branches_total,
               cov_regions_covered,
               cov_regions_total,
               cov_functions_covered,
               cov_functions_total
          FROM snapshots
         WHERE trial_id=?
           AND snapshot_id<>?
           AND (
                cov_lines_covered IS NOT NULL
             OR cov_branches_covered IS NOT NULL
             OR cov_regions_covered IS NOT NULL
             OR cov_functions_covered IS NOT NULL
           )
         ORDER BY idx DESC
         LIMIT 1
        """,
        (int(trial_row_id), int(snapshot_id)),
    )
    if not previous:
        return
    _update_snapshot_coverage(db, snapshot_id=snapshot_id, coverage=CoverageSummary.from_row(previous[0]))


def copy_seed_baseline_coverage_fields(
    db: DB,
    *,
    run_id: str,
    fuzzer: str,
    benchmark: str,
    fuzz_target: str,
    snapshot_id: int,
) -> bool:
    '''Copy recorded seed baseline coverage fields into one trial snapshot row.'''
    baseline = db.q(
        """
        SELECT coverage_html_dir,
               cov_lines_covered,
               cov_lines_total,
               cov_branches_covered,
               cov_branches_total,
               cov_regions_covered,
               cov_regions_total,
               cov_functions_covered,
               cov_functions_total
          FROM agg_snapshots
         WHERE run_id=?
           AND fuzzer=?
           AND benchmark=?
           AND fuzz_target=?
           AND idx=?
         LIMIT 1
        """,
        (str(run_id), str(fuzzer), str(benchmark), str(fuzz_target), SEED_BASELINE_IDX),
    )
    if not baseline:
        return False
    _update_snapshot_coverage(db, snapshot_id=snapshot_id, coverage=CoverageSummary.from_row(baseline[0]))
    return True


def set_snapshot_coverage_fields(db: DB, *, snapshot_id: int, coverage: CoverageSummary) -> None:
    '''Store coverage summary fields on one snapshot row.'''

    if any(
        value is None
        for value in [
            coverage.cov_lines_covered,
            coverage.cov_lines_total,
            coverage.cov_branches_covered,
            coverage.cov_branches_total,
        ]
    ):
        LOG.warning(
            'Coverage summary missing fields for snapshot_id=%d: lines %s/%s branches %s/%s',
            snapshot_id,
            coverage.cov_lines_covered,
            coverage.cov_lines_total,
            coverage.cov_branches_covered,
            coverage.cov_branches_total,
        )

    _update_snapshot_coverage(db, snapshot_id=snapshot_id, coverage=coverage)


def _update_snapshot_coverage(db: DB, *, snapshot_id: int, coverage: CoverageSummary) -> None:
    '''Store coverage fields on one snapshot row without extra validation.'''

    db.exec(
        """
        UPDATE snapshots
           SET coverage_html_dir=?,
               cov_lines_covered=?,
               cov_lines_total=?,
               cov_branches_covered=?,
               cov_branches_total=?,
               cov_regions_covered=?,
               cov_regions_total=?,
               cov_functions_covered=?,
               cov_functions_total=?
         WHERE snapshot_id=?
        """,
        (*coverage.values(), int(snapshot_id)),
    )


def upsert_agg_snapshot(
    db: DB,
    *,
    run_id: str,
    fuzzer: str,
    benchmark: str,
    fuzz_target: str,
    idx: int,
    ts: int,
) -> int:
    '''Insert or update one aggregated snapshot row and return its id.'''

    db.exec(
        """
        INSERT OR IGNORE INTO agg_snapshots(run_id, fuzzer, benchmark, fuzz_target, idx, ts)
        VALUES(?,?,?,?,?,?)
        """,
        (str(run_id), str(fuzzer), str(benchmark), str(fuzz_target), int(idx), int(ts)),
    )
    db.exec(
        """
        UPDATE agg_snapshots
           SET ts=?
         WHERE run_id=? AND fuzzer=? AND benchmark=? AND fuzz_target=? AND idx=?
        """,
        (int(ts), str(run_id), str(fuzzer), str(benchmark), str(fuzz_target), int(idx)),
    )
    sid = db.scalar(
        """
        SELECT agg_snapshot_id
          FROM agg_snapshots
         WHERE run_id=? AND fuzzer=? AND benchmark=? AND fuzz_target=? AND idx=?
        """,
        (str(run_id), str(fuzzer), str(benchmark), str(fuzz_target), int(idx)),
    )
    return int(sid or 0)


def update_agg_snapshot_coverage(
    db: DB,
    *,
    agg_snapshot_id: int,
    coverage: CoverageSummary,
    coverage_sets_json_rel: str | None = None,
) -> None:
    '''Store aggregated coverage outputs on one aggregated snapshot row.'''

    db.exec(
        """
        UPDATE agg_snapshots
           SET coverage_html_dir=?,
               cov_lines_covered=?,
               cov_lines_total=?,
               cov_branches_covered=?,
               cov_branches_total=?,
               cov_regions_covered=?,
               cov_regions_total=?,
               cov_functions_covered=?,
               cov_functions_total=?,
               coverage_sets_json_rel=?
         WHERE agg_snapshot_id=?
        """,
        (
            *coverage.values(),
            coverage_sets_json_rel,
            int(agg_snapshot_id),
        ),
    )
