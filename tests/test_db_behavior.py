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
from fuzzmeter.db import metadata as db_metadata
from fuzzmeter.db import snapshot as db_snapshot
from fuzzmeter.db import trials as db_trials
from fuzzmeter.db.base import open_readonly_connection
from fuzzmeter.db.report_views import ReportingDB


class DatabaseBehaviorTest(unittest.TestCase):
    '''Pin behavior-sensitive database helper semantics before cleanup.'''

    def test_snapshot_tick_status_is_persisted_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'fuzzmeter.db'
            with _open_test_db(db_path) as db:
                db_snapshot.insert_tick(db, run_id='run', idx=1, ts=10)
                db_snapshot.mark_tick_failed(db, run_id='run', idx=1, error='coverage failed')
                tick = db_snapshot.list_ticks(db, run_id='run')[0]
                db.commit()
                with ReportingDB(db_path) as reporting:
                    overview = reporting.run_overview('run')

        self.assertEqual('failed', tick['status'])
        self.assertEqual('coverage failed', tick['error'])
        self.assertEqual(1, overview['failed_snapshot_ticks'])

    def test_schema_adds_status_to_existing_snapshot_ticks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = DB.open(Path(tmp_dir) / 'fuzzmeter.db')
            try:
                db.exec(
                    '''
                    CREATE TABLE snapshot_ticks(
                      run_id TEXT NOT NULL,
                      idx INTEGER NOT NULL,
                      ts INTEGER NOT NULL,
                      PRIMARY KEY(run_id, idx)
                    )
                    ''',
                )
                db.exec('INSERT INTO snapshot_ticks(run_id, idx, ts) VALUES(?,?,?)', ('run', 1, 10))

                ensure_schema(db)

                tick = db_snapshot.list_ticks(db, run_id='run')[0]
            finally:
                db.close()

        self.assertEqual('pending', tick['status'])
        self.assertIsNone(tick['error'])

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
                _snapshot_record(trial_id=trial_id, tick_idx=1, end_ts=10, corpus_files=0),
            )
            db.exec(
                'UPDATE snapshots SET coverage_html_dir=? WHERE snapshot_id=?',
                ('coverage/empty/html/index.html', empty_id),
            )

            target_id = db_snapshot.save_snapshot_data(
                db,
                _snapshot_record(trial_id=trial_id, tick_idx=2, end_ts=20, corpus_files=0),
            )
            db_snapshot.copy_previous_coverage_fields(db, trial_row_id=trial_id, snapshot_id=target_id)
            target_without_metrics = _snapshot_coverage_row(db, target_id)

            covered_id = db_snapshot.save_snapshot_data(
                db,
                _snapshot_record(trial_id=trial_id, tick_idx=3, end_ts=30, corpus_files=1, execs_done=10),
            )
            db_snapshot.set_snapshot_coverage_fields(
                db,
                snapshot_id=covered_id,
                coverage=db_snapshot.CoverageSummary(
                    coverage_html_dir='coverage/covered/html/index.html',
                    cov_lines_covered=7,
                    cov_lines_total=11,
                    cov_branches_covered=3,
                    cov_branches_total=5,
                    cov_regions_covered=13,
                    cov_regions_total=17,
                    cov_functions_covered=2,
                    cov_functions_total=4,
                ),
            )

            copied_id = db_snapshot.save_snapshot_data(
                db,
                _snapshot_record(trial_id=trial_id, tick_idx=4, end_ts=40, corpus_files=1, execs_done=20),
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
                _snapshot_record(trial_id=trial_id, tick_idx=1, end_ts=10, corpus_files=0),
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
                coverage=db_snapshot.CoverageSummary.from_mapping(
                    coverage_html_dir='coverage/nonbaseline/html/index.html',
                    summary={'cov_lines_covered': 99, 'cov_lines_total': 100},
                ),
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
                coverage=db_snapshot.CoverageSummary.from_mapping(
                    coverage_html_dir='coverage_seed/fz/bench/target/html/index.html',
                    summary={'cov_lines_covered': 5, 'cov_lines_total': 8},
                ),
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
                coverage=db_snapshot.CoverageSummary.from_mapping(
                    coverage_html_dir='coverage/fz/bench/target/campaign/html/index.html',
                    summary={'cov_lines_covered': 1, 'cov_lines_total': 2},
                ),
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
                _snapshot_record(trial_id=trial_id, tick_idx=1, end_ts=10, corpus_files=1, crashes=1),
            )
            first_bug_id = db_bug.ensure_bug(
                db,
                db_bug.BugRecord(
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
                ),
            )
            second_bug_id = db_bug.ensure_bug(
                db,
                db_bug.BugRecord(
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
                ),
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
                    coverage=db_snapshot.CoverageSummary.from_mapping(
                        coverage_html_dir='coverage/fz/bench/target/campaign/html/index.html',
                        summary={'cov_lines_covered': 9, 'cov_lines_total': 10},
                    ),
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

    def test_readonly_connection_does_not_create_sidecars_for_finished_wal_db(self) -> None:
        '''Finished WAL databases remain readable without filesystem writes.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'fuzzmeter.db'
            with _open_test_db(db_path) as db:
                db.con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            for suffix in ('-wal', '-shm'):
                Path(f'{db_path}{suffix}').unlink(missing_ok=True)
            before_mtime = root.stat().st_mtime_ns

            con = open_readonly_connection(db_path)
            try:
                run_id = con.execute('SELECT run_id FROM runs').fetchone()[0]
            finally:
                con.close()

            self.assertEqual('run', run_id)
            self.assertEqual(before_mtime, root.stat().st_mtime_ns)
            self.assertEqual(['fuzzmeter.db'], [path.name for path in root.iterdir()])

    def test_readonly_connection_reads_live_wal_rows(self) -> None:
        '''Live reporting reads include rows that have not left the WAL.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'fuzzmeter.db'
            db = DB.open(db_path)
            try:
                ensure_schema(db)
                db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('live', 1, 'config'))
                self.assertTrue(Path(f'{db_path}-wal').is_file())

                con = open_readonly_connection(db_path)
                try:
                    run_id = con.execute('SELECT run_id FROM runs').fetchone()[0]
                finally:
                    con.close()
            finally:
                db.close()

        self.assertEqual('live', run_id)

    def test_reporting_run_summary_counts_current_schema_rows(self) -> None:
        '''ReportingDB exposes current-schema run summary counts for the web UI.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'fuzzmeter.db'
            with _open_test_db(db_path) as db:
                trial_id = _ensure_trial(db)
                db_trials.set_trial_status(db, trial_id=trial_id, status='done', ended_ts=200)
                snapshot_id = db_snapshot.save_snapshot_data(
                    db,
                    _snapshot_record(trial_id=trial_id, tick_idx=1, end_ts=200, corpus_files=1),
                )
                db_bug.ensure_bug(
                    db,
                    db_bug.BugRecord(
                        run_id='run',
                        fuzzer='fz',
                        benchmark='bench',
                        fuzz_target='target',
                        bug_key='bug',
                        issue_type='crash',
                        top_func='main',
                        frames=['main'],
                        output='output',
                        first_seen_ts=200,
                        first_seen_snapshot_id=snapshot_id,
                    ),
                )

            with ReportingDB(db_path) as reporting_db:
                counts = reporting_db.run_summary_counts('run')

        self.assertEqual(1, counts['trials'])
        self.assertEqual(1, counts['snapshots'])
        self.assertEqual(1, counts['bugs'])
        self.assertEqual(1, counts['benchmark_count'])
        self.assertEqual(1, counts['target_count'])
        self.assertEqual(1, counts['fuzzer_count'])
        self.assertEqual({'done': 1}, counts['status_counts'])
        self.assertEqual('config', counts['config_src'])

    def test_metadata_rows_are_replaceable(self) -> None:
        '''Composite descriptor rows are keyed by run, fuzzer, and target.'''
        with _open_test_db() as db:
            db_metadata.upsert_metadata(
                db,
                db_metadata.MetadataRecord(
                    run_id='run',
                    fuzzer='fz',
                    benchmark='bench',
                    fuzz_target='target',
                    repetitions=1,
                    runtime_seconds=60,
                    environment_digest='env1',
                    config_digest='cfg1',
                    source_digest='src1',
                    metadata={'a': 1},
                    created_at=100,
                ),
            )
            db_metadata.upsert_metadata(
                db,
                db_metadata.MetadataRecord(
                    run_id='run',
                    fuzzer='fz',
                    benchmark='bench',
                    fuzz_target='target',
                    repetitions=2,
                    runtime_seconds=120,
                    environment_digest='env2',
                    config_digest='cfg2',
                    source_digest='src2',
                    metadata={'b': [1, 2]},
                    created_at=200,
                ),
            )

            rows = db_metadata.list_metadata(db)

        self.assertEqual(1, len(rows))
        self.assertEqual(2, rows[0].repetitions)
        self.assertEqual(120, rows[0].runtime_seconds)
        self.assertEqual('env2', rows[0].environment_digest)
        self.assertEqual('cfg2', rows[0].config_digest)
        self.assertEqual('src2', rows[0].source_digest)
        self.assertEqual({'b': [1, 2]}, rows[0].metadata)

    def test_current_schema_rejects_orphan_child_rows_and_cascades_owned_rows(self) -> None:
        '''Current foreign keys protect owned child rows.'''
        with _open_test_db() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.exec(
                    '''
                    INSERT INTO trials(run_id, fuzzer, benchmark, fuzz_target, rep)
                    VALUES(?,?,?,?,?)
                    ''',
                    ('missing-run', 'fz', 'bench', 'target', 0),
                )

            with self.assertRaises(sqlite3.IntegrityError):
                db.exec(
                    '''
                    INSERT INTO snapshots(trial_id, idx, ts, corpus_files)
                    VALUES(?,?,?,?)
                    ''',
                    (999, 1, 10, 0),
                )

            with self.assertRaises(sqlite3.IntegrityError):
                db.exec(
                    '''
                    INSERT INTO resource_telemetry(trial_id, idx, ts, container_name)
                    VALUES(?,?,?,?)
                    ''',
                    (999, 1, 10, 'container'),
                )

            trial_id = _ensure_trial(db)
            snapshot_id = db_snapshot.save_snapshot_data(
                db,
                _snapshot_record(trial_id=trial_id, tick_idx=1, end_ts=10, corpus_files=1),
            )
            bug_id = db_bug.ensure_bug(
                db,
                db_bug.BugRecord(
                    run_id='run',
                    fuzzer='fz',
                    benchmark='bench',
                    fuzz_target='target',
                    bug_key='bug',
                    issue_type='crash',
                    top_func='main',
                    frames=['main'],
                    output='output',
                    first_seen_ts=10,
                    first_seen_snapshot_id=snapshot_id,
                ),
            )

            with self.assertRaises(sqlite3.IntegrityError):
                db_bug.upsert_bug_hits(db, bug_id=bug_id, snapshot_id=999, hits=1)
            with self.assertRaises(sqlite3.IntegrityError):
                db_bug.upsert_bug_hits(db, bug_id=999, snapshot_id=snapshot_id, hits=1)

            db_bug.upsert_bug_hits(db, bug_id=bug_id, snapshot_id=snapshot_id, hits=1)
            db.exec(
                '''
                INSERT INTO resource_telemetry(trial_id, idx, ts, container_name)
                VALUES(?,?,?,?)
                ''',
                (trial_id, 1, 10, 'container'),
            )
            db.exec('DELETE FROM trials WHERE trial_id=?', (trial_id,))

            child_counts = {
                'snapshots': db.scalar('SELECT COUNT(*) FROM snapshots'),
                'bug_hits': db.scalar('SELECT COUNT(*) FROM bug_hits'),
                'resource_telemetry': db.scalar('SELECT COUNT(*) FROM resource_telemetry'),
                'bugs': db.scalar('SELECT COUNT(*) FROM bugs'),
            }

        self.assertEqual(
            {
                'snapshots': 0,
                'bug_hits': 0,
                'resource_telemetry': 0,
                'bugs': 1,
            },
            child_counts,
        )


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
        db_trials.TrialRecord(
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
        ),
    )


def _snapshot_record(
    *,
    trial_id: int,
    tick_idx: int,
    end_ts: int,
    corpus_files: int,
    execs_done: int | None = None,
    stats: dict | None = None,
    crashes: int | None = 0,
    hangs: int | None = 0,
) -> db_snapshot.SnapshotRecord:
    return db_snapshot.SnapshotRecord(
        trial_db_id=trial_id,
        tick_idx=tick_idx,
        end_ts=end_ts,
        corpus_files=corpus_files,
        execs_done=execs_done,
        stats=stats,
        crashes=crashes,
        hangs=hangs,
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
