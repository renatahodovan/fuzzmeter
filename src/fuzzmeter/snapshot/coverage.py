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
from pathlib import Path

from ..config import CampaignCase
from ..db import DB
from ..db import snapshot as db_snapshot
from ..docker import DockerRuntime
from ..repro.coverage_measure import (
    CoverageBatch,
    build_coverage_batches,
    coverage_measurement_context,
    execute_coverage_batches,
    merge_coverage_outputs,
)
from ..repro.coverage_state import (
    apply_snapshot_summary,
    collect_inputs,
    load_coverage_summary,
    load_measurement_provenance,
    seed_coverage_root,
    trial_coverage_root,
)
from ..trial.models import TrialInstance
from .parallel import run_parallel_jobs
from .progress import SnapshotProgress
from .trial_snapshot import TrialCoverageSnapshot


def process_snapshot_coverage(
    *,
    db: DB,
    run_dir: Path,
    run_id: str,
    tick_idx: int,
    ts: int,
    jobs: int,
    coverage_jobs: int | None = None,
    snapshots: list[TrialCoverageSnapshot],
    campaign_trials: Sequence[TrialInstance],
    docker_runtime: DockerRuntime,
    write_export: bool,
    progress: SnapshotProgress | None = None,
) -> None:
    '''Process every coverage snapshot scheduled for a tick.'''
    coverage_jobs = jobs if coverage_jobs is None else coverage_jobs

    # Plan every trial batch before sharing the coverage execution pool.
    measurements: list[tuple[TrialCoverageSnapshot, list[CoverageBatch]]] = []
    coverage_batches: list[CoverageBatch] = []
    for snapshot in snapshots:
        trial = snapshot.trial
        corpus_dir = snapshot.snapshot_dir / 'corpus'
        latest_root = (
            trial_coverage_root(run_dir, trial.config.case)
            / trial.config.trial_key
        )
        state_dir = trial.layout.snapshots_dir / '.state' / 'coverage'
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
                carried_forward=True,
            )
            db.commit()
            continue

        batches = build_coverage_batches(
            image=trial.config.case.images.coverage,
            fuzz_target=trial.config.fuzz_target.fuzz_target,
            input_mode=trial.config.fuzz_target.input_mode,
            inputs=inputs,
            artifact_dir=snapshot.snapshot_dir / '.artifacts' / 'coverage',
            timeout_s=trial.config.fuzz_target.target_timeout_s * 2,
            container_prefix=f'fm-{run_id}-cov-{tick_idx}-{trial.config.trial_key}',
            trial_key=trial.config.trial_key,
        )
        measurements.append((snapshot, batches))
        coverage_batches.extend(batches)

    if progress is not None:
        progress.start_coverage(tick_idx=tick_idx, total=len(coverage_batches), phase='Batch')

    # Execute all trial batches under one global coverage budget.
    if coverage_batches:
        execute_coverage_batches(
            docker_runtime=docker_runtime,
            batches=coverage_batches,
            jobs=coverage_jobs,
            on_batch_done=progress.step_coverage if progress is not None else None,
        )

    if progress is not None:
        progress.start_coverage(tick_idx=tick_idx, total=len(measurements), phase='Merge')

    # Merge trials in parallel after every coverage batch has finished.
    summaries = run_parallel_jobs(
        jobs=jobs,
        total=len(measurements),
        desc=f'#{tick_idx} snapshot coverage merge',
        position=1,
        leave=False,
        submit_jobs=lambda executor: [
            executor.submit(
                merge_trial_coverage_outputs,
                docker_runtime=docker_runtime,
                run_dir=run_dir,
                snapshot=snapshot,
                batches=batches,
                write_export=write_export,
            )
            for snapshot, batches in measurements
        ],
        progress_step=progress.step_coverage if progress is not None else None,
    )

    # Persist trial summaries only after every merge has succeeded.
    for (snapshot, _), summary in zip(measurements, summaries, strict=True):
        trial_config = snapshot.trial.config
        apply_snapshot_summary(
            db=db,
            run_dir=run_dir,
            snapshot_id=snapshot.snapshot_id,
            out_root=trial_coverage_root(run_dir, trial_config.case) / trial_config.trial_key,
            summary=summary,
        )
    if progress is not None:
        progress.idle_coverage()

    campaigns: dict[tuple[str, str, str], CampaignCase] = {}
    for snapshot in snapshots:
        case = snapshot.trial.config.case
        campaigns[(case.fuzzer.id, case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target)] = case

    for (fuzzer, benchmark, fuzz_target), case in sorted(campaigns.items()):
        profile_inputs = []
        for trial in campaign_trials:
            if trial.config.case is not case:
                continue
            profile_input = trial.layout.snapshots_dir / '.state' / 'coverage' / 'merged.profdata'
            if profile_input.is_file() and profile_input.stat().st_size > 64:
                profile_inputs.append(profile_input)
        if not profile_inputs:
            continue

        campaign_trial_keys = {
            trial.config.trial_key
            for trial in campaign_trials
            if trial.config.case is case
        }
        campaign_batches = [
            batch
            for _, batches in measurements
            for batch in batches
            if batch.trial_key in campaign_trial_keys
        ]

        agg_root = run_dir / 'coverage' / fuzzer / benchmark / fuzz_target / 'campaign'
        state_dir = agg_root / '_state'
        summary = merge_coverage_outputs(
            docker_runtime=docker_runtime,
            run_dir=run_dir,
            case=case,
            out_root=agg_root,
            state_dir=state_dir,
            work_dir=state_dir / '_work',
            profile_inputs=profile_inputs,
            write_coverage_sets=write_export,
            container_name=f'fm-{run_id}-cov-{tick_idx}-{fuzzer}-{benchmark}-{fuzz_target}-campaign',
            measurement_context=coverage_measurement_context(
                batches=campaign_batches,
                image=case.images.coverage,
                snapshot_tick=tick_idx,
                repetitions=len(profile_inputs),
            ),
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
            coverage=db_snapshot.CoverageSummary.from_mapping(
                coverage_html_dir=str(html_index.relative_to(run_dir)) if html_index.exists() else None,
                summary=summary,
            ),
            coverage_sets_json_rel=coverage_sets_json_rel,
            measurement_provenance=load_measurement_provenance(
                agg_root / 'measurement-provenance.json'
            ),
        )
    db.commit()


