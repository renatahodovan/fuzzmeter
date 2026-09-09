# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Run live and replay fuzzing experiments and coordinate trial execution.'''

from __future__ import annotations

import logging
import os
import threading
import time
import uuid

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TypeVar

from ..artifacts.builder import prepare_artifacts
from ..composite.collect import collect_records, save_records
from ..config import CampaignConfig
from ..db import ensure_schema, open_db
from ..db import runs as db_runs
from ..db import trials as db_trials
from ..docker import DockerRuntime
from ..snapshot import ReplaySnapshotScheduler, SnapshotScheduler
from ..trial.builder import plan_trials
from ..trial.models import ReplayTrialConfig, TrialConfig
from ..trial.replay import prepare_replay_trial
from ..trial.runner import run_one_trial
from .shutdown import RunShutdown, cleanup_containers

LOG = logging.getLogger(__name__)

_T = TypeVar('_T')


def _live_resource_plan(*, total_jobs: int, snapshot_jobs: int | None = None) -> tuple[int, int]:
    if snapshot_jobs:
        if snapshot_jobs >= total_jobs:
            raise ValueError(
                f'Snapshot jobs must not exhaust all the available parallelism ({total_jobs} > {snapshot_jobs})'
            )
        return total_jobs - snapshot_jobs, snapshot_jobs

    if total_jobs == 1:
        trial_workers, snapshot_workers = 1, 0
    elif total_jobs == 2:
        trial_workers, snapshot_workers = 1, 1
    else:
        snapshot_workers = total_jobs // 3
        trial_workers = total_jobs - snapshot_workers

    return trial_workers, snapshot_workers


def _initialize_run_dir(
    *,
    run_dir: Path,
    run_id: str,
    db_path: Path,
    config_src: str,
    campaign_config: CampaignConfig,
    label: str | None = None,
) -> None:
    '''Initialize run metadata, config files, and database schema.'''
    (run_dir / 'config.yaml').write_text(config_src, encoding='utf-8')
    with open_db(db_path) as db:
        ensure_schema(db)
        db_runs.upsert_run(
            db,
            run_id=run_id,
            created_ts=int(time.time()),
            config_src=config_src,
            label=label,
        )

    campaign_config.write_run_config(run_dir)
    save_records(
        run_dir / 'fuzzmeter.db',
        collect_records(run_id=run_id, campaign_config=campaign_config),
    )


def run_experiment(
    campaign_config: CampaignConfig,
    out_root: Path,
    config_src: str,
    label: str | None = None,
) -> Path:
    '''Run a fuzzing or replay experiment and return the run directory.'''
    run_id = str(uuid.uuid4())
    docker_runtime = DockerRuntime(
        fuzzer_dirs=campaign_config.fuzzer_dirs,
        out_src=str(out_root),
        run_user=f'{os.getuid()}:{os.getgid()}',
        run_id=run_id,
        memory=campaign_config.settings.memory,
        memory_swap=campaign_config.settings.memory_swap
    )

    timestamp = time.strftime('%Y-%m-%d_%H%M%S', time.localtime())
    if label is not None:
        timestamp = f'{timestamp}-{label}'
    run_dir = Path(out_root) / timestamp
    with RunShutdown(docker_runtime) as shutdown:
        run_dir.mkdir(parents=True)

        db_path = run_dir / 'fuzzmeter.db'
        _initialize_run_dir(run_dir=run_dir,
                            run_id=run_id,
                            db_path=db_path,
                            config_src=config_src,
                            campaign_config=campaign_config,
                            label=label)

        fuzz_binaries = prepare_artifacts(
            campaign_config=campaign_config,
            db_path=db_path,
            run_dir=run_dir,
            run_id=run_id,
            docker_runtime=docker_runtime,
        )
        trial_configs = plan_trials(campaign_config=campaign_config, fuzz_binaries=fuzz_binaries)
        replay_trial_configs = [cfg for cfg in trial_configs if isinstance(cfg, ReplayTrialConfig)]

        if replay_trial_configs:
            if len(replay_trial_configs) != len(trial_configs):
                raise RuntimeError('Replay trials cannot be mixed with live fuzzing trials in the same run')

            _run_replay_experiment(
                db_path=db_path,
                campaign_config=campaign_config,
                run_dir=run_dir,
                run_id=run_id,
                docker_runtime=docker_runtime,
                trial_configs=replay_trial_configs,
            )
            return run_dir

        if not trial_configs:
            raise RuntimeError('Does not found any valid experiment to run.')

        _run_live_experiment(
            db_path=db_path,
            campaign_config=campaign_config,
            run_dir=run_dir,
            run_id=run_id,
            docker_runtime=docker_runtime,
            trial_configs=trial_configs,
            stop_event=shutdown.stop_event,
        )
        return run_dir


