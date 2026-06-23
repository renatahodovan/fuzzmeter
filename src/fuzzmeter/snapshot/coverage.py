# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Run coverage measurement for snapshot corpus batches.'''

from __future__ import annotations

import shutil

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..db import DB, open_db
from ..db import snapshot as db_snapshot
from ..docker import DockerRuntime
from ..repro.coverage_measure import merge_coverage_outputs, replay_coverage_batch
from ..repro.coverage_state import (
    apply_snapshot_summary,
    collect_inputs,
    load_coverage_summary,
    trial_coverage_root,
)
from ..repro.coverage_trial import bootstrap_from_seed_baseline
from ..trial.models import TrialInstance
from .parallel import run_parallel_jobs
from .progress import SnapshotProgress
from .trial_snapshot import TrialCoverageSnapshot


DEFAULT_COVERAGE_BATCH_SIZE = 256


@dataclass(frozen=True)
class TrialCoverageSnapshotState:
    '''Store derived state needed to process one trial coverage snapshot.'''

    snapshot: TrialCoverageSnapshot
    state_dir: Path
    batch_profdata_paths: list[Path]


def process_snapshot_coverage(
    *,
    db: DB,
    db_path: Path,
    run_dir: Path,
    run_id: str,
    tick_idx: int,
    ts: int,
    jobs: int,
    snapshots: list[TrialCoverageSnapshot],
    campaign_trials: Sequence[TrialInstance],
    docker_runtime: DockerRuntime,
    write_export: bool,
    progress: SnapshotProgress | None = None,
) -> None:
    '''Process every coverage snapshot scheduled for a tick.'''
    coverage_states: list[TrialCoverageSnapshotState] = []
    coverage_batches: list[tuple[TrialCoverageSnapshotState, int, list[Path]]] = []
    for snapshot in snapshots:
        trial = snapshot.trial
        corpus_dir = snapshot.snapshot_dir / 'corpus'
        latest_root = (
            trial_coverage_root(run_dir, trial.config.fuzzer, trial.config.benchmark, trial.config.fuzz_target)
            / trial.config.trial_key
        )
        state_dir = trial.layout.trial_dir / 'coverage_state'
        latest_root.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)

        if not (state_dir / 'merged.profdata').exists():
            bootstrap_from_seed_baseline(run_dir=run_dir, trial=trial, latest_root=latest_root, state_dir=state_dir)

        inputs = collect_inputs(corpus_dir) if corpus_dir.exists() else []
        if not inputs:
            apply_snapshot_summary(
                db=db,
                run_dir=run_dir,
                snapshot_id=snapshot.snapshot_id,
                out_root=latest_root,
                summary=load_coverage_summary(latest_root / 'summary.json'),
            )
            db.commit()
            continue

        input_batches = [
            inputs[index:index + DEFAULT_COVERAGE_BATCH_SIZE]
            for index in range(0, len(inputs), DEFAULT_COVERAGE_BATCH_SIZE)
        ]
        batch_root = state_dir / f'_batches_{snapshot.snapshot_id}'
        batch_root.mkdir(parents=True, exist_ok=True)
        coverage_state = TrialCoverageSnapshotState(
            snapshot=snapshot,
            state_dir=state_dir,
            batch_profdata_paths=[batch_root / f'batch_{index:06d}.profdata' for index in range(len(input_batches))],
        )
        coverage_states.append(coverage_state)
        coverage_batches.extend((coverage_state, index, input_batch) for index, input_batch in enumerate(input_batches))

    if progress is not None:
        progress.start_coverage(tick_idx=tick_idx, total=len(coverage_batches), phase='Batch')

    run_parallel_jobs(
        jobs=jobs,
        total=len(coverage_batches),
        desc=f'#{tick_idx} snapshot coverage',
        position=1,
        leave=False,
        submit_jobs=lambda executor: [
            executor.submit(
                replay_coverage_batch,
                docker_runtime=docker_runtime,
                image=coverage_state.snapshot.trial.config.images.coverage,
                fuzz_target=coverage_state.snapshot.trial.config.fuzz_target,
                input_mode=coverage_state.snapshot.trial.config.fuzz_target_input_mode,
                inputs=input_batch,
                batch_profdata_path=coverage_state.batch_profdata_paths[index],
                diagnostics_dir=coverage_state.state_dir / f'_batch_diag_{coverage_state.snapshot.snapshot_id}' / f'{index:06d}',
            )
            for coverage_state, index, input_batch in coverage_batches
        ],
        progress_step=progress.step_coverage if progress is not None else None,
    )

    if progress is not None:
        progress.start_coverage(tick_idx=tick_idx, total=len(coverage_states), phase='Merge')

    run_parallel_jobs(
        jobs=jobs,
        total=len(coverage_states),
        desc=f'#{tick_idx} snapshot coverage merge',
        position=1,
        leave=False,
        submit_jobs=lambda executor: [
            executor.submit(
                merge_trial_coverage_outputs,
                docker_runtime=docker_runtime,
                db_path=db_path,
                run_dir=run_dir,
                coverage_state=coverage_state,
                write_export=write_export,
            )
            for coverage_state in coverage_states
        ],
        progress_step=progress.step_coverage if progress is not None else None,
    )
    if progress is not None:
        progress.idle_coverage()

    campaigns: dict[tuple[str, str, str], str] = {}
    for snapshot in snapshots:
        config = snapshot.trial.config
        campaigns[(config.fuzzer, config.benchmark, config.fuzz_target)] = config.images.coverage

    for (fuzzer, benchmark, fuzz_target), image in sorted(campaigns.items()):
        profile_inputs = []
        for trial in campaign_trials:
            if (
                trial.config.fuzzer != fuzzer
                or trial.config.benchmark != benchmark
                or trial.config.fuzz_target != fuzz_target
            ):
                continue
            profile_input = trial.layout.trial_dir / 'coverage_state' / 'merged.profdata'
            if profile_input.is_file() and profile_input.stat().st_size > 64:
                profile_inputs.append(profile_input)
        if not profile_inputs:
            continue

        agg_root = run_dir / 'coverage' / fuzzer / benchmark / fuzz_target / 'campaign'
        state_dir = agg_root / '_state'
        summary = merge_coverage_outputs(
            docker_runtime=docker_runtime,
            run_dir=run_dir,
            image=image,
            out_root=agg_root,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            state_dir=state_dir,
            work_dir=state_dir / '_work',
            profile_inputs=profile_inputs,
            write_coverage_sets=write_export,
        )

        coverage_sets_json_rel = None
        coverage_sets = agg_root / 'coverage-sets.json'
        if coverage_sets.exists():
            coverage_sets_tick = agg_root.parent / 'campaign_snapshots' / f'{tick_idx:06d}' / 'coverage-sets.json'
            coverage_sets_tick.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(coverage_sets, coverage_sets_tick)
            coverage_sets_json_rel = str(coverage_sets_tick.relative_to(run_dir))

        html_index = agg_root / 'html' / 'index.html'
        agg_id = db_snapshot.upsert_agg_snapshot(
            db,
            run_id=run_id,
            fuzzer=fuzzer,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            idx=tick_idx,
            ts=ts,
        )
        db_snapshot.update_agg_snapshot_coverage(
            db,
            agg_snapshot_id=agg_id,
            coverage_html_dir=str(html_index.relative_to(run_dir)) if html_index.exists() else None,
            summary=summary,
            coverage_sets_json_rel=coverage_sets_json_rel,
        )
    db.commit()