def merge_trial_coverage_outputs(
    *,
    docker_runtime: DockerRuntime,
    run_dir: Path,
    snapshot: TrialCoverageSnapshot,
    batches: list[CoverageBatch],
    write_export: bool,
) -> dict:
    '''Merge one trial snapshot's batch coverage and return its summary.'''
    trial_config = snapshot.trial.config
    state_dir = snapshot.trial.layout.snapshots_dir / '.state' / 'coverage'
    out_root = trial_coverage_root(run_dir, trial_config.case) / trial_config.trial_key
    return merge_coverage_outputs(
        docker_runtime=docker_runtime,
        run_dir=run_dir,
        case=trial_config.case,
        out_root=out_root,
        state_dir=state_dir,
        work_dir=snapshot.snapshot_dir / '.artifacts' / 'coverage' / 'merge-work',
        profile_inputs=[batch.profdata_path for batch in batches],
        render_html=False,
        write_coverage_sets=write_export,
        container_name=(
            f'fm-{docker_runtime.run_id or "run"}-cov-{snapshot.tick_idx}-'
            f'{trial_config.trial_key}-merge'
        ),
        trial_key=trial_config.trial_key,
        measurement_context=coverage_measurement_context(
            batches=batches,
            image=trial_config.case.images.coverage,
            snapshot_tick=snapshot.tick_idx,
            repetitions=1,
        ),
    )


def bootstrap_from_seed_baseline(
    *,
    run_dir: Path,
    trial: TrialInstance,
    latest_root: Path,
    state_dir: Path,
) -> None:
    '''Copy seed baseline coverage state into an empty trial coverage state.'''
    base_root = seed_coverage_root(run_dir, trial.config.case)
    baseline_profdata = base_root / '_state' / 'merged.profdata'

    if not (base_root / 'summary.json').exists():
        return

    if not (state_dir / 'merged.profdata').exists() and baseline_profdata.exists():
        state_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(baseline_profdata, state_dir / 'merged.profdata')

    latest_root.parent.mkdir(parents=True, exist_ok=True)
    for name in (
        'summary.json',
        'coverage-sets.json',
        'measurement-provenance.json',
        'input_exec_diagnostics.json',
    ):
        src = base_root / name
        dst = latest_root / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
