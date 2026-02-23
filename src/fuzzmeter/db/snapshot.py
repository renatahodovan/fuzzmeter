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

from typing import Any

from .base import DB

LOG = logging.getLogger(__name__)


def insert_tick(db: DB, *, run_id: str, idx: int, ts: int) -> None:
    db.exec(
        "INSERT OR IGNORE INTO snapshot_ticks(run_id, idx, ts) VALUES(?,?,?)",
        (str(run_id), int(idx), int(ts)),
    )


def get_latest_tick_idx(db: DB, *, run_id: str) -> int:
    return int(db.scalar("SELECT COALESCE(MAX(idx), 0) FROM snapshot_ticks WHERE run_id=?", (str(run_id),)) or 0)


def get_next_tick_idx(db: DB, *, run_id: str) -> int:
    return get_latest_tick_idx(db, run_id=run_id) + 1


def list_ticks(db: DB, *, run_id: str) -> list[dict[str, Any]]:
    '''Return snapshot ticks for a run ordered by tick index.'''
    return db.q(
        """
        SELECT run_id, idx, ts
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


def ensure_snapshot_row(
    db: DB,
    *,
    trial_row_id: int,
    idx: int,
    ts: int,
    corpus_files: int,
    execs_done: int | None,
    stats: dict[str, Any] | None,
    crashes: int | None,
    hangs: int | None,
) -> int:
    stats_json = None
    if isinstance(stats, dict) and stats:
        stats_json = json.dumps(stats, sort_keys=True, separators=(",", ":"), default=str)
    db.exec(
        """
        INSERT OR IGNORE INTO snapshots(trial_id, idx, ts, corpus_files, execs_done, stats_json, crashes, hangs)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            int(trial_row_id),
            int(idx),
            int(ts),
            int(corpus_files),
            None if execs_done is None else int(execs_done),
            stats_json,
            crashes,
            hangs,
        ),
    )
    sid = db.scalar("SELECT snapshot_id FROM snapshots WHERE trial_id=? AND idx=?", (int(trial_row_id), int(idx)))
    return int(sid or 0)


def latest_trial_snapshot(db: DB, *, trial_row_id: int) -> dict[str, Any] | None:
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
    row = previous[0]
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
        (
            row.get("coverage_html_dir"),
            row.get("cov_lines_covered"),
            row.get("cov_lines_total"),
            row.get("cov_branches_covered"),
            row.get("cov_branches_total"),
            row.get("cov_regions_covered"),
            row.get("cov_regions_total"),
            row.get("cov_functions_covered"),
            row.get("cov_functions_total"),
            int(snapshot_id),
        ),
    )


def trial_has_coverage_snapshots(db: DB, *, trial_row_id: int) -> bool:
    return bool(
        db.scalar(
            """
            SELECT 1
              FROM snapshots
             WHERE trial_id=?
               AND (
                    cov_lines_covered IS NOT NULL
                 OR cov_branches_covered IS NOT NULL
                 OR cov_regions_covered IS NOT NULL
                 OR cov_functions_covered IS NOT NULL
               )
             LIMIT 1
            """,
            (int(trial_row_id),),
        )
    )


def set_snapshot_coverage_fields(
    db: DB,
    *,
    snapshot_id: int,
    coverage_html_dir: str | None,
    cov_lines_covered: int | None,
    cov_lines_total: int | None,
    cov_branches_covered: int | None,
    cov_branches_total: int | None,
    cov_regions_covered: int | None,
    cov_regions_total: int | None,
    cov_functions_covered: int | None,
    cov_functions_total: int | None,
) -> None:
    if any(v is None for v in [cov_lines_covered, cov_lines_total, cov_branches_covered, cov_branches_total]):
        LOG.warning("Coverage summary missing fields for snapshot_id=%d: lines %s/%s branches %s/%s", snapshot_id, cov_lines_covered, cov_lines_total, cov_branches_covered, cov_branches_total)

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
        (
            coverage_html_dir,
            cov_lines_covered,
            cov_lines_total,
            cov_branches_covered,
            cov_branches_total,
            cov_regions_covered,
            cov_regions_total,
            cov_functions_covered,
            cov_functions_total,
            int(snapshot_id),
        ),
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
    coverage_html_dir: str | None,
    summary: dict[str, Any],
    coverage_sets_json_rel: str | None = None,
) -> None:
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
            coverage_html_dir,
            summary.get("cov_lines_covered"),
            summary.get("cov_lines_total"),
            summary.get("cov_branches_covered"),
            summary.get("cov_branches_total"),
            summary.get("cov_regions_covered"),
            summary.get("cov_regions_total"),
            summary.get("cov_functions_covered"),
            summary.get("cov_functions_total"),
            coverage_sets_json_rel,
            int(agg_snapshot_id),
        ),
    )
