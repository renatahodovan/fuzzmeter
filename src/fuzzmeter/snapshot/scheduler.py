# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import logging
import queue
import sys
import threading
import time

from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from ..db import DB
from ..db import snapshot as db_snapshot
from ..docker import DockerRuntime
from ..trial.models import ActiveTrial
from .aggregate import SnapshotAggregateUpdater
from .collector import SnapshotCollector
from .coverage import SnapshotCoverageRunner
from .crashes import SnapshotCrashRunner
from .resource_telemetry import ResourceTelemetryCollector

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ScheduledSnapshot:
    tick_idx: int
    ts: int
    render_heavy: bool
    trials: tuple[ActiveTrial, ...] | None = None


def _open_progress_bar(total_seconds: int):
    return tqdm(
        total=max(int(total_seconds), 1),
        desc='Run',
        unit='s',
        position=0,
        leave=True,
        dynamic_ncols=True,
        disable=not sys.stderr.isatty(),
    )


def _update_progress(bar, *, total_seconds: int, elapsed_seconds: int, tick_idx: int, active_trials: int) -> None:
    target = max(0, min(int(elapsed_seconds), max(int(total_seconds), 1)))
    delta = target - int(bar.n)
    if delta > 0:
        bar.update(delta)
    bar.set_postfix(tick=tick_idx, active=active_trials, refresh=False)
    bar.refresh()


def _close_progress(bar) -> None:
    if bar is not None:
        bar.close()


def _logger_level() -> int:
    level = getattr(LOG, 'level', 0)
    return int(level) if isinstance(level, (int, float)) else 0


