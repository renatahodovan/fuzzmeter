# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Detect and copy newly visible fuzzer output files for snapshots.'''

from __future__ import annotations

import concurrent.futures as cf
import logging
import os
import shutil
import sys
import time

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ..config import CampaignCase
from ..docker import DockerRuntime
from ..fuzzers import HookRunner, HookSpec

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectedFile:
    '''Describe one snapshot input file and its logical timestamp.'''

    rel_path: str
    abs_src: Path
    mtime_ns: int


@dataclass(frozen=True)
class InputSet:
    '''Describe the files and processing context of one collected input set.'''

    snapshot_dir: Path
    input_dir: Path
    input_files: tuple[DetectedFile, ...]
    snapshot_preprocess: Path | None
    case: CampaignCase


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


def prepare_input_sets(
    *,
    docker_runtime: DockerRuntime,
    input_sets: list[InputSet],
    jobs: int,
) -> list[list[Path]]:
    '''Copy collected input sets and run their preprocess hooks.'''
    if not input_sets:
        return []

    # Copy every input set before assigning preprocess capacity.
    with cf.ThreadPoolExecutor(max_workers=min(jobs, len(input_sets))) as executor:
        copy_futures = [
            executor.submit(
                _copy_snapshot_inputs,
                dst_dir=input_set.input_dir,
                input_files=list(input_set.input_files),
            )
            for input_set in input_sets
        ]
        prepared = [future.result() for future in copy_futures]

    preprocess_sets = [
        (index, input_set)
        for index, input_set in enumerate(input_sets)
        if input_set.snapshot_preprocess is not None and prepared[index]
    ]
    if not preprocess_sets:
        return prepared

    max_workers = min(jobs, len(preprocess_sets))
    # Give each input set one job, then favor sets with more remaining work.
    input_set_jobs = {index: 1 for index, _ in preprocess_sets}
    remaining_jobs = max(0, jobs - len(preprocess_sets))
    while remaining_jobs:
        expandable = [
            index
            for index, _ in preprocess_sets
            if input_set_jobs[index] < len(prepared[index])
        ]
        if not expandable:
            break
        selected = max(
            expandable,
            key=lambda index: len(prepared[index]) / input_set_jobs[index],
        )
        input_set_jobs[selected] += 1
        remaining_jobs -= 1

    runner = HookRunner(docker_runtime=docker_runtime)
    with cf.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                runner.run,
                HookSpec(
                    name='snapshot_preprocess',
                    script=input_set.snapshot_preprocess,
                    env=_snapshot_preprocess_env(
                        snapshot_dir=input_set.snapshot_dir,
                        input_dir=input_set.input_dir,
                        artifact_dir=(
                            input_set.snapshot_dir
                            / '.artifacts'
                            / 'preprocess'
                            / input_set.input_dir.name
                        ),
                        benchmark=input_set.case.fuzz_target.benchmark.name,
                        fuzz_target=input_set.case.fuzz_target.fuzz_target,
                        fuzzer=input_set.case.fuzzer.id,
                        runner_image=input_set.case.images.runner,
                        jobs=input_set_jobs[index],
                    ),
                    cwd=input_set.snapshot_dir,
                ),
            )
            for index, input_set in preprocess_sets
        ]
        for future in futures:
            future.result()

    # Re-scan hook outputs because preprocessing may add or remove files.
    for index, input_set in preprocess_sets:
        prepared[index] = sorted(
            path
            for path in input_set.input_dir.rglob('*')
            if path.is_file()
        )
    return prepared


def _copy_snapshot_inputs(*, dst_dir: Path, input_files: list[DetectedFile]) -> list[Path]:
    if not input_files:
        return []
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for input_file in input_files:
        dst = dst_dir / input_file.rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            _link_or_copy_snapshot_file(input_file.abs_src, dst)
            copied.append(dst)
        except OSError:
            continue

    failed = len(input_files) - len(copied)
    if failed:
        LOG.warning(
            'Could not copy %d of %d snapshot input files to %s.',
            failed,
            len(input_files),
            dst_dir,
        )
    return copied


def _snapshot_preprocess_env(
    *,
    snapshot_dir: Path,
    input_dir: Path,
    artifact_dir: Path,
    benchmark: str,
    fuzz_target: str,
    fuzzer: str,
    runner_image: str,
    jobs: int,
) -> dict[str, str]:
    return {
        'FM_SNAPSHOT_DIR': str(snapshot_dir),
        'FM_SNAPSHOT_INPUT_DIR': str(input_dir),
        'FM_SNAPSHOT_ARTIFACT_DIR': str(artifact_dir),
        'FM_BENCHMARK': benchmark,
        'FM_FUZZ_TARGET': fuzz_target,
        'FM_FUZZER': fuzzer,
        'FM_RUNNER_IMAGE': runner_image,
        'FM_JOBS': str(jobs),
    }


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


def _link_or_copy_snapshot_file(src: Path, dst: Path) -> None:
    '''Prefer a hard link or copy-on-write clone, falling back to a full copy.'''
    try:
        os.link(src, dst)
        return
    except OSError:
        pass

    if not _clone_file(src, dst):
        shutil.copy2(src, dst)
    dst.chmod(dst.stat().st_mode | 0o444)


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
            with src.open('rb') as src_handle, dst.open('wb') as dst_handle:
                fcntl.ioctl(dst_handle.fileno(), ficlone, src_handle.fileno())
            shutil.copystat(src, dst, follow_symlinks=True)
            return True
        except Exception:
            with suppress(OSError):
                dst.unlink(missing_ok=True)
            return False

    return False
