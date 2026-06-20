# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Run live and replay fuzzing experiments and coordinate trial execution.'''

from __future__ import annotations

import logging
import threading
import time

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TypeVar

from ..artifacts.builder import prepare_artifacts
from ..config import CampaignConfig
from ..db import open_db
from ..db import trials as db_trials
from ..docker import DockerRuntime
from ..snapshot import ReplaySnapshotScheduler, SnapshotScheduler
from ..trial.builder import plan_trials
from ..trial.models import TrialConfig, TrialInstance
from ..trial.replay import ReplayTrialRunner
from ..trial.runner import TrialRunner
from ..trial.runtime import TrialContainer
from .workspace import initialize_run_dir

LOG = logging.getLogger(__name__)

_T = TypeVar('_T')


def _live_resource_plan(*, total_jobs: int, requested_snapshot_jobs: int | None = None) -> tuple[int, int]:
    if requested_snapshot_jobs is not None:
        snapshot_workers = min(max(0, int(requested_snapshot_jobs)), max(0, int(total_jobs) - 1))
        trial_workers = max(1, int(total_jobs) - snapshot_workers)
        return trial_workers, snapshot_workers

    if total_jobs == 1:
        trial_workers, snapshot_workers = 1, 0
    elif total_jobs == 2:
        trial_workers, snapshot_workers = 1, 1
    else:
        snapshot_workers = total_jobs // 2
        trial_workers = total_jobs - snapshot_workers

    return trial_workers, snapshot_workers


def run_experiment(campaign_config: CampaignConfig, out_root: Path, repo_root: Path, config_src: str) -> Path:
    '''Run a fuzzing or replay experiment and return the run directory.'''
    docker_runtime = DockerRuntime.from_paths(repo_root=repo_root, out_root=out_root).with_docker_limits(
        memory=campaign_config.settings.memory,
        memory_swap=campaign_config.settings.memory_swap,
    )
    run_id = time.strftime('%Y-%m-%d_%H%M%S', time.localtime())
    run_dir = Path(out_root) / 'runs' / run_id
    run_dir.mkdir(parents=True)

    db_path = (Path(run_dir) / 'fuzzmeter.db')
    initialize_run_dir(
        run_dir=run_dir,
        run_id=run_id,
        config_src=config_src,
        campaign_config=campaign_config,
    )

    fuzz_binaries = prepare_artifacts(
        campaign_config=campaign_config,
        run_dir=run_dir,
        repo_root=repo_root,
        docker_runtime=docker_runtime,
    )
    trial_configs = plan_trials(
        campaign_config=campaign_config,
        repo_root=repo_root,
        fuzz_binaries=fuzz_binaries,
    )
    replay_trial_configs = [cfg for cfg in trial_configs if cfg.replay_dir is not None]

    if replay_trial_configs:
        if len(replay_trial_configs) != len(trial_configs):
            raise RuntimeError('Replay trials cannot be mixed with live fuzzing trials in the same run')

        return _run_replay_experiment(
            db_path=db_path,
            campaign_config=campaign_config,
            run_dir=run_dir,
            run_id=run_id,
            docker_runtime=docker_runtime,
            trial_configs=replay_trial_configs,
        )

    if not trial_configs:
        raise RuntimeError('Does not found any valid experiment to run.')

    return _run_live_experiment(
        db_path=db_path,
        campaign_config=campaign_config,
        run_dir=run_dir,
        run_id=run_id,
        docker_runtime=docker_runtime,
        trial_configs=trial_configs,
    )


def _run_live_experiment(
    *,
    db_path: Path,
    campaign_config: CampaignConfig,
    run_dir: Path,
    run_id: str,
    docker_runtime: DockerRuntime,
    trial_configs: list[TrialConfig],
) -> Path:
    trial_workers, snap_jobs = _live_resource_plan(
        total_jobs=campaign_config.settings.parallel_jobs,
        requested_snapshot_jobs=campaign_config.settings.snapshot_jobs,
    )
    LOG.info(
        'Using trial_workers=%s snapshot_jobs=%s (parallel_jobs=%s)',
        trial_workers,
        snap_jobs,
        max(2, int(campaign_config.settings.parallel_jobs)),
    )

    scheduler = SnapshotScheduler(
        db_path=db_path,
        run_dir=run_dir,
        run_id=run_id,
        campaign_seconds=campaign_config.settings.time_seconds,
        every_seconds=campaign_config.settings.snapshot_every_seconds,
        coverage_export_every_ticks=campaign_config.settings.snapshot_export_every_ticks,
        docker_runtime=docker_runtime,
        jobs=snap_jobs,
    )
    scheduler_thread = threading.Thread(target=scheduler.run_loop, name='snapshot-scheduler')
    stop_event = threading.Event()
    executor: ThreadPoolExecutor | None = None
    futures: list[Future[None]] = []
    interrupted = False

    LOG.info('Planned trials: %d', len(trial_configs))

    scheduler_thread.start()
    try:
        executor = ThreadPoolExecutor(max_workers=trial_workers)
        futures = [
            executor.submit(
                _run_one_trial,
                db_path=db_path,
                run_dir=run_dir,
                run_id=run_id,
                docker_runtime=docker_runtime,
                scheduler=scheduler,
                stop_event=stop_event,
                cfg=cfg,
            )
            for cfg in trial_configs
        ]
        _wait_for_futures(futures)
    except KeyboardInterrupt:
        interrupted = True
        LOG.warning('Interrupt received, stopping active trial containers...')
        for future in futures:
            future.cancel()
        raise
    except Exception as exc:
        interrupted = True
        LOG.error('Failure during fuzzing: %s', exc)
        raise
    finally:
        if interrupted:
            try:
                stop_event.set()
                TrialContainer.force_stop_all_active()
                scheduler.stop()
            except Exception as exc:
                LOG.error('Failed to stop snapshot scheduler: %s', exc)
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=interrupted)
        if not interrupted:
            try:
                scheduler.stop()
            except Exception as exc:
                LOG.error('Failed to stop snapshot scheduler: %s', exc)
        scheduler_thread.join()

    return run_dir


