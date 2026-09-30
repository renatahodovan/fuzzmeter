# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Prepare and measure seed corpora used by campaigns.'''

from __future__ import annotations

import concurrent.futures as cf
import logging
import shutil

from pathlib import Path

from ..config import CampaignCase, CampaignConfig
from ..db import open_db
from ..db.snapshot import SEED_BASELINE_IDX, CoverageSummary, update_agg_snapshot_coverage, upsert_agg_snapshot
from ..docker import DockerRuntime
from ..fuzzers import FuzzerLoader
from ..repro.coverage_measure import (
    CoverageBatch,
    build_coverage_batches,
    coverage_measurement_context,
    execute_coverage_batches,
    merge_coverage_outputs,
)
from ..repro.coverage_state import load_measurement_provenance, seed_coverage_root
from ..repro.ingest import DetectedFile, InputSet, prepare_input_sets
from ..trial.workspace import extract_seed_corpus_from_image

LOG = logging.getLogger(__name__)


def prepare_seed_corpora(
    *,
    campaign_config: CampaignConfig,
    run_dir: Path,
    docker_runtime: DockerRuntime | None = None,
) -> None:
    '''Prepare configured or image-provided seed corpora for a run.'''
    seeds_out = run_dir / 'seed_corpora'
    seeds_out.mkdir(parents=True, exist_ok=True)

    LOG.info('Preparing shared seed corpora...')
    for case in campaign_config.cases:
        extracted = extract_seed_corpus_from_image(
            case=case,
            out_dir=seeds_out,
            docker_runtime=docker_runtime,
        )
        if extracted is None:
            LOG.info('Starting without seed corpus for %s', case.seed_dir_name)


def measure_seed_baselines(
    *,
    campaign_config: CampaignConfig,
    db_path: Path,
    run_dir: Path,
    run_id: str,
    docker_runtime: DockerRuntime,
) -> None:
    '''Measure coverage for all prepared seed corpora.'''
    fuzzer_loader = FuzzerLoader(campaign_config.fuzzer_dirs)

    # Collect every seed corpus before sharing preprocessing capacity between them.
    seed_input_sets: list[InputSet] = []
    for case in campaign_config.cases:
        seed_root = run_dir / 'seed_corpora' / case.seed_dir_name / 'corpus'
        if not seed_root.exists() or not any(seed_root.iterdir()):
            continue
        base_root = seed_coverage_root(run_dir, case)
        snapshot_dir = base_root / '_snapshot'
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        seed_input_sets.append(
            InputSet(
                snapshot_dir=snapshot_dir,
                input_dir=snapshot_dir / 'corpus',
                input_files=tuple(
                    DetectedFile(
                        rel_path=src.relative_to(seed_root).as_posix(),
                        abs_src=src,
                        mtime_ns=src.stat().st_mtime_ns,
                    )
                    for src in sorted(path for path in seed_root.rglob('*') if path.is_file())
                ),
                snapshot_preprocess=fuzzer_loader.load(case.fuzzer.name).snapshot_preprocess_script(),
                case=case,
            )
        )
    if not seed_input_sets:
        return

    # Preprocess all seed corpora under the campaign-wide worker budget.
    jobs = campaign_config.settings.parallel_jobs
    LOG.info('Preparing %d seed baselines with %d workers', len(seed_input_sets), jobs)
    prepared_inputs = prepare_input_sets(
        docker_runtime=docker_runtime,
        input_sets=seed_input_sets,
        jobs=jobs,
    )

    # Plan all coverage batches before sharing execution capacity between baselines.
    measurements: list[tuple[CampaignCase, list[CoverageBatch], str]] = []
    coverage_batches: list[CoverageBatch] = []
    for input_set, inputs in zip(seed_input_sets, prepared_inputs, strict=True):
        if not inputs:
            continue
        case = input_set.case
        container_prefix = (
            f'fm-{run_id}-cov-seed-{case.fuzzer.id}-'
            f'{case.fuzz_target.benchmark.name}-{case.fuzz_target.fuzz_target}'
        )
        batches = build_coverage_batches(
            image=case.images.coverage,
            fuzz_target=case.fuzz_target.fuzz_target,
            input_mode=case.fuzz_target.input_mode,
            inputs=inputs,
            artifact_dir=input_set.snapshot_dir / '.artifacts' / 'coverage',
            timeout_s=case.fuzz_target.target_timeout_s * 2,
            container_prefix=container_prefix,
        )
        measurements.append((case, batches, container_prefix))
        coverage_batches.extend(batches)

    if not measurements:
        return

    # Execute all baseline batches in one global worker pool.
    LOG.info('Measuring %d seed baselines with %d workers', len(measurements), jobs)
    execute_coverage_batches(
        docker_runtime=docker_runtime,
        batches=coverage_batches,
        jobs=jobs,
    )

    # Merge baselines only after every batch has finished, one at a time: each merge loads the whole coverage mapping.
    with cf.ThreadPoolExecutor(max_workers=1) as executor:
        futures = [
            executor.submit(
                _merge_seed_baseline,
                docker_runtime=docker_runtime,
                run_dir=run_dir,
                case=case,
                batches=batches,
                container_prefix=container_prefix,
            )
            for case, batches, container_prefix in measurements
        ]
        summaries = [future.result() for future in futures]

    # Persist baselines only after every merge has succeeded.
    with open_db(db_path) as db:
        for (case, _, _), summary in zip(measurements, summaries, strict=True):
            base_root = seed_coverage_root(run_dir, case)
            html_index = base_root / 'html' / 'index.html'
            coverage_sets = base_root / 'coverage-sets.json'
            baseline_id = upsert_agg_snapshot(
                db,
                run_id=run_id,
                fuzzer=case.fuzzer.id,
                benchmark=case.fuzz_target.benchmark.name,
                fuzz_target=case.fuzz_target.fuzz_target,
                idx=SEED_BASELINE_IDX,
                ts=0,
            )
            if baseline_id <= 0:
                raise RuntimeError('Could not save seed baseline coverage data.')
            update_agg_snapshot_coverage(
                db,
                agg_snapshot_id=baseline_id,
                coverage=CoverageSummary.from_mapping(
                    coverage_html_dir=str(html_index.relative_to(run_dir)) if html_index.exists() else None,
                    summary=summary,
                ),
                coverage_sets_json_rel=str(coverage_sets.relative_to(run_dir)) if coverage_sets.exists() else None,
                measurement_provenance=load_measurement_provenance(base_root / 'measurement-provenance.json'),
            )
            LOG.debug(
                'Seed coverage summary for %s/%s/%s: %s',
                case.fuzzer.id,
                case.fuzz_target.benchmark.name,
                case.fuzz_target.fuzz_target,
                summary,
            )


def _merge_seed_baseline(
    *,
    docker_runtime: DockerRuntime,
    run_dir: Path,
    case: CampaignCase,
    batches: list[CoverageBatch],
    container_prefix: str,
) -> dict:
    '''Merge one seed baseline after all coverage batches finish.'''
    base_root = seed_coverage_root(run_dir, case)
    state_dir = base_root / '_state'
    return merge_coverage_outputs(
        docker_runtime=docker_runtime,
        run_dir=run_dir,
        case=case,
        out_root=base_root,
        state_dir=state_dir,
        work_dir=state_dir / '_tmp_seed',
        profile_inputs=[batch.profdata_path for batch in batches],
        container_name=f'{container_prefix}-merge',
        measurement_context=coverage_measurement_context(
            batches=batches,
            image=case.images.coverage,
            snapshot_tick=SEED_BASELINE_IDX,
            repetitions=1,
        ),
    )
