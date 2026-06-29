# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Resolve and validate run-local paths for the web interface.'''

from __future__ import annotations

from pathlib import Path


def resolve_run_dir(runs_root: Path, run_id: str) -> Path:
    '''Return a run directory path after preventing traversal outside the runs root.'''

    root = Path(runs_root).resolve()
    run_dir = (root / run_id).resolve()
    try:
        run_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError('invalid run path') from exc
    return run_dir


def require_run_dir(runs_root: Path, run_id: str) -> Path:
    '''Return an existing run directory or raise FileNotFoundError.'''

    run_dir = resolve_run_dir(runs_root, run_id)
    if not run_dir.is_dir():
        raise FileNotFoundError(str(run_dir))
    return run_dir


def resolve_run_file(runs_root: Path, run_id: str, relpath: str) -> Path:
    '''Return a run-local file path after preventing traversal outside the run.'''

    run_dir = resolve_run_dir(runs_root, run_id)
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


def require_run_file(runs_root: Path, run_id: str, relpath: str) -> Path:
    '''Return an existing run-local file or raise FileNotFoundError.'''

    full = resolve_run_file(runs_root, run_id, relpath)
    if not full.is_file():
        raise FileNotFoundError(str(full))
    return full
