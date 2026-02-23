# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for snapshot-time corpus/crash detection.'''

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
import unittest

from pathlib import Path
from unittest.mock import patch

from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.db import snapshot as db_snapshot
from fuzzmeter.repro.coverage_state import seed_coverage_root
from fuzzmeter.repro.ingest import DetectedFile, copy_into_snapshot, detect_new_files
from fuzzmeter.snapshot.collector import SnapshotCollector
from fuzzmeter.snapshot.coverage import SnapshotCoverageRunner
from fuzzmeter.snapshot.models import CoverageTask
from fuzzmeter.snapshot.scheduler import SnapshotScheduler
from fuzzmeter.trial.models import ActiveTrial
from fuzzers.aflplusplus.run import fuzz as aflplusplus_fuzzer
from fuzzers.libfuzzer.run import fuzz as libfuzzer_fuzzer


def _active_trial(root: Path, *, started_ts: int | None = None) -> ActiveTrial:
    trial_root = root / 'trial'
    return ActiveTrial(
        trial_row_id=1,
        trial_id='aflplusplus__target__rep0',
        container_name='container',
        fuzzer='aflplusplus',
        fuzzer_base='aflplusplus',
        benchmark='bench',
        fuzz_target='target',
        input_mode='mode',
        rep=0,
        runner_image='runner',
        coverage_image='coverage',
        asan_image='asan',
        snapshot_preprocess_script=None,
        trial_root=trial_root,
        live_out=trial_root / 'work',
        fuzzer_log=trial_root / 'logs' / 'fuzzer.log',
        corpus_root=trial_root / 'work' / 'default' / 'queue',
        crashes_root=trial_root / 'work' / 'default' / 'crashes',
        snapshots_root=trial_root / 'snapshots',
        seed_root=None,
        repo_root=root,
        started_ts=started_ts,
    )


