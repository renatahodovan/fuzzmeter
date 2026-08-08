# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Schedule snapshot collection for live and replay trial instances.'''

from __future__ import annotations

import logging
import queue
import threading
import time

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..db import DB
from ..db import snapshot as db_snapshot
from ..docker import DockerRuntime
from ..trial.models import ReplayTrialInstance, TrialInstance
from .collector import collect_snapshots
from .coverage import process_snapshot_coverage
from .crashes import process_snapshot_crashes
from .progress import SnapshotProgress
from .resource_telemetry import ResourceTelemetryCollector

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SnapshotData:
    tick_idx: int
    end_ts: int
    render_heavy: bool
    trials: tuple[TrialInstance, ...]
    campaign_trials: tuple[TrialInstance, ...]


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
        coverage_export_every: int = 1,
        jobs: int = 4,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.stop_event = stop_event
        self.db_path = Path(db_path)
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.campaign_seconds = campaign_seconds
        self.every_seconds = every_seconds
        self.coverage_export_every = coverage_export_every
        self.jobs = jobs
        self.docker_runtime = docker_runtime
        self.start_ts = int(time.time())

        self._active: dict[str, TrialInstance] = {}
        self._campaign_trials: dict[str, TrialInstance] = {}
        self._next_periodic_ts: dict[str, int] = {}
        self._stop = False

        self._lock = threading.Lock()
        self._tick_lock = threading.Lock()
        self._tick_seq_lock = threading.Lock()
        self._tick_queue: queue.Queue[SnapshotData | None] = queue.Queue()
        self._next_tick_idx: int | None = None
        self._scheduled_ticks = 0
        self._processed_ticks = 0
        self._progress = SnapshotProgress(
            total_seconds=self.campaign_seconds,
            enabled=LOG.isEnabledFor(logging.INFO),
        )

        self._resource_telemetry = ResourceTelemetryCollector()

    def register(self, trial: TrialInstance) -> None:
        '''Register an active trial for future snapshots.'''
        trial_key = trial.config.trial_key
        next_due_ts = trial.start_ts + self.every_seconds
        campaign_end_ts = trial.start_ts + self.campaign_seconds
        with self._lock:
            self._active[trial_key] = trial
            self._campaign_trials[trial_key] = trial
            if next_due_ts < campaign_end_ts:
                self._next_periodic_ts[trial_key] = next_due_ts
            else:
                self._next_periodic_ts.pop(trial_key, None)

    def unregister(self, trial_id: str) -> None:
        '''Remove a trial from future snapshots.'''
        with self._lock:
            self._active.pop(trial_id, None)
            self._next_periodic_ts.pop(trial_id, None)

    def stop(self) -> None:
        '''Request the scheduler loop to stop after pending work.'''
        self._stop = True

    @property
    def _shutting_down(self) -> bool:
        '''Report whether this scheduler or the whole run is stopping.

        The signal handler sets the shared stop event before it sweeps the
        containers, so consulting it is what lets a tick that a sweep killed be
        recorded as aborted rather than as a measurement failure.
        '''
        return self._stop or (self.stop_event is not None and self.stop_event.is_set())

    def _record_tick_error(self, db: DB, *, tick_idx: int, exc: BaseException) -> None:
        '''Persist a tick error as aborted while stopping and as failed otherwise.'''
        error = f'{type(exc).__name__}: {exc}'
        if self._shutting_down:
            db_snapshot.mark_tick_aborted(db, run_id=self.run_id, idx=tick_idx, error=error)
        else:
            db_snapshot.mark_tick_failed(db, run_id=self.run_id, idx=tick_idx, error=error)
        db.commit()

    def schedule_final_tick(self, trial: TrialInstance, *, render_heavy: bool = True) -> None:
        '''Queue a final snapshot for one trial without blocking its worker slot.'''
        db = DB.open(self.db_path)
        try:
            tick_idx = self._allocate_tick_idx(db)
            ts = int(time.time())
            db_snapshot.insert_tick(db, run_id=self.run_id, idx=tick_idx, ts=ts)
            db.commit()
            self._schedule_tick(
                tick_idx=tick_idx,
                ts=ts,
                render_heavy=render_heavy,
                trials=(trial,),
                campaign_trials=self._campaign_trial_snapshots(),
            )
        finally:
            db.close()

    def run_loop(self) -> None:
        '''Run the snapshot scheduler until the campaign ends or stop is requested.'''
        if self.every_seconds <= 0 or self.every_seconds > self.campaign_seconds:
            self._progress.close()
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
            while True:
                now = time.time()
                self._progress.update_run(
                    elapsed_seconds=max(0, int(now) - self.start_ts),
                    total_seconds=self.campaign_seconds,
                    tick_idx=self._scheduled_ticks,
                    active_trials=self._active_trials_count(),
                )
                due_snapshots, next_due_ts = self._due_periodic_snapshots(now_ts=int(now))
                for ts, trials in due_snapshots:
                    self._schedule_periodic_tick(
                        db=db,
                        tick_idx=self._allocate_tick_idx(db),
                        ts=ts,
                        trials=trials,
                    )

                if self._stop:
                    break
                if next_due_ts is None:
                    time.sleep(1.0)
                    continue
                time.sleep(max(0.0, float(next_due_ts) - now))
        finally:
            self._tick_queue.put(None)
            worker.join()
            db.close()
            self._progress.close()

    def _active_trials(self) -> list[TrialInstance]:
        with self._lock:
            return list(self._active.values())

    def _campaign_trial_snapshots(self) -> tuple[TrialInstance, ...]:
        with self._lock:
            return tuple(self._campaign_trials.values())

    def _replay_trials(self) -> list[ReplayTrialInstance]:
        with self._lock:
            return [trial for trial in self._active.values() if isinstance(trial, ReplayTrialInstance)]

    def _active_trials_count(self) -> int:
        with self._lock:
            return len(self._active)

    def _due_periodic_snapshots(self, *, now_ts: int) -> tuple[list[tuple[int, tuple[TrialInstance, ...]]], int | None]:
        due_by_ts: dict[int, list[TrialInstance]] = {}
        with self._lock:
            for trial_key, scheduled_ts in list(self._next_periodic_ts.items()):
                trial = self._active.get(trial_key)
                if trial is None:
                    self._next_periodic_ts.pop(trial_key, None)
                    continue
                campaign_end_ts = trial.start_ts + self.campaign_seconds
                next_scheduled_ts = scheduled_ts
                while next_scheduled_ts <= now_ts and next_scheduled_ts < campaign_end_ts:
                    due_by_ts.setdefault(next_scheduled_ts, []).append(trial)
                    next_scheduled_ts += self.every_seconds
                if next_scheduled_ts < campaign_end_ts:
                    self._next_periodic_ts[trial_key] = next_scheduled_ts
                else:
                    self._next_periodic_ts.pop(trial_key, None)
            next_due_ts = min(self._next_periodic_ts.values()) if self._next_periodic_ts else None

        return [
            (ts, tuple(trials))
            for ts, trials in sorted(due_by_ts.items(), key=lambda item: item[0])
        ], next_due_ts

    def _schedule_periodic_tick(
        self,
        *,
        db: DB,
        tick_idx: int,
        ts: int,
        trials: tuple[TrialInstance, ...],
    ) -> None:
        db_snapshot.insert_tick(db, run_id=self.run_id, idx=tick_idx, ts=ts)
        self._resource_telemetry.collect(db=db, tick_idx=tick_idx, ts=ts, active_trials=list(trials))
        db.commit()
        self._schedule_tick(
            tick_idx=tick_idx,
            ts=ts,
            render_heavy=False,
            trials=trials,
            campaign_trials=self._campaign_trial_snapshots(),
        )
        LOG.debug(
            'Scheduled snapshot tick %s at %s with %s active trials',
            tick_idx,
            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())),
            len(trials),
        )

    def _process_tick(
        self,
        *,
        db: DB,
        tick_idx: int,
        end_ts: int,
        selected_trials: Sequence[TrialInstance],
        campaign_trials: Sequence[TrialInstance],
        replay_mode: bool = False,
        render_heavy: bool = False,
    ) -> None:
        active_trials = list(selected_trials)
        write_export = render_heavy or (
            self.coverage_export_every > 0 and tick_idx % self.coverage_export_every == 0
        )
        self._progress.update_run(
            elapsed_seconds=max(0, end_ts - self.start_ts),
            total_seconds=self.campaign_seconds,
            tick_idx=tick_idx,
            active_trials=len(active_trials),
        )

        coverage_snapshots, crash_snapshots = collect_snapshots(
            db_path=self.db_path,
            run_id=self.run_id,
            docker_runtime=self.docker_runtime,
            tick_idx=tick_idx,
            end_ts=end_ts,
            active_trials=active_trials,
            replay_mode=replay_mode,
            jobs=self.jobs,
        )

        if coverage_snapshots:
            cur_time = time.time()
            process_snapshot_coverage(
                db=db,
                db_path=self.db_path,
                run_dir=self.run_dir,
                run_id=self.run_id,
                tick_idx=tick_idx,
                ts=end_ts,
                jobs=self.jobs,
                snapshots=coverage_snapshots,
                campaign_trials=campaign_trials,
                docker_runtime=self.docker_runtime,
                write_export=write_export,
                progress=self._progress,
            )
            db.commit()
            LOG.debug('Coverage processing of %s tick finished in %.1f seconds', tick_idx, time.time() - cur_time)

        if crash_snapshots:
            cur_time = time.time()
            process_snapshot_crashes(
                db_path=self.db_path,
                run_dir=self.run_dir,
                run_id=self.run_id,
                tick_idx=tick_idx,
                jobs=self.jobs,
                snapshots=crash_snapshots,
                docker_runtime=self.docker_runtime,
                progress=self._progress,
            )
            LOG.debug('Crash processing of %s tick finished in %.1f seconds', tick_idx, time.time() - cur_time)

        db_snapshot.mark_tick_completed(db, run_id=self.run_id, idx=tick_idx)
        db.commit()
        self._processed_ticks += 1
        self._update_scheduler_progress(ts=end_ts)

    def _allocate_tick_idx(self, db: DB) -> int:
        with self._tick_seq_lock:
            if self._next_tick_idx is None:
                self._next_tick_idx = db_snapshot.get_next_tick_idx(db, run_id=self.run_id)
            tick_idx = self._next_tick_idx
            self._next_tick_idx += 1
            return tick_idx

    def _tick_worker_loop(self) -> None:
        db = DB.open(self.db_path)
        try:
            while True:
                snapshot_item = self._tick_queue.get()
                if snapshot_item is None:
                    break
                try:
                    with self._tick_lock:
                        LOG.debug(
                            'Starting snapshot processing for tick %s after %s seconds',
                            snapshot_item.tick_idx,
                            max(0, snapshot_item.end_ts - self.start_ts),
                        )
                        self._process_tick(
                            db=db,
                            tick_idx=snapshot_item.tick_idx,
                            end_ts=snapshot_item.end_ts,
                            selected_trials=snapshot_item.trials,
                            campaign_trials=snapshot_item.campaign_trials,
                            replay_mode=False,
                            render_heavy=snapshot_item.render_heavy,
                        )
                        LOG.debug('Finished snapshot processing for tick %s', snapshot_item.tick_idx)
                except Exception as exc:
                    self._record_tick_error(db, tick_idx=snapshot_item.tick_idx, exc=exc)
                    LOG.exception('Error during snapshot tick %s', snapshot_item.tick_idx)
        finally:
            db.close()

    def _schedule_tick(
        self,
        *,
        tick_idx: int,
        ts: int,
        render_heavy: bool,
        trials: tuple[TrialInstance, ...],
        campaign_trials: tuple[TrialInstance, ...],
    ) -> None:
        self._tick_queue.put(
            SnapshotData(
                tick_idx=tick_idx,
                end_ts=ts,
                render_heavy=render_heavy,
                trials=trials,
                campaign_trials=campaign_trials,
            )
        )
        self._scheduled_ticks += 1
        self._update_scheduler_progress(ts=ts)

    def _update_scheduler_progress(self, *, ts: int) -> None:
        self._progress.update_scheduler(
            scheduled_ticks=self._scheduled_ticks,
            processed_ticks=self._processed_ticks,
            lag_seconds=max(0, int(time.time()) - ts),
        )


