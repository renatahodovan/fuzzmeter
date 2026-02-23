# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Docker runtime settings for host-driven container workflows.'''

from __future__ import annotations

import os

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class DockerRuntime:
    '''Hold docker-related host settings for a fuzzmeter run.'''

    repo_root: Path
    out_src: str
    run_user: str | None
    memory: str | None = None
    memory_swap: str | None = None

    @classmethod
    def from_paths(cls, *, repo_root: Path, out_root: Path) -> 'DockerRuntime':
        '''Create Docker runtime settings from explicit host paths.'''
        return cls(
            repo_root=Path(repo_root).expanduser().resolve(),
            out_src=str(Path(out_root).expanduser().resolve()),
            run_user=_host_user(),
        )

    def with_docker_limits(self, *, memory: str | None = None, memory_swap: str | None = None) -> 'DockerRuntime':
        '''Return a copy with docker memory limits applied.'''
        return DockerRuntime(
            repo_root=self.repo_root,
            out_src=self.out_src,
            run_user=self.run_user,
            memory=memory,
            memory_swap=memory_swap,
        )

    def out_volume_mount(self, container_path: str = '/tmp/fuzzmeter/out') -> str:
        '''Return the shared output volume mount specification.'''
        return f'{self.out_src}:{container_path}'

    def host_out_root(self) -> Path | None:
        '''Return the host output root when it is an absolute filesystem path.'''
        try:
            path = Path(self.out_src)
        except Exception:
            return None
        if not path.is_absolute():
            return None
        return path

    def map_out_path(self, host_path: Path, *, container_root: str = '/tmp/fuzzmeter/out') -> str:
        '''Map a host output path to the corresponding container output path.'''
        host_root = self.host_out_root()
        if host_root is None:
            return str(host_path)

        try:
            rel = Path(host_path).resolve().relative_to(host_root.resolve())
        except Exception:
            return str(host_path)

        return str(Path(container_root) / rel)

    def hook_env(self, extra: Mapping[str, object] | None = None) -> dict[str, str]:
        '''Return environment variables for host-side hook execution.'''
        env = os.environ.copy()
        env['FM_REPO'] = str(self.repo_root)
        env['FM_OUT_SRC'] = self.out_src
        if os.environ.get('FM_LOG_LEVEL'):
            env['FM_LOG_LEVEL'] = str(os.environ['FM_LOG_LEVEL'])
            env['FUZZMETER_LOG_LEVEL'] = str(os.environ['FM_LOG_LEVEL'])
        python_path = env.get('PYTHONPATH', '')
        env['PYTHONPATH'] = f'{self.repo_root}:{python_path}'.rstrip(':')
        if extra:
            env.update({key: str(value) for key, value in extra.items()})
        return env


def _host_user() -> str | None:
    try:
        return f'{os.getuid()}:{os.getgid()}'
    except Exception:
        return None
