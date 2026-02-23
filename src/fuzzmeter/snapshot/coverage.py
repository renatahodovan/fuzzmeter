# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..db import DB
from ..docker import DockerRuntime
from ..repro.coverage_measure import finalize_coverage, run_coverage_batch
from ..repro.coverage_state import (
    apply_snapshot_summary,
    collect_inputs,
    load_coverage_summary,
    trial_coverage_root,
)
from ..repro.coverage_trial import bootstrap_from_seed_baseline
from .common import run_parallel_jobs
from .models import (
    DEFAULT_COVERAGE_BATCH_SIZE,
    CoverageBatchTask,
    CoverageInprocessTask,
    CoverageTask,
    SnapshotTickPlan,
)


@dataclass(frozen=True)
class _PreparedCoverageTask:
    task: CoverageTask
    latest_root: Path
    state_dir: Path
    inputs: list[Path]
    batch_profdata_paths: list[Path]


class SnapshotCoverageRunner:
    '''Run per-trial coverage measurement for snapshot ticks.'''

    def __init__(self, *, docker_runtime: DockerRuntime, export_every_ticks: int = 1) -> None:
        self.docker_runtime = docker_runtime
        self.export_every_ticks = int(export_every_ticks)

    def process(
        self,
        *,
        db: DB,
        db_path: Path,
        run_dir: Path,
        tick_idx: int,
        jobs: int,
        plan: SnapshotTickPlan,
    ) -> None:
        '''Process every coverage task scheduled for a snapshot tick.'''
        prepared_tasks, batch_tasks = self._prepare_batch_tasks(
            db=db,
            run_dir=run_dir,
            coverage_tasks=plan.coverage_tasks,
        )

        run_parallel_jobs(
            jobs=jobs,
            total=len(batch_tasks),
            desc=f'Snapshot {tick_idx} coverage',
            position=1,
            leave=False,
            submit_jobs=lambda executor: [
                executor.submit(
                    self._run_batch_task,
                    task=task,
                )
                for task in batch_tasks
            ],
        )

        run_parallel_jobs(
            jobs=jobs,
            total=len(prepared_tasks),
            desc=f'Snapshot {tick_idx} coverage reduce',
            position=1,
            leave=False,
            submit_jobs=lambda executor: [
                executor.submit(
                    self._finalize_prepared_task,
                    db_path=db_path,
                    run_dir=run_dir,
                    prepared=prepared,
                )
                for prepared in prepared_tasks
            ],
        )
        if plan.coverage_tasks:
            db.commit()

    def _prepare_batch_tasks(
        self,
        *,
        db: DB,
        run_dir: Path,
        coverage_tasks: list[CoverageTask],
    ) -> tuple[list[_PreparedCoverageTask], list[CoverageInprocessTask | CoverageBatchTask]]:
        prepared_tasks: list[_PreparedCoverageTask] = []
        batch_tasks: list[CoverageInprocessTask | CoverageBatchTask] = []
        for task in coverage_tasks:
            prepared = self._prepare_one_task(db=db, run_dir=run_dir, task=task)
            if prepared is None:
                continue
            prepared_tasks.append(prepared)
            batch_tasks.extend(self._build_batches(prepared))
        return prepared_tasks, batch_tasks

    def _prepare_one_task(self, *, db: DB, run_dir: Path, task: CoverageTask) -> _PreparedCoverageTask | None:
        trial = task.trial
        corpus_dir = Path(task.snap_dir) / 'corpus'
        latest_root = trial_coverage_root(run_dir, trial.fuzzer, trial.benchmark, trial.fuzz_target) / trial.trial_id
        latest_root.mkdir(parents=True, exist_ok=True)
        summary_path = latest_root / 'summary.json'
        state_dir = trial.trial_root / 'coverage_state'
        state_dir.mkdir(parents=True, exist_ok=True)

        if not (state_dir / 'merged.profdata').exists():
            bootstrap_from_seed_baseline(
                run_dir=run_dir,
                trial=trial,
                latest_root=latest_root,
                state_dir=state_dir,
            )

        if not corpus_dir.exists() or not any(path.is_file() for path in corpus_dir.rglob('*')):
            summary = load_coverage_summary(summary_path)
            apply_snapshot_summary(db=db, run_dir=run_dir, snapshot_id=task.snapshot_id, out_root=latest_root, summary=summary)
            db.commit()
            return None

        inputs = collect_inputs(corpus_dir)
        if not inputs:
            return None

        batch_root = state_dir / f'_batches_{task.snapshot_id}'
        batch_root.mkdir(parents=True, exist_ok=True)
        batch_profdata_paths = [
            batch_root / f'batch_{index:06d}.profdata'
            for index, _ in enumerate(_chunks(inputs, DEFAULT_COVERAGE_BATCH_SIZE))
        ]
        return _PreparedCoverageTask(
            task=task,
            latest_root=latest_root,
            state_dir=state_dir,
            inputs=inputs,
            batch_profdata_paths=batch_profdata_paths,
        )

    @staticmethod
    def _build_batches(prepared: _PreparedCoverageTask) -> list[CoverageInprocessTask | CoverageBatchTask]:
        task = prepared.task
        batches: list[CoverageInprocessTask | CoverageBatchTask] = []
        use_inprocess = task.trial.input_mode == 'in_process'
        for index, input_batch in enumerate(_chunks(prepared.inputs, DEFAULT_COVERAGE_BATCH_SIZE)):
            task_cls = CoverageInprocessTask if use_inprocess else CoverageBatchTask
            batches.append(
                task_cls(
                    trial=task.trial,
                    snapshot_id=task.snapshot_id,
                    inputs=input_batch,
                    batch_index=index,
                    batch_profdata_path=prepared.batch_profdata_paths[index],
                    diagnostics_dir=prepared.state_dir / f'_batch_diag_{task.snapshot_id}' / f'{index:06d}',
                )
            )
        return batches

    def _run_batch_task(self, *, task: CoverageInprocessTask | CoverageBatchTask) -> None:
        run_coverage_batch(
            docker_runtime=self.docker_runtime,
            image=task.trial.coverage_image,
            fuzz_target=task.trial.fuzz_target,
            input_mode=task.trial.input_mode,
            inputs=task.inputs,
            batch_profdata_path=task.batch_profdata_path,
            diagnostics_dir=task.diagnostics_dir,
        )

    def _finalize_prepared_task(
        self,
        *,
        db_path: Path,
        run_dir: Path,
        prepared: _PreparedCoverageTask,
    ) -> None:
        db = DB.open(db_path)
        try:
            task = prepared.task
            summary = finalize_coverage(
                docker_runtime=self.docker_runtime,
                run_dir=run_dir,
                image=task.trial.coverage_image,
                benchmark=task.trial.benchmark,
                fuzz_target=task.trial.fuzz_target,
                state_dir=prepared.state_dir,
                work_dir=prepared.state_dir / f'_tmp_{task.snapshot_id}_final',
                out_root=prepared.latest_root,
                profile_inputs=prepared.batch_profdata_paths,
                render_html=False,
                write_coverage_sets=self._should_write_export(task.tick_idx, task.render_heavy),
            )
            apply_snapshot_summary(
                db=db,
                run_dir=run_dir,
                snapshot_id=task.snapshot_id,
                out_root=prepared.latest_root,
                summary=summary,
            )
            db.commit()
        finally:
            db.close()

    def _should_write_export(self, tick_idx: int, render_heavy: bool) -> bool:
        if render_heavy:
            return True
        if self.export_every_ticks <= 0:
            return False
        return int(tick_idx) % int(self.export_every_ticks) == 0


def _chunks(items: list[Path], size: int) -> Iterable[list[Path]]:
    for index in range(0, len(items), size):
        yield items[index:index + size]
