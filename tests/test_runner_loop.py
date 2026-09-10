# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Functional tests for the runner and snapshot scheduler main loop.'''

from __future__ import annotations

import os
import tempfile
import threading
import unittest

from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

from fuzzmeter.config import CampaignConfig, CampaignSettings
from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.db import snapshot as db_snapshot
from fuzzmeter.db import trials as db_trials
from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.repro.ingest import DetectedFile
from fuzzmeter.run.runner import (
    _live_resource_plan,
    _run_live_experiment,
    _run_replay_experiment,
    _wait_for_futures,
    run_experiment,
)
from fuzzmeter.snapshot.collector import collect_snapshots
from fuzzmeter.snapshot.scheduler import ReplaySnapshotScheduler, SnapshotScheduler
from fuzzmeter.snapshot.trial_snapshot import TrialCoverageSnapshot, TrialCrashSnapshot
from fuzzmeter.trial.models import ReplayTrialInstance, TrialConfig, TrialInstance, TrialLayout
from tests.support.trials import make_trial_config


def _trial_config(root: Path, *, rep_idx: int = 0, replay_dir: Path | None = None) -> TrialConfig:
    return make_trial_config(
        fuzzer='aflplusplus',
        fuzzer_impl='aflplusplus',
        benchmark='bench',
        fuzz_target='target',
        fuzz_target_bin=root / f'target-{rep_idx}',
        fuzz_target_input_mode='file',
        fuzz_target_timeout=1.0,
        rep_idx=rep_idx,
        trial_key=f'trial-{rep_idx}',
        output_paths=OutputPaths(
            corpus_root=Path('default/queue'),
            crashes_root=Path('default/crashes'),
        ),
        trial_timeout=300,
        snapshot_preprocess=None,
        replay_dir=replay_dir,
    )


def _bare_trial_instance(
    *,
    db_id: int,
    root: Path,
    start_ts: int,
    rep_idx: int = 0,
    end_ts: int | None = None,
) -> TrialInstance:
    config = _trial_config(root, rep_idx=rep_idx)
    layout = TrialLayout.from_config(trial_dir=root / f'trial-{db_id}', cfg=config)
    trial = TrialInstance(
        db_id=db_id,
        config=config,
        layout=layout,
        container_name=f'container-{db_id}',
        fuzzer_dirs={'aflplusplus': root / 'aflplusplus'},
        start_ts=start_ts,
    )
    if end_ts is None:
        return trial
    return ReplayTrialInstance(
        db_id=trial.db_id,
        config=trial.config,
        layout=trial.layout,
        container_name=trial.container_name,
        fuzzer_dirs=trial.fuzzer_dirs,
        start_ts=trial.start_ts,
        end_ts=end_ts,
    )


def _create_trial_instance(
    *,
    root: Path,
    db_path: Path,
    start_ts: int,
    rep_idx: int = 0,
    end_ts: int | None = None,
) -> TrialInstance:
    db = DB.open(db_path)
    try:
        ensure_schema(db)
        db.exec('INSERT OR IGNORE INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run', 1, 'config'))
        trial_db_id = db_trials.ensure_trial_row(
            db,
            run_id='run',
            started_ts=start_ts,
            record=db_trials.TrialRecord(
                fuzzer='aflplusplus',
                benchmark='bench',
                fuzz_target='target',
                rep=rep_idx,
                time_seconds=300,
                status='running',
                fuzzer_image='runner',
                build_config_json=None,
                runtime_config_json=None,
            ),
        )
        db.commit()
    finally:
        db.close()

    trial = _bare_trial_instance(
        db_id=trial_db_id,
        root=root,
        start_ts=start_ts,
        rep_idx=rep_idx,
        end_ts=end_ts,
    )
    trial.layout.corpus_dir.mkdir(parents=True, exist_ok=True)
    trial.layout.crashes_dir.mkdir(parents=True, exist_ok=True)
    trial.layout.snapshots_dir.mkdir(parents=True, exist_ok=True)
    return trial


