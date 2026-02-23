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

from ..reporting.keys import TRIAL_METADATA_FIELDS


class ReportingDB:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.con: sqlite3.Connection | None = None

    def __enter__(self) -> 'ReportingDB':
        uri = f'file:{self.db_path.as_posix()}?mode=ro'
        self.con = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute('PRAGMA busy_timeout=3000')
        self.con.execute('PRAGMA temp_store=MEMORY')
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.con is not None:
            self.con.close()
            self.con = None

    def rows(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        assert self.con is not None
        return [dict(row) for row in self.con.execute(sql, tuple(params)).fetchall()]

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        assert self.con is not None
        row = self.con.execute(sql, tuple(params)).fetchone()
        return None if row is None else row[0]

    def table_exists(self, table_name: str) -> bool:
        assert self.con is not None
        return bool(self.scalar(
            'SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=? LIMIT 1',
            (str(table_name),),
        ))

    def col_exists(self, table_name: str, col_name: str) -> bool:
        assert self.con is not None
        rows = self.rows(f'PRAGMA table_info({table_name})')
        return any(str(row.get('name') or '') == str(col_name) for row in rows)

    def infer_run_id(self, fallback: str) -> str:
        run_id = self.scalar('SELECT run_id FROM runs ORDER BY created_ts DESC LIMIT 1')
        return str(run_id or fallback)

    def run_overview(self, run_id: str) -> dict[str, Any]:
        overview: dict[str, Any] = {'run_id': run_id}
        overview['created_ts'] = self.scalar('SELECT created_ts FROM runs WHERE run_id=? LIMIT 1', (run_id,))
        overview['suite_yaml'] = self.scalar('SELECT suite_yaml FROM runs WHERE run_id=? LIMIT 1', (run_id,))
        overview['trials'] = int(self.scalar('SELECT COUNT(*) FROM trials WHERE run_id=?', (run_id,)) or 0)
        overview['snapshots'] = int(self.scalar(
            'SELECT COUNT(*) FROM snapshots s JOIN trials t ON t.trial_id=s.trial_id WHERE t.run_id=?',
            (run_id,),
        ) or 0)
        overview['bugs'] = int(self.scalar('SELECT COUNT(*) FROM bugs WHERE run_id=?', (run_id,)) or 0)
        return overview

    def trial_rows(self, run_id: str) -> list[dict[str, Any]]:
        metadata_select = ', '.join(TRIAL_METADATA_FIELDS)
        return self.rows(
            f"""
            SELECT trial_id, fuzzer, benchmark, fuzz_target, rep,
                   time_seconds, jobs, status, started_ts, ended_ts, {metadata_select}
            FROM trials
            WHERE run_id=?
            ORDER BY benchmark, fuzz_target, fuzzer, rep
            """,
            (run_id,),
        )

    def latest_snapshots_by_trial(self, trial_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
        if not trial_ids:
            return {}
        placeholders = ','.join('?' for _ in trial_ids)
        rows = self.rows(
            f"""
            SELECT s.*
            FROM snapshots AS s
            JOIN (
                SELECT trial_id, MAX(idx) AS max_idx
                FROM snapshots
                WHERE trial_id IN ({placeholders})
                GROUP BY trial_id
            ) AS m
              ON m.trial_id = s.trial_id AND m.max_idx = s.idx
            """,
            tuple(int(tid) for tid in trial_ids),
        )
        return {int(row['trial_id']): row for row in rows}

    def snapshot_rows(self, trial_ids: Sequence[int]) -> list[dict[str, Any]]:
        if not trial_ids:
            return []
        placeholders = ','.join('?' for _ in trial_ids)
        return self.rows(
            f"""
            SELECT snapshot_id, trial_id, idx, ts, corpus_files, execs_done, stats_json,
                   crashes, hangs,
                   cov_lines_covered, cov_lines_total,
                   cov_branches_covered, cov_branches_total,
                   cov_functions_covered, cov_functions_total,
                   cov_regions_covered, cov_regions_total,
                   coverage_html_dir
            FROM snapshots
            WHERE trial_id IN ({placeholders})
            ORDER BY trial_id, idx
            """,
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
                   corpus_disk_usage_bytes, corpus_disk_usage_human, stats_json
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
                WHERE run_id=?
                GROUP BY fuzzer, benchmark, fuzz_target
            ) AS latest
              ON latest.fuzzer = a.fuzzer
             AND latest.benchmark = a.benchmark
             AND latest.fuzz_target = a.fuzz_target
             AND latest.max_idx = a.idx
            WHERE a.run_id=?
            ''',
            (run_id, run_id),
        )
        return {
            (str(row['fuzzer']), str(row['benchmark']), str(row['fuzz_target'])): row
            for row in rows
        }

    def bug_hits_by_snapshot(self) -> dict[int, int]:
        return {int(row['snapshot_id']): int(row['hits'] or 0) for row in self.rows(
            'SELECT snapshot_id, SUM(hits) AS hits FROM bug_hits GROUP BY snapshot_id'
        )}

    def unique_bug_delta_by_snapshot(self) -> dict[int, int]:
        return {int(row['snapshot_id']): int(row['c'] or 0) for row in self.rows(
            '''
            SELECT first_seen_snapshot_id AS snapshot_id, COUNT(*) AS c
            FROM bugs
            WHERE first_seen_snapshot_id IS NOT NULL
            GROUP BY first_seen_snapshot_id
            '''
        )}

    def bug_stats_by_trial(self, run_id: str) -> dict[int, tuple[int, int]]:
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

    def bug_rows(self, run_id: str) -> list[dict[str, Any]]:
        return self.rows(
            '''
            SELECT bug_id, run_id, fuzzer, benchmark, fuzz_target, bug_key,
                   issue_type, top_func, frames_json, output, first_seen_ts, first_seen_snapshot_id
            FROM bugs
            WHERE run_id=?
            ORDER BY benchmark, fuzz_target, fuzzer, first_seen_ts
            ''',
            (run_id,),
        )

    def bug_hits_by_bug(self) -> dict[int, int]:
        return {int(row['bug_id']): int(row['hits'] or 0) for row in self.rows(
            'SELECT bug_id, SUM(hits) AS hits FROM bug_hits GROUP BY bug_id'
        )}

    def bug_trials_by_bug(self) -> dict[int, list[int]]:
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
