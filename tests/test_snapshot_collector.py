# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for snapshot-time corpus/crash detection.'''

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest

from pathlib import Path
from unittest.mock import patch

from fuzzers.aflplusplus.run import fuzz as aflplusplus_fuzzer
from fuzzers.libfuzzer.run import fuzz as libfuzzer_fuzzer
from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.repro.ingest import DetectedFile, detect_new_files, prepare_snapshot_inputs
from fuzzmeter.snapshot.collector import _collect_trial_snapshot, _detect_replay_files
from fuzzmeter.snapshot.scheduler import SnapshotScheduler
from fuzzmeter.trial.models import ReplayTrialInstance, TrialInstance, TrialLayout
from tests.support.trials import make_trial_config


def _active_trial(
    root: Path,
    *,
    started_ts: int | None = None,
    db_id: int = 1,
    rep_idx: int = 0,
) -> TrialInstance:
    trial_root = root / f'trial_{db_id}'
    config = make_trial_config(
        fuzzer='aflplusplus',
        fuzzer_impl='aflplusplus',
        benchmark='bench',
        fuzz_target='target',
        fuzz_target_bin=root / 'target_bin',
        fuzz_target_input_mode='mode',
        fuzz_target_timeout=1.0,
        rep_idx=rep_idx,
        trial_key=f'aflplusplus__bench-target__rep{rep_idx}',
        output_paths=OutputPaths(
            corpus_root=Path('default/queue'),
            crashes_root=Path('default/crashes'),
        ),
        trial_timeout=300,
        snapshot_preprocess=None,
    )
    layout = TrialLayout.from_config(trial_dir=trial_root, cfg=config)
    layout.corpus_dir.mkdir(parents=True, exist_ok=True)
    layout.crashes_dir.mkdir(parents=True, exist_ok=True)
    layout.snapshots_dir.mkdir(parents=True, exist_ok=True)
    return TrialInstance(
        db_id=db_id,
        config=config,
        layout=layout,
        container_name=f'container-{db_id}',
        fuzzer_dirs={'aflplusplus': root / 'aflplusplus'},
        start_ts=0 if started_ts is None else started_ts,
    )


def _replay_trial(root: Path, *, start_ts: int, end_ts: int, db_id: int = 1, rep_idx: int = 0) -> ReplayTrialInstance:
    trial = _active_trial(root, started_ts=start_ts, db_id=db_id, rep_idx=rep_idx)
    return ReplayTrialInstance(
        db_id=trial.db_id,
        config=trial.config,
        layout=trial.layout,
        container_name=trial.container_name,
        fuzzer_dirs=trial.fuzzer_dirs,
        start_ts=trial.start_ts,
        end_ts=end_ts,
    )


