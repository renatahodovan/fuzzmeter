# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for current database helper behavior.'''

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.db import bug as db_bug
from fuzzmeter.db import snapshot as db_snapshot
from fuzzmeter.db import trials as db_trials
from fuzzmeter.db.base import open_readonly_connection


class DatabaseBehaviorTest(unittest.TestCase):
    '''Pin behavior-sensitive database helper semantics before cleanup.'''

    def test_trial_rows_are_idempotent_and_refresh_started_timestamp(self) -> None:
        '''Repeated trial creation returns the same row and updates start time.'''
        with _open_test_db() as db:
            first_id = _ensure_trial(db, start_ts=100)
            second_id = _ensure_trial(db, start_ts=200)

            row = db.q1('SELECT trial_id, started_ts FROM trials')

        self.assertEqual(first_id, second_id)
        self.assertEqual({'trial_id': first_id, 'started_ts': 200}, row)

    def test_previous_coverage_copy_skips_rows_without_coverage_metrics(self) -> None:
        '''Coverage copying ignores earlier rows that only have an HTML path.'''
        with _open_test_db() as db:
            trial_id = _ensure_trial(db)
            empty_id = db_snapshot.save_snapshot_data(
                db,
                trial_db_id=trial_id,
                tick_idx=1,
                end_ts=10,
                corpus_files=0,
                execs_done=None,
                stats=None,
                crashes=0,
                hangs=0,
            )
            db.exec(
                'UPDATE snapshots SET coverage_html_dir=? WHERE snapshot_id=?',
                ('coverage/empty/html/index.html', empty_id),
            )

            target_id = db_snapshot.save_snapshot_data(
                db,
                trial_db_id=trial_id,
                tick_idx=2,
                end_ts=20,
                corpus_files=0,
                execs_done=None,
                stats=None,
                crashes=0,
                hangs=0,
            )
            db_snapshot.copy_previous_coverage_fields(db, trial_row_id=trial_id, snapshot_id=target_id)
            target_without_metrics = _snapshot_coverage_row(db, target_id)

            covered_id = db_snapshot.save_snapshot_data(
                db,
                trial_db_id=trial_id,
                tick_idx=3,
                end_ts=30,
                corpus_files=1,
                execs_done=10,
                stats={},
                crashes=0,
                hangs=0,
            )
            db_snapshot.set_snapshot_coverage_fields(
                db,
                snapshot_id=covered_id,
                coverage_html_dir='coverage/covered/html/index.html',
                cov_lines_covered=7,
                cov_lines_total=11,
                cov_branches_covered=3,
                cov_branches_total=5,
                cov_regions_covered=13,
                cov_regions_total=17,
                cov_functions_covered=2,
                cov_functions_total=4,
            )

            copied_id = db_snapshot.save_snapshot_data(
                db,
                trial_db_id=trial_id,
                tick_idx=4,
                end_ts=40,
                corpus_files=1,
                execs_done=20,
                stats={},
                crashes=0,
                hangs=0,
            )
            db_snapshot.copy_previous_coverage_fields(db, trial_row_id=trial_id, snapshot_id=copied_id)
            copied = _snapshot_coverage_row(db, copied_id)

        self.assertIsNone(target_without_metrics['coverage_html_dir'])
        self.assertEqual('coverage/covered/html/index.html', copied['coverage_html_dir'])
        self.assertEqual(7, copied['cov_lines_covered'])
        self.assertEqual(11, copied['cov_lines_total'])
        self.assertEqual(3, copied['cov_branches_covered'])
        self.assertEqual(5, copied['cov_branches_total'])
        self.assertEqual(13, copied['cov_regions_covered'])
        self.assertEqual(17, copied['cov_regions_total'])
        self.assertEqual(2, copied['cov_functions_covered'])
        self.assertEqual(4, copied['cov_functions_total'])

    def test_seed_baseline_coverage_copy_uses_aggregate_snapshot_index_zero(self) -> None:
        '''Seed baseline copy only uses the aggregate snapshot at index zero.'''
        with _open_test_db() as db:
            trial_id = _ensure_trial(db)
            snapshot_id = db_snapshot.save_snapshot_data(
                db,
                trial_db_id=trial_id,
                tick_idx=1,
                end_ts=10,
                corpus_files=0,
                execs_done=None,
                stats=None,
                crashes=0,
                hangs=0,
            )
            non_baseline_id = db_snapshot.upsert_agg_snapshot(
                db,
                run_id='run',
                fuzzer='fz',
                benchmark='bench',
                fuzz_target='target',
                idx=1,
                ts=10,
            )
            db_snapshot.update_agg_snapshot_coverage(
                db,
                agg_snapshot_id=non_baseline_id,
                coverage_html_dir='coverage/nonbaseline/html/index.html',
                summary={'cov_lines_covered': 99, 'cov_lines_total': 100},
                coverage_sets_json_rel='coverage/nonbaseline/coverage-sets.json',
            )

            copied_without_baseline = db_snapshot.copy_seed_baseline_coverage_fields(
                db,
                run_id='run',
                fuzzer='fz',
                benchmark='bench',
                fuzz_target='target',
                snapshot_id=snapshot_id,
            )

            baseline_id = db_snapshot.upsert_agg_snapshot(
                db,
                run_id='run',
                fuzzer='fz',
                benchmark='bench',
                fuzz_target='target',
                idx=db_snapshot.SEED_BASELINE_IDX,
                ts=1,
            )
            db_snapshot.update_agg_snapshot_coverage(
                db,
                agg_snapshot_id=baseline_id,
                coverage_html_dir='coverage_seed/fz/bench/target/html/index.html',
                summary={'cov_lines_covered': 5, 'cov_lines_total': 8},
                coverage_sets_json_rel='coverage_seed/fz/bench/target/coverage-sets.json',
            )
            copied_with_baseline = db_snapshot.copy_seed_baseline_coverage_fields(
                db,
                run_id='run',
                fuzzer='fz',
                benchmark='bench',
                fuzz_target='target',
                snapshot_id=snapshot_id,
            )
            copied = _snapshot_coverage_row(db, snapshot_id)

        self.assertFalse(copied_without_baseline)
        self.assertTrue(copied_with_baseline)
        self.assertEqual('coverage_seed/fz/bench/target/html/index.html', copied['coverage_html_dir'])
        self.assertEqual(5, copied['cov_lines_covered'])
        self.assertEqual(8, copied['cov_lines_total'])

    def test_aggregate_snapshot_upsert_refreshes_timestamp_without_clearing_coverage(self) -> None:
        '''Aggregate snapshot upserts preserve the row id and stored coverage fields.'''
        with _open_test_db() as db:
            first_id = db_snapshot.upsert_agg_snapshot(
                db,
                run_id='run',
                fuzzer='fz',
                benchmark='bench',
                fuzz_target='target',
                idx=7,
                ts=10,
            )
            db_snapshot.update_agg_snapshot_coverage(
                db,
                agg_snapshot_id=first_id,
                coverage_html_dir='coverage/fz/bench/target/campaign/html/index.html',
                summary={'cov_lines_covered': 1, 'cov_lines_total': 2},
                coverage_sets_json_rel='coverage/fz/bench/target/campaign_snapshots/000007/coverage-sets.json',
            )
            second_id = db_snapshot.upsert_agg_snapshot(
                db,
                run_id='run',
                fuzzer='fz',
                benchmark='bench',
                fuzz_target='target',
                idx=7,
                ts=20,
            )
            row = db.q1('SELECT agg_snapshot_id, ts, coverage_html_dir, coverage_sets_json_rel FROM agg_snapshots')

        self.assertEqual(first_id, second_id)
        self.assertEqual(first_id, row['agg_snapshot_id'])
        self.assertEqual(20, row['ts'])
        self.assertEqual('coverage/fz/bench/target/campaign/html/index.html', row['coverage_html_dir'])
        self.assertEqual(
            'coverage/fz/bench/target/campaign_snapshots/000007/coverage-sets.json',
            row['coverage_sets_json_rel'],
        )

    def test_bug_rows_are_deduplicated_and_hits_are_replaced(self) -> None:
        '''Bug identity is stable and per-snapshot hit counts are replaceable.'''
        with _open_test_db() as db:
            trial_id = _ensure_trial(db)
            snapshot_id = db_snapshot.save_snapshot_data(
                db,
                trial_db_id=trial_id,
                tick_idx=1,
                end_ts=10,
                corpus_files=1,
                execs_done=None,
                stats=None,
                crashes=1,
                hangs=0,
            )
            first_bug_id = db_bug.ensure_bug(
                db,
                run_id='run',
                fuzzer='fz',
                benchmark='bench',
                fuzz_target='target',
                bug_key='asan|top',
                issue_type='asan',
                top_func='top',
                frames=['top', 'caller'],
                output='first output',
                first_seen_ts=10,
                first_seen_snapshot_id=snapshot_id,
            )
            second_bug_id = db_bug.ensure_bug(
                db,
                run_id='run',
                fuzzer='fz',
                benchmark='bench',
                fuzz_target='target',
                bug_key='asan|top',
                issue_type='different',
                top_func='different',
                frames=['different'],
                output='second output',
                first_seen_ts=20,
                first_seen_snapshot_id=snapshot_id,
            )
            db_bug.upsert_bug_hits(db, bug_id=first_bug_id, snapshot_id=snapshot_id, hits=2)
            db_bug.upsert_bug_hits(db, bug_id=first_bug_id, snapshot_id=snapshot_id, hits=5)

            bug_row = db.q1('SELECT bug_id, issue_type, top_func, output, first_seen_ts FROM bugs')
            hit_row = db.q1('SELECT bug_id, snapshot_id, hits FROM bug_hits')

        self.assertEqual(first_bug_id, second_bug_id)
        self.assertEqual(
            {
                'bug_id': first_bug_id,
                'issue_type': 'asan',
                'top_func': 'top',
                'output': 'first output',
                'first_seen_ts': 10,
            },
            bug_row,
        )
        self.assertEqual({'bug_id': first_bug_id, 'snapshot_id': snapshot_id, 'hits': 5}, hit_row)

    def test_aggregate_snapshots_store_run_relative_campaign_coverage_paths(self) -> None:
        '''Aggregate coverage paths are stored as run-relative values.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'fuzzmeter.db'
            with _open_test_db(db_path) as db:
                agg_id = db_snapshot.upsert_agg_snapshot(
                    db,
                    run_id='run',
                    fuzzer='fz',
                    benchmark='bench',
                    fuzz_target='target',
                    idx=3,
                    ts=30,
                )
                db_snapshot.update_agg_snapshot_coverage(
                    db,
                    agg_snapshot_id=agg_id,
                    coverage_html_dir='coverage/fz/bench/target/campaign/html/index.html',
                    summary={'cov_lines_covered': 9, 'cov_lines_total': 10},
                    coverage_sets_json_rel='coverage/fz/bench/target/campaign_snapshots/000003/coverage-sets.json',
                )
                row = db.q1(
                    '''
                    SELECT coverage_html_dir, coverage_sets_json_rel
                      FROM agg_snapshots
                     WHERE agg_snapshot_id=?
                    ''',
                    (agg_id,),
                )

        self.assertEqual(
            {
                'coverage_html_dir': 'coverage/fz/bench/target/campaign/html/index.html',
                'coverage_sets_json_rel': 'coverage/fz/bench/target/campaign_snapshots/000003/coverage-sets.json',
            },
            row,
        )

    def test_readonly_connection_enables_foreign_keys_and_rejects_writes(self) -> None:
        '''Read-only DB connections keep reporting and web reads non-mutating.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'fuzzmeter.db'
            with _open_test_db(db_path):
                pass

            con = open_readonly_connection(db_path)
            try:
                foreign_keys = con.execute('PRAGMA foreign_keys').fetchone()[0]
                with self.assertRaises(sqlite3.OperationalError):
                    con.execute(
                        'INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)',
                        ('other-run', 2, 'config'),
                    )
            finally:
                con.close()

        self.assertEqual(1, foreign_keys)


@contextmanager
def _open_test_db(db_path: Path | None = None) -> Iterator[DB]:
    tmp_dir: tempfile.TemporaryDirectory[str] | None = None
    if db_path is None:
        tmp_dir = tempfile.TemporaryDirectory()
        db_path = Path(tmp_dir.name) / 'fuzzmeter.db'

    db = DB.open(db_path)
    try:
        ensure_schema(db)
        db.exec('INSERT OR IGNORE INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run', 1, 'config'))
        yield db
    finally:
        db.close()
        if tmp_dir is not None:
            tmp_dir.cleanup()


def _ensure_trial(db: DB, *, start_ts: int = 100) -> int:
    return db_trials.ensure_trial_row(
        db,
        run_id='run',
        fuzzer='fz',
        benchmark='bench',
        fuzz_target='target',
        rep=0,
        time_seconds=60,
        status='running',
        fuzzer_image='image',
        build_config_json=None,
        runtime_config_json=None,
        start_ts=start_ts,
    )


def _snapshot_coverage_row(db: DB, snapshot_id: int) -> dict:
    row = db.q1(
        '''
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
         WHERE snapshot_id=?
        ''',
        (snapshot_id,),
    )
    assert row is not None
    return row


if __name__ == '__main__':
    unittest.main()