class SnapshotCollectorTest(unittest.TestCase):
    '''Verify snapshot collection and scheduling corner cases.'''

    def test_copy_into_snapshot_prefers_hardlink_when_possible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            src = root / 'live' / 'id:000001'
            src.parent.mkdir(parents=True)
            src.write_text('input', encoding='utf-8')
            detected = DetectedFile(
                kind='corpus',
                rel_path='id:000001',
                db_rel_path='id:000001',
                abs_src=src,
                mtime_ns=src.stat().st_mtime_ns,
            )

            self.assertEqual(1, copy_into_snapshot([detected], snap_dir=root / 'snap', subdir='corpus'))

            dst = root / 'snap' / 'corpus' / 'id:000001'
            self.assertTrue(dst.is_file())
            if src.stat().st_dev == dst.stat().st_dev:
                self.assertEqual(src.stat().st_ino, dst.stat().st_ino)

    def test_detect_new_corpus_files_uses_update_time_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            corpus_root = root / 'queue'
            corpus_root.mkdir()
            files = {
                'old': 90_000_000_000,
                'start': 100_000_000_000,
                'new': 150_000_000_000,
                'future': 210_000_000_000,
            }
            for name in files:
                (corpus_root / name).write_text(name, encoding='utf-8')

            try:
                detected = detect_new_files(
                    db,
                    kind='corpus',
                    trial_row_id=1,
                    src_root=corpus_root,
                    start_ts=100,
                    end_ts=200,
                    replay_time_fn=lambda path: files[Path(path).name],
                )
                self.assertIsNone(
                    db.scalar("SELECT name FROM sqlite_master WHERE type='table' AND name='seen_corpus_files'")
                )
            finally:
                db.close()

            self.assertEqual(['new', 'start'], sorted(item.rel_path for item in detected))

    def test_collect_trial_snapshot_uses_tick_time_for_live_file_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            db.close()

            trial_root = root / 'trial'
            (trial_root / 'work' / 'default' / 'queue').mkdir(parents=True)
            (trial_root / 'work' / 'default' / 'crashes').mkdir(parents=True)
            (trial_root / 'snapshots').mkdir()

            trial = ActiveTrial(
                trial_row_id=1,
                trial_id='aflplusplus__target__rep0',
                container_name='container',
                fuzzer='aflplusplus',
                fuzzer_base='aflplusplus',
                benchmark='bench',
                fuzz_target='target',
                input_mode='mode',
                rep=0,
                runner_image='runner',
                coverage_image='coverage',
                asan_image='asan',
                snapshot_preprocess_script=None,
                trial_root=trial_root,
                live_out=trial_root / 'work',
                fuzzer_log=trial_root / 'logs' / 'fuzzer.log',
                corpus_root=trial_root / 'work' / 'default' / 'queue',
                crashes_root=trial_root / 'work' / 'default' / 'crashes',
                snapshots_root=trial_root / 'snapshots',
                seed_root=None,
                repo_root=root,
                started_ts=0,
            )
            collector = SnapshotCollector(db_path=db_path, run_id='run-1', docker_runtime=None)
            seen_intervals: list[tuple[int, int]] = []

            def _capture_detect_new_files(_db, *, kind, trial_row_id, src_root, start_ts, end_ts, replay_time_fn=None):
                seen_intervals.append((int(start_ts), int(end_ts)))
                return []

            with patch('fuzzmeter.snapshot.collector.time.time', return_value=120), \
                 patch.object(SnapshotCollector, '_read_stats', return_value={}), \
                 patch.object(SnapshotCollector, '_copy_new_corpus', return_value=0), \
                 patch.object(SnapshotCollector, '_should_run_coverage', return_value=False), \
                 patch('fuzzmeter.snapshot.collector.repro_ingest.detect_new_files', side_effect=_capture_detect_new_files), \
                 patch('fuzzmeter.snapshot.collector.db_snapshot.ensure_snapshot_row', return_value=1):
                collector._collect_trial_snapshot(
                    tick_idx=2,
                    ts=100,
                    trial=trial,
                    preprocess_jobs=1,
                    render_heavy=False,
                )

            self.assertEqual(seen_intervals, [(0, 100), (0, 100)])

    def test_collect_trial_snapshot_uses_tick_time_for_replay_file_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            trial_root = root / 'trial'
            (trial_root / 'work' / 'default' / 'queue').mkdir(parents=True)
            (trial_root / 'work' / 'default' / 'crashes').mkdir(parents=True)
            (trial_root / 'work' / 'default' / 'queue' / 'id:000001').write_text('a', encoding='utf-8')
            (trial_root / 'work' / 'default' / 'queue' / 'id:000002').write_text('b', encoding='utf-8')
            (trial_root / 'work' / 'default' / 'crashes' / 'id:000003').write_text('c', encoding='utf-8')
            (trial_root / 'replay_timeline.json').write_text(
                json.dumps(
                    {
                        'replay_start_ts': 100,
                        'replay_end_ts': 200,
                        'file_times_ns': {
                            'default/queue/id:000001': 110_000_000_000,
                            'default/queue/id:000002': 120_000_000_000,
                            'default/crashes/id:000003': 115_000_000_000,
                        },
                    }
                ),
                encoding='utf-8',
            )

            trial = ActiveTrial(
                trial_row_id=1,
                trial_id='aflplusplus__target__rep0',
                container_name='container',
                fuzzer='aflplusplus_replay',
                fuzzer_base='aflplusplus',
                benchmark='bench',
                fuzz_target='target',
                input_mode='mode',
                rep=0,
                runner_image='runner',
                coverage_image='coverage',
                asan_image='asan',
                snapshot_preprocess_script=None,
                trial_root=trial_root,
                live_out=trial_root / 'work',
                fuzzer_log=trial_root / 'logs' / 'fuzzer.log',
                corpus_root=trial_root / 'work' / 'default' / 'queue',
                crashes_root=trial_root / 'work' / 'default' / 'crashes',
                snapshots_root=trial_root / 'snapshots',
                seed_root=None,
                repo_root=root,
                replay_start_ts=100,
                replay_end_ts=200,
            )
            collector = SnapshotCollector(db_path=db_path, run_id='run-1', docker_runtime=None)
            db = DB.open(root / 'unused.db')
            try:
                first_tick = collector._detect_new_files(
                    db,
                    kind='corpus',
                    trial_row_id=1,
                    trial=trial,
                    src_root=trial.corpus_root,
                    start_ts=100,
                    end_ts=110,
                )
                second_tick = collector._detect_new_files(
                    db,
                    kind='corpus',
                    trial_row_id=1,
                    trial=trial,
                    src_root=trial.corpus_root,
                    start_ts=110,
                    end_ts=120,
                )
                crashes = collector._detect_new_files(
                    db,
                    kind='crashes',
                    trial_row_id=1,
                    trial=trial,
                    src_root=trial.crashes_root,
                    start_ts=100,
                    end_ts=120,
                )
            finally:
                db.close()

            self.assertEqual(['id:000001'], [file.rel_path for file in first_tick])
            self.assertEqual(['id:000002'], [file.rel_path for file in second_tick])
            self.assertEqual(['id:000003'], [file.rel_path for file in crashes])

    def test_final_snapshot_request_captures_request_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            db.close()

            scheduler = SnapshotScheduler(
                db_path=db_path,
                run_dir=root,
                run_id='run-1',
                campaign_seconds=300,
                every_seconds=300,
                docker_runtime=None,
            )

            with patch('fuzzmeter.snapshot.scheduler.time.time', return_value=1234):
                scheduler.request_trial_snapshot(_active_trial(root, started_ts=934))

            item = scheduler._tick_queue.get_nowait()
            self.assertEqual(1234, item.ts)

    def test_equal_period_and_campaign_time_only_runs_requested_final_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            db.close()

            scheduler = SnapshotScheduler(
                db_path=db_path,
                run_dir=root,
                run_id='run-1',
                campaign_seconds=1,
                every_seconds=1,
                docker_runtime=None,
            )
            trial = _active_trial(root, started_ts=int(time.time()))
            scheduler.register(trial)
            processed: list[tuple[int, tuple[ActiveTrial, ...] | None]] = []
            processed_event = threading.Event()

            def _capture_tick(**kwargs):
                processed.append((int(kwargs['tick_idx']), kwargs.get('selected_trials')))
                processed_event.set()

            with patch.object(scheduler, '_process_tick', side_effect=_capture_tick):
                worker = threading.Thread(target=scheduler.run_loop)
                worker.start()
                try:
                    scheduler.request_trial_snapshot(trial)
                    self.assertTrue(processed_event.wait(2.0))
                    time.sleep(1.2)
                finally:
                    scheduler.stop()
                    worker.join(2.0)

            self.assertFalse(worker.is_alive())
            self.assertEqual(1, len(processed))
            self.assertEqual(1, processed[0][0])
            self.assertEqual((trial,), processed[0][1])

    def test_periodic_snapshots_follow_global_grid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            db.close()

            scheduler = SnapshotScheduler(
                db_path=db_path,
                run_dir=root,
                run_id='run-1',
                campaign_seconds=3,
                every_seconds=1,
                docker_runtime=None,
            )
            scheduler.started_ts = int(time.time())
            trial = _active_trial(root, started_ts=int(time.time()))
            scheduler.register(trial)
            processed: list[int] = []
            processed_event = threading.Event()

            def _capture_tick(**kwargs):
                processed.append(int(kwargs['tick_idx']))
                if len(processed) >= 2:
                    processed_event.set()

            with patch.object(scheduler, '_process_tick', side_effect=_capture_tick):
                worker = threading.Thread(target=scheduler.run_loop)
                worker.start()
                try:
                    self.assertTrue(processed_event.wait(3.0))
                finally:
                    scheduler.stop()
                    worker.join(2.0)

            self.assertFalse(worker.is_alive())
            self.assertGreaterEqual(len(processed), 2)

    def test_periodic_tick_captures_active_trials_on_global_grid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            db.close()

            scheduler = SnapshotScheduler(
                db_path=db_path,
                run_dir=root,
                run_id='run-1',
                campaign_seconds=300,
                every_seconds=60,
                docker_runtime=None,
            )
            scheduler.started_ts = 100
            trial = _active_trial(root, started_ts=100)
            trial_late = _active_trial(root, started_ts=130)
            trial_late = ActiveTrial(
                **{
                    **trial_late.__dict__,
                    'trial_row_id': 2,
                    'trial_id': 'aflplusplus__target__rep1',
                }
            )
            scheduler.register(trial)
            scheduler.register(trial_late)
            due = scheduler._due_periodic_snapshots(now_ts=280)
            self.assertEqual(
                [(160, (trial,)), (190, (trial_late,)), (220, (trial,)), (250, (trial_late,)), (280, (trial,))],
                due,
            )
            self.assertEqual([], scheduler._due_periodic_snapshots(now_ts=280))
            scheduler._schedule_periodic_tick(tick_idx=2, ts=160, trials=(trial, trial_late))
            scheduler.unregister(trial.trial_id)

            item = scheduler._tick_queue.get_nowait()
            self.assertEqual(2, item.tick_idx)
            self.assertEqual(160, item.ts)
            self.assertEqual((trial, trial_late), item.trials)

    def test_coverage_does_not_run_without_new_corpus_after_prior_corpus_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            trial = _active_trial(root)
            db.exec(
                'INSERT INTO snapshots(trial_id, idx, ts, corpus_files) VALUES(?,?,?,?)',
                (trial.trial_row_id, 1, 100, 1),
            )
            try:
                with patch.object(SnapshotCollector, '_seed_baseline_exists', return_value=False):
                    self.assertFalse(
                        SnapshotCollector._should_run_coverage(
                            db=db,
                            trial=trial,
                            copied_corpus=0,
                            tick_idx=2,
                        )
                    )
            finally:
                db.close()

    def test_seed_baseline_coverage_runs_for_late_first_trial_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            trial = _active_trial(root)
            run_dir = trial.trial_root.parent.parent
            base_root = seed_coverage_root(run_dir, trial.fuzzer, trial.benchmark, trial.fuzz_target)
            (base_root / '_state').mkdir(parents=True, exist_ok=True)
            (base_root / 'summary.json').write_text('{}', encoding='utf-8')
            (base_root / '_state' / 'merged.profdata').write_bytes(b'profdata')
            try:
                self.assertTrue(
                    SnapshotCollector._should_run_coverage(
                        db=db,
                        trial=trial,
                        copied_corpus=0,
                        tick_idx=29,
                    )
                )

                db.exec(
                    'INSERT INTO snapshots(trial_id, idx, ts, corpus_files, cov_branches_covered) VALUES(?,?,?,?,?)',
                    (trial.trial_row_id, 29, 1234, 0, 1),
                )
                self.assertFalse(
                    SnapshotCollector._should_run_coverage(
                        db=db,
                        trial=trial,
                        copied_corpus=0,
                        tick_idx=30,
                    )
                )
            finally:
                db.close()

    def test_late_first_trial_coverage_bootstraps_seed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            trial = _active_trial(root)
            run_dir = trial.trial_root.parent.parent
            snap_dir = trial.snapshots_root / 'snap_000029'
            (snap_dir / 'corpus').mkdir(parents=True)
            (snap_dir / 'corpus' / 'input').write_text('x', encoding='utf-8')
            base_root = seed_coverage_root(run_dir, trial.fuzzer, trial.benchmark, trial.fuzz_target)
            (base_root / '_state').mkdir(parents=True, exist_ok=True)
            (base_root / 'summary.json').write_text('{}', encoding='utf-8')
            (base_root / '_state' / 'merged.profdata').write_bytes(b'profdata')
            snapshot_id = db_snapshot.ensure_snapshot_row(
                db,
                trial_row_id=trial.trial_row_id,
                idx=29,
                ts=1234,
                corpus_files=1,
                execs_done=None,
                stats={},
                crashes=0,
                hangs=0,
            )

            try:
                prepared = SnapshotCoverageRunner(docker_runtime=None)._prepare_one_task(
                    db=db,
                    run_dir=run_dir,
                    task=CoverageTask(
                        trial=trial,
                        snap_dir=snap_dir,
                        snapshot_id=snapshot_id,
                        tick_idx=29,
                        render_heavy=False,
                    ),
                )
                self.assertIsNotNone(prepared)
                assert prepared is not None
                self.assertTrue((prepared.state_dir / 'merged.profdata').is_file())
                self.assertTrue((prepared.latest_root / 'summary.json').is_file())
            finally:
                db.close()

    def test_coverage_runner_prepares_batch_when_snapshot_has_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            try:
                ensure_schema(db)
                trial = _active_trial(root)
                snap_dir = trial.snapshots_root / 'snap_000001'
                corpus_dir = snap_dir / 'corpus'
                corpus_dir.mkdir(parents=True)
                data = b'seed input'
                (corpus_dir / 'id:000001').write_bytes(data)
                snapshot_id = db_snapshot.ensure_snapshot_row(
                    db,
                    trial_row_id=trial.trial_row_id,
                    idx=1,
                    ts=1234,
                    corpus_files=1,
                    execs_done=None,
                    stats={},
                    crashes=0,
                    hangs=0,
                )
                latest_root = root / 'coverage' / trial.fuzzer / trial.benchmark / trial.fuzz_target / trial.trial_id
                latest_root.mkdir(parents=True)
                (latest_root / 'summary.json').write_text(
                    json.dumps(
                        {
                            'cov_lines_covered': 10,
                            'cov_lines_total': 20,
                            'cov_branches_covered': 3,
                            'cov_branches_total': 8,
                        }
                    ),
                    encoding='utf-8',
                )
                (trial.trial_root / 'coverage_state').mkdir(parents=True)
                (trial.trial_root / 'coverage_state' / 'merged.profdata').write_bytes(b'profdata')

                runner = SnapshotCoverageRunner(docker_runtime=None)
                prepared = runner._prepare_one_task(
                    db=db,
                    run_dir=root,
                    task=CoverageTask(
                        trial=trial,
                        snap_dir=snap_dir,
                        snapshot_id=snapshot_id,
                        tick_idx=1,
                        render_heavy=False,
                    ),
                )

                self.assertIsNotNone(prepared)
                assert prepared is not None
                self.assertEqual([corpus_dir / 'id:000001'], prepared.inputs)
                self.assertEqual(
                    [trial.trial_root / 'coverage_state' / f'_batches_{snapshot_id}' / 'batch_000000.profdata'],
                    prepared.batch_profdata_paths,
                )
                self.assertTrue((trial.trial_root / 'coverage_state' / f'_batches_{snapshot_id}').is_dir())
            finally:
                db.close()

    def test_libfuzzer_stats_respect_snapshot_elapsed_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trial_root = Path(tmp_dir)
            (trial_root / 'logs').mkdir()
            (trial_root / 'logs' / 'fuzzer.log').write_text(
                '\n'.join(
                    [
                        '#100: cov: 1 ft: 1 corp: 1 exec/s: 10 time: 10s job: 1',
                        '#200: cov: 2 ft: 2 corp: 2 exec/s: 20 time: 20s job: 1',
                        '#300: cov: 3 ft: 3 corp: 3 exec/s: 30 time: 30s job: 1',
                    ]
                ),
                encoding='utf-8',
            )

            stats = libfuzzer_fuzzer.get_stats_until(trial_root, cutoff_elapsed_s=20)

            self.assertEqual(200, stats['execs_done'])
            self.assertEqual(20, stats['execs_per_sec'])

    def test_aflplusplus_stats_respect_snapshot_elapsed_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trial_root = Path(tmp_dir)
            stats_root = trial_root / 'work' / 'default'
            stats_root.mkdir(parents=True)
            (stats_root / 'plot_data').write_text(
                '\n'.join(
                    [
                        '# relative_time, cycles_done, cur_item, corpus_count, pending_total, pending_favs, map_size, saved_crashes, saved_hangs, max_depth, execs_per_sec, total_execs, edges_found, total_crashes, servers_count',
                        '60, 0, 0, 10, 0, 0, 1.0%, 0, 0, 1, 100.5, 1000, 1, 0, 0',
                        '120, 0, 0, 20, 0, 0, 1.0%, 0, 0, 1, 200.5, 2000, 1, 0, 0',
                    ]
                ),
                encoding='utf-8',
            )

            stats = aflplusplus_fuzzer.get_stats_until(trial_root, cutoff_elapsed_s=60)

            self.assertEqual(1000, stats['execs_done'])
            self.assertEqual(100.5, stats['execs_per_sec'])

    def test_aflplusplus_stats_use_first_plot_sample_for_early_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trial_root = Path(tmp_dir)
            stats_root = trial_root / 'work' / 'default'
            stats_root.mkdir(parents=True)
            (stats_root / 'plot_data').write_text(
                '\n'.join(
                    [
                        '# relative_time, cycles_done, cur_item, corpus_count, pending_total, pending_favs, map_size, saved_crashes, saved_hangs, max_depth, execs_per_sec, total_execs, edges_found, total_crashes, servers_count',
                        '61, 0, 0, 10, 0, 0, 1.0%, 0, 0, 1, 100.5, 1000, 1, 0, 0',
                        '66, 0, 0, 20, 0, 0, 1.0%, 0, 0, 1, 200.5, 2000, 1, 0, 0',
                    ]
                ),
                encoding='utf-8',
            )

            stats = aflplusplus_fuzzer.get_stats_until(trial_root, cutoff_elapsed_s=60)

            self.assertEqual(1000, stats['execs_done'])
            self.assertEqual(100.5, stats['execs_per_sec'])


if __name__ == '__main__':
    unittest.main()
