# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import os
from pathlib import Path

from ..db import DB
from ..docker import DockerRuntime
from ..repro import bugs as repro_bugs
from .common import run_parallel_jobs
from .models import DEFAULT_CRASH_BATCH_SIZE, CrashBatchTask, SnapshotTickPlan


class SnapshotCrashRunner:
    '''Run crash reproduction for snapshot ticks.'''

    def __init__(self, *, docker_runtime: DockerRuntime) -> None:
        self.docker_runtime = docker_runtime

    def process(
        self,
        *,
        db: DB,
        db_path: Path,
        run_id: str,
        repro_logs_dir: Path,
        tick_idx: int,
        jobs: int,
        plan: SnapshotTickPlan,
    ) -> None:
        '''Process every crash reproduction task scheduled for a snapshot tick.'''
        batch_tasks = self._build_batch_tasks(plan)
        run_parallel_jobs(
            jobs=jobs,
            total=len(batch_tasks),
            desc=f"Snapshot {tick_idx} crashes",
            position=1,
            leave=False,
            submit_jobs=lambda executor: [
                executor.submit(
                    self._bugs_one_repro,
                    db_path=db_path,
                    run_id=run_id,
                    task=task,
                    repro_logs_dir=repro_logs_dir,
                )
                for task in batch_tasks
            ],
        )
        if plan.crash_tasks:
            db.commit()

    def _bugs_one_repro(
        self,
        *,
        db_path: Path,
        run_id: str,
        task: CrashBatchTask,
        repro_logs_dir: Path | None,
    ) -> None:
        db = DB.open(db_path)
        try:
            repro_bugs.reproduce_new_crashes(
                db=db,
                docker_runtime=self.docker_runtime,
                run_id=run_id,
                trial=task.trial,
                snapshot_id=task.snapshot_id,
                ts=task.ts,
                snapshot_crashes_dir=task.snapshot_crashes_dir,
                new_crash_files=task.new_crash_files,
                repro_logs_dir=repro_logs_dir,
                jobs=1,
            )
        finally:
            db.close()

    @staticmethod
    def _build_batch_tasks(plan: SnapshotTickPlan) -> list[CrashBatchTask]:
        batch_tasks: list[CrashBatchTask] = []
        for task in plan.crash_tasks:
            for batch_index, batch in enumerate(_chunks(task.new_crash_files, DEFAULT_CRASH_BATCH_SIZE)):
                batch_tasks.append(
                    CrashBatchTask(
                        trial=task.trial,
                        snapshot_id=task.snapshot_id,
                        ts=task.ts,
                        snapshot_crashes_dir=task.snapshot_crashes_dir,
                        new_crash_files=batch,
                        batch_index=batch_index,
                    )
                )
        return batch_tasks


def _chunks(items, size: int):
    for index in range(0, len(items), size):
        yield items[index:index + size]
