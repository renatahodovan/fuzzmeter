# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Read the effective build settings out of a benchmark Dockerfile."""

from __future__ import annotations

import re
import shlex

from pathlib import Path, PurePosixPath

DOCKER_ENV_RE = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


def benchmark_workdir(benchmark_dir: Path) -> str:
    path = benchmark_dir / 'Dockerfile'
    env = {'OUT': '/out', 'SRC': '/src', 'WORK': '/work'}
    workdir = env['SRC']
    if not path.is_file():
        return workdir

    for raw_line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if not line:
            continue
        instruction, _, value = line.partition(' ')
        instruction = instruction.upper()
        value = value.strip()
        if instruction == 'ENV':
            _update_docker_env(env, value)
        elif instruction == 'WORKDIR':
            workdir = _resolve_workdir(value, env, workdir)
    return workdir


def _update_docker_env(env: dict[str, str], value: str) -> None:
    try:
        parts = shlex.split(value)
    except ValueError:
        return
    if len(parts) == 2 and '=' not in parts[0]:
        env[parts[0]] = _expand_docker_env(parts[1], env)
        return
    for part in parts:
        key, sep, raw_value = part.partition('=')
        if sep and key:
            env[key] = _expand_docker_env(raw_value, env)


def _resolve_workdir(value: str, env: dict[str, str], current: str) -> str:
    try:
        parts = shlex.split(value)
    except ValueError:
        parts = []
    raw_workdir = parts[0] if parts else value
    workdir = _expand_docker_env(raw_workdir, env)
    if not workdir.startswith('/'):
        workdir = str(PurePosixPath(current) / workdir)
    return str(PurePosixPath(workdir))


def _expand_docker_env(value: str, env: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return env.get(match.group(1) or match.group(2) or '', match.group(0))

    return DOCKER_ENV_RE.sub(replace, value)
