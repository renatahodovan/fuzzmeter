# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Read database rows for report generation.'''

from __future__ import annotations

import sqlite3

from pathlib import Path
from typing import Any, Sequence

from .base import open_readonly_connection
from .bug import BugRow
from .fields import TRIAL_METADATA_FIELDS
from .snapshot import SEED_BASELINE_IDX


class ReportingDB:
    '''Expose read-only report queries over the run database.'''

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.con: sqlite3.Connection | None = None

    def __enter__(self) -> 'ReportingDB':
        self.con = open_readonly_connection(self.db_path)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.con is not None:
            self.con.close()
            self.con = None

    def rows(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        '''Execute a query and return all rows as dictionaries.'''

        assert self.con is not None
        return [dict(row) for row in self.con.execute(sql, tuple(params)).fetchall()]

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        '''Execute a query and return the first scalar value.'''

        assert self.con is not None
        row = self.con.execute(sql, tuple(params)).fetchone()
        return None if row is None else row[0]

    def infer_run_id(self, fallback: str) -> str:
        '''Return the newest run id or the provided fallback.'''

        run_id = self.scalar('SELECT run_id FROM runs ORDER BY created_ts DESC LIMIT 1')
        return str(run_id or fallback)

    def run_overview(self, run_id: str) -> dict[str, Any]:
        '''Return aggregate run counters and basic metadata.'''

        overview: dict[str, Any] = {'run_id': run_id}
        overview['created_ts'] = self.scalar('SELECT created_ts FROM runs WHERE run_id=? LIMIT 1', (run_id,))
        overview['config_src'] = self.scalar('SELECT config_src FROM runs WHERE run_id=? LIMIT 1', (run_id,))
        overview['trials'] = int(self.scalar('SELECT COUNT(*) FROM trials WHERE run_id=?', (run_id,)) or 0)
        overview['snapshots'] = int(self.scalar(
            'SELECT COUNT(*) FROM snapshots s JOIN trials t ON t.trial_id=s.trial_id WHERE t.run_id=?',
            (run_id,),
        ) or 0)
        overview['failed_snapshot_ticks'] = int(self.scalar(
            "SELECT COUNT(*) FROM snapshot_ticks WHERE run_id=? AND status='failed'",
            (run_id,),
        ) or 0)
        overview['bugs'] = int(self.scalar('SELECT COUNT(*) FROM bugs WHERE run_id=?', (run_id,)) or 0)
        return overview

    def status_counts(self, run_id: str) -> dict[str, int]:
        '''Return trial status counts for a run.'''

        rows = self.rows(
            '''
            SELECT status, COUNT(*) AS c
              FROM trials
             WHERE run_id=?
             GROUP BY status
            ''',
            (run_id,),
        )
        return {str(row.get('status') or 'unknown'): int(row.get('c') or 0) for row in rows}

    def run_summary_counts(self, run_id: str) -> dict[str, Any]:
        '''Return web run summary counts for a run.'''

        overview = self.run_overview(run_id)
        return {
            'created_ts': int(overview.get('created_ts') or 0) or None,
            'trials': int(overview.get('trials') or 0),
            'snapshots': int(overview.get('snapshots') or 0),
            'bugs': int(overview.get('bugs') or 0),
            'benchmark_count': int(
                self.scalar('SELECT COUNT(DISTINCT benchmark) FROM trials WHERE run_id=?', (run_id,)) or 0
            ),
            'target_count': int(
                self.scalar(
                    'SELECT COUNT(DISTINCT benchmark || \'::\' || fuzz_target) FROM trials WHERE run_id=?',
                    (run_id,),
                ) or 0
            ),
            'fuzzer_count': int(
                self.scalar('SELECT COUNT(DISTINCT fuzzer) FROM trials WHERE run_id=?', (run_id,)) or 0
            ),
            'status_counts': self.status_counts(run_id),
            'config_src': overview.get('config_src'),
            'label': self.scalar('SELECT label FROM runs WHERE run_id=? LIMIT 1', (run_id,)),
        }

    def trial_rows(self, run_id: str) -> list[dict[str, Any]]:
        '''Return all trial rows that belong to a run.'''

        metadata_select = ', '.join(TRIAL_METADATA_FIELDS)
        return self.rows(
            f'''
            SELECT trial_id, fuzzer, benchmark, fuzz_target, rep,
                   time_seconds, jobs, status, started_ts, ended_ts, {metadata_select}
            FROM trials
            WHERE run_id=?
            ORDER BY benchmark, fuzz_target, fuzzer, rep
            ''',
            (run_id,),
        )

    def latest_snapshots_by_trial(self, trial_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
        '''Return the newest snapshot row for each requested trial.'''

        if not trial_ids:
            return {}
        placeholders = ','.join('?' for _ in trial_ids)
        rows = self.rows(
            f'''
            SELECT s.*
            FROM snapshots AS s
            JOIN (
                SELECT trial_id, MAX(idx) AS max_idx
                FROM snapshots
                WHERE trial_id IN ({placeholders})
                GROUP BY trial_id
            ) AS m
              ON m.trial_id = s.trial_id AND m.max_idx = s.idx
            ''',
            tuple(int(tid) for tid in trial_ids),
        )
        return {int(row['trial_id']): row for row in rows}

    def snapshot_rows(self, trial_ids: Sequence[int]) -> list[dict[str, Any]]:
        '''Return all snapshot rows for the requested trials.'''

        if not trial_ids:
            return []
        placeholders = ','.join('?' for _ in trial_ids)
        return self.rows(
            f'''
            SELECT snapshot_id, trial_id, idx, ts, corpus_files, execs_done, stats_json,
                   crashes, hangs,
                   cov_lines_covered, cov_lines_total,
                   cov_branches_covered, cov_branches_total,
                   cov_functions_covered, cov_functions_total,
                   cov_regions_covered, cov_regions_total,
                   coverage_html_dir, coverage_sets_json_rel,
                   measurement_provenance_json
            FROM snapshots
            WHERE trial_id IN ({placeholders})
            ORDER BY trial_id, idx
            ''',
            tuple(int(tid) for tid in trial_ids),
        )

    def resource_telemetry_rows(self, trial_ids: Sequence[int]) -> list[dict[str, Any]]:
        '''Return resource telemetry rows for report time series.'''

        if not trial_ids:
            return []
        placeholders = ','.join('?' for _ in trial_ids)
        return self.rows(
            f'''
            SELECT trial_id, idx, ts, container_name,
                   cpu_percent, memory_usage_bytes, memory_limit_bytes, memory_percent,
                   corpus_disk_usage_bytes
            FROM resource_telemetry
            WHERE trial_id IN ({placeholders})
            ORDER BY trial_id, idx
            ''',
            tuple(int(tid) for tid in trial_ids),
        )

    def latest_agg_snapshots_by_fuzzer_target(self, run_id: str) -> dict[tuple[str, str, str], dict[str, Any]]:
        '''Return latest campaign coverage rows keyed by fuzzer and target.'''
        rows = self.rows(
            '''
            SELECT a.*
            FROM agg_snapshots AS a
            JOIN (
                SELECT fuzzer, benchmark, fuzz_target, MAX(idx) AS max_idx
                FROM agg_snapshots
                WHERE run_id=? AND idx>?
                GROUP BY fuzzer, benchmark, fuzz_target
            ) AS latest
              ON latest.fuzzer = a.fuzzer
             AND latest.benchmark = a.benchmark
             AND latest.fuzz_target = a.fuzz_target
             AND latest.max_idx = a.idx
            WHERE a.run_id=?
            ''',
            (run_id, SEED_BASELINE_IDX, run_id),
        )
        return {
            (str(row['fuzzer']), str(row['benchmark']), str(row['fuzz_target'])): row
            for row in rows
        }

    def seed_baselines_by_fuzzer_target(self, run_id: str) -> dict[tuple[str, str, str], dict[str, Any]]:
        '''Return seed baseline coverage rows keyed by fuzzer and target.'''
        rows = self.rows(
            '''
            SELECT *
            FROM agg_snapshots
            WHERE run_id=? AND idx=?
            ''',
            (run_id, SEED_BASELINE_IDX),
        )
        return {
            (str(row['fuzzer']), str(row['benchmark']), str(row['fuzz_target'])): row
            for row in rows
        }

    def metadata_rows(self, run_id: str) -> list[dict[str, Any]]:
        '''Return composite metadata rows for a run.'''

        try:
            return self.rows(
                '''
                SELECT run_id, fuzzer, benchmark, fuzz_target, metadata_schema_version,
                       repetitions, runtime_seconds, environment_digest, config_digest,
                       source_digest, metadata_json, created_at
                FROM metadata
                WHERE run_id=?
                ORDER BY benchmark, fuzz_target, fuzzer
                ''',
                (run_id,),
            )
        except sqlite3.OperationalError:
            return []

    def bug_hits_by_snapshot(self) -> dict[int, int]:
        '''Return total bug hit counts keyed by snapshot id.'''

        return {int(row['snapshot_id']): int(row['hits'] or 0) for row in self.rows(
            'SELECT snapshot_id, SUM(hits) AS hits FROM bug_hits GROUP BY snapshot_id'
        )}

    def unique_bug_delta_by_snapshot(self) -> dict[int, int]:
        '''Return newly discovered bug counts keyed by first-seen snapshot id.'''

        return {int(row['snapshot_id']): int(row['c'] or 0) for row in self.rows(
            '''
            SELECT first_seen_snapshot_id AS snapshot_id, COUNT(*) AS c
            FROM bugs
            WHERE first_seen_snapshot_id IS NOT NULL
            GROUP BY first_seen_snapshot_id
            '''
        )}

    def bug_stats_by_trial(self, run_id: str) -> dict[int, tuple[int, int]]:
        '''Return total hits and unique bug counts keyed by trial id.'''

        rows = self.rows(
            '''
            SELECT s.trial_id AS trial_id,
                   COALESCE(SUM(bh.hits),0) AS hits,
                   COUNT(DISTINCT b.bug_id) AS uniq
            FROM bug_hits bh
            JOIN bugs b ON b.bug_id=bh.bug_id
            JOIN snapshots s ON s.snapshot_id=bh.snapshot_id
            WHERE b.run_id=?
            GROUP BY s.trial_id
            ''',
            (run_id,),
        )
        return {int(row['trial_id']): (int(row['hits'] or 0), int(row['uniq'] or 0)) for row in rows}

    def bug_rows(self, run_id: str) -> list[BugRow]:
        '''Return all stored bug rows for a run.'''

        return [
            BugRow.from_row(row)
            for row in self.rows(
                '''
                SELECT bug_id, run_id, fuzzer, benchmark, fuzz_target, bug_key,
                       issue_type, top_func, frames_json, output, first_seen_ts, first_seen_snapshot_id
                FROM bugs
                WHERE run_id=?
                ORDER BY benchmark, fuzz_target, fuzzer, first_seen_ts
                ''',
                (run_id,),
            )
        ]

    def bug_hits_by_bug(self) -> dict[int, int]:
        '''Return total hit counts keyed by bug id.'''

        return {int(row['bug_id']): int(row['hits'] or 0) for row in self.rows(
            'SELECT bug_id, SUM(hits) AS hits FROM bug_hits GROUP BY bug_id'
        )}

    def bug_trials_by_bug(self) -> dict[int, list[int]]:
        '''Return distinct trial ids keyed by bug id.'''

        rows = self.rows(
            '''
            SELECT bh.bug_id AS bug_id, s.trial_id AS trial_id
            FROM bug_hits AS bh
            JOIN snapshots AS s ON s.snapshot_id = bh.snapshot_id
            GROUP BY bh.bug_id, s.trial_id
            '''
        )
        out: dict[int, list[int]] = {}
        for row in rows:
            bug_id = int(row['bug_id'])
            out.setdefault(bug_id, []).append(int(row['trial_id']))
        return out
