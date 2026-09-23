# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Measure baseline coverage for prepared seed corpora.'''

from __future__ import annotations

import logging
import shutil

from dataclasses import dataclass
from pathlib import Path

from ..config import CampaignCase
from ..config.models import FuzzTarget
from ..db import open_db
from ..db.snapshot import SEED_BASELINE_IDX, CoverageSummary, update_agg_snapshot_coverage, upsert_agg_snapshot
from ..docker import DockerRuntime
from .coverage_measure import (
    build_coverage_replay_batches,
    coverage_measurement_context,
    merge_coverage_outputs,
    replay_coverage_batches,
)
from .coverage_state import collect_inputs, load_measurement_provenance, seed_coverage_root
from .ingest import DetectedFile, prepare_snapshot_inputs

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeedBaselineJob:
    '''Describe one prepared seed corpus coverage measurement.'''

    case: CampaignCase
    snapshot_preprocess_script: Path | None
    seed_root: Path

    @property
    def fuzz_target(self) -> FuzzTarget:
        return self.case.fuzz_target


def measure_seed_baseline(
    *,
    db_path: Path,
    job: SeedBaselineJob,
    run_dir: Path,
    run_id: str,
    docker_runtime: DockerRuntime,
    jobs: int,
) -> None:
    '''Measure baseline coverage for one prepared seed corpus.'''
    base_root = seed_coverage_root(run_dir, job.case)
    snapshot_dir = base_root / '_snapshot'
    corpus_dir = snapshot_dir / 'corpus'
    shutil.rmtree(snapshot_dir, ignore_errors=True)

    seed_input_files = [
        DetectedFile(
            rel_path=str(src.relative_to(job.seed_root)).replace('\\', '/'),
            abs_src=src,
            mtime_ns=src.stat().st_mtime_ns,
        )
        for src in sorted(path for path in job.seed_root.rglob('*') if path.is_file())
    ]
    if not seed_input_files:
        return

    prepare_snapshot_inputs(
        docker_runtime=docker_runtime,
        snapshot_dir=snapshot_dir,
        input_dir=corpus_dir,
        input_files=seed_input_files,
        snapshot_preprocess=job.snapshot_preprocess_script,
        benchmark=job.fuzz_target.benchmark.name,
        fuzz_target=job.fuzz_target.fuzz_target,
        fuzzer=job.case.fuzzer.id,
        runner_image=job.case.images.runner,
    )

    state_dir = base_root / '_state'
    inputs = collect_inputs(corpus_dir)
    if not inputs:
        return

    LOG.debug('Measuring seed baseline coverage for %s/%s/%s', job.case.fuzzer.id, job.fuzz_target.benchmark.name, job.fuzz_target.fuzz_target)
    batch_profdata_paths, coverage_batches = build_coverage_replay_batches(
        image=job.case.images.coverage,
        fuzz_target=job.fuzz_target.fuzz_target,
        input_mode=job.fuzz_target.input_mode,
        inputs=inputs,
        artifact_dir=snapshot_dir / '.artifacts' / 'coverage',
        timeout_s=job.fuzz_target.target_timeout_s * 2,
        container_prefix=f'fm-{run_id}-cov-seed-{job.case.fuzzer.id}-{job.fuzz_target.benchmark.name}-{job.fuzz_target.fuzz_target}',
    )
    replay_coverage_batches(
        docker_runtime=docker_runtime,
        batches=coverage_batches,
        jobs=jobs,
    )
    summary = merge_coverage_outputs(
        docker_runtime=docker_runtime,
        run_dir=run_dir,
        case=job.case,
        out_root=base_root,
        state_dir=state_dir,
        work_dir=state_dir / '_tmp_seed',
        profile_inputs=batch_profdata_paths,
        container_name=f'fm-{run_id}-cov-seed-{job.case.fuzzer.id}-{job.fuzz_target.benchmark.name}-{job.fuzz_target.fuzz_target}-merge',
        measurement_context=coverage_measurement_context(
            batches=coverage_batches,
            image=job.case.images.coverage,
            snapshot_tick=SEED_BASELINE_IDX,
            repetitions=1,
        ),
    )

    html_index = base_root / 'html' / 'index.html'
    coverage_sets = base_root / 'coverage-sets.json'
    with open_db(db_path) as db:
        baseline_id = upsert_agg_snapshot(
            db,
            run_id=run_id,
            fuzzer=job.case.fuzzer.id,
            benchmark=job.fuzz_target.benchmark.name,
            fuzz_target=job.fuzz_target.fuzz_target,
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
            measurement_provenance=load_measurement_provenance(
                base_root / 'measurement-provenance.json'
            ),
        )
    LOG.debug('Seed coverage summary for %s/%s/%s: %s', job.case.fuzzer.id, job.fuzz_target.benchmark.name, job.fuzz_target.fuzz_target, summary)
