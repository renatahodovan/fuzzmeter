# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import shutil

from dataclasses import dataclass
from pathlib import Path

from ..config import CampaignCase, CampaignConfig
from ..docker import DockerClient
from ..trial.models import TrialImages


def extract_fuzz_binaries(*, campaign_config: CampaignConfig, run_dir: Path) -> dict[tuple[str, str], Path]:
    '''Extract built target binaries for a run.'''
    built_root = Path(run_dir) / 'built_bins'
    fuzz_root = built_root / 'fuzz'
    coverage_root = built_root / 'coverage'
    asan_root = built_root / 'asan'

    for path in (fuzz_root, coverage_root, asan_root):
        path.mkdir(parents=True, exist_ok=True)

    docker = DockerClient()
    fuzz_binaries: dict[tuple[str, str], Path] = {}
    for entry in campaign_config.cases:
        runner_image = TrialImages.for_trial(
            fuzzer_name=entry.fuzzer_name,
            target_id=entry.target_id,
        ).runner
        fuzz_binaries[(entry.fuzzer_name, entry.target_id)] = _extract_named_binary_from_image(
            docker=docker,
            image=runner_image,
            binary_name=entry.fuzz_target,
            dst_dir=fuzz_root / entry.fuzzer_name / entry.target_id,
        )

    cases_by_target: dict[str, CampaignCase] = {}
    for case in campaign_config.cases:
        cases_by_target[case.target_id] = case
    
    for target_id, owner_entry in cases_by_target.items():
        images = TrialImages.for_trial(fuzzer_name=owner_entry.fuzzer_name, target_id=target_id)
        _extract_named_binary_from_image(
            docker=docker,
            image=images.coverage,
            binary_name=owner_entry.fuzz_target,
            dst_dir=coverage_root / target_id,
        )

        _extract_named_binary_from_image(
            docker=docker,
            image=images.asan,
            binary_name=owner_entry.fuzz_target,
            dst_dir=asan_root / target_id,
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
