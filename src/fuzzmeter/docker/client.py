# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Bounded Docker CLI operations for run-scoped containers.'''

from __future__ import annotations

import logging
import subprocess
import time

from dataclasses import dataclass, field
from pathlib import Path

from .runtime import DockerRuntime

logger = logging.getLogger(__name__)

# Control-plane operations must not wedge the process, so they get a deadline.
# Passing timeout_s=None means unbounded, which is required both for the worker
# containers that do the actual measuring and for cleanup that has to complete.
DEFAULT_DOCKER_TIMEOUT_S = 30


class DockerTimeoutError(RuntimeError):
    '''Report a Docker CLI command that exceeded its deadline.'''


@dataclass(frozen=True)
class ContainerSpec:
    '''Describe a docker container run.'''

    image: str
    name: str | None = None
    entrypoint: str | None = None
    command: list[str] | None = None
    args: list[str] | None = None
    detach: bool = True
    env: dict[str, str] = field(default_factory=dict)
    volumes: list[str] = field(default_factory=list)
    workdir: str | None = None
    read_only_rootfs: bool = False
    user: str | None = None
    memory: str | None = None
    memory_swap: str | None = None
    mounts: dict[Path, str] = field(default_factory=dict)
    mounts_ro: dict[Path, str] = field(default_factory=dict)
    kind: str = 'trial'
    trial_key: str | None = None
    init: bool = False