class SnapshotCollectorTest(unittest.TestCase):
    '''Verify snapshot collection and scheduling corner cases.'''

    def test_prepare_snapshot_inputs_prefers_hardlink_when_possible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            src = root / 'live' / 'id:000001'
            src.parent.mkdir(parents=True)
            src.write_text('input', encoding='utf-8')
            detected = DetectedFile(
                rel_path='id:000001',
                abs_src=src,
                mtime_ns=src.stat().st_mtime_ns,
            )

            copied = prepare_snapshot_inputs(
                docker_runtime=None,
                snapshot_dir=root / 'snap',
                input_dir=root / 'snap' / 'corpus',
                input_files=[detected],
                snapshot_preprocess=None,
                benchmark='bench',
                fuzz_target='target',
                fuzzer='fuzzer',
                runner_image='runner',
            )

            dst = root / 'snap' / 'corpus' / 'id:000001'
            self.assertEqual([dst], copied)
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
            (corpus_root / 'old').write_text('old', encoding='utf-8')
            time.sleep(1.1)
            start_ts = int(time.time())
            (corpus_root / 'new').write_text('new', encoding='utf-8')
            time.sleep(1.1)
            end_ts = int(time.time())
            (corpus_root / 'future').write_text('future', encoding='utf-8')

            try:
                detected = detect_new_files(
                    kind='corpus',
                    src_root=corpus_root,
                    start_ts=start_ts,
                    end_ts=end_ts,
                )
                self.assertIsNone(
                    db.scalar("SELECT name FROM sqlite_master WHERE type='table' AND name='seen_corpus_files'")
                )
            finally:
                db.close()

            self.assertEqual(['new'], sorted(item.rel_path for item in detected))

    def test_collect_trial_snapshot_uses_tick_time_for_live_file_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run-1', 1, 'config'))
            db.exec(
                '''
                INSERT INTO trials(trial_id, run_id, fuzzer, benchmark, fuzz_target, rep, status)
                VALUES(?,?,?,?,?,?,?)
                ''',
                (1, 'run-1', 'aflplusplus', 'bench', 'target', 0, 'running'),
            )
            db.close()

            trial = _active_trial(root, started_ts=0)
            seen_intervals: list[tuple[int, int]] = []

            def _capture_detect_new_files(*, kind, src_root, start_ts, end_ts):
                seen_intervals.append((int(start_ts), int(end_ts)))
                return []

            with patch('fuzzmeter.snapshot.collector.time.time', return_value=120), \
                 patch('fuzzmeter.snapshot.collector._read_stats', return_value={}), \
                 patch('fuzzmeter.snapshot.collector.repro_ingest.detect_new_files', side_effect=_capture_detect_new_files):
                _collect_trial_snapshot(
                    db_path=db_path,
                    run_id='run-1',
                    docker_runtime=None,
                    tick_idx=2,
                    end_ts=100,
                    trial=trial,
                    replay_mode=False,
                    preprocess_jobs=1,
                )

            self.assertEqual(seen_intervals, [(-1, 100), (-1, 100)])

    def test_collect_trial_snapshot_persists_custom_metrics_in_stats_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run-1', 1, 'config'))
            db.exec(
                '''
                INSERT INTO trials(trial_id, run_id, fuzzer, benchmark, fuzz_target, rep, status)
                VALUES(?,?,?,?,?,?,?)
                ''',
                (1, 'run-1', 'aflplusplus', 'bench', 'target', 0, 'running'),
            )
            db.close()

            trial = _active_trial(root, started_ts=0)
            custom_metric = {
                'schema_version': 1,
                'id': 'afl-mutator-counts',
                'kind': 'counter_map',
                'counts': {'havoc': 2},
            }
            with patch('fuzzmeter.snapshot.collector._read_stats', return_value={'execs_done': 10}), \
                 patch('fuzzmeter.snapshot.collector._read_custom_metrics', return_value=[custom_metric]), \
                 patch('fuzzmeter.snapshot.collector.repro_ingest.detect_new_files', return_value=[]):
                _collect_trial_snapshot(
                    db_path=db_path,
                    run_id='run-1',
                    docker_runtime=None,
                    tick_idx=1,
                    end_ts=100,
                    trial=trial,
                    replay_mode=False,
                    preprocess_jobs=1,
                )

            db = DB.open(db_path)
            try:
                stats_json = db.scalar('SELECT stats_json FROM snapshots WHERE trial_id=? AND idx=?', (1, 1))
            finally:
                db.close()

            stats = json.loads(str(stats_json))
            self.assertEqual(1, stats['custom_metrics_schema_version'])
            self.assertEqual([custom_metric], stats['custom_metrics'])

    def test_collect_trial_snapshot_uses_tick_time_for_replay_file_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            trial_root = root / 'trial_1'
            (trial_root / 'work' / 'default' / 'queue').mkdir(parents=True)
            (trial_root / 'work' / 'default' / 'crashes').mkdir(parents=True)
            (trial_root / 'work' / 'default' / 'queue' / 'id:000001').write_text('a', encoding='utf-8')
            (trial_root / 'work' / 'default' / 'queue' / 'id:000002').write_text('b', encoding='utf-8')
            (trial_root / 'work' / 'default' / 'crashes' / 'id:000003').write_text('c', encoding='utf-8')
            (trial_root / 'replay_timeline.json').write_text(
                json.dumps(
                    {
                        'start_ts': 100,
                        'end_ts': 200,
                        'file_times_ns': {
                            'default/queue/id:000001': 110_000_000_000,
                            'default/queue/id:000002': 120_000_000_000,
                            'default/crashes/id:000003': 115_000_000_000,
                        },
                    }
                ),
                encoding='utf-8',
            )

            trial = _replay_trial(root, start_ts=100, end_ts=200)
            first_tick = _detect_replay_files(
                kind='corpus',
                trial=trial,
                src_root=trial.layout.corpus_dir,
                start_ts=100,
                end_ts=110,
            )
            second_tick = _detect_replay_files(
                kind='corpus',
                trial=trial,
                src_root=trial.layout.corpus_dir,
                start_ts=110,
                end_ts=120,
            )
            crashes = _detect_replay_files(
                kind='crashes',
                trial=trial,
                src_root=trial.layout.crashes_dir,
                start_ts=100,
                end_ts=120,
            )

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
                scheduler.schedule_final_tick(_active_trial(root, started_ts=934))

            item = scheduler._tick_queue.get_nowait()
            self.assertEqual(1234, item.end_ts)

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
            processed: list[tuple[int, tuple[TrialInstance, ...] | None]] = []
            processed_event = threading.Event()

            def _capture_tick(**kwargs):
                processed.append((int(kwargs['tick_idx']), kwargs.get('selected_trials')))
                processed_event.set()

            with patch.object(scheduler, '_process_tick', side_effect=_capture_tick), \
                 patch.object(scheduler._resource_telemetry, 'collect'):
                worker = threading.Thread(target=scheduler.run_loop)
                worker.start()
                try:
                    scheduler.schedule_final_tick(trial)
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
            scheduler.start_ts = int(time.time())
            trial = _active_trial(root, started_ts=int(time.time()))
            scheduler.register(trial)
            processed: list[int] = []
            processed_event = threading.Event()

            def _capture_tick(**kwargs):
                processed.append(int(kwargs['tick_idx']))
                if len(processed) >= 2:
                    processed_event.set()

            with patch.object(scheduler, '_process_tick', side_effect=_capture_tick), \
                 patch.object(scheduler._resource_telemetry, 'collect'):
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
            scheduler.start_ts = 100
            trial = _active_trial(root, started_ts=100)
            trial_late = _active_trial(root, started_ts=130, db_id=2, rep_idx=1)
            scheduler.register(trial)
            scheduler.register(trial_late)
            due, _ = scheduler._due_periodic_snapshots(now_ts=280)
            self.assertEqual(
                [(160, (trial,)), (190, (trial_late,)), (220, (trial,)), (250, (trial_late,)), (280, (trial,))],
                due,
            )
            self.assertEqual(([], 310), scheduler._due_periodic_snapshots(now_ts=280))
            db = DB.open(db_path)
            try:
                with patch.object(scheduler._resource_telemetry, 'collect'):
                    scheduler._schedule_periodic_tick(db=db, tick_idx=2, ts=160, trials=(trial, trial_late))
            finally:
                db.close()
            scheduler.unregister(trial.config.trial_key)

            item = scheduler._tick_queue.get_nowait()
            self.assertEqual(2, item.tick_idx)
            self.assertEqual(160, item.end_ts)
            self.assertEqual((trial, trial_late), item.trials)

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
