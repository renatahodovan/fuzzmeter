# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import logging
import os
import shutil
import sys
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from typing import Iterator
from typing import Literal

from ..db import DB

LOG = logging.getLogger(__name__)

OutputFileKind = Literal['corpus', 'crashes']


@dataclass(frozen=True)
class DetectedFile:
    '''Describe one new or changed fuzzer output file.'''

    kind: OutputFileKind
    rel_path: str
    db_rel_path: str
    abs_src: Path
    mtime_ns: int


def detect_new_files(
    db: DB,
    *,
    kind: OutputFileKind,
    trial_row_id: int,
    src_root: Path,
    start_ts: int,
    end_ts: int,
    replay_time_fn: Callable[[str], int | None],
) -> list[DetectedFile]:
    '''Detect fuzzer output files whose update time falls in the tick interval.'''
    if not src_root.exists():
        return []
    detected: list[DetectedFile] = []
    start_mtime_ns = int(start_ts) * 1_000_000_000
    end_mtime_ns = int(end_ts) * 1_000_000_000

    for path, rel_path, stat, mtime_ns in iter_visible_files_in_time_range(
        src_root,
        start_mtime_ns=start_mtime_ns,
        end_mtime_ns=end_mtime_ns,
        replay_time_fn=replay_time_fn,
    ):
        db_rel_path = _db_rel_path(rel_path)
        detected.append(
            DetectedFile(
                kind=kind,
                rel_path=str(rel_path).replace('\\', '/'),
                db_rel_path=db_rel_path,
                abs_src=path,
                mtime_ns=mtime_ns,
            )
        )

    LOG.debug('Detected %d new/changed %s files in %s from %s', 
              len(detected), kind, src_root, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_ts)))
    return detected


def iter_visible_files_in_time_range(
    root: str | Path,
    *,
    start_mtime_ns: int,
    end_mtime_ns: int,
    replay_time_fn: Callable[[str], int | None] | None = None,
) -> Iterator[tuple[Path, Path, os.stat_result, int]]:
    '''Yield visible regular files under root whose effective mtime is in range.'''
    stack: list[tuple[str, str]] = [(os.fspath(root), '')]
    while stack:
        directory, rel_dir = stack.pop()

        with os.scandir(directory) as entries:
            for entry in entries:
                name = entry.name
                if name.startswith('.'):
                    continue
                rel_path = name if not rel_dir else f'{rel_dir}/{name}'
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append((entry.path, rel_path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue

                mtime_ns = None
                if replay_time_fn:
                    mtime_ns = replay_time_fn(entry.path)

                if mtime_ns is None:
                    mtime_ns = _file_update_time_ns(stat)

                if start_mtime_ns <= mtime_ns <= end_mtime_ns:
                    yield Path(entry.path), Path(rel_path), stat, mtime_ns


def _file_update_time_ns(stat_result: os.stat_result) -> int:
    mtime_ns = int(stat_result.st_mtime_ns)
    birthtime = getattr(stat_result, 'st_birthtime', None)
    if birthtime is None:
        return mtime_ns
    try:
        birthtime_ns = int(float(birthtime) * 1_000_000_000)
    except (TypeError, ValueError):
        return mtime_ns
    return max(mtime_ns, birthtime_ns)


def copy_into_snapshot(new_files: list[DetectedFile], *, snap_dir: Path, subdir: str) -> int:
    '''Link detected files into a snapshot subdirectory and return the linked/copied count.'''
    if not new_files:
        return 0

    dst_root = snap_dir / subdir
    dst_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    for new_file in new_files:
        dst = dst_root / new_file.rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            _materialize_snapshot_file(new_file.abs_src, dst)
        except OSError:
            continue
        copied += 1
    return copied


def _materialize_snapshot_file(src: Path, dst: Path) -> None:
    '''Prefer no-copy snapshot materialization, falling back to a real copy.'''
    try:
        os.link(src, dst)
        return
    except OSError:
        pass

    if _clone_file(src, dst):
        os.chmod(dst, dst.stat().st_mode | 0o444)
        return

    shutil.copy2(src, dst)
    os.chmod(dst, dst.stat().st_mode | 0o444)


def _clone_file(src: Path, dst: Path) -> bool:
    '''Best-effort copy-on-write clone for cross-directory snapshots.'''
    if sys.platform == 'darwin':
        try:
            import ctypes

            libc = ctypes.CDLL('libc.dylib', use_errno=True)
            return int(libc.clonefile(str(src).encode(), str(dst).encode(), 0)) == 0
        except Exception:
            return False

    if sys.platform.startswith('linux'):
        try:
            import fcntl

            ficlone = 0x40049409
            with src.open('rb') as src_handle:
                with dst.open('wb') as dst_handle:
                    fcntl.ioctl(dst_handle.fileno(), ficlone, src_handle.fileno())
            shutil.copystat(src, dst, follow_symlinks=True)
            return True
        except Exception:
            try:
                dst.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    return False


def _db_rel_path(rel_path: Path) -> str:
    return b'/'.join(os.fsencode(part) for part in rel_path.parts).hex()