class _SchedulerStub:
    def __init__(self) -> None:
        self.registered = []
        self.unregistered = []
        self.final_ticks = 0
        self.run_calls = 0
        self.stop_calls = 0

    def register(self, trial: TrialInstance) -> None:
        self.registered.append(trial)

    def run_loop(self) -> None:
        self.run_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    def unregister(self, trial_id: str) -> None:
        self.unregistered.append(trial_id)

    def schedule_final_tick(self) -> None:
        self.final_ticks += 1


class _ThreadStub:
    def __init__(self, target=None, name=None) -> None:
        self.target = target
        self.name = name
        self.started = False
        self.joined = False

    def start(self) -> None:
        self.started = True

    def join(self) -> None:
        self.joined = True


class _ExecutorStub:
    def __init__(self, max_workers=None) -> None:
        self.max_workers = max_workers

    def submit(self, fn, *args, **kwargs) -> Future:
        future = Future()
        future.set_result(None)
        return future

    def shutdown(self, wait=True, cancel_futures=False) -> None:
        return None


def _write_output(path: Path, content: str, *, mtime_s: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    os.utime(path, ns=(mtime_s * 1_000_000_000, mtime_s * 1_000_000_000))


class RunnerLoopTest(unittest.TestCase):
    '''Verify the main loop snapshot behavior without Docker side effects.'''

    def test_live_resource_plan_and_empty_live_run_do_not_create_zero_worker_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            config = CampaignConfig(settings=CampaignSettings(parallel_jobs=1, snapshot_jobs=0), cases=[])

            self.assertEqual((1, 0), _live_resource_plan(total_jobs=1))
            self.assertEqual((32, 16), _live_resource_plan(total_jobs=48))
            self.assertEqual((36, 12), _live_resource_plan(total_jobs=48, snapshot_jobs=12))

            result = _run_live_experiment(
                db_path=run_dir / 'state.db',
                campaign_config=config,
                run_dir=run_dir,
                run_id='run',
                docker_runtime=None,
                trial_configs=[],
                stop_event=threading.Event(),
            )

        self.assertEqual(run_dir, result)

    def test_run_experiment_rejects_mixed_live_and_replay_trials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = CampaignConfig(settings=CampaignSettings(), cases=[])
            live_cfg = _trial_config(root, rep_idx=0)
            replay_cfg = _trial_config(root, rep_idx=1, replay_dir=root / 'replay')

            with patch('fuzzmeter.run.runner.prepare_artifacts', return_value={}), \
                 patch('fuzzmeter.run.runner.plan_trials', return_value=[live_cfg, replay_cfg]), \
                 patch('fuzzmeter.run.shutdown.DockerClient.sweep_run', return_value=0) as sweep:
                with self.assertRaisesRegex(RuntimeError, 'Replay trials cannot be mixed'):
                    run_experiment(
                        campaign_config=config,
                        out_root=root / 'out',
                        config_src='config',
                    )
            self.assertGreaterEqual(sweep.call_count, 1)

    def test_replay_run_registers_trials_runs_scheduler_and_marks_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            try:
                ensure_schema(db)
                db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run', 1, 'config'))
                trial_db_ids = [
                    db_trials.ensure_trial_row(
                        db,
                        run_id='run',
                        started_ts=100 + idx,
                        record=db_trials.TrialRecord(
                            fuzzer=f'fuzzer_{idx}',
                            benchmark='bench',
                            fuzz_target='target',
                            rep=idx,
                            time_seconds=300,
                            status='preparing_replay',
                            fuzzer_image='runner',
                            build_config_json=None,
                            runtime_config_json=None,
                        ),
                    )
                    for idx in (1, 2)
                ]
                db.commit()
            finally:
                db.close()

            prepared_trials = [
                _bare_trial_instance(db_id=trial_db_ids[0], root=root, start_ts=101, rep_idx=0, end_ts=160),
                _bare_trial_instance(db_id=trial_db_ids[1], root=root, start_ts=102, rep_idx=1, end_ts=190),
            ]
            scheduler_refs: list[_SchedulerStub] = []

            def _prepare_factory(**kwargs):
                return prepared_trials[kwargs['cfg'].rep_idx]

            def _scheduler_factory(**kwargs):
                scheduler = _SchedulerStub()
                scheduler_refs.append(scheduler)
                self.assertEqual(88, kwargs['campaign_seconds'])
                return scheduler

            with patch('fuzzmeter.run.runner.prepare_replay_trial', side_effect=_prepare_factory), \
                 patch('fuzzmeter.run.runner.ReplaySnapshotScheduler', side_effect=_scheduler_factory):
                result = _run_replay_experiment(
                    db_path=db_path,
                    campaign_config=CampaignConfig(
                        settings=CampaignSettings(parallel_jobs=2, snapshot_every_seconds=30),
                        cases=[],
                    ),
                    run_dir=root,
                    run_id='run',
                    docker_runtime=None,
                    trial_configs=[_trial_config(root, rep_idx=0), _trial_config(root, rep_idx=1)],
                )

            self.assertEqual(root, result)
            self.assertEqual(1, len(scheduler_refs))
            self.assertEqual(
                sorted(trial.config.trial_key for trial in prepared_trials),
                sorted(trial.config.trial_key for trial in scheduler_refs[0].registered),
            )
            self.assertEqual(1, scheduler_refs[0].run_calls)
            self.assertEqual(
                sorted(trial.config.trial_key for trial in prepared_trials),
                sorted(scheduler_refs[0].unregistered),
            )

            db = DB.open(db_path)
            try:
                rows = db.q('SELECT trial_id, status, ended_ts FROM trials ORDER BY trial_id')
            finally:
                db.close()
            self.assertEqual(
                [
                    {'trial_id': trial_db_ids[0], 'status': 'done', 'ended_ts': 160},
                    {'trial_id': trial_db_ids[1], 'status': 'done', 'ended_ts': 190},
                ],
                rows,
            )

    def test_wait_for_futures_cancels_pending_work_after_first_failure(self) -> None:
        failed = Future()
        pending = Future()
        failed.set_exception(RuntimeError('boom'))

        with self.assertRaisesRegex(RuntimeError, 'boom'):
            _wait_for_futures([failed, pending])

        self.assertTrue(pending.cancelled())

    def test_live_run_stops_scheduler_after_normal_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            config = CampaignConfig(settings=CampaignSettings(parallel_jobs=2), cases=[])
            scheduler_refs: list[_SchedulerStub] = []
            thread_refs: list[_ThreadStub] = []

            def _scheduler_factory(**kwargs):
                scheduler = _SchedulerStub()
                scheduler_refs.append(scheduler)
                return scheduler

            def _thread_factory(*args, **kwargs):
                thread = _ThreadStub(*args, **kwargs)
                thread_refs.append(thread)
                return thread

            with patch('fuzzmeter.run.runner.SnapshotScheduler', side_effect=_scheduler_factory), \
                 patch('fuzzmeter.run.runner.threading.Thread', side_effect=_thread_factory), \
                 patch('fuzzmeter.run.runner.ThreadPoolExecutor', _ExecutorStub):
                result = _run_live_experiment(
                    db_path=run_dir / 'state.db',
                    campaign_config=config,
                    run_dir=run_dir,
                    run_id='run',
                    docker_runtime=None,
                    trial_configs=[_trial_config(run_dir)],
                    stop_event=threading.Event(),
                )

            self.assertEqual(run_dir, result)
            self.assertEqual(1, len(scheduler_refs))
            self.assertEqual(1, scheduler_refs[0].final_ticks)
            self.assertEqual(1, scheduler_refs[0].stop_calls)
            self.assertEqual(1, len(thread_refs))
            self.assertTrue(thread_refs[0].started)
            self.assertTrue(thread_refs[0].joined)

    def test_process_tick_creates_tick_snapshot_and_runs_snapshot_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            trial = _create_trial_instance(root=root, db_path=db_path, start_ts=100)
            _write_output(trial.layout.corpus_dir / 'id:000001', 'corpus', mtime_s=110)
            _write_output(trial.layout.crashes_dir / 'id:000002', 'crash', mtime_s=120)

            scheduler = SnapshotScheduler(
                db_path=db_path,
                run_dir=root,
                run_id='run',
                campaign_seconds=300,
                every_seconds=60,
                docker_runtime=None,
                jobs=2,
            )
            coverage_snapshot = TrialCoverageSnapshot(
                trial=trial,
                snapshot_id=1,
                snapshot_dir=trial.layout.snapshots_dir / 'snap_000001',
                tick_idx=1,
            )
            crash_snapshot = TrialCrashSnapshot(
                trial=trial,
                snapshot_id=1,
                snapshot_dir=trial.layout.snapshots_dir / 'snap_000001',
                tick_idx=1,
                crash_files=[
                    DetectedFile(
                        rel_path='id:000002',
                        abs_src=trial.layout.crashes_dir / 'id:000002',
                        mtime_ns=120_000_000_000,
                    )
                ],
            )

            db = DB.open(db_path)
            try:
                db_snapshot.insert_tick(db, run_id='run', idx=1, ts=130)
                with patch(
                    'fuzzmeter.snapshot.scheduler.collect_snapshots',
                    return_value=([coverage_snapshot], [crash_snapshot]),
                ) as collect, \
                     patch('fuzzmeter.snapshot.scheduler.process_snapshot_coverage') as process_coverage, \
                     patch('fuzzmeter.snapshot.scheduler.process_snapshot_crashes') as process_crashes:
                    scheduler._process_tick(
                        db=db,
                        tick_idx=1,
                        end_ts=130,
                        selected_trials=(trial,),
                        campaign_trials=(trial,),
                     render_heavy=True,
                    )
                tick = db_snapshot.list_ticks(db, run_id='run')[0]
            finally:
                db.close()

            collect.assert_called_once()
            self.assertEqual([trial], collect.call_args.kwargs['active_trials'])
            self.assertEqual(False, collect.call_args.kwargs['replay_mode'])
            process_coverage.assert_called_once()
            self.assertEqual([coverage_snapshot], process_coverage.call_args.kwargs['snapshots'])
            self.assertEqual((trial,), process_coverage.call_args.kwargs['campaign_trials'])
            process_crashes.assert_called_once()
            self.assertEqual([crash_snapshot], process_crashes.call_args.kwargs['snapshots'])
            self.assertEqual('completed', tick['status'])
            self.assertIsNone(tick['error'])

    def test_collector_parallelizes_trial_snapshot_collection(self) -> None:
        seen_threads: set[int] = set()
        barrier = threading.Barrier(2)
        trials = [_bare_trial_instance(db_id=idx, root=Path('/tmp'), start_ts=100, rep_idx=idx) for idx in (1, 2, 3)]

        def _collect_trial_snapshot(**kwargs):
            seen_threads.add(threading.get_ident())
            try:
                barrier.wait(timeout=2)
            except threading.BrokenBarrierError:
                pass
            return None, None

        with patch('fuzzmeter.snapshot.collector._collect_trial_snapshot', side_effect=_collect_trial_snapshot):
            coverage_snapshots, crash_snapshots = collect_snapshots(
                db_path=Path('/tmp/unused.db'),
                run_id='run',
                docker_runtime=None,
                tick_idx=1,
                end_ts=200,
                active_trials=trials,
                replay_mode=False,
                jobs=2,
            )

        self.assertEqual([], coverage_snapshots)
        self.assertEqual([], crash_snapshots)
        self.assertGreaterEqual(len(seen_threads), 2)

    def test_collector_accepts_tick_without_active_trials(self) -> None:
        coverage_snapshots, crash_snapshots = collect_snapshots(
            db_path=Path('/tmp/unused.db'),
            run_id='run',
            docker_runtime=None,
            tick_idx=1,
            end_ts=200,
            active_trials=[],
            replay_mode=True,
            jobs=2,
        )

        self.assertEqual([], coverage_snapshots)
        self.assertEqual([], crash_snapshots)

    def test_tick_worker_records_processing_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            try:
                ensure_schema(db)
                db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run', 1, 'config'))
                db_snapshot.insert_tick(db, run_id='run', idx=1, ts=100)
                db.commit()
            finally:
                db.close()

            scheduler = SnapshotScheduler(
                db_path=db_path,
                run_dir=root,
                run_id='run',
                campaign_seconds=300,
                every_seconds=60,
                docker_runtime=None,
            )
            scheduler._schedule_tick(
                tick_idx=1,
                ts=100,
                render_heavy=False,
                trials=(),
                campaign_trials=(),
            )
            scheduler._tick_queue.put(None)

            with patch.object(scheduler, '_process_tick', side_effect=RuntimeError('coverage exploded')):
                scheduler._tick_worker_loop()

            db = DB.open(db_path)
            try:
                tick = db_snapshot.list_ticks(db, run_id='run')[0]
            finally:
                db.close()

        self.assertEqual('failed', tick['status'])
        self.assertIn('coverage exploded', tick['error'])

    def test_tick_worker_records_shutdown_interruption_as_aborted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            try:
                ensure_schema(db)
                db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run', 1, 'config'))
                db_snapshot.insert_tick(db, run_id='run', idx=1, ts=100)
                db.commit()
            finally:
                db.close()

            # The signal handler sets the shared stop event before it sweeps the
            # containers, so a tick killed by that sweep must not be reported as
            # a measurement failure.
            stop_event = threading.Event()
            stop_event.set()
            scheduler = SnapshotScheduler(
                db_path=db_path,
                run_dir=root,
                run_id='run',
                campaign_seconds=300,
                every_seconds=60,
                docker_runtime=None,
                stop_event=stop_event,
            )
            scheduler._schedule_tick(
                tick_idx=1,
                ts=100,
                render_heavy=False,
                trials=(),
                campaign_trials=(),
            )
            scheduler._tick_queue.put(None)

            with patch.object(scheduler, '_process_tick', side_effect=RuntimeError('container removed')):
                scheduler._tick_worker_loop()

            db = DB.open(db_path)
            try:
                tick = db_snapshot.list_ticks(db, run_id='run')[0]
            finally:
                db.close()

        self.assertEqual('aborted', tick['status'])
        self.assertIn('container removed', tick['error'])

    def test_replay_scheduler_creates_periodic_and_last_ticks_from_replay_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            trial = _create_trial_instance(root=root, db_path=db_path, start_ts=100, end_ts=220)
            _write_output(trial.layout.corpus_dir / 'id:000001', 'first', mtime_s=110)
            _write_output(trial.layout.corpus_dir / 'id:000002', 'last', mtime_s=210)
            (trial.layout.trial_dir / 'replay_timeline.json').write_text(
                (
                    '{"start_ts":100,"end_ts":220,'
                    '"file_times_ns":{"default/queue/id:000001":110000000000,'
                    '"default/queue/id:000002":210000000000}}'
                ),
                encoding='utf-8',
            )

            scheduler = ReplaySnapshotScheduler(
                db_path=db_path,
                run_dir=root,
                run_id='run',
                campaign_seconds=120,
                every_seconds=50,
                docker_runtime=None,
                jobs=2,
            )
            scheduler.register(trial)

            with patch('fuzzmeter.snapshot.collector._read_stats', return_value={}), \
                 patch('fuzzmeter.snapshot.scheduler.process_snapshot_coverage'), \
                 patch('fuzzmeter.snapshot.scheduler.process_snapshot_crashes'):
                scheduler.run_loop()

            db = DB.open(db_path)
            try:
                ticks = db_snapshot.list_ticks(db, run_id='run')
                snapshots = db_snapshot.list_trial_snapshots(db, trial_row_id=trial.db_id)
            finally:
                db.close()

            self.assertEqual([150, 200, 220], [row['ts'] for row in ticks])
            self.assertEqual([1, 2, 3], [row['idx'] for row in ticks])
            self.assertEqual([1, 2, 3], [row['idx'] for row in snapshots])
            self.assertEqual(2, snapshots[-1]['corpus_files'])
            self.assertTrue((trial.layout.snapshots_dir / 'snap_000003' / 'corpus' / 'id:000002').is_file())


if __name__ == '__main__':
    unittest.main()
