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

from pathlib import Path

from ..docker import ContainerSpec, DockerClient, DockerRuntime
from .models import FUZZER_LOG, FUZZ_DIR, TrialConfig

LOG = logging.getLogger(__name__)


class TrialContainer:
    '''Run and stop fuzzer trial containers.'''

    _active_container_names: set[str] = set()
    _active_lock = threading.Lock()

    def __init__(
        self,
        *,
        docker_runtime: DockerRuntime,
        container_name: str,
        config: TrialConfig,
        run_dir: Path,
        input_corpus_dir: Path,
        run_id: str,
        fuzzer_log: Path,
        start_ts: int,
    ) -> None:
        self.docker = DockerClient(docker_runtime)
        self.container_name = container_name
        self.cfg = config
        self.run_dir = Path(run_dir)
        self.input_corpus_dir = Path(input_corpus_dir)
        self.run_mount_dir = Path('/tmp/fuzzmeter/out') / 'runs' / run_id
        self.trial_mount_dir = self.run_mount_dir / 'trials' / config.trial_key
        self.fuzzer_log = Path(fuzzer_log)
        self.start_ts = start_ts

    def monitor_until_deadline(
        self,
        *,
        stop_event: threading.Event | None = None,
    ) -> None:
        '''Wait until a trial container stops, times out, or receives a stop signal.'''
        deadline = time.time() + self.cfg.trial_timeout
        while time.time() < deadline and self.docker.is_running(self.container_name):
            if stop_event is not None and stop_event.is_set():
                break
            time.sleep(0.5)
        if stop_event is not None and stop_event.is_set():
            return
        if time.time() >= deadline:
            return

        exit_code = self.docker.wait(self.container_name, 10)
        elapsed_s = max(0, int(time.time() - self.start_ts))
        remaining_s = max(0, int(deadline - time.time()))
        self._append_premature_exit_logs()
        raise RuntimeError(
            f'Fuzzer container exited before the configured deadline: {self.container_name} '
            f'exit_code={exit_code}, elapsed_s={elapsed_s}, remaining_s={remaining_s}. See: {self.fuzzer_log}'
        )

    def _container_start_cmd(self) -> str:
        return f'''
        set -euo pipefail
        LOG="{self.trial_mount_dir / FUZZER_LOG}"
        umask 022
        mkdir -p "$(dirname "$LOG")"
        : > "$LOG"
        echo "[fuzzmeter] fuzzer={self.cfg.fuzzer} benchmark={self.cfg.benchmark}" >> "$LOG"
        echo "[fuzzmeter] fuzz_target={self.cfg.fuzz_target} trial={self.cfg.trial_key}" >> "$LOG"
        echo "[fuzzmeter] container_name={self.container_name}" >> "$LOG"
        echo "[fuzzmeter] runner_image={self.cfg.images.runner}" >> "$LOG"
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

    def start(self) -> None:
        '''Start a fuzzer trial container.'''
        fuzz_target_bin = self._mounted_path(self.cfg.fuzz_target_bin)
        input_corpus_dir = self._mounted_path(self.input_corpus_dir)
        fuzz_dir = self.trial_mount_dir / FUZZ_DIR
        fuzzer_log_in_container = self.trial_mount_dir / FUZZER_LOG

        env = {
            'FM_TARGET_BIN': str(fuzz_target_bin),
            'FM_INPUT_MODE': str(self.cfg.fuzz_target_input_mode),
            'FM_INPUT': str(input_corpus_dir),
            'FM_OUTPUT': str(fuzz_dir),
            'FM_TIME_SECONDS': str(self.cfg.trial_timeout),
            'FUZZER': self.cfg.fuzzer_base,
            'FM_FUZZER_RUNTIME_CONFIG_JSON': json.dumps(self.cfg.runtime_config, sort_keys=True),
            'FM_LOG': str(fuzzer_log_in_container),
            'FM_LOG_LEVEL': str(logging.getLevelName(LOG.getEffectiveLevel())),
        }
        self.docker.start(
            ContainerSpec(
                image=self.cfg.images.runner,
                name=self.container_name,
                workdir='/',
                entrypoint='/bin/bash',
                env=env,
                volumes=[self.docker.out_volume('/tmp/fuzzmeter/out')],
                mounts_ro={},
                user=self.docker.run_user,
                args=['-lc', self._container_start_cmd()],
                detach=True,
            )
        )
        self._register_active_container(self.container_name)
        time.sleep(0.5)
        if self.docker.is_running(self.container_name):
            return
        try:
            self._append_immediate_exit_logs()
            self.docker.rm(self.container_name)
        finally:
            self._unregister_active_container(self.container_name)
            raise RuntimeError(f'Fuzzer container exited immediately. See: {self.fuzzer_log}')

    def _mounted_path(self, path: Path) -> Path:
        return self.run_mount_dir / Path(path).relative_to(self.run_dir)

    def stop(self, *, log_proc: subprocess.Popen[str] | None) -> None:
        '''Stop a fuzzer trial container and its log stream.'''
        try:
            self.docker.kill(self.container_name)
            self.docker.wait(self.container_name, 10)
            self.docker.rm(self.container_name)
        finally:
            self._stop_log_stream(log_proc, self.container_name)
            self._unregister_active_container(self.container_name)

    def _append_immediate_exit_logs(self) -> None:
        logs = self.docker.logs(self.container_name, tail=500)
        with self.fuzzer_log.open('a', encoding='utf-8', errors='replace') as handle:
            handle.write('\n[fuzzmeter] container exited immediately; docker logs:\n')
            handle.write(logs)

    def _append_premature_exit_logs(self) -> None:
        logs = self.docker.logs(self.container_name, tail=500)
        with self.fuzzer_log.open('a', encoding='utf-8', errors='replace') as handle:
            handle.write('\n[fuzzmeter] container exited before the configured deadline; docker logs tail:\n')
            handle.write(logs)

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
            cls._active_container_names.add(container_name)

    @classmethod
    def _unregister_active_container(cls, container_name: str) -> None:
        with cls._active_lock:
            cls._active_container_names.discard(container_name)

    @classmethod
    def force_stop_all_active(cls) -> None:
        '''Stop all trial containers tracked by this process.'''
        with cls._active_lock:
            active = list(cls._active_container_names)
        docker = DockerClient()
        for container_name in active:
            try:
                docker.kill(container_name)
                docker.rm(container_name)
            finally:
                cls._unregister_active_container(container_name)