def _run_live_experiment(
    *,
    db_path: Path,
    campaign_config: CampaignConfig,
    run_dir: Path,
    run_id: str,
    docker_runtime: DockerRuntime,
    trial_configs: list[TrialConfig],
    stop_event: threading.Event,
) -> Path:
    trial_workers, snap_jobs = _live_resource_plan(
        total_jobs=campaign_config.settings.parallel_jobs,
        snapshot_jobs=campaign_config.settings.snapshot_jobs,
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
        coverage_export_every=campaign_config.settings.snapshot_export_every_ticks,
        docker_runtime=docker_runtime,
        jobs=snap_jobs,
        parallel_jobs=campaign_config.settings.parallel_jobs,
        total_trials=len(trial_configs),
        trial_workers=trial_workers,
        stop_event=stop_event,
    )
    scheduler_thread = threading.Thread(target=scheduler.run_loop, name='snapshot-scheduler')
    executor: ThreadPoolExecutor | None = None
    futures: list[Future[None]] = []
    interrupted = False

    LOG.info('Planned trials: %d', len(trial_configs))

    scheduler_thread.start()
    try:
        executor = ThreadPoolExecutor(max_workers=trial_workers)
        futures = [
            executor.submit(
                run_one_trial,
                docker_runtime=docker_runtime,
                db_path=db_path,
                run_dir=run_dir,
                run_id=run_id,
                config=cfg,
                scheduler=scheduler,
                stop_event=stop_event,
            )
            for cfg in trial_configs
        ]
        _wait_for_futures(futures)
    except (KeyboardInterrupt, SystemExit):
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
                # Order matters: the scheduler has to know it is stopping before
                # the sweep removes the containers under its in-flight tick, or
                # the resulting error is recorded as a measurement failure.
                stop_event.set()
                scheduler.stop()
                cleanup_containers(docker_runtime)
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
    trial_configs: list[ReplayTrialConfig],
) -> Path:
    prep_jobs = min(campaign_config.settings.parallel_jobs, len(trial_configs))
    snap_jobs = max(campaign_config.settings.snapshot_jobs or campaign_config.settings.parallel_jobs, 1)
    LOG.info('Using replay prep_workers=%s snap_jobs=%s', prep_jobs, snap_jobs)

    with ThreadPoolExecutor(max_workers=prep_jobs) as executor:
        futures = [
            executor.submit(
                prepare_replay_trial,
                db_path=db_path,
                docker_runtime=docker_runtime,
                run_dir=run_dir,
                run_id=run_id,
                cfg=cfg,
            )
            for cfg in trial_configs
        ]
        prepared_trials = _wait_for_futures(futures)

    if not prepared_trials:
        raise RuntimeError('Could not find any replayable artifacts.')

    for trial in prepared_trials:
        if trial.end_ts - trial.start_ts <= 0:
            raise ValueError('The length of the replayable data in %s is 0 or shorter.' % trial.layout.fuzz_dir)

    scheduler = ReplaySnapshotScheduler(
        db_path=db_path,
        run_dir=run_dir,
        run_id=run_id,
        campaign_seconds=max(trial.end_ts - trial.start_ts for trial in prepared_trials),
        every_seconds=campaign_config.settings.snapshot_every_seconds,
        coverage_export_every=campaign_config.settings.snapshot_export_every_ticks,
        docker_runtime=docker_runtime,
        jobs=snap_jobs,
    )

    for prepared in prepared_trials:
        scheduler.register(prepared)

    status: str = 'done'
    try:
        scheduler.run_loop()
    except (KeyboardInterrupt, SystemExit):
        scheduler.stop()
        status = 'interrupted'
        raise
    except Exception:
        status = 'failed_replay'
        raise
    finally:
        try:
            with open_db(db_path) as db:
                for prepared in prepared_trials:
                    db_trials.set_trial_status(
                        db,
                        trial_id=prepared.db_id,
                        status=status,
                        ended_ts=prepared.end_ts,
                    )
        finally:
            for prepared in prepared_trials:
                scheduler.unregister(prepared.config.trial_key)
            cleanup_containers(docker_runtime)

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
