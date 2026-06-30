# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Docker image build orchestration for campaign artifacts.'''

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import logging
from pathlib import Path
import shutil
import subprocess

from ..config import CampaignConfig
from ..docker import DockerRuntime, fuzzer_source_dirs, generate_run_bake_hcl
from ..docker.bake import INSTRUMENTATION_PROFILES
from ..paths import ExternalRoots, docker_resources, entrypoint_resources, instrumentation_resources
from .extract import extract_fuzz_binaries
from .seeds import measure_seed_baselines, prepare_seed_corpora

logger = logging.getLogger('fuzzmeter')


@dataclass(frozen=True)
class _FuzzerContexts:
    build_by_fuzzer: dict[str, Path]
    run_by_fuzzer: dict[str, Path]
    instrumentation_build_by_profile: dict[str, Path]

    def paths(self) -> list[Path]:
        paths = [
            *self.build_by_fuzzer.values(),
            *self.run_by_fuzzer.values(),
            *self.instrumentation_build_by_profile.values(),
        ]
        return sorted(set(paths))


def _build_images(*, campaign_config: CampaignConfig, run_dir: Path, external_roots: ExternalRoots) -> None:
    '''Build all docker images needed by a run.'''
    fuzzer_contexts = _prepare_fuzzer_contexts(
        campaign_config=campaign_config,
        run_dir=run_dir,
        fuzzers_root=external_roots.fuzzers_root,
    )
    with (
        resources.as_file(docker_resources()) as docker_resources_path,
        resources.as_file(entrypoint_resources()) as entrypoint_resources_path,
    ):
        fuzzmeter_resources_path = Path(__file__).resolve().parents[1] / 'resources'
        bake_hcl = generate_run_bake_hcl(
            fuzzers_root=external_roots.fuzzers_root,
            targets_root=external_roots.targets_root,
            entries=campaign_config.cases,
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
            *[f'--allow=fs.read={path.resolve()}' for path in fuzzer_contexts.paths()],
            f'--allow=fs.read={external_roots.targets_root.resolve()}',
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
    fuzzers_root: Path,
) -> _FuzzerContexts:
    resources_root = Path(run_dir) / 'fuzzer_resources'
    build_root = resources_root / 'build'
    run_root = resources_root / 'run'
    instrumentation_root = resources_root / 'instrumentation'

    # Ensure using empty directories.
    for root in (build_root, run_root, instrumentation_root):
        if root.exists():
            for child in root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
        else:
            root.mkdir(parents=True, exist_ok=True)

    fuzzer_impls = sorted({entry.fuzzer_base for entry in campaign_config.cases})
    build_by_fuzzer: dict[str, Path] = {}
    run_by_fuzzer: dict[str, Path] = {}
    for fuzzer in fuzzer_impls:
        source_dirs = fuzzer_source_dirs(Path(fuzzers_root), fuzzer)
        build_by_fuzzer[fuzzer] = _copy_fuzzer_context(
            fuzzers_root=fuzzers_root,
            root=build_root,
            context_name=fuzzer,
            fuzzers=source_dirs,
            phase='build',
        )
        run_by_fuzzer[fuzzer] = _copy_fuzzer_context(
            fuzzers_root=fuzzers_root,
            root=run_root,
            context_name=fuzzer,
            fuzzers=source_dirs,
            phase='run',
        )

    return _FuzzerContexts(
        build_by_fuzzer=build_by_fuzzer,
        run_by_fuzzer=run_by_fuzzer,
        instrumentation_build_by_profile=_copy_internal_instrumentation_sources(out_root=instrumentation_root),
    )


def _copy_fuzzer_context(
    *,
    fuzzers_root: Path,
    root: Path,
    context_name: str,
    fuzzers: list[str],
    phase: str,
) -> Path:
    out_root = root / context_name
    out_root.mkdir(parents=True, exist_ok=True)
    _write_fuzzer_namespace(out_root=out_root)
    for fuzzer in fuzzers:
        _copy_fuzzer_phase(fuzzers_root=fuzzers_root, out_root=out_root, fuzzer=fuzzer, phase=phase)
    return out_root


def _write_fuzzer_namespace(*, out_root: Path) -> None:
    (out_root / '__init__.py').write_text('', encoding='utf-8')


def _copy_fuzzer_phase(*, fuzzers_root: Path, out_root: Path, fuzzer: str, phase: str) -> None:
    src_dir = fuzzers_root / fuzzer
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


def _copy_internal_instrumentation_sources(*, out_root: Path) -> dict[str, Path]:
    contexts: dict[str, Path] = {}
    with resources.as_file(instrumentation_resources()) as instrumentation_root:
        for name, _, _ in INSTRUMENTATION_PROFILES:
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
    external_roots: ExternalRoots,
    docker_runtime: DockerRuntime,
) -> dict[tuple[str, str], Path]:
    '''Build images, extract binaries, prepare seeds, and measure seed baselines.'''
    _build_images(campaign_config=campaign_config, run_dir=run_dir, external_roots=external_roots)
    fuzz_binaries = extract_fuzz_binaries(campaign_config=campaign_config, run_dir=run_dir)
    prepare_seed_corpora(campaign_config=campaign_config, run_dir=run_dir)
    measure_seed_baselines(
        campaign_config=campaign_config,
        db_path=db_path,
        run_dir=run_dir,
        run_id=run_id,
        fuzzers_root=external_roots.fuzzers_root,
        docker_runtime=docker_runtime,
    )
    return fuzz_binaries
