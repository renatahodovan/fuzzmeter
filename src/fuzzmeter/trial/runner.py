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
import subprocess
import threading
import time

from pathlib import Path

from ..db import DB
from ..db import trials as db_trials
from ..docker import DockerRuntime
from ..snapshot import SnapshotScheduler
from .models import TrialConfig, TrialInstance
from .runtime import TrialContainer
from .workspace import prepare_live_workspace

LOG = logging.getLogger(__name__)


class TrialRunner:
    '''Run one live fuzzing trial in a prepared container workspace.'''

    def __init__(
        self,
        *,
        docker_runtime: DockerRuntime,
        db_path: Path,
        run_id: str,
    ) -> None:
        self.db_path = Path(db_path)
        self.docker_runtime = docker_runtime
        self.run_id = str(run_id)

    def _set_trial_status(self, trial_row_id: int, status: str) -> None:
        db = DB.open(self.db_path)
        try:
            db_trials.set_trial_status(db, trial_id=trial_row_id, status=status, ended_ts=int(time.time()))
            db.commit()
        finally:
            db.close()

    def _record_trial(self, *, config: TrialConfig, start_ts: int) -> int:
        db = DB.open(self.db_path)
        try:
            trial_row_id = db_trials.ensure_trial_row(
                db,
                run_id=self.run_id,
                fuzzer=config.fuzzer,
                benchmark=config.benchmark,
                fuzz_target=config.fuzz_target,
                rep=config.rep_idx,
                time_seconds=config.trial_timeout,
                status='running',
                fuzzer_image=config.images.runner,
                build_config_json=json.dumps(config.build_config, sort_keys=True),
                runtime_config_json=json.dumps(config.runtime_config, sort_keys=True),
                start_ts=start_ts,
            )
            db.commit()
            return trial_row_id
        finally:
            db.close()

    def run(
        self,
        *,
        run_dir: Path,
        config: TrialConfig,
        scheduler: SnapshotScheduler,
        stop_event: threading.Event | None = None,
    ) -> None:
        LOG.info('Start fuzzing in %s', run_dir)
        layout, host_input_corpus_dir = prepare_live_workspace(run_dir=run_dir, cfg=config)
        start_ts = int(time.time())
        trial_db_id = self._record_trial(config=config, start_ts=start_ts)
        container_name = f'fm_{self.run_id}_{trial_db_id}_{config.trial_key}'
        trial_container = TrialContainer(
            docker_runtime=self.docker_runtime,
            container_name=container_name,
            config=config,
            run_dir=run_dir,
            input_corpus_dir=host_input_corpus_dir,
            run_id=self.run_id,
            fuzzer_log=layout.fuzzer_log,
            start_ts=start_ts,
        )
        trial = TrialInstance(
            db_id=trial_db_id,
            config=config,
            layout=layout,
            container_name=container_name,
            repo_root=self.docker_runtime.repo_root,
            start_ts=start_ts,
        )
        log_proc: subprocess.Popen[str] | None = None
        scheduler.register(trial)
        status: str | None = None
        started = False
        try:
            trial_container.start()
            started = True
            with layout.fuzzer_log.open('a', encoding='utf-8', errors='replace') as log_file:
                log_proc = subprocess.Popen(
                    ['docker', 'logs', '-f', container_name],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                trial_container.monitor_until_deadline(stop_event=stop_event)
        except Exception:
            status = 'failed_runtime' if started else 'failed_start'
            LOG.error('Failed to execute fuzzer in %s directory.', run_dir)
            raise
        else:
            status = 'interrupted' if stop_event is not None and stop_event.is_set() else 'done'
        finally:
            try:
                if started:
                    try:
                        trial_container.stop(log_proc=log_proc)
                    except Exception as exc:
                        LOG.error('Failed to stop trial container for %s: %s', config.trial_key, exc)

                if status is not None:
                    self._set_trial_status(trial_db_id, status)

                if status == 'done':
                    try:
                        scheduler.schedule_final_tick(trial)
                    except Exception as exc:
                        LOG.error('Failed to schedule last tick: %s', exc)
            finally:
                scheduler.unregister(config.trial_key)
