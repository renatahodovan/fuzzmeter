# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Docker-backed runtime management for live fuzzing trial containers.'''

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ..docker import ContainerSpec, DockerClient, DockerRuntime
from .models import TrialConfig, TrialPaths
from .workspace import PreparedTrialWorkspace

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrialRunContext:
    '''Hold container paths and runtime settings for one trial.'''

    cfg: TrialConfig
    jobs: int
    paths: TrialPaths
    seed_root: Path | None
    trial_row_id: int
    started_ts: int
    container_name: str
    run_user: str | None
    container_trial_dir: Path
    target_bin_container_path: Path
    input_container_path: Path
    output_container_path: Path
    log_container_path: Path

    @property
    def log_path(self) -> Path:
        '''Return the host-side fuzzer log path.'''
        return self.paths.fuzzer_log


class TrialContainerRuntime:
    '''Run and stop fuzzer trial containers.'''

    _active_container_names: set[str] = set()
    _active_lock = threading.Lock()

    def __init__(
        self,
        *,
        run_id: str,
        docker_runtime: DockerRuntime,
        fuzzer_image: str,
        target_bin_host_path: Path,
    ) -> None:
        self.run_id = str(run_id)
        self.docker_runtime = docker_runtime
        self.docker = DockerClient(docker_runtime)
        self.fuzzer_image = str(fuzzer_image)
        self.target_bin_host_path = Path(target_bin_host_path)

    def build_context(
        self,
        *,
        run_dir: Path,
        workspace: PreparedTrialWorkspace,
        cfg: TrialConfig,
        jobs: int,
        trial_row_id: int,
        started_ts: int,
    ) -> TrialRunContext:
        '''Build the container context for a prepared trial workspace.'''
        container_run_dir = Path('/tmp/fuzzmeter/out') / 'runs' / self.run_id
        container_trial_dir = container_run_dir / 'trials' / cfg.trial_key

        try:
            target_rel = self.target_bin_host_path.resolve().relative_to(run_dir.resolve())
        except Exception as exc:
            raise RuntimeError(f'Target binary must live under run_dir: {self.target_bin_host_path}') from exc

        try:
            input_seed_rel = workspace.input_seed_root.resolve().relative_to(run_dir.resolve())
        except Exception as exc:
            raise RuntimeError(f'Input seed root must live under run_dir: {workspace.input_seed_root}') from exc
        input_container_path = container_run_dir / input_seed_rel

        return TrialRunContext(
            cfg=cfg,
            jobs=jobs,
            paths=workspace.paths,
            seed_root=workspace.seed_root,
            trial_row_id=trial_row_id,
            started_ts=int(started_ts),
            container_name=self._container_name(cfg=cfg, trial_row_id=trial_row_id),
            run_user=self.docker.run_user,
            container_trial_dir=container_trial_dir,
            target_bin_container_path=container_run_dir / target_rel,
            input_container_path=input_container_path,
            output_container_path=container_trial_dir / cfg.paths.live_out_root,
            log_container_path=container_trial_dir / cfg.paths.fuzzer_log,
        )

    def _container_name(self, *, cfg: TrialConfig, trial_row_id: int) -> str:
        '''Return a docker container name unique across concurrent runs.'''
        return (
            f'fm_{self.run_id}_{trial_row_id}_{cfg.trial_key}'
            .replace(':', '_')
            .replace('/', '_')
        )

    def monitor_until_deadline(self, ctx: TrialRunContext, *, stop_event: threading.Event | None = None) -> None:
        '''Wait until a trial container stops, times out, or receives a stop signal.'''
        deadline = time.time() + ctx.cfg.time_seconds
        while time.time() < deadline and self.docker.is_running(ctx.container_name):
            if stop_event is not None and stop_event.is_set():
                break
            time.sleep(0.5)
        if stop_event is not None and stop_event.is_set():
            return
        if time.time() >= deadline:
            return

        exit_code = self.docker.wait(ctx.container_name, 10)
        elapsed_s = max(0, int(time.time() - ctx.started_ts))
        remaining_s = max(0, int(deadline - time.time()))
        self._append_premature_exit_logs(log_path=ctx.log_path, container_name=ctx.container_name)
        raise RuntimeError(
            f'Fuzzer container exited before the configured deadline: {ctx.container_name} '
            f'exit_code={exit_code}, elapsed_s={elapsed_s}, remaining_s={remaining_s}. See: {ctx.log_path}'
        )

    @contextmanager
    def running(self, ctx: TrialRunContext) -> Iterator[None]:
        '''Run a trial container for the duration of a context manager.'''
        self._start_container(ctx)
        log_proc: subprocess.Popen[str] | None = None
        try:
            with ctx.paths.fuzzer_log.open('a', encoding='utf-8', errors='replace') as log_file:
                log_proc = subprocess.Popen(
                    ['docker', 'logs', '-f', ctx.container_name],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                yield
        finally:
            self._stop_container(container_name=ctx.container_name, log_proc=log_proc)

    def _container_env(self, ctx: TrialRunContext) -> dict[str, str]:
        env = {
            'FM_TARGET_BIN': str(ctx.target_bin_container_path),
            'FM_INPUT_MODE': str(ctx.cfg.input_mode),
            'FM_INPUT': str(ctx.input_container_path),
            'FM_OUTPUT': str(ctx.output_container_path),
            'FM_LOG': str(ctx.log_container_path),
            'FM_TIME_SECONDS': str(int(ctx.cfg.time_seconds)),
            'FM_JOBS': str(ctx.jobs),
            'FUZZER': ctx.cfg.fuzzer_base,
            'FM_FUZZER_RUNTIME_CONFIG_JSON': json.dumps(ctx.cfg.runtime_config, sort_keys=True),
        }
        log_level = str(logging.getLevelName(LOG.getEffectiveLevel()))
        env['FM_LOG_LEVEL'] = log_level
        env['FUZZMETER_LOG_LEVEL'] = log_level
        return env

    def _container_start_cmd(self, ctx: TrialRunContext) -> str:
        return f'''
        set -euo pipefail
        LOG="{ctx.log_container_path}"
        umask 022
        mkdir -p "$(dirname "$LOG")"
        : > "$LOG"
        echo "[fuzzmeter] fuzzer={ctx.cfg.fuzzer} benchmark={ctx.cfg.benchmark}" >> "$LOG"
        echo "[fuzzmeter] fuzz_target={ctx.cfg.fuzz_target} trial={ctx.cfg.trial_key}" >> "$LOG"
        echo "[fuzzmeter] container_name={ctx.container_name}" >> "$LOG"
        echo "[fuzzmeter] self.fuzzer_image={self.fuzzer_image}" >> "$LOG"
        echo "[fuzzmeter] FM_TARGET_BIN=$FM_TARGET_BIN" >> "$LOG"
        echo "[fuzzmeter] FM_INPUT=$FM_INPUT FM_OUTPUT=$FM_OUTPUT" >> "$LOG"
        echo "[fuzzmeter] FM_LOG_LEVEL=$FM_LOG_LEVEL" >> "$LOG"
        set +e
        python3 -u "/opt/fuzzmeter/run_fuzzer.py" >> "$LOG" 2>&1
        rc=$?
        set -e
        echo "[fuzzmeter] run_fuzzer exit_code=$rc" >> "$LOG"
        exit $rc
        '''.strip()

    def _start_container(self, ctx: TrialRunContext) -> None:
        # LOG.info('Starting trial container %s with user=%s', ctx.container_name, ctx.run_user)
        self._register_active_container(ctx.container_name)
        self.docker.start(
            ContainerSpec(
                image=ctx.cfg.runner_image,
                name=ctx.container_name,
                workdir='/',
                entrypoint='/bin/bash',
                env=self._container_env(ctx),
                volumes=[self.docker.out_volume('/tmp/fuzzmeter/out')],
                mounts_ro={},
                user=ctx.run_user,
                args=['-lc', self._container_start_cmd(ctx)],
                detach=True,
            )
        )
        time.sleep(0.5)
        if self.docker.is_running(ctx.container_name):
            return
        self._append_immediate_exit_logs(log_path=ctx.log_path, container_name=ctx.container_name)
        self._safe_remove_container(ctx.container_name)
        raise RuntimeError(f'Fuzzer container exited immediately. See: {ctx.log_path}')

    def _stop_container(self, *, container_name: str, log_proc: subprocess.Popen[str] | None) -> None:
        try:
            if self.docker.is_running(container_name):
                self.docker.kill(container_name)
        except Exception as exc:
            LOG.warning('Failed to kill container %s: %s', container_name, exc)
        try:
            self.docker.wait(container_name, 10)
        except Exception as exc:
            LOG.warning('Failed to wait for container %s: %s', container_name, exc)
        self._stop_log_stream(log_proc, container_name)
        self._safe_remove_container(container_name)
        self._unregister_active_container(container_name)

    def _append_immediate_exit_logs(self, *, log_path: Path, container_name: str) -> None:
        logs = self.docker.logs(container_name, tail=500)
        with log_path.open('a', encoding='utf-8', errors='replace') as handle:
            handle.write('\n[fuzzmeter] container exited immediately; docker logs:\n')
            handle.write(logs)

    def _append_premature_exit_logs(self, *, log_path: Path, container_name: str) -> None:
        logs = self.docker.logs(container_name, tail=500)
        with log_path.open('a', encoding='utf-8', errors='replace') as handle:
            handle.write('\n[fuzzmeter] container exited before the configured deadline; docker logs tail:\n')
            handle.write(logs)

    def _safe_remove_container(self, container_name: str) -> None:
        if not self.docker.rm(container_name):
            LOG.warning('Failed to remove container %s', container_name)

    @staticmethod
    def _stop_log_stream(log_proc: subprocess.Popen[str] | None, container_name: str) -> None:
        if log_proc is None:
            return
        try:
            if log_proc.poll() is None:
                log_proc.terminate()
            log_proc.wait(timeout=2)
        except Exception as exc:
            LOG.warning('Failed to stop docker log stream for %s: %s', container_name, exc)

    @classmethod
    def _register_active_container(cls, container_name: str) -> None:
        with cls._active_lock:
            cls._active_container_names.add(str(container_name))

    @classmethod
    def _unregister_active_container(cls, container_name: str) -> None:
        with cls._active_lock:
            cls._active_container_names.discard(str(container_name))

    @classmethod
    def force_stop_all_active(cls) -> None:
        '''Stop all trial containers tracked by this process.'''
        with cls._active_lock:
            active = list(cls._active_container_names)
        docker = DockerClient()
        for container_name in active:
            try:
                if docker.is_running(container_name):
                    docker.kill(container_name)
            except Exception as exc:
                LOG.warning('Failed to kill active container %s during interrupt cleanup: %s', container_name, exc)
            try:
                docker.rm(container_name)
            except Exception as exc:
                LOG.warning('Failed to remove active container %s during interrupt cleanup: %s', container_name, exc)
            finally:
                cls._unregister_active_container(container_name)
