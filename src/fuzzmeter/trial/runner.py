# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Run live fuzzing trials and coordinate their scheduler registration.'''

from __future__ import annotations

import json
import logging
import threading
import time

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..db import DB
from ..db import trials as db_trials
from ..docker import DockerRuntime
from ..snapshot import SnapshotScheduler
from .models import ActiveTrial, TrialConfig
from .runtime import TrialContainerRuntime, TrialRunContext
from .workspace import PreparedTrialWorkspace, TrialWorkspacePreparer

LOG = logging.getLogger(__name__)


class TrialRunner:
    '''Run one live fuzzing trial in a prepared container workspace.'''

    def __init__(
        self,
        *,
        repo_root: Path,
        docker_runtime: DockerRuntime,
        db_path: Path,
        run_id: str,
        fuzzer_image: str,
        target_bin_host_path: Path,
    ) -> None:
        self.db_path = Path(db_path)
        self.fuzzer_image = str(fuzzer_image)
        self.repo_root = Path(repo_root)
        self.docker_runtime = docker_runtime
        self.run_id = str(run_id)
        self.target_bin_host_path = Path(target_bin_host_path)

    def _set_trial_status(self, trial_row_id: int, status: str) -> None:
        db = DB.open(self.db_path)
        try:
            db_trials.set_trial_status(db, trial_id=trial_row_id, status=status, ended_ts=int(time.time()))
            db.commit()
        finally:
            db.close()

    def _insert_trial_row(self, *, cfg: TrialConfig, jobs: int, started_ts: int | None = None) -> int:
        db = DB.open(self.db_path)
        try:
            trial_row_id = db_trials.ensure_trial_row(
                db,
                run_id=self.run_id,
                fuzzer=cfg.fuzzer,
                benchmark=cfg.benchmark,
                fuzz_target=cfg.fuzz_target,
                rep=cfg.rep,
                time_seconds=cfg.time_seconds,
                jobs=jobs,
                status='running',
                fuzzer_image=self.fuzzer_image,
                build_config_json=json.dumps(cfg.build_config, sort_keys=True),
                runtime_config_json=json.dumps(cfg.runtime_config, sort_keys=True),
                started_ts=int(time.time()) if started_ts is None else int(started_ts),
            )
            db.commit()
            return trial_row_id
        finally:
            db.close()

    def _build_context(self, *, run_dir: Path, cfg: TrialConfig, jobs: int) -> TrialRunContext:
        workspace = self._prepare_workspace(run_dir=run_dir, cfg=cfg)
        started_ts = int(time.time())
        trial_row_id = self._insert_trial_row(cfg=cfg, jobs=jobs, started_ts=started_ts)
        return self._runtime().build_context(
            run_dir=run_dir,
            workspace=workspace,
            cfg=cfg,
            jobs=jobs,
            trial_row_id=trial_row_id,
            started_ts=started_ts,
        )

    def _prepare_workspace(self, *, run_dir: Path, cfg: TrialConfig) -> PreparedTrialWorkspace:
        return TrialWorkspacePreparer(
            target_bin_host_path=self.target_bin_host_path,
        ).prepare(run_dir=run_dir, cfg=cfg)

    def _runtime(self) -> TrialContainerRuntime:
        return TrialContainerRuntime(
            run_id=self.run_id,
            docker_runtime=self.docker_runtime,
            fuzzer_image=self.fuzzer_image,
            target_bin_host_path=self.target_bin_host_path,
        )

    @staticmethod
    @contextmanager
    def _registered_trial(ctx: TrialRunContext, scheduler: SnapshotScheduler, repo_root: Path) -> Iterator[None]:
        active_trial = ActiveTrial(
            trial_row_id=ctx.trial_row_id,
            trial_id=ctx.cfg.trial_key,
            container_name=ctx.container_name,
            fuzzer=ctx.cfg.fuzzer,
            fuzzer_base=ctx.cfg.fuzzer_base,
            benchmark=ctx.cfg.benchmark,
            fuzz_target=ctx.cfg.fuzz_target,
            input_mode=ctx.cfg.input_mode,
            target_timeout_s=ctx.cfg.target_timeout_s,
            rep=ctx.cfg.rep,
            runner_image=ctx.cfg.runner_image,
            coverage_image=ctx.cfg.coverage_image,
            asan_image=ctx.cfg.asan_image,
            snapshot_preprocess_script=ctx.cfg.snapshot_preprocess_script,
            trial_root=ctx.paths.trial_dir,
            live_out=ctx.paths.live_out_root,
            fuzzer_log=ctx.paths.fuzzer_log,
            corpus_root=ctx.paths.corpus_root,
            crashes_root=ctx.paths.crashes_root,
            snapshots_root=ctx.paths.snapshots_root,
            seed_root=ctx.seed_root,
            repo_root=repo_root,
            started_ts=ctx.started_ts,
        )
        scheduler.register(active_trial)
        try:
            yield
        finally:
            try:
                scheduler.request_trial_snapshot(active_trial)
            except Exception as exc:
                LOG.error('Final snapshot request failed for %s: %s', ctx.cfg.trial_key, exc)
            finally:
                scheduler.unregister(ctx.cfg.trial_key)

    def run(
        self,
        *,
        run_dir: Path,
        cfg: TrialConfig,
        scheduler: SnapshotScheduler,
        jobs: int,
        stop_event: threading.Event | None = None,
    ) -> None:
        LOG.info('Start fuzzing in %s', str(run_dir))
        started = False
        ctx = self._build_context(run_dir=run_dir, cfg=cfg, jobs=jobs)
        runtime = self._runtime()
        try:
            with self._registered_trial(ctx, scheduler, self.docker_runtime.repo_root):
                with runtime.running(ctx):
                    started = True
                    runtime.monitor_until_deadline(ctx, stop_event=stop_event)
        except Exception as exc:
            self._set_trial_status(ctx.trial_row_id, 'failed_runtime' if started else 'failed_start')
            LOG.error('Failed to execute fuzzer in %s directory.', run_dir)
            raise
        else:
            self._set_trial_status(ctx.trial_row_id, 'interrupted' if stop_event is not None and stop_event.is_set() else 'done')