def merge_trial_coverage_outputs(
    *,
    docker_runtime: DockerRuntime,
    db_path: Path,
    run_dir: Path,
    coverage_state: TrialCoverageSnapshotState,
    write_export: bool,
) -> None:
    '''Merge one trial snapshot's batch coverage and store its summary.'''
    snapshot = coverage_state.snapshot
    trial_config = snapshot.trial.config
    out_root = trial_coverage_root(
        run_dir,
        trial_config.fuzzer,
        trial_config.benchmark,
        trial_config.fuzz_target,
    ) / trial_config.trial_key
    summary = merge_coverage_outputs(
        docker_runtime=docker_runtime,
        run_dir=run_dir,
        image=trial_config.images.coverage,
        out_root=out_root,
        benchmark=trial_config.benchmark,
        fuzz_target=trial_config.fuzz_target,
        state_dir=coverage_state.state_dir,
        work_dir=coverage_state.state_dir / f'_tmp_{snapshot.snapshot_id}_final',
        profile_inputs=coverage_state.batch_profdata_paths,
        render_html=False,
        write_coverage_sets=write_export,
    )
    with open_db(db_path) as worker_db:
        apply_snapshot_summary(
            db=worker_db,
            run_dir=run_dir,
            snapshot_id=snapshot.snapshot_id,
            out_root=out_root,
            summary=summary,
        )