class SnapshotScheduler:
    '''Schedule periodic snapshot collection for active trials.'''

    def __init__(
        self,
        *,
        db_path: Path,
        run_dir: Path,
        run_id: str,
        campaign_seconds: int,
        every_seconds: int,
        docker_runtime: DockerRuntime,
        coverage_export_every_ticks: int = 1,
        jobs: int = 4,
    ) -> None:
        self.db_path = Path(db_path)
        self.run_dir = Path(run_dir)
        self.run_id = str(run_id)
        self.campaign_seconds = int(campaign_seconds)
        self.every_seconds = int(every_seconds)
        self.coverage_export_every_ticks = int(coverage_export_every_ticks)
        self.jobs = int(jobs)
        self.docker_runtime = docker_runtime
        self.started_ts = int(time.time())

        self._active: dict[str, ActiveTrial] = {}
        self._periodic_ordinals: dict[str, int] = {}
        self._stop = False

        self._lock = threading.Lock()
        self._tick_lock = threading.Lock()
        self._tick_seq_lock = threading.Lock()
        self._tick_queue: queue.Queue[_ScheduledSnapshot | None] = queue.Queue()
        self._next_tick_idx: int | None = None

        self._collector = SnapshotCollector(
            db_path=self.db_path,
            run_id=self.run_id,
            docker_runtime=self.docker_runtime,
        )
        self._coverage_runner = SnapshotCoverageRunner(
            docker_runtime=self.docker_runtime,
            export_every_ticks=self.coverage_export_every_ticks,
        )
        self._crash_runner = SnapshotCrashRunner(docker_runtime=self.docker_runtime)
        self._aggregate_updater = SnapshotAggregateUpdater(
            docker_runtime=self.docker_runtime,
            export_every_ticks=self.coverage_export_every_ticks,
        )
        self._resource_telemetry = ResourceTelemetryCollector()
        self._run_progress = _open_progress_bar(self.campaign_seconds) if _logger_level() >= 20 else None

    def register(self, trial: ActiveTrial) -> None:
        '''Register an active trial for future snapshots.'''
        with self._lock:
            self._active[trial.trial_id] = trial
            self._periodic_ordinals.setdefault(trial.trial_id, 0)

    def unregister(self, trial_id: str) -> None:
        '''Remove a trial from future snapshots.'''
        with self._lock:
            self._active.pop(trial_id, None)
            self._periodic_ordinals.pop(trial_id, None)

    def stop(self) -> None:
        '''Request the scheduler loop to stop after pending work.'''
        self._stop = True

    def request_trial_snapshot(self, trial: ActiveTrial, *, render_heavy: bool = True) -> None:
        '''Queue a final snapshot for one trial without blocking its worker slot.'''
        db = DB.open(self.db_path)
        try:
            tick_idx = self._allocate_tick_idx(db)
            self._tick_queue.put(
                _ScheduledSnapshot(
                    tick_idx=tick_idx,
                    ts=int(time.time()),
                    render_heavy=render_heavy,
                    trials=(trial,),
                )
            )
        finally:
            db.close()

    def run_loop(self) -> None:
        '''Run the snapshot scheduler until the campaign ends or stop is requested.'''
        if self.every_seconds <= 0:
            _close_progress(self._run_progress)
            return

        db = DB.open(self.db_path)
        worker = threading.Thread(target=self._tick_worker_loop, name='snapshot-tick-worker')
        worker.start()
        try:
            start_time = time.time()
            LOG.info(
                'Start fuzzing at %s, campaign_seconds=%s, every_seconds=%s',
                time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time)),
                self.campaign_seconds,
                self.every_seconds,
            )
            periodic_enabled = self.every_seconds < self.campaign_seconds
            while True:
                now = time.time()
                if periodic_enabled:
                    for ts, trials in self._due_periodic_snapshots(now_ts=int(now)):
                        tick_idx = self._allocate_tick_idx(db)
                        self._schedule_periodic_tick(tick_idx=tick_idx, ts=ts, trials=trials)

                if self._stop:
                    break
                time.sleep(0.5)
        finally:
            self._tick_queue.put(None)
            worker.join()
            db.close()
            _close_progress(self._run_progress)

    def _snapshot_active(self) -> list[ActiveTrial]:
        with self._lock:
            return list(self._active.values())

    def _active_for_ts(self, ts: int) -> list[ActiveTrial]:
        active_trials = self._snapshot_active()
        return self._filter_trials_for_ts(active_trials, ts)

    def _due_periodic_snapshots(self, *, now_ts: int) -> list[tuple[int, tuple[ActiveTrial, ...]]]:
        due_by_ts: dict[int, list[ActiveTrial]] = {}
        with self._lock:
            for trial in self._active.values():
                start_ts = trial.replay_start_ts if trial.replay_start_ts is not None else trial.started_ts
                if start_ts is None:
                    continue

                next_ordinal = int(self._periodic_ordinals.get(trial.trial_id, 0)) + 1
                last_due_ordinal = int(self._periodic_ordinals.get(trial.trial_id, 0))
                while True:
                    due_ts = int(start_ts) + next_ordinal * self.every_seconds
                    if due_ts >= int(start_ts) + self.campaign_seconds:
                        break
                    if due_ts > int(now_ts):
                        break
                    due_by_ts.setdefault(due_ts, []).append(trial)
                    last_due_ordinal = next_ordinal
                    next_ordinal += 1
                self._periodic_ordinals[trial.trial_id] = last_due_ordinal

        return [
            (ts, tuple(trials))
            for ts, trials in sorted(due_by_ts.items(), key=lambda item: item[0])
        ]

    def _schedule_periodic_tick(
        self,
        *,
        tick_idx: int,
        ts: int,
        trials: tuple[ActiveTrial, ...],
    ) -> None:
        self._tick_queue.put(
            _ScheduledSnapshot(
                tick_idx=tick_idx,
                ts=ts,
                render_heavy=False,
                trials=trials,
            )
        )
        LOG.info(
            'Scheduled snapshot tick %s at %s with %s active trials',
            tick_idx,
            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())),
            len(trials),
        )

    @staticmethod
    def _filter_trials_for_ts(trials: list[ActiveTrial] | tuple[ActiveTrial, ...], ts: int) -> list[ActiveTrial]:
        filtered: list[ActiveTrial] = []
        for trial in trials:
            start_ts = trial.replay_start_ts if trial.replay_start_ts is not None else trial.started_ts
            end_ts = trial.replay_end_ts
            if start_ts is not None and ts < int(start_ts):
                continue
            if end_ts is not None and ts > int(end_ts):
                continue
            filtered.append(trial)
        return filtered

    def _process_tick(
        self,
        *,
        db: DB,
        tick_idx: int,
        ts: int,
        render_heavy: bool = False,
        selected_trials: tuple[ActiveTrial, ...] | None = None,
    ) -> None:
        active_trials = (
            self._filter_trials_for_ts(selected_trials, ts)
            if selected_trials is not None
            else self._active_for_ts(ts)
        )
        if self._run_progress:
            _update_progress(
                self._run_progress,
                total_seconds=self.campaign_seconds,
                elapsed_seconds=ts - self.started_ts,
                tick_idx=tick_idx,
                active_trials=len(active_trials),
            )

        db_snapshot.insert_tick(db, run_id=self.run_id, idx=tick_idx, ts=ts)
        self._resource_telemetry.collect(db=db, tick_idx=tick_idx, ts=ts, active_trials=active_trials)
        db.commit()

        plan = self._collector.collect(
            db=db,
            tick_idx=tick_idx,
            ts=ts,
            active_trials=active_trials,
            jobs=self.jobs,
            render_heavy=render_heavy,
        )

        db.commit()

        cur_time = time.time()
        self._coverage_runner.process(
            db=db,
            db_path=self.db_path,
            run_dir=self.run_dir,
            tick_idx=tick_idx,
            jobs=self.jobs,
            plan=plan,
        )
        LOG.info('Coverage processing of %s tick finished in %.1f seconds', tick_idx, time.time() - cur_time)

        cur_time = time.time()
        self._crash_runner.process(
            db=db,
            db_path=self.db_path,
            run_id=self.run_id,
            repro_logs_dir=self.run_dir / 'repro_logs',
            tick_idx=tick_idx,
            jobs=self.jobs,
            plan=plan,
        )
        LOG.info('Crash processing of %s tick finished in %.1f seconds', tick_idx, time.time() - cur_time)

        self._aggregate_updater.update(
            db=db,
            run_dir=self.run_dir,
            run_id=self.run_id,
            tick_idx=tick_idx,
            ts=ts,
            coverage_tasks=plan.coverage_tasks,
        )
        db.commit()

    def _allocate_tick_idx(self, db: DB) -> int:
        with self._tick_seq_lock:
            if self._next_tick_idx is None:
                self._next_tick_idx = db_snapshot.get_next_tick_idx(db, run_id=self.run_id)
            tick_idx = int(self._next_tick_idx)
            self._next_tick_idx += 1
            return tick_idx

    def _tick_worker_loop(self) -> None:
        db = DB.open(self.db_path)
        try:
            while True:
                item = self._tick_queue.get()
                if item is None:
                    break
                try:
                    with self._tick_lock:
                        ts = int(item.ts)
                        LOG.info(
                            'Starting %s. snapshot processing after %s seconds',
                            item.tick_idx,
                            max(0, ts - self.started_ts),
                        )
                        self._process_tick(
                            db=db,
                            tick_idx=item.tick_idx,
                            ts=ts,
                            render_heavy=item.render_heavy,
                            selected_trials=item.trials,
                        )
                        LOG.info('Finished %s. snapshot processing', item.tick_idx)
                except Exception:
                    LOG.exception('Error during snapshot tick %s', item.tick_idx)
        finally:
            db.close()


