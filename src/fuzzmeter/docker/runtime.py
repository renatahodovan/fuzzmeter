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

    fuzzer_dirs: dict[str, Path]
    out_src: str
    run_user: str
    run_id: str
    memory: str | None
    memory_swap: str | None

    def out_volume_mount(self, container_path: str = '/tmp/fuzzmeter/out') -> str:
        '''Return the shared output volume mount specification.'''
        return f'{self.out_src}:{container_path}'

    def map_out_path(self, host_path: Path, *, container_root: str = '/tmp/fuzzmeter/out') -> str:
        '''Map a host output path to the corresponding container output path.'''
        host_root = Path(self.out_src)
        if not host_root.is_absolute():
            return str(host_path)

        try:
            rel = Path(host_path).resolve().relative_to(host_root.resolve())
        except Exception:
            return str(host_path)

        return str(Path(container_root) / rel)

    def hook_env(self, extra: Mapping[str, object] | None = None) -> dict[str, str]:
        '''Return environment variables for host-side hook execution.'''
        env = os.environ.copy()
        env['FM_OUT_SRC'] = self.out_src
        env['FM_LOG_LEVEL'] = os.environ['FM_LOG_LEVEL']
        roots = os.pathsep.join(sorted({str(path.parent) for path in self.fuzzer_dirs.values()}))
        if roots:
            env['PYTHONPATH'] = roots if not env.get('PYTHONPATH') else f'{roots}{os.pathsep}{env["PYTHONPATH"]}'
        if extra:
            env.update({key: str(value) for key, value in extra.items()})
        return env
