# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import logging
import os

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..config import CampaignConfig
from ..docker import DockerRuntime
from ..fuzzers import FuzzerLoader
from ..repro.coverage_baseline import SeedBaselineJob, measure_seed_baseline
from ..trial.models import TrialImages
from ..trial.workspace import TrialWorkspacePreparer

LOG = logging.getLogger(__name__)


def prepare_seed_corpora(*, campaign_config: CampaignConfig, run_dir: Path, repo_root: Path) -> None:
    '''Prepare configured or image-provided seed corpora for a run.'''
    seeds_out = Path(run_dir) / 'seed_corpora'
    seeds_out.mkdir(parents=True, exist_ok=True)

    LOG.info('Preparing shared seed corpora...')
    for entry in campaign_config.cases:
        runner_image = TrialImages.for_trial(
            fuzzer_name=entry.fuzzer_name,
            target_id=entry.target_id,
        ).runner
        extracted = TrialWorkspacePreparer.extract_seed_corpus_from_image(
            image=runner_image,
            fuzzer=entry.fuzzer_name,
            benchmark=entry.benchmark,
            fuzz_target=entry.fuzz_target,
            out_dir=seeds_out,
        )
        if extracted is None:
            LOG.info(
                'Starting without seed corpus for %s/%s__%s',
                entry.fuzzer_name,
                entry.benchmark,
                entry.fuzz_target,
            )


def measure_seed_baselines(
    *,
    campaign_config: CampaignConfig,
    run_dir: Path,
    repo_root: Path,
    docker_runtime: DockerRuntime,
) -> None:
    '''Measure coverage for all prepared seed corpora.'''
    fuzzer_loader = FuzzerLoader(Path(repo_root))
    jobs = _collect_seed_baseline_jobs(campaign_config=campaign_config, run_dir=run_dir, fuzzer_loader=fuzzer_loader)
    if not jobs:
        return

    max_workers = min(os.cpu_count() or 1, len(jobs))
    LOG.info('Measuring %d seed baselines with %d workers', len(jobs), max_workers)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for future in as_completed([
            executor.submit(
                measure_seed_baseline,
                job=job,
                run_dir=run_dir,
                repo_root=repo_root,
                docker_runtime=docker_runtime,
            )
            for job in jobs
        ]):
            future.result()


def _collect_seed_baseline_jobs(
    *,
    campaign_config: CampaignConfig,
    run_dir: Path,
    fuzzer_loader: FuzzerLoader,
) -> list[SeedBaselineJob]:
    jobs: list[SeedBaselineJob] = []
    for entry in campaign_config.cases:
        seed_key = _seed_key(entry.fuzzer_name, entry.benchmark, entry.fuzz_target)
        seed_root = Path(run_dir) / 'seed_corpora' / seed_key / 'corpus'
        if not seed_root.exists() or not any(seed_root.iterdir()):
            continue
        images = TrialImages.for_trial(fuzzer_name=entry.fuzzer_name, target_id=entry.target_id)
        jobs.append(
            SeedBaselineJob(
                fuzzer=entry.fuzzer_name,
                benchmark=entry.benchmark,
                fuzz_target=entry.fuzz_target,
                input_mode=entry.input_mode,
                runner_image=images.runner,
                coverage_image=images.coverage,
                snapshot_preprocess_script=fuzzer_loader.load(entry.fuzzer_base).snapshot_preprocess_script(),
                seed_root=seed_root,
            )
        )
    return jobs


def _seed_key(fuzzer: str, benchmark: str, fuzz_target: str) -> str:
    return f'{fuzzer}__{benchmark}__{fuzz_target}'.replace('/', '_').replace(':', '_')
