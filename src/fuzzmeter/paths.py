# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Resolve packaged resources and persistent run artifact paths.'''

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any


def docker_resources() -> Any:
    '''Return the packaged Docker resource directory.'''

    return resources.files('fuzzmeter').joinpath('resources', 'docker')


def entrypoint_resources() -> Any:
    '''Return the packaged container entrypoint resource directory.'''

    return resources.files('fuzzmeter').joinpath('resources', 'entrypoints')


def instrumentation_resources() -> Any:
    '''Return the packaged instrumentation resource directory.'''

    return resources.files('fuzzmeter').joinpath('resources', 'instrumentation')


def run_fuzzer_resources_root(run_dir: Path) -> Path:
    '''Return the persistent root containing copied fuzzer resources.'''

    return Path(run_dir) / 'fuzzer_resources'


def resolve_run_fuzzer_dirs(run_dir: Path) -> dict[str, Path]:
    '''Resolve copied fuzzer definitions from a persistent run artifact.'''

    fuzzer_dirs: dict[str, Path] = {}
    contexts_root = run_fuzzer_resources_root(run_dir) / 'run'
    if not contexts_root.is_dir():
        return fuzzer_dirs
    for context_root in sorted(contexts_root.iterdir()):
        if not context_root.is_dir():
            continue
        for fuzzer_dir in sorted(context_root.iterdir()):
            if fuzzer_dir.is_dir():
                fuzzer_dirs.setdefault(fuzzer_dir.name, fuzzer_dir)
    return fuzzer_dirs
