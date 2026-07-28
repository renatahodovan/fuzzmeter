# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Run crash reproduction work for snapshot batches.'''

from __future__ import annotations

from pathlib import Path

from ..docker import DockerRuntime
from ..repro import bugs as repro_bugs
from ..repro.ingest import DetectedFile
from .parallel import run_parallel_jobs
from .progress import SnapshotProgress
from .trial_snapshot import TrialCrashSnapshot

DEFAULT_CRASH_BATCH_SIZE = 64


def process_snapshot_crashes(
    *,
    db_path: Path,
    run_dir: Path,
    run_id: str,
    tick_idx: int,
    jobs: int,
    snapshots: list[TrialCrashSnapshot],
    docker_runtime: DockerRuntime,
    progress: SnapshotProgress | None = None,
) -> None:
    '''Process every crash snapshot scheduled for a tick.'''
    crash_batches: list[tuple[TrialCrashSnapshot, int, list[DetectedFile]]] = []
    for snapshot in snapshots:
        for batch_index, index in enumerate(range(0, len(snapshot.crash_files), DEFAULT_CRASH_BATCH_SIZE)):
            crash_batches.append((snapshot, batch_index, snapshot.crash_files[index:index + DEFAULT_CRASH_BATCH_SIZE]))

    if progress is not None:
        progress.start_crashes(tick_idx=tick_idx, total=len(crash_batches))

    run_parallel_jobs(
        jobs=jobs,
        total=len(crash_batches),
        desc=f'Snapshot {tick_idx} crashes',
        position=1,
        leave=False,
        submit_jobs=lambda executor: [
            executor.submit(
                repro_bugs.repro_crash_batch,
                db_path=db_path,
                docker_runtime=docker_runtime,
                run_id=run_id,
                trial=snapshot.trial,
                snapshot_id=snapshot.snapshot_id,
                snapshot_crashes_dir=snapshot.snapshot_dir / 'crashes',
                crash_tests=crash_tests,
                batch_index=batch_index,
                tick_idx=tick_idx,
                repro_logs_dir=run_dir / 'repro_logs',
            )
            for snapshot, batch_index, crash_tests in crash_batches
        ],
        progress_step=progress.step_crashes if progress is not None else None,
    )
    if progress is not None:
        progress.idle_crashes()
