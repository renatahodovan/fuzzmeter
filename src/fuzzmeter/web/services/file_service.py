# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Resolve and validate run-local paths for the web interface.'''

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def resolve_run_dir(run_dirs: Iterable[Path], run_id: str) -> Path:
    '''Return one configured run directory after validating its name.'''

    if run_id != Path(run_id).name or run_id in ('', '.', '..'):
        raise ValueError('invalid run path')
    for run_dir in run_dirs:
        resolved = Path(run_dir).resolve()
        if resolved.name == run_id:
            return resolved
    raise FileNotFoundError(run_id)


def require_run_dir(run_dirs: Iterable[Path], run_id: str) -> Path:
    '''Return an existing run directory or raise FileNotFoundError.'''

    run_dir = resolve_run_dir(run_dirs, run_id)
    if not run_dir.is_dir():
        raise FileNotFoundError(str(run_dir))
    return run_dir


def resolve_run_file(run_dirs: Iterable[Path], run_id: str, relpath: str) -> Path:
    '''Return a run-local file path after preventing traversal outside the run.'''

    run_dir = resolve_run_dir(run_dirs, run_id)
    rel = Path(relpath)
    if '..' in rel.parts:
        raise ValueError('invalid relative path')

    full = (run_dir / rel).resolve()
    try:
        full.relative_to(run_dir)
    except ValueError as exc:
        raise ValueError('invalid file path') from exc

    if full.is_dir():
        full = (full / 'index.html').resolve()
    return full


def require_run_file(run_dirs: Iterable[Path], run_id: str, relpath: str) -> Path:
    '''Return an existing run-local file or raise FileNotFoundError.'''

    full = resolve_run_file(run_dirs, run_id, relpath)
    if not full.is_file():
        raise FileNotFoundError(str(full))
    return full
