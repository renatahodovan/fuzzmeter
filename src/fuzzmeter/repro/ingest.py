# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Detect and materialize newly visible fuzzer output files for snapshots.'''

from __future__ import annotations

import logging
import os
import shutil
import sys
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ..docker import DockerRuntime
from ..fuzzers import HookRunner, HookSpec

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectedFile:
    '''Describe one snapshot input file and its logical timestamp.'''

    rel_path: str
    abs_src: Path
    mtime_ns: int


def detect_new_files(
    *,
    kind: str,
    src_root: Path,
    start_ts: int,
    end_ts: int,
) -> list[DetectedFile]:
    '''Detect fuzzer output files whose update time falls in the tick interval.'''
    if not src_root.exists():
        return []
    detected: list[DetectedFile] = []
    start_mtime_ns = start_ts * 1_000_000_000
    end_mtime_ns = end_ts * 1_000_000_000

    for path, rel_path, mtime_ns in iter_visible_files_in_time_range(
        src_root,
        start_mtime_ns=start_mtime_ns,
        end_mtime_ns=end_mtime_ns,
    ):
        detected.append(
            DetectedFile(
                rel_path=rel_path,
                abs_src=path,
                mtime_ns=mtime_ns,
            )
        )

    LOG.debug(
        'Detected %d new/changed %s files in %s from %s',
        len(detected),
        kind,
        src_root,
        time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_ts)),
    )
    return detected


def prepare_snapshot_inputs(
    *,
    docker_runtime: DockerRuntime,
    snapshot_dir: Path,
    input_dir: Path,
    input_files: list[DetectedFile],
    snapshot_preprocess: Path | None,
    benchmark: str,
    fuzz_target: str,
    fuzzer: str,
    runner_image: str,
    repo_root: Path,
    jobs: int | None = None,
) -> list[Path]:
    '''Copy snapshot inputs and optionally run the snapshot preprocess hook on them.'''
    if not input_files:
        return []

    input_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for input_file in input_files:
        dst = input_dir / input_file.rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            _materialize_snapshot_file(input_file.abs_src, dst)
            copied.append(dst)
        except OSError:
            continue

    if snapshot_preprocess is None:
        return copied

    HookRunner(docker_runtime=docker_runtime).run(
        HookSpec(
            name='snapshot_preprocess',
            script=snapshot_preprocess,
            env={
                'FM_SNAPSHOT_DIR': str(snapshot_dir),
                'FM_SNAPSHOT_INPUT_DIR': str(input_dir),
                'FM_BENCHMARK': benchmark,
                'FM_FUZZ_TARGET': fuzz_target,
                'FM_FUZZER': fuzzer,
                'FM_RUNNER_IMAGE': runner_image,
                'FM_REPO_ROOT': str(repo_root),
                'FM_JOBS': str(max(1, int(jobs or 1))),
            },
            cwd=snapshot_dir,
        )
    )
    return [path for path in input_dir.rglob('*') if path.is_file()]


def iter_visible_files_in_time_range(
    root: str | Path,
    *,
    start_mtime_ns: int,
    end_mtime_ns: int,
) -> Iterator[tuple[Path, str, int]]:
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

                mtime_ns = _file_update_time_ns(stat)
                if start_mtime_ns < mtime_ns <= end_mtime_ns:
                    yield Path(entry.path), rel_path, mtime_ns


def _file_update_time_ns(stat_result: os.stat_result) -> int:
    mtime_ns = stat_result.st_mtime_ns
    birthtime = getattr(stat_result, 'st_birthtime', None)
    if birthtime is None:
        return mtime_ns
    try:
        birthtime_ns = int(float(birthtime) * 1_000_000_000)
    except (TypeError, ValueError):
        return mtime_ns
    return max(mtime_ns, birthtime_ns)


def _materialize_snapshot_file(src: Path, dst: Path) -> None:
    '''Prefer no-copy snapshot materialization, falling back to a real copy.'''
    try:
        os.link(src, dst)
        return
    except OSError:
        pass

    if _clone_file(src, dst):
        os.chmod(dst, dst.stat().st_mode | 0o444)
    else:
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