class ReplaySnapshotScheduler(SnapshotScheduler):
    '''Replay snapshot processing from trial timestamps.'''

    def run_loop(self) -> None:
        '''Run replay snapshot collection.'''
        active_trials = self._snapshot_active()
        if not active_trials:
            _close_progress(self._run_progress)
            return

        db = DB.open(self.db_path)
        try:
            tick_schedule = self._build_tick_schedule(active_trials)
            if not tick_schedule:
                LOG.warning('Replay run has no snapshot ticks to process')
                return

            self.started_ts = min(
                int(trial.replay_start_ts)
                for trial in active_trials
                if trial.replay_start_ts is not None
            )
            LOG.debug('Start replay snapshot loop with %s ticks', len(tick_schedule))
            for ts in tick_schedule:
                if self._stop:
                    break
                with self._tick_lock:
                    tick_idx = self._allocate_tick_idx(db)
                    self._process_tick(db=db, tick_idx=tick_idx, ts=ts, render_heavy=True)
        finally:
            db.close()
            _close_progress(self._run_progress)

    def _build_tick_schedule(self, active_trials: list[ActiveTrial]) -> list[int]:
        tick_ts: set[int] = set()
        for trial in active_trials:
            start_ts = trial.replay_start_ts
            end_ts = trial.replay_end_ts
            if start_ts is None or end_ts is None:
                continue
            if end_ts < start_ts:
                end_ts = start_ts

            next_ts = int(start_ts) + self.every_seconds
            if self.every_seconds > 0:
                while next_ts < int(end_ts):
                    tick_ts.add(next_ts)
                    next_ts += self.every_seconds
            tick_ts.add(int(end_ts))
        return sorted(tick_ts)
