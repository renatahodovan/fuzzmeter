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

from ..config import CampaignCase
from ..db import DB, open_db
from ..db import snapshot as db_snapshot
from ..docker import DockerRuntime
from ..repro.coverage_measure import (
    CoverageBatch,
    build_coverage_replay_batches,
    coverage_measurement_context,
    merge_coverage_outputs,
    replay_coverage_batches,
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


@dataclass(frozen=True)
class TrialCoverageSnapshotState:
    '''Store derived state needed to process one trial coverage snapshot.'''

    snapshot: TrialCoverageSnapshot
    state_dir: Path
    batch_profdata_paths: list[Path]
    batches: list[CoverageBatch]


def process_snapshot_coverage(
    *,
    db: DB,
    db_path: Path,
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
    coverage_states: list[TrialCoverageSnapshotState] = []
    coverage_batches = []
    for snapshot in snapshots:
        trial = snapshot.trial
        corpus_dir = snapshot.snapshot_dir / 'corpus'
        latest_root = (
            trial_coverage_root(run_dir, trial.config.case)
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
                carried_forward=True,
            )
            db.commit()
            continue

        batch_profdata_paths, batches = build_coverage_replay_batches(
            image=trial.config.case.images.coverage,
            fuzz_target=trial.config.fuzz_target.fuzz_target,
            input_mode=trial.config.fuzz_target.input_mode,
            inputs=inputs,
            state_dir=state_dir,
            batch_tag=snapshot.snapshot_id,
            timeout_s=trial.config.fuzz_target.target_timeout_s * 2,
            container_prefix=f'fm-{run_id}-cov-{tick_idx}-{trial.config.trial_key}',
            trial_key=trial.config.trial_key,
        )
        coverage_state = TrialCoverageSnapshotState(
            snapshot=snapshot,
            state_dir=state_dir,
            batch_profdata_paths=batch_profdata_paths,
            batches=batches,
        )
        coverage_states.append(coverage_state)
        coverage_batches.extend(batches)

    if progress is not None:
        progress.start_coverage(tick_idx=tick_idx, total=len(coverage_batches), phase='Batch')

    if coverage_batches:
        replay_coverage_batches(
            docker_runtime=docker_runtime,
            batches=coverage_batches,
            jobs=coverage_jobs,
            on_batch_done=progress.step_coverage if progress is not None else None,
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

    campaigns: dict[tuple[str, str, str], CampaignCase] = {}
    for snapshot in snapshots:
        case = snapshot.trial.config.case
        campaigns[(case.fuzzer.id, case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target)] = case

    for (fuzzer, benchmark, fuzz_target), case in sorted(campaigns.items()):
        profile_inputs = []
        for trial in campaign_trials:
            if trial.config.case is not case:
                continue
            profile_input = trial.layout.trial_dir / 'coverage_state' / 'merged.profdata'
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
            for coverage_state in coverage_states
            for batch in coverage_state.batches
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
    db_path: Path,
    run_dir: Path,
    coverage_state: TrialCoverageSnapshotState,
    write_export: bool,
) -> None:
    '''Merge one trial snapshot's batch coverage and store its summary.'''
    snapshot = coverage_state.snapshot
    trial_config = snapshot.trial.config
    out_root = trial_coverage_root(run_dir, trial_config.case) / trial_config.trial_key
    summary = merge_coverage_outputs(
        docker_runtime=docker_runtime,
        run_dir=run_dir,
        case=trial_config.case,
        out_root=out_root,
        state_dir=coverage_state.state_dir,
        work_dir=coverage_state.state_dir / f'_tmp_{snapshot.snapshot_id}_final',
        profile_inputs=coverage_state.batch_profdata_paths,
        render_html=False,
        write_coverage_sets=write_export,
        container_name=(
            f'fm-{docker_runtime.run_id or "run"}-cov-{snapshot.tick_idx}-'
            f'{trial_config.trial_key}-merge'
        ),
        trial_key=trial_config.trial_key,
        measurement_context=coverage_measurement_context(
            batches=coverage_state.batches,
            image=trial_config.case.images.coverage,
            snapshot_tick=snapshot.tick_idx,
            repetitions=1,
        ),
    )
    with open_db(db_path) as worker_db:
        apply_snapshot_summary(
            db=worker_db,
            run_dir=run_dir,
            snapshot_id=snapshot.snapshot_id,
            out_root=out_root,
            summary=summary,
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