class ReplaySnapshotScheduler(SnapshotScheduler):
    '''Replay snapshot processing from trial timestamps.'''

    def run_loop(self) -> None:
        '''Run replay snapshot collection.'''
        active_trials = self._replay_trials()

        db = DB.open(self.db_path)
        try:
            tick_schedule = self._build_tick_schedule(active_trials)
            if not tick_schedule:
                LOG.warning('Replay run has no snapshot ticks to process')
                return

            self.start_ts = min(trial.start_ts for trial in active_trials)
            LOG.debug('Start replay snapshot loop with %s ticks', len(tick_schedule))
            for ts in tick_schedule:
                if self._stop:
                    break
                selected_trials = [trial for trial in active_trials if trial.start_ts <= ts <= trial.end_ts]
                campaign_trials = [trial for trial in active_trials if trial.start_ts <= ts]
                with self._tick_lock:
                    tick_idx = self._allocate_tick_idx(db)
                    db_snapshot.insert_tick(db, run_id=self.run_id, idx=tick_idx, ts=ts)
                    db.commit()
                    self._scheduled_ticks += 1
                    self._update_scheduler_progress(ts=ts)
                    try:
                        self._process_tick(
                            db=db,
                            tick_idx=tick_idx,
                            end_ts=ts,
                            selected_trials=selected_trials,
                            campaign_trials=campaign_trials,
                            replay_mode=True,
                            render_heavy=True,
                        )
                    except Exception as exc:
                        self._record_tick_error(db, tick_idx=tick_idx, exc=exc)
                        raise
        finally:
            db.close()
            self._progress.close()

    def _build_tick_schedule(self, active_trials: Sequence[ReplayTrialInstance]) -> list[int]:
        tick_ts: set[int] = set()
        for trial in active_trials:
            start_ts = trial.start_ts
            end_ts = trial.end_ts
            end_ts = max(end_ts, start_ts)

            next_ts = start_ts + self.every_seconds
            if self.every_seconds > 0:
                while next_ts < end_ts:
                    tick_ts.add(next_ts)
                    next_ts += self.every_seconds
            tick_ts.add(end_ts)
        return sorted(tick_ts)
