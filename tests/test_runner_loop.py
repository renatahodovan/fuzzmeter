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
from types import SimpleNamespace
from unittest.mock import patch

from fuzzmeter.config import CampaignConfig, CampaignSettings
from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.db import snapshot as db_snapshot
from fuzzmeter.db import trials as db_trials
from fuzzmeter.run.runner import (
    _live_resource_plan,
    _run_live_experiment,
    _run_replay_experiment,
    _wait_for_futures,
    run_experiment,
)
from fuzzmeter.snapshot.collector import SnapshotCollector
from fuzzmeter.snapshot.collector import _CollectedTrialSnapshot
from fuzzmeter.snapshot.scheduler import ReplaySnapshotScheduler, SnapshotScheduler
from fuzzmeter.trial.models import ActiveTrial
from fuzzmeter.trial.replay import PreparedReplayTrial


class _ProcessorRecorder:
    def __init__(self) -> None:
        self.calls = []

    def process(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _AggregateRecorder:
    def __init__(self) -> None:
        self.calls = []

    def update(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _ResourceRecorder:
    def __init__(self) -> None:
        self.calls = []

    def collect(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _SchedulerStub:
    def __init__(self) -> None:
        self.registered = []
        self.unregistered = []
        self.run_calls = 0
        self.stop_calls = 0

    def register(self, trial: ActiveTrial) -> None:
        self.registered.append(trial)

    def run_loop(self) -> None:
        self.run_calls += 1
        return None

    def stop(self) -> None:
        self.stop_calls += 1

    def unregister(self, trial_id: str) -> None:
        self.unregistered.append(trial_id)


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


class _ParallelCollector(SnapshotCollector):
    def __init__(self, *, barrier: threading.Barrier, seen_threads: set[int]) -> None:
        super().__init__(db_path=Path('/tmp/unused.db'), run_id='run', docker_runtime=None)
        self.barrier = barrier
        self.seen_threads = seen_threads

    def _collect_trial_snapshot(self, **kwargs) -> _CollectedTrialSnapshot:
        self.seen_threads.add(threading.get_ident())
        try:
            self.barrier.wait(timeout=2)
        except threading.BrokenBarrierError:
            pass
        return _CollectedTrialSnapshot()


class RunnerLoopTest(unittest.TestCase):
    '''Verify the main loop snapshot behavior without Docker side effects.'''

    def test_live_resource_plan_and_empty_live_run_do_not_create_zero_worker_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            config = CampaignConfig(settings=CampaignSettings(parallel_jobs=1), cases=[])

            self.assertEqual((1, 0), _live_resource_plan(total_jobs=1))
            self.assertEqual((24, 24), _live_resource_plan(total_jobs=48))
            self.assertEqual((36, 12), _live_resource_plan(total_jobs=48, requested_snapshot_jobs=12))
            with self.assertLogs('fuzzmeter.run.runner', level='WARNING') as logs:
                result = _run_live_experiment(
                    db_path=run_dir / 'state.db',
                    repo_root=run_dir,
                    campaign_config=config,
                    run_dir=run_dir,
                    run_id='run',
                    docker_runtime=None,
                    trial_plans=[],
                )

            self.assertEqual(run_dir, result)
            self.assertEqual(['WARNING:fuzzmeter.run.runner:No trials were planned for this live run'], logs.output)

    def test_run_experiment_rejects_mixed_live_and_replay_trials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = CampaignConfig(settings=CampaignSettings(), cases=[])
            live_plan = SimpleNamespace(config=SimpleNamespace(replay_trial_path=None))
            replay_plan = SimpleNamespace(config=SimpleNamespace(replay_trial_path=root / 'replay'))

            with patch('fuzzmeter.run.runner.prepare_artifacts', return_value={}), \
                 patch('fuzzmeter.run.runner.plan_trials', return_value=[live_plan, replay_plan]):
                with self.assertRaisesRegex(RuntimeError, 'Replay trials cannot be mixed'):
                    run_experiment(
                        campaign_config=config,
                        out_root=root / 'out',
                        repo_root=root,
                        suite_yaml_text='suite',
                    )

    def test_replay_run_registers_trials_runs_scheduler_and_marks_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            try:
                ensure_schema(db)
                db.exec('INSERT INTO runs(run_id, created_ts, suite_yaml) VALUES(?,?,?)', ('run', 1, 'suite'))
                trial_ids = [
                    db_trials.ensure_trial_row(
                        db,
                        run_id='run',
                        fuzzer=f'fuzzer_{idx}',
                        benchmark='bench',
                        fuzz_target='target',
                        rep=idx,
                        time_seconds=300,
                        jobs=1,
                        status='preparing_replay',
                        fuzzer_image='runner',
                        build_config_json=None,
                        runtime_config_json=None,
                        started_ts=100 + idx,
                    )
                    for idx in (1, 2)
                ]
                db.commit()
            finally:
                db.close()

            active_trials = [
                _bare_active_trial(
                    trial_row_id=trial_ids[0],
                    root=root,
                    started_ts=101,
                    replay_start_ts=100,
                    replay_end_ts=160,
                ),
                _bare_active_trial(
                    trial_row_id=trial_ids[1],
                    root=root,
                    started_ts=102,
                    replay_start_ts=110,
                    replay_end_ts=190,
                ),
            ]
            prepared_by_key = {
                'trial-1': PreparedReplayTrial(
                    trial_row_id=trial_ids[0],
                    trial_id='trial-1',
                    replay_start_ts=100,
                    replay_end_ts=160,
                    active_trial=active_trials[0],
                ),
                'trial-2': PreparedReplayTrial(
                    trial_row_id=trial_ids[1],
                    trial_id='trial-2',
                    replay_start_ts=110,
                    replay_end_ts=190,
                    active_trial=active_trials[1],
                ),
            }
            trial_plans = [
                SimpleNamespace(
                    config=SimpleNamespace(trial_key='trial-1', runner_image='runner'),
                    target_bin=root / 'bin1',
                ),
                SimpleNamespace(
                    config=SimpleNamespace(trial_key='trial-2', runner_image='runner'),
                    target_bin=root / 'bin2',
                ),
            ]
            scheduler_refs: list[_SchedulerStub] = []

            def _prepare_factory(**kwargs):
                return prepared_by_key[kwargs['trial_plan'].config.trial_key]

            def _scheduler_factory(**kwargs):
                scheduler = _SchedulerStub()
                scheduler_refs.append(scheduler)
                self.assertEqual(80, kwargs['campaign_seconds'])
                return scheduler

            with patch('fuzzmeter.run.runner._prepare_one_replay_trial', side_effect=_prepare_factory), \
                 patch('fuzzmeter.run.runner.ReplaySnapshotScheduler', side_effect=_scheduler_factory):
                result = _run_replay_experiment(
                    db_path=db_path,
                    repo_root=root,
                    campaign_config=CampaignConfig(
                        settings=CampaignSettings(parallel_jobs=2, snapshot_every_seconds=30),
                        cases=[],
                    ),
                    run_dir=root,
                    run_id='run',
                    docker_runtime=None,
                    trial_plans=trial_plans,
                )

            self.assertEqual(root, result)
            self.assertEqual(1, len(scheduler_refs))
            self.assertEqual(
                sorted(trial.trial_id for trial in active_trials),
                sorted(trial.trial_id for trial in scheduler_refs[0].registered),
            )
            self.assertEqual(1, scheduler_refs[0].run_calls)
            self.assertEqual(['trial-1', 'trial-2'], sorted(scheduler_refs[0].unregistered))

            db = DB.open(db_path)
            try:
                rows = db.q('SELECT trial_id, status, ended_ts FROM trials ORDER BY trial_id')
            finally:
                db.close()
            self.assertEqual(
                [
                    {'trial_id': trial_ids[0], 'status': 'done', 'ended_ts': 160},
                    {'trial_id': trial_ids[1], 'status': 'done', 'ended_ts': 190},
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
                    repo_root=run_dir,
                    campaign_config=config,
                    run_dir=run_dir,
                    run_id='run',
                    docker_runtime=None,
                    trial_plans=[
                        SimpleNamespace(
                            config=SimpleNamespace(runner_image='runner'),
                            target_bin=run_dir / 'target-bin',
                        )
                    ],
                )

            self.assertEqual(run_dir, result)
            self.assertEqual(1, len(scheduler_refs))
            self.assertEqual(1, scheduler_refs[0].stop_calls)
            self.assertEqual(1, len(thread_refs))
            self.assertTrue(thread_refs[0].started)
            self.assertTrue(thread_refs[0].joined)

    def test_process_tick_creates_tick_snapshot_and_runs_snapshot_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            trial = _create_active_trial(root=root, db_path=db_path, started_ts=100)
            _write_output(trial.corpus_root / 'id:000001', 'corpus', mtime_s=110)
            _write_output(trial.crashes_root / 'id:000002', 'crash', mtime_s=120)

            scheduler = SnapshotScheduler(
                db_path=db_path,
                run_dir=root,
                run_id='run',
                campaign_seconds=300,
                every_seconds=60,
                docker_runtime=None,
                jobs=2,
            )
            _install_recorders(scheduler)
            scheduler._collector._read_stats = lambda trial, tick_ts=None: {'execs_done': 42}

            db = DB.open(db_path)
            try:
                scheduler._process_tick(db=db, tick_idx=1, ts=130, selected_trials=(trial,), render_heavy=True)

                self.assertEqual([{'run_id': 'run', 'idx': 1, 'ts': 130}], db_snapshot.list_ticks(db, run_id='run'))
                snapshots = db_snapshot.list_trial_snapshots(db, trial_row_id=trial.trial_row_id)
            finally:
                db.close()

            self.assertEqual(1, len(snapshots))
            self.assertEqual(1, snapshots[0]['idx'])
            self.assertEqual(1, snapshots[0]['corpus_files'])
            self.assertEqual(42, snapshots[0]['execs_done'])
            self.assertTrue((trial.snapshots_root / 'snap_000001' / 'corpus' / 'id:000001').is_file())
            self.assertTrue((trial.snapshots_root / 'snap_000001' / 'crashes' / 'id:000002').is_file())
            self.assertEqual(1, len(scheduler._coverage_runner.calls))
            self.assertEqual(1, len(scheduler._crash_runner.calls))
            self.assertEqual(1, len(scheduler._aggregate_updater.calls))
            self.assertEqual(1, len(scheduler._resource_telemetry.calls))

    def test_collector_parallelizes_trial_snapshot_collection(self) -> None:
        seen_threads: set[int] = set()
        collector = _ParallelCollector(barrier=threading.Barrier(2), seen_threads=seen_threads)
        trials = [_bare_active_trial(trial_row_id=idx, root=Path('/tmp'), started_ts=100) for idx in (1, 2, 3)]

        plan = collector.collect(
            db=None,
            tick_idx=1,
            ts=200,
            active_trials=trials,
            jobs=2,
        )

        self.assertEqual(trials, plan.active_trials)
        self.assertGreaterEqual(len(seen_threads), 2)

    def test_replay_scheduler_creates_periodic_and_last_ticks_from_replay_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            trial = _create_active_trial(root=root, db_path=db_path, started_ts=100, replay_start_ts=100, replay_end_ts=220)
            _write_output(trial.corpus_root / 'id:000001', 'first', mtime_s=110)
            _write_output(trial.corpus_root / 'id:000002', 'last', mtime_s=210)
            (trial.trial_root / 'replay_timeline.json').write_text(
                (
                    '{"replay_start_ts":100,"replay_end_ts":220,'
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
            _install_recorders(scheduler)
            scheduler._collector._read_stats = lambda trial, tick_ts=None: {}
            scheduler.register(trial)

            scheduler.run_loop()

            db = DB.open(db_path)
            try:
                ticks = db_snapshot.list_ticks(db, run_id='run')
                snapshots = db_snapshot.list_trial_snapshots(db, trial_row_id=trial.trial_row_id)
            finally:
                db.close()

            self.assertEqual([150, 200, 220], [row['ts'] for row in ticks])
            self.assertEqual([1, 2, 3], [row['idx'] for row in ticks])
            self.assertEqual([1, 2, 3], [row['idx'] for row in snapshots])
            self.assertEqual(2, snapshots[-1]['corpus_files'])
            self.assertTrue((trial.snapshots_root / 'snap_000003' / 'corpus' / 'id:000002').is_file())


def _install_recorders(scheduler: SnapshotScheduler) -> None:
    scheduler._coverage_runner = _ProcessorRecorder()
    scheduler._crash_runner = _ProcessorRecorder()
    scheduler._aggregate_updater = _AggregateRecorder()
    scheduler._resource_telemetry = _ResourceRecorder()


def _create_active_trial(
    *,
    root: Path,
    db_path: Path,
    started_ts: int,
    replay_start_ts: int | None = None,
    replay_end_ts: int | None = None,
) -> ActiveTrial:
    db = DB.open(db_path)
    try:
        ensure_schema(db)
        trial_row_id = db_trials.ensure_trial_row(
            db,
            run_id='run',
            fuzzer='aflplusplus',
            benchmark='bench',
            fuzz_target='target',
            rep=0,
            time_seconds=300,
            jobs=1,
            status='running',
            fuzzer_image='runner',
            build_config_json=None,
            runtime_config_json=None,
            started_ts=started_ts,
        )
        db.commit()
    finally:
        db.close()

    trial = _bare_active_trial(
        trial_row_id=trial_row_id,
        root=root,
        started_ts=started_ts,
        replay_start_ts=replay_start_ts,
        replay_end_ts=replay_end_ts,
    )
    trial.corpus_root.mkdir(parents=True)
    trial.crashes_root.mkdir(parents=True)
    trial.snapshots_root.mkdir(parents=True)
    return trial


def _bare_active_trial(
    *,
    trial_row_id: int,
    root: Path,
    started_ts: int,
    replay_start_ts: int | None = None,
    replay_end_ts: int | None = None,
) -> ActiveTrial:
    trial_root = root / f'trial-{trial_row_id}'
    return ActiveTrial(
        trial_row_id=trial_row_id,
        trial_id=f'aflplusplus__target__rep{trial_row_id}',
        container_name=f'container-{trial_row_id}',
        fuzzer='aflplusplus',
        fuzzer_base='aflplusplus',
        benchmark='bench',
        fuzz_target='target',
        input_mode='mode',
        rep=trial_row_id,
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
        replay_start_ts=replay_start_ts,
        replay_end_ts=replay_end_ts,
    )


def _write_output(path: Path, content: str, *, mtime_s: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    os.utime(path, ns=(mtime_s * 1_000_000_000, mtime_s * 1_000_000_000))


if __name__ == '__main__':
    unittest.main()