def _run_replay_experiment(
    *,
    db_path: Path,
    campaign_config: CampaignConfig,
    run_dir: Path,
    run_id: str,
    docker_runtime: DockerRuntime,
    trial_configs: list[TrialConfig],
) -> Path:
    prep_workers = max(min(max(1, int(campaign_config.settings.parallel_jobs)), len(trial_configs)), 1)
    snap_jobs = max(
        1,
        int(campaign_config.settings.snapshot_jobs)
        if campaign_config.settings.snapshot_jobs is not None
        else int(campaign_config.settings.parallel_jobs),
    )
    LOG.info('Using replay prep_workers=%s snap_jobs=%s', prep_workers, snap_jobs)

    with ThreadPoolExecutor(max_workers=prep_workers) as executor:
        futures = [
            executor.submit(
                _prepare_one_replay_trial,
                db_path=db_path,
                run_dir=run_dir,
                run_id=run_id,
                docker_runtime=docker_runtime,
                cfg=cfg,
            )
            for cfg in trial_configs
        ]
        prepared_trials = _wait_for_futures(futures)

    campaign_seconds = max(
        max(0, int(prepared.end_ts) - int(prepared.start_ts))
        for prepared in prepared_trials
    )
    scheduler = ReplaySnapshotScheduler(
        db_path=db_path,
        run_dir=run_dir,
        run_id=run_id,
        campaign_seconds=max(campaign_seconds, 1),
        every_seconds=campaign_config.settings.snapshot_every_seconds,
        coverage_export_every_ticks=campaign_config.settings.snapshot_export_every_ticks,
        docker_runtime=docker_runtime,
        jobs=snap_jobs,
    )

    for prepared in prepared_trials:
        scheduler.register(prepared)

    status: str | None = 'done'
    try:
        scheduler.run_loop()
    except KeyboardInterrupt:
        scheduler.stop()
        status = 'interrupted'
        raise
    except Exception:
        status = 'failed_replay'
        raise
    finally:
        try:
            if status is not None:
                _set_replay_trial_statuses(
                    db_path=db_path,
                    prepared_trials=prepared_trials,
                    status=status,
                )
        finally:
            for prepared in prepared_trials:
                scheduler.unregister(prepared.config.trial_key)

    return run_dir


def _wait_for_futures(futures: list[Future[_T]]) -> list[_T]:
    results: list[_T] = []
    for future in as_completed(futures):
        try:
            results.append(future.result())
        except Exception as exc:
            for pending in futures:
                if pending is not future:
                    pending.cancel()
            raise exc

    return results


def _run_one_trial(
    *,
    db_path: Path,
    run_dir: Path,
    run_id: str,
    docker_runtime: DockerRuntime,
    scheduler: SnapshotScheduler,
    stop_event: threading.Event | None,
    cfg: TrialConfig,
) -> None:
    TrialRunner(
        docker_runtime=docker_runtime,
        db_path=db_path,
        run_id=run_id,
    ).run(
        run_dir=run_dir,
        config=cfg,
        scheduler=scheduler,
        stop_event=stop_event,
    )


def _prepare_one_replay_trial(
    *,
    db_path: Path,
    run_dir: Path,
    run_id: str,
    docker_runtime: DockerRuntime,
    cfg: TrialConfig,
) -> TrialInstance:
    return ReplayTrialRunner(
        docker_runtime=docker_runtime,
        db_path=db_path,
        run_id=run_id,
    ).prepare(
        run_dir=run_dir,
        cfg=cfg,
    )


def _set_replay_trial_statuses(
    *,
    db_path: Path,
    prepared_trials: list[TrialInstance],
    status: str,
) -> None:
    with open_db(db_path) as db:
        for prepared in prepared_trials:
            db_trials.set_trial_status(
                db,
                trial_id=prepared.db_id,
                status=status,
                ended_ts=int(prepared.end_ts),
            )
