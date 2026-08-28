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

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from fuzzmeter.config.models import Fuzzer

from ..composite.collect import collect_records, save_records
from ..config import CampaignConfig
from ..docker import DockerRuntime, generate_run_bake_hcl
from ..docker.bake import INSTRUMENTATION_PROFILES
from ..paths import docker_resources, entrypoint_resources, instrumentation_resources
from .extract import extract_fuzz_binaries
from .seeds import measure_seed_baselines, prepare_seed_corpora

logger = logging.getLogger('fuzzmeter')


@dataclass(frozen=True)
class _FuzzerContexts:
    build_by_fuzzer: dict[str, Path]
    run_by_fuzzer: dict[str, Path]
    instrumentation_build_by_profile: dict[str, Path]


def _build_images(*, campaign_config: CampaignConfig, run_dir: Path) -> None:
    '''Build all docker images needed by a run.'''
    fuzzer_contexts = _prepare_fuzzer_contexts(
        campaign_config=campaign_config,
        run_dir=run_dir,
    )
    with (
        resources.as_file(docker_resources()) as docker_resources_path,
        resources.as_file(entrypoint_resources()) as entrypoint_resources_path,
    ):
        fuzzmeter_resources_path = Path(__file__).resolve().parents[1]
        local_repo_paths: dict[str, Path] = {}
        for case in campaign_config.cases:
            for fuzzer in case.fuzzer.dependencies:
                if fuzzer.local_repo is None:
                    continue
                if not fuzzer.local_repo.is_dir():
                    raise NotADirectoryError(
                        f'Local fuzzer repository from {fuzzer.local_repo_env} '
                        f'is not a directory: {fuzzer.local_repo}'
                    )
                local_repo_paths[fuzzer.name] = fuzzer.local_repo
        bake_hcl = generate_run_bake_hcl(
            campaign_cases=campaign_config.cases,
            memory_limit=campaign_config.settings.memory,
            fuzzer_build_sources=fuzzer_contexts.build_by_fuzzer,
            fuzzer_run_sources=fuzzer_contexts.run_by_fuzzer,
            instrumentation_build_sources=fuzzer_contexts.instrumentation_build_by_profile,
            docker_resources=Path(docker_resources_path),
            entrypoint_resources=Path(entrypoint_resources_path),
            fuzzmeter_resources=fuzzmeter_resources_path,
        )
        bake_hcl_path = Path(run_dir) / 'bake.hcl'
        bake_hcl_path.write_text(str(bake_hcl), encoding='utf-8')
        info_enabled = logger.isEnabledFor(logging.INFO)
        progress = 'auto' if info_enabled else 'plain'
        allow_args = [
            f'--allow=fs.read={Path(docker_resources_path).resolve()}',
            f'--allow=fs.read={Path(entrypoint_resources_path).resolve()}',
            f'--allow=fs.read={fuzzmeter_resources_path.resolve()}',
            f'--allow=fs.read={(Path(run_dir) / "fuzzer_resources").resolve()}',
            *[f'--allow=fs.read={path.resolve()}' for path in campaign_config.fuzzer_dirs.values()],
            *[f'--allow=fs.read={path}' for path in local_repo_paths.values()],
            *[f'--allow=fs.read={case.fuzz_target.benchmark.src_dir}' for case in campaign_config.cases],
        ]

        subprocess.run(
            ['docker', 'buildx', 'bake', *allow_args, '--progress', progress, '-f', str(bake_hcl_path), 'fm'],
            check=True,
            cwd=Path(run_dir),
        )


def _prepare_fuzzer_contexts(
    *,
    campaign_config: CampaignConfig,
    run_dir: Path,
) -> _FuzzerContexts:
    resources_root = Path(run_dir) / 'fuzzer_resources'
    build_root = resources_root / 'build'
    run_root = resources_root / 'run'
    instrumentation_root = resources_root / 'instrumentation'

    for root in (build_root, run_root, instrumentation_root):
        root.mkdir(parents=True)

    build_by_fuzzer: dict[str, Path] = {}
    run_by_fuzzer: dict[str, Path] = {}
    fuzzers = {case.fuzzer.name: case.fuzzer for case in campaign_config.cases}
    for fuzzer in fuzzers.values():
        build_by_fuzzer[fuzzer.name] = _copy_fuzzer_context(fuzzer=fuzzer, root=build_root, phase='build')
        run_by_fuzzer[fuzzer.name] = _copy_fuzzer_context(fuzzer=fuzzer, root=run_root, phase='run')

    return _FuzzerContexts(
        build_by_fuzzer=build_by_fuzzer,
        run_by_fuzzer=run_by_fuzzer,
        instrumentation_build_by_profile=_copy_internal_instrumentation_sources(out_root=instrumentation_root),
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
