# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Extract built fuzzing binaries from campaign images.'''

from __future__ import annotations

from pathlib import Path

from ..config import CampaignCase, CampaignConfig, target_key
from ..docker import DockerClient, DockerRuntime
from ..trial.models import TrialImages


def extract_fuzz_binaries(
    *,
    campaign_config: CampaignConfig,
    run_dir: Path,
    docker_runtime: DockerRuntime,
) -> dict[tuple[str, str], Path]:
    '''Extract built target binaries for a run.'''
    built_root = Path(run_dir) / 'built_bins'
    fuzz_root = built_root / 'fuzz'
    coverage_root = built_root / 'coverage'
    asan_root = built_root / 'asan'

    for path in (fuzz_root, coverage_root, asan_root):
        path.mkdir(parents=True, exist_ok=True)

    docker = DockerClient(docker_runtime)
    fuzz_binaries: dict[tuple[str, str], Path] = {}
    for entry in campaign_config.cases:
        target = target_key(entry.benchmark, entry.fuzz_target)
        runner_image = TrialImages(
            fuzzer_name=entry.fuzzer_name,
            target_key=target,
        ).runner
        fuzz_binaries[(entry.fuzzer_name, target)] = _extract_named_binary_from_image(
            docker=docker,
            image=runner_image,
            binary_name=entry.fuzz_target,
            dst_dir=fuzz_root / entry.fuzzer_name / target,
        )

    cases_by_target: dict[str, CampaignCase] = {
        target_key(case.benchmark, case.fuzz_target): case for case in campaign_config.cases
    }

    for target, owner_entry in cases_by_target.items():
        images = TrialImages(fuzzer_name=owner_entry.fuzzer_name, target_key=target)
        _extract_named_binary_from_image(
            docker=docker,
            image=images.coverage,
            binary_name=owner_entry.fuzz_target,
            dst_dir=coverage_root / target,
        )

        _extract_named_binary_from_image(
            docker=docker,
            image=images.asan,
            binary_name=owner_entry.fuzz_target,
            dst_dir=asan_root / target,
        )

    return fuzz_binaries


def _extract_named_binary_from_image(
    *,
    docker: DockerClient,
    image: str,
    binary_name: str,
    dst_dir: Path,
) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_path = dst_dir / binary_name
    docker.copy_from_image(image=image, src_path=f'/out/{binary_name}', dst_path=dst_path)
    dst_path.chmod(0o755)
    return dst_path
