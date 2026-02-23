# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import logging
import shlex
import subprocess
import time

from dataclasses import dataclass, field
from pathlib import Path

from .runtime import DockerRuntime

logger = logging.getLogger(__name__)


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
            name=spec.name,
            env=spec.env,
            volumes=spec.volumes,
            user=spec.user,
            workdir=spec.workdir,
            memory=spec.memory,
            memory_swap=spec.memory_swap,
            read_only_rootfs=spec.read_only_rootfs,
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
    ) -> subprocess.CompletedProcess:
        '''Run a docker container synchronously and return the completed process.'''
        args = ['docker', 'run', '--rm']
        if name:
            self._run(['docker', 'rm', '-f', name], check=False, capture=True)
        args += self._common_run_args(
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

        try:
            result = subprocess.run(args, text=True, timeout=timeout_s, check=False, capture_output=True)
        except subprocess.TimeoutExpired:
            joined_args = ' '.join(args)
            result = subprocess.CompletedProcess(
                args,
                returncode=-1,
                stdout='',
                stderr=f'Command timed out after {timeout_s} seconds: {joined_args}',
            )
            if check:
                raise RuntimeError(result.stderr)
            return result

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
            result = self._run(['docker', 'wait', container_id_or_name], check=True, capture=True)
            return _parse_int(result.stdout.strip(), default=1)

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            running = subprocess.run(
                ['docker', 'inspect', '-f', '{{.State.Running}}', container_id_or_name],
                text=True,
                capture_output=True,
            )
            if running.returncode != 0:
                return 1
            if running.stdout.strip().lower() != 'true':
                exit_code = subprocess.run(
                    ['docker', 'inspect', '-f', '{{.State.ExitCode}}', container_id_or_name],
                    text=True,
                    capture_output=True,
                )
                return _parse_int(exit_code.stdout.strip(), default=1)
            time.sleep(0.5)
        return 1

    def create(self, image: str) -> str:
        '''Create a docker container from an image and return its id.'''
        result = self._run(['docker', 'create', image], check=True, capture=True)
        return result.stdout.strip()

    def copy_from_image(self, *, image: str, src_path: str, dst_path: str | Path) -> None:
        '''Copy a path from an image to the host.'''
        dst = Path(dst_path)
        dst.parent.mkdir(parents=True, exist_ok=True)

        quoted_src_path = shlex.quote(src_path)
        probe_cmd = [
            'docker',
            'run',
            '--rm',
            image,
            'bash',
            '-lc',
            f'test -d {quoted_src_path} && echo DIR || (test -f {quoted_src_path} && echo FILE || echo MISSING)',
        ]
        kind = self._run(probe_cmd, check=True, capture=True).stdout.strip()
        if kind == 'MISSING':
            raise RuntimeError(f'Docker image path is missing in {image}: {src_path}')

        container_id = self.create(image)
        try:
            self._run(['docker', 'cp', f'{container_id}:{src_path}', str(dst)], check=True, capture=True)
        finally:
            self._run(['docker', 'rm', '-f', container_id], check=False, capture=True)

    def is_running(self, container_id_or_name: str) -> bool:
        '''Return whether a docker container is currently running.'''
        result = subprocess.run(
            ['docker', 'inspect', '-f', '{{.State.Running}}', container_id_or_name],
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            return False
        return result.stdout.strip().lower() == 'true'

    def rm(self, container_id_or_name: str) -> bool:
        '''Remove a docker container if it exists.'''
        return subprocess.run(['docker', 'rm', '-f', container_id_or_name], check=False).returncode == 0

    def kill(self, container_id_or_name: str) -> bool:
        '''Kill a docker container if it is running.'''
        return subprocess.run(['docker', 'kill', container_id_or_name], check=False).returncode == 0

    def logs(self, container_id_or_name: str, tail: int = 200) -> str:
        '''Return docker logs for a container.'''
        result = subprocess.run(
            ['docker', 'logs', '--tail', str(int(tail)), container_id_or_name],
            text=True,
            capture_output=True,
        )
        out = result.stdout or ''
        if result.stderr:
            out += '\n' + result.stderr
        return out

    def _common_run_args(
        self,
        *,
        name: str | None = None,
        env: dict[str, str],
        volumes: list[str],
        user: str | None = None,
        workdir: str | None = None,
        memory: str | None = None,
        memory_swap: str | None = None,
        read_only_rootfs: bool = False,
    ) -> list[str]:
        args: list[str] = []
        if name:
            args += ['--name', name]
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

    @staticmethod
    def _run(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(cmd, check=check, text=True, capture_output=capture)
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
