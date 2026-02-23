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

from pathlib import Path

from ..config import CampaignConfig
from ..docker import DockerRuntime, fuzzer_source_dirs, generate_run_bake_hcl
from .extract import extract_fuzz_binaries
from .seeds import measure_seed_baselines, prepare_seed_corpora

logger = logging.getLogger("fuzzmeter")


def _build_images(*, campaign_config: CampaignConfig, run_dir: Path, repo_root: Path) -> None:
    '''Build all docker images needed by a run.'''
    fuzzer_build_sources, fuzzer_run_sources = _prepare_fuzzer_contexts(
        campaign_config=campaign_config,
        run_dir=run_dir,
        repo_root=repo_root,
    )
    bake_hcl = generate_run_bake_hcl(
        repo_root=Path(repo_root),
        entries=campaign_config.cases,
        memory_limit=campaign_config.settings.memory,
        fuzzer_build_sources=fuzzer_build_sources,
        fuzzer_run_sources=fuzzer_run_sources,
    )
    bake_hcl_path = Path(run_dir) / 'bake.hcl'
    bake_hcl_path.write_text(str(bake_hcl), encoding='utf-8')
    info_enabled = logger.isEnabledFor(logging.INFO)
    progress = 'auto' if info_enabled else 'plain'
    allow_args = [
        f'--allow=fs.read={fuzzer_build_sources.resolve()}',
        f'--allow=fs.read={fuzzer_run_sources.resolve()}',
    ]

    subprocess.run(
        ['docker', 'buildx', 'bake', *allow_args, '--progress', progress, '-f', str(bake_hcl_path), 'fm'],
        check=True,
        cwd=repo_root,
    )


def _prepare_fuzzer_contexts(*, campaign_config: CampaignConfig, run_dir: Path, repo_root: Path) -> tuple[Path, Path]:
    resources_root = Path(run_dir) / 'fuzzer_resources'
    build_root = resources_root / 'build'
    run_root = resources_root / 'run'

    # Ensure using empty directories.
    for root in (build_root, run_root):
        if root.exists():
            for child in root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
        else:
            root.mkdir(parents=True, exist_ok=True)

    fuzzers = sorted({
        source_dir
        for entry in campaign_config.cases
        for source_dir in fuzzer_source_dirs(Path(repo_root), entry.fuzzer_base)
    } | {'coverage', 'asan'})

    for phase, root in (('build', build_root), ('run', run_root)):
        _copy_common_fuzzer_sources(repo_root=repo_root, out_root=root)
        for fuzzer in fuzzers:
            _copy_fuzzer_phase(repo_root=repo_root, out_root=root, fuzzer=fuzzer, phase=phase)

    return build_root, run_root


def _copy_common_fuzzer_sources(*, repo_root: Path, out_root: Path) -> None:
    src_root = repo_root / 'fuzzers'
    shutil.copy2(src_root / '__init__.py', out_root / '__init__.py')
    shutil.copy2(src_root / 'utils.py', out_root / 'utils.py')
    shutil.copytree(
        src_root / '_common',
        out_root / '_common',
        ignore=shutil.ignore_patterns('__pycache__', '.*'),
        dirs_exist_ok=True,
    )


def _copy_fuzzer_phase(*, repo_root: Path, out_root: Path, fuzzer: str, phase: str) -> None:
    src_dir = repo_root / 'fuzzers' / fuzzer
    if not src_dir.is_dir():
        return

    dst_dir = out_root / fuzzer
    dst_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(src_dir.glob('*.py')):
        shutil.copy2(path, dst_dir / path.name)

    phase_dir = src_dir / phase
    if not phase_dir.is_dir():
        return
    shutil.copytree(
        phase_dir,
        dst_dir / phase,
        ignore=shutil.ignore_patterns('__pycache__', '.*'),
        dirs_exist_ok=True,
    )


def prepare_artifacts(
    *,
    campaign_config: CampaignConfig,
    run_dir: Path,
    repo_root: Path,
    docker_runtime: DockerRuntime,
) -> dict[tuple[str, str], Path]:
    '''Build images, extract binaries, prepare seeds, and measure seed baselines.'''
    _build_images(campaign_config=campaign_config, run_dir=run_dir, repo_root=repo_root)
    fuzz_binaries = extract_fuzz_binaries(campaign_config=campaign_config, run_dir=run_dir)
    prepare_seed_corpora(campaign_config=campaign_config, run_dir=run_dir, repo_root=repo_root)
    measure_seed_baselines(
        campaign_config=campaign_config,
        run_dir=run_dir,
        repo_root=repo_root,
        docker_runtime=docker_runtime,
    )
    return fuzz_binaries
