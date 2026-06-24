# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import logging
import shutil

from dataclasses import dataclass
from pathlib import Path

from ..db import open_db
from ..db.snapshot import SEED_BASELINE_IDX, update_agg_snapshot_coverage, upsert_agg_snapshot
from ..docker import DockerRuntime
from .coverage_measure import replay_coverage_batch, merge_coverage_outputs
from .coverage_state import collect_inputs, seed_coverage_root
from .ingest import DetectedFile, prepare_snapshot_inputs

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeedBaselineJob:
    '''Describe one prepared seed corpus coverage measurement.'''

    fuzzer: str
    benchmark: str
    fuzz_target: str
    input_mode: str
    runner_image: str
    coverage_image: str
    snapshot_preprocess_script: Path | None
    seed_root: Path


def measure_seed_baseline(
    *,
    db_path: Path,
    job: SeedBaselineJob,
    run_dir: Path,
    run_id: str,
    repo_root: Path,
    docker_runtime: DockerRuntime,
) -> None:
    '''Measure baseline coverage for one prepared seed corpus.'''
    if not job.seed_root.exists():
        return

    base_root = seed_coverage_root(run_dir, job.fuzzer, job.benchmark, job.fuzz_target)
    snapshot_dir = base_root / '_snapshot'
    corpus_dir = snapshot_dir / 'corpus'
    shutil.rmtree(snapshot_dir, ignore_errors=True)
    prepare_snapshot_inputs(
        docker_runtime=docker_runtime,
        snapshot_dir=snapshot_dir,
        input_dir=corpus_dir,
        input_files=[
            DetectedFile(
                rel_path=str(src.relative_to(job.seed_root)).replace('\\', '/'),
                abs_src=src,
                mtime_ns=src.stat().st_mtime_ns,
            )
            for src in sorted(path for path in job.seed_root.rglob('*') if path.is_file())
        ],
        snapshot_preprocess=job.snapshot_preprocess_script,
        benchmark=job.benchmark,
        fuzz_target=job.fuzz_target,
        fuzzer=job.fuzzer,
        runner_image=job.runner_image,
        repo_root=repo_root,
    )

    LOG.debug('Measuring seed baseline coverage for %s/%s/%s', job.fuzzer, job.benchmark, job.fuzz_target)
    state_dir = base_root / '_state'
    inputs = collect_inputs(corpus_dir)
    if not inputs:
        return

    batch_profdata_path = state_dir / 'batch.profdata'
    replay_coverage_batch(
        docker_runtime=docker_runtime,
        image=job.coverage_image,
        fuzz_target=job.fuzz_target,
        input_mode=job.input_mode,
        inputs=inputs,
        batch_profdata_path=batch_profdata_path,
        diagnostics_dir=state_dir / '_batch_diag',
    )
    summary = merge_coverage_outputs(
        docker_runtime=docker_runtime,
        run_dir=run_dir,
        image=job.coverage_image,
        out_root=base_root,
        benchmark=job.benchmark,
        fuzz_target=job.fuzz_target,
        state_dir=state_dir,
        work_dir=state_dir / '_tmp_seed',
        profile_inputs=[batch_profdata_path],
    )
    with open_db(db_path) as db:
        baseline_id = upsert_agg_snapshot(
            db,
            run_id=run_id,
            fuzzer=job.fuzzer,
            benchmark=job.benchmark,
            fuzz_target=job.fuzz_target,
            idx=SEED_BASELINE_IDX,
            ts=0,
        )
        if baseline_id <= 0:
            raise RuntimeError('Could not save seed baseline coverage data.')
        update_agg_snapshot_coverage(
            db,
            agg_snapshot_id=baseline_id,
            coverage_html_dir=_rel_if_exists(base_root / 'html' / 'index.html', run_dir),
            coverage_sets_json_rel=_rel_if_exists(base_root / 'coverage-sets.json', run_dir),
            summary=summary,
        )
    LOG.debug('Seed coverage summary for %s/%s/%s: %s', job.fuzzer, job.benchmark, job.fuzz_target, summary)


def _rel_if_exists(path: Path, root: Path) -> str | None:
    return str(path.relative_to(root)) if path.exists() else None