class DockerClient:
    '''Run docker CLI operations with one runtime configuration.'''

    def __init__(self, runtime: DockerRuntime | None = None) -> None:
        self.runtime = runtime

    @property
    def run_user(self) -> str | None:
        '''Return the docker user configured for this client.'''
        return self.runtime.run_user if self.runtime else None

    def out_volume(self, container_path: str = '/tmp/fuzzmeter/out') -> str:
        '''Return the shared output volume mount specification.'''
        if self.runtime is None:
            return f'./out:{container_path}'
        return self.runtime.out_volume_mount(container_path)

    def container_path(self, host_path: Path, *, container_root: str = '/tmp/fuzzmeter/out') -> str:
        '''Map a host output path to its container-side path.'''
        if self.runtime is None:
            return str(host_path)
        return self.runtime.map_out_path(host_path, container_root=container_root)

    def start(self, spec: ContainerSpec) -> str:
        '''Start a docker container and return docker stdout.'''
        if spec.name:
            self._run(['docker', 'rm', '-f', spec.name], check=False, capture=True)

        cmd: list[str] = ['docker', 'run']
        if spec.detach:
            cmd.append('-d')
        cmd += self._common_run_args(
            kind=spec.kind,
            trial_key=spec.trial_key,
            name=spec.name,
            env=spec.env,
            volumes=spec.volumes,
            user=spec.user,
            workdir=spec.workdir,
            memory=spec.memory,
            memory_swap=spec.memory_swap,
            read_only_rootfs=spec.read_only_rootfs,
            init=spec.init,
        )
        for host_path, container_path in spec.mounts.items():
            cmd += ['-v', f'{host_path}:{container_path}']
        for host_path, container_path in spec.mounts_ro.items():
            cmd += ['-v', f'{host_path}:{container_path}:ro']
        if spec.entrypoint:
            cmd += ['--entrypoint', spec.entrypoint]

        cmd.append(spec.image)
        if spec.command:
            cmd += spec.command
        if spec.args:
            cmd += spec.args

        return self._run(cmd, check=True, capture=True).stdout.strip()

    def run(
        self,
        *,
        image: str,
        name: str | None = None,
        env: dict[str, str] | None = None,
        volumes: list[str] | None = None,
        user: str | None = None,
        workdir: str | None = None,
        cmd: list[str] | None = None,
        timeout_s: int | None = None,
        check: bool = False,
        memory: str | None = None,
        memory_swap: str | None = None,
        kind: str,
        trial_key: str | None = None,
    ) -> subprocess.CompletedProcess:
        '''Run a docker container synchronously and return the completed process.'''
        args = ['docker', 'run', '--rm']
        if name:
            self._run(['docker', 'rm', '-f', name], check=False, capture=True)
        args += self._common_run_args(
            kind=kind,
            trial_key=trial_key,
            name=name,
            env=env or {},
            volumes=volumes or [],
            user=user,
            workdir=workdir,
            memory=memory,
            memory_swap=memory_swap,
        )
        args.append(image)
        if cmd:
            args += list(cmd)

        # Worker containers do the measuring, and their runtime depends on the
        # target and the corpus, so they stay unbounded unless a caller decides
        # otherwise. Bounding them here would turn a slow measurement into a
        # failed tick, which leaves a permanent hole in the cumulative coverage.
        result = self._run(args, check=False, capture=True, timeout_s=timeout_s)

        if check and result.returncode != 0:
            joined_args = ' '.join(args)
            stdout = result.stdout or ''
            stderr = result.stderr or ''
            raise RuntimeError(
                'Docker run failed\n'
                f'cmd: {joined_args}\n'
                f'rc: {result.returncode}\n'
                f'stdout:\n{stdout}\n'
                f'stderr:\n{stderr}\n'
           )

        return result

    def wait(self, container_id_or_name: str, timeout_s: int | None = None) -> int:
        '''Wait for a docker container and return its exit code.'''
        if timeout_s is None:
            # docker wait blocks for the whole remaining container lifetime.
            result = self._run(
                ['docker', 'wait', container_id_or_name],
                check=True,
                capture=True,
                timeout_s=None,
            )
            return _parse_int(result.stdout.strip(), default=1)

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            remaining_s = max(0.001, deadline - time.time())
            running = self._run(
                ['docker', 'inspect', '-f', '{{.State.Running}}', container_id_or_name],
                check=False,
                capture=True,
                timeout_s=min(DEFAULT_DOCKER_TIMEOUT_S, remaining_s),
            )
            if running.returncode != 0:
                return 1
            if running.stdout.strip().lower() != 'true':
                exit_code = self._run(
                    ['docker', 'inspect', '-f', '{{.State.ExitCode}}', container_id_or_name],
                    check=False,
                    capture=True,
                    timeout_s=min(DEFAULT_DOCKER_TIMEOUT_S, max(0.001, deadline - time.time())),
                )
                return _parse_int(exit_code.stdout.strip(), default=1)
            time.sleep(0.5)
        return 1

    def create(self, image: str, *, kind: str = 'build') -> str:
        '''Create a docker container from an image and return its id.'''
        result = self._run(
            ['docker', 'create', *self._label_args(kind=kind), image],
            check=True,
            capture=True,
        )
        return result.stdout.strip()

    def image_id(self, image: str) -> str | None:
        '''Return the immutable local image identifier when available.'''

        result = self._run(
            ['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
            check=False,
            capture=True,
        )
        return result.stdout.strip() or None if result.returncode == 0 else None

    def copy_from_image(self, *, image: str, src_path: str, dst_path: Path) -> None:
        '''Copy a path from an image to the host.'''
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        container_id = self.create(image, kind='build')
        try:
            self._run(['docker', 'cp', f'{container_id}:{src_path}', str(dst_path)], check=True, capture=True)
        finally:
            self._run(['docker', 'rm', '-f', container_id], check=False, capture=True)

    def is_running(self, container_id_or_name: str) -> bool:
        '''Return whether a docker container is currently running.'''
        result = self._run(
            ['docker', 'inspect', '-f', '{{.State.Running}}', container_id_or_name],
            check=False,
            capture=True,
        )
        if result.returncode != 0:
            return False
        return result.stdout.strip().lower() == 'true'

    def rm(self, container_id_or_name: str) -> bool:
        '''Remove a docker container if it exists.'''
        # Unbounded on purpose: a half-finished cleanup leaves a container
        # behind, and the repeated-signal path is the escape hatch if the
        # daemon is wedged.
        return self._run(
            ['docker', 'rm', '-f', container_id_or_name],
            check=False,
            capture=True,
            timeout_s=None,
        ).returncode == 0

    def kill(self, container_id_or_name: str) -> bool:
        '''Kill a docker container if it is running.'''
        return self._run(
            ['docker', 'kill', container_id_or_name],
            check=False,
            capture=True,
            timeout_s=None,
        ).returncode == 0

    def logs(self, container_id_or_name: str, tail: int = 200) -> str:
        '''Return docker logs for a container.'''
        result = self._run(
            ['docker', 'logs', '--tail', str(int(tail)), container_id_or_name],
            check=False,
            capture=True,
        )
        out = result.stdout or ''
        if result.stderr:
            out += '\n' + result.stderr
        return out

    def _common_run_args(
        self,
        *,
        kind: str,
        trial_key: str | None = None,
        name: str | None = None,
        env: dict[str, str],
        volumes: list[str],
        user: str | None = None,
        workdir: str | None = None,
        memory: str | None = None,
        memory_swap: str | None = None,
        read_only_rootfs: bool = False,
        init: bool = False,
    ) -> list[str]:
        args = self._label_args(kind=kind, trial_key=trial_key)
        if name:
            args += ['--name', name]
        if init:
            args.append('--init')
        if read_only_rootfs:
            args += ['--read-only']

        resolved_user = user or self.run_user
        if resolved_user:
            args += ['--user', resolved_user]
        resolved_memory = memory or (self.runtime.memory if self.runtime else None)
        if resolved_memory:
            args += ['--memory', resolved_memory]
        resolved_memory_swap = memory_swap or (self.runtime.memory_swap if self.runtime else None)
        if resolved_memory_swap:
            args += ['--memory-swap', resolved_memory_swap]
        if workdir:
            args += ['-w', workdir]

        for key, value in env.items():
            args += ['-e', f'{key}={value}']
        for volume in volumes:
            args += ['-v', volume]
        return args

    def _label_args(self, *, kind: str, trial_key: str | None = None) -> list[str]:
        if self.runtime is None or self.runtime.run_id is None:
            return []
        args = [
            '--label',
            f'fuzzmeter.run={self.runtime.run_id}',
            '--label',
            f'fuzzmeter.kind={kind}',
        ]
        if trial_key is not None:
            args += ['--label', f'fuzzmeter.trial={trial_key}']
        return args

    def sweep_run(self) -> int:
        '''Force-remove all containers carrying this client's run label.'''
        if self.runtime is None or self.runtime.run_id is None:
            raise ValueError('A run-scoped Docker runtime is required for sweeping')
        result = self._run(
            ['docker', 'ps', '-aq', '--filter', f'label=fuzzmeter.run={self.runtime.run_id}'],
            check=True,
            capture=True,
        )
        container_ids = result.stdout.split()
        if container_ids:
            # Unbounded: removing many containers may take a while and this
            # sweep is the only thing standing between an interrupt and a leak.
            self._run(['docker', 'rm', '-f', *container_ids], check=False, capture=True, timeout_s=None)
        return len(container_ids)

    @staticmethod
    def _run(
        cmd: list[str],
        *,
        check: bool = True,
        capture: bool = False,
        timeout_s: float | None = DEFAULT_DOCKER_TIMEOUT_S,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                cmd,
                check=check,
                text=True,
                capture_output=capture,
                timeout=timeout_s,
                start_new_session=True,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired as exc:
            raise DockerTimeoutError(
                f'Docker command timed out after {timeout_s} seconds: {" ".join(cmd)}'
            ) from exc
        except subprocess.CalledProcessError as exc:
            out = ''
            if getattr(exc, 'stdout', None):
                out += f'\n--- stdout ---\n{exc.stdout}'
            if getattr(exc, 'stderr', None):
                out += f'\n--- stderr ---\n{exc.stderr}'
            raise RuntimeError(f'Command failed (exit={exc.returncode}): {exc.cmd}{out}') from exc


def _parse_int(value: str, *, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default
