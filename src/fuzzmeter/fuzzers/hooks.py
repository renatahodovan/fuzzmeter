# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Run fuzzer hook scripts with the configured campaign environment.'''

from __future__ import annotations

import logging
import os
import subprocess

from dataclasses import dataclass, field
from pathlib import Path

from ..docker import DockerRuntime

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class HookSpec:
    '''Describe one hook script invocation.'''

    name: str
    script: Path | None
    env: dict[str, str] = field(default_factory=dict)
    cwd: Path | None = None


class HookRunner:
    '''Run host-side fuzzer hook scripts.'''

    def __init__(self, *, docker_runtime: DockerRuntime) -> None:
        self.docker_runtime = docker_runtime

    def run(self, spec: HookSpec) -> None:
        '''Run a hook and log captured output when it fails.'''
        if spec.script is None:
            return

        script = self._resolve_script(spec.script)
        if not script.exists():
            raise FileNotFoundError(f'{spec.name} hook does not exist: {script}')

        cmd = ['python3', str(script)] if script.suffix == '.py' else [str(script)]
        result = subprocess.run(
            cmd,
            check=False,
            cwd=str(spec.cwd) if spec.cwd else None,
            env=self.docker_runtime.hook_env(spec.env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode == 0:
            if result.stdout:
                LOG.debug('%s hook output:\n%s', spec.name, result.stdout.rstrip())
            return
        if result.stdout:
            LOG.error('%s hook failed with output:\n%s', spec.name, result.stdout.rstrip())
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout)

    def _resolve_script(self, script: Path) -> Path:
        '''Resolve a hook script path relative to the repository root.'''
        return script if script.is_absolute() else (self.docker_runtime.repo_root / script)
