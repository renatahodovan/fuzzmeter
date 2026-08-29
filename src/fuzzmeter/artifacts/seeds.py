# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Prepare and measure seed corpora used by campaigns.'''

from __future__ import annotations

import logging
import os

from pathlib import Path

from ..config import CampaignConfig
from ..docker import DockerRuntime
from ..fuzzers import FuzzerLoader
from ..repro.coverage_baseline import SeedBaselineJob, measure_seed_baseline
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
    baseline_jobs = _collect_seed_baseline_jobs(
        campaign_config=campaign_config,
        run_dir=run_dir,
        fuzzer_loader=fuzzer_loader,
    )
    if not baseline_jobs:
        return

    max_workers = min(os.cpu_count() or 1, len(baseline_jobs))
    LOG.info('Measuring %d seed baselines with %d workers', len(baseline_jobs), max_workers)
    for job in baseline_jobs:
        measure_seed_baseline(
            db_path=db_path,
            job=job,
            run_dir=run_dir,
            run_id=run_id,
            docker_runtime=docker_runtime,
            jobs=max_workers,
        )


def _collect_seed_baseline_jobs(
    *,
    campaign_config: CampaignConfig,
    run_dir: Path,
    fuzzer_loader: FuzzerLoader,
) -> list[SeedBaselineJob]:
    jobs: list[SeedBaselineJob] = []
    for case in campaign_config.cases:
        seed_root = run_dir / 'seed_corpora' / case.seed_dir_name / 'corpus'
        if not seed_root.exists() or not any(seed_root.iterdir()):
            continue
        jobs.append(
            SeedBaselineJob(
                case=case,
                snapshot_preprocess_script=fuzzer_loader.load(case.fuzzer.name).snapshot_preprocess_script(),
                seed_root=seed_root,
            )
        )
    return jobs
