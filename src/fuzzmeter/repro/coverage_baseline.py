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

from ..docker import DockerRuntime
from ..fuzzers import HookRunner, HookSpec
from .coverage_measure import finalize_coverage, run_coverage_batch
from .coverage_state import collect_inputs, seed_coverage_root

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
    job: SeedBaselineJob,
    run_dir: Path,
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
    corpus_dir.mkdir(parents=True, exist_ok=True)

    for src in sorted(path for path in job.seed_root.rglob('*') if path.is_file()):
        dst = corpus_dir / src.relative_to(job.seed_root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    if job.snapshot_preprocess_script:
        LOG.debug('Decoding seed corpus for %s/%s/%s', job.fuzzer, job.benchmark, job.fuzz_target)
        HookRunner(docker_runtime=docker_runtime).run(
            HookSpec(
                name='snapshot_preprocess',
                script=job.snapshot_preprocess_script,
                env={
                    'FM_SNAPSHOT_DIR': str(snapshot_dir),
                    'FM_SNAPSHOT_CORPUS_DIR': str(corpus_dir),
                    'FM_BENCHMARK': job.benchmark,
                    'FM_FUZZ_TARGET': job.fuzz_target,
                    'FM_FUZZER': job.fuzzer,
                    'FM_RUNNER_IMAGE': job.runner_image,
                    'FM_REPO_ROOT': str(repo_root),
                },
                cwd=snapshot_dir,
            )
        )

    LOG.debug('Measuring seed baseline coverage for %s/%s/%s', job.fuzzer, job.benchmark, job.fuzz_target)
    state_dir = base_root / '_state'
    inputs = collect_inputs(corpus_dir)
    if not inputs:
        return

    batch_profdata_path = state_dir / 'batch.profdata'
    run_coverage_batch(
        docker_runtime=docker_runtime,
        image=job.coverage_image,
        fuzz_target=job.fuzz_target,
        input_mode=job.input_mode,
        inputs=inputs,
        batch_profdata_path=batch_profdata_path,
        diagnostics_dir=state_dir / '_batch_diag',
    )
    summary = finalize_coverage(
        docker_runtime=docker_runtime,
        run_dir=run_dir,
        image=job.coverage_image,
        benchmark=job.benchmark,
        fuzz_target=job.fuzz_target,
        state_dir=state_dir,
        work_dir=state_dir / '_tmp_seed',
        out_root=base_root,
        profile_inputs=[batch_profdata_path],
    )
    LOG.debug('Seed coverage summary for %s/%s/%s: %s', job.fuzzer, job.benchmark, job.fuzz_target, summary)
