# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Docker image build orchestration for campaign artifacts.'''

from __future__ import annotations

import logging
import shutil
import subprocess

from importlib import resources
from pathlib import Path

from fuzzmeter.config.models import Fuzzer

from ..composite.collect import collect_records, save_records
from ..config import CampaignConfig
from ..docker import DockerRuntime, generate_run_bake_hcl
from ..docker.bake import INSTRUMENTATION_PROFILES
from ..paths import (
    docker_resources,
    entrypoint_resources,
    instrumentation_resources,
    run_fuzzer_resources_root,
)
from .extract import extract_fuzz_binaries
from .seeds import measure_seed_baselines, prepare_seed_corpora

logger = logging.getLogger('fuzzmeter')


def _build_images(*, campaign_config: CampaignConfig, run_dir: Path) -> None:
    '''Build all docker images needed by a run.'''
    resources_root = run_fuzzer_resources_root(run_dir)
    build_root = resources_root / 'build'
    run_root = resources_root / 'run'
    instrumentation_root = resources_root / 'instrumentation'

    for root in (build_root, run_root, instrumentation_root):
        root.mkdir(parents=True)

    fuzzers = {case.fuzzer.name: case.fuzzer for case in campaign_config.cases}
    build_by_fuzzer = {
        name: _copy_fuzzer_context(fuzzer=fuzzer, root=build_root, phase='build')
        for name, fuzzer in fuzzers.items()
    }
    run_by_fuzzer = {
        name: _copy_fuzzer_context(fuzzer=fuzzer, root=run_root, phase='run')
        for name, fuzzer in fuzzers.items()
    }
    instrumentation_build_by_profile = _copy_internal_instrumentation_sources(out_root=instrumentation_root)

    # as_file yields a real filesystem path for the packaged resources, extracting them to a
    # temporary directory when fuzzmeter is not installed as plain files; docker buildx reads
    # them while the context is open.
    with (
        resources.as_file(docker_resources()) as docker_resources_dir,
        resources.as_file(entrypoint_resources()) as entrypoint_resources_dir,
    ):
        docker_resources_path = Path(docker_resources_dir).resolve()
        entrypoint_resources_path = Path(entrypoint_resources_dir).resolve()
        fuzzmeter_resources_path = Path(__file__).resolve().parents[1]
        local_repo_paths = {
            fuzzer.name: fuzzer.local_repo
            for case in campaign_config.cases
            for fuzzer in case.fuzzer.dependencies
            if fuzzer.local_repo is not None
        }
        bake_hcl = generate_run_bake_hcl(
            campaign_cases=campaign_config.cases,
            fuzzer_build_sources=build_by_fuzzer,
            fuzzer_run_sources=run_by_fuzzer,
            instrumentation_build_sources=instrumentation_build_by_profile,
            docker_resources=docker_resources_path,
            entrypoint_resources=entrypoint_resources_path,
            fuzzmeter_resources=fuzzmeter_resources_path,
            memory_limit=campaign_config.settings.memory,
            build_compile_jobs=campaign_config.settings.build_compile_jobs,
        )
        bake_hcl_path = run_dir / 'bake.hcl'
        bake_hcl_path.write_text(bake_hcl, encoding='utf-8')
        allow_args = [
            f'--allow=fs.read={docker_resources_path}',
            f'--allow=fs.read={entrypoint_resources_path}',
            f'--allow=fs.read={fuzzmeter_resources_path}',
            f'--allow=fs.read={run_dir / "fuzzer_resources"}',
            *[f'--allow=fs.read={path}' for path in campaign_config.fuzzer_dirs.values()],
            *[f'--allow=fs.read={path}' for path in local_repo_paths.values()],
            *[f'--allow=fs.read={case.fuzz_target.benchmark.src_dir}' for case in campaign_config.cases],
        ]

        progress = 'auto' if logger.isEnabledFor(logging.INFO) else 'plain'
        bake_targets = [
            f'runner_{case.fuzzer.id}_{case.fuzz_target.ident}'
            for case in campaign_config.cases
        ]
        target_cases = {case.fuzz_target.ident: case for case in campaign_config.cases}
        bake_targets.extend(
            f'{stage_name}_{fuzz_target_id}'
            for _, stage_name in INSTRUMENTATION_PROFILES
            for fuzz_target_id in target_cases
        )
        for start in range(0, len(bake_targets), campaign_config.settings.build_jobs):
            subprocess.run(
                [
                    'docker', 'buildx', 'bake', *allow_args, '--progress', progress,
                    '-f', str(bake_hcl_path), *bake_targets[start:start + campaign_config.settings.build_jobs],
                ],
                check=True,
                cwd=Path(run_dir),
            )


def _copy_fuzzer_context(
    *,
    fuzzer: Fuzzer,
    root: Path,
    phase: str,
) -> Path:
    out_root = root / fuzzer.name
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / '__init__.py').write_text('', encoding='utf-8')
    for dep_fuzzer in fuzzer.dependencies:
        src_dir = dep_fuzzer.src_dir
        dst_dir = out_root / dep_fuzzer.name
        dst_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(src_dir.glob('*.py')):
            shutil.copy2(path, dst_dir / path.name)

        phase_dir = src_dir / phase
        if phase_dir.is_dir():
            shutil.copytree(
                phase_dir,
                dst_dir / phase,
                ignore=shutil.ignore_patterns('__pycache__', '.*'),
                dirs_exist_ok=True,
            )
    return out_root


def _copy_internal_instrumentation_sources(*, out_root: Path) -> dict[str, Path]:
    contexts: dict[str, Path] = {}
    with resources.as_file(instrumentation_resources()) as instrumentation_root:
        for name, _ in INSTRUMENTATION_PROFILES:
            src_dir = Path(instrumentation_root) / name
            context_root = out_root / name
            dst_dir = context_root / name
            build_dir = dst_dir / 'build'
            build_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_dir / 'Dockerfile', dst_dir / 'Dockerfile')
            shutil.copy2(src_dir / 'build.py', build_dir / 'build.py')
            (dst_dir / '__init__.py').write_text('', encoding='utf-8')
            (build_dir / '__init__.py').write_text('', encoding='utf-8')
            contexts[name] = context_root
    return contexts


def prepare_artifacts(
    *,
    campaign_config: CampaignConfig,
    db_path: Path,
    run_dir: Path,
    run_id: str,
    docker_runtime: DockerRuntime,
) -> dict[tuple[str, str], Path]:
    '''Build images, extract binaries, prepare seeds, and measure seed baselines.'''
    _build_images(
        campaign_config=campaign_config,
        run_dir=run_dir,
    )
    fuzz_binaries = extract_fuzz_binaries(
        campaign_config=campaign_config,
        run_dir=run_dir,
        docker_runtime=docker_runtime,
    )
    # TODO: Enrich metadata with image IDs, binary hashes, and seed digests.
    save_records(
        db_path,
        collect_records(
            run_id=run_id,
            campaign_config=campaign_config,
        ),
    )
    prepare_seed_corpora(
        campaign_config=campaign_config,
        run_dir=run_dir,
        docker_runtime=docker_runtime,
    )
    measure_seed_baselines(
        campaign_config=campaign_config,
        db_path=db_path,
        run_dir=run_dir,
        run_id=run_id,
        docker_runtime=docker_runtime,
    )
    return fuzz_binaries
