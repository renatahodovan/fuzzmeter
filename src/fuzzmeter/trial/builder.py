# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import CampaignCase, CampaignConfig
from ..fuzzers import FuzzerLoader, OutputPaths
from .models import TrialConfig, TrialImages, TrialPathConfig


@dataclass(frozen=True)
class TrialPlan:
    config: TrialConfig
    target_bin: Path


@dataclass(frozen=True)
class _PreparedTrialEntry:
    entry: CampaignCase
    output_paths: OutputPaths
    images: TrialImages
    target_bin: Path
    snapshot_preprocess_script: Path | None
    rep_specs: tuple[tuple[int, Path | None], ...]


def plan_trials(
    *,
    campaign_config: CampaignConfig,
    repo_root: Path,
    fuzz_binaries: dict[tuple[str, str], Path],
) -> list[TrialPlan]:
    '''Create trial plans from campaign configuration and prepared artifacts.'''
    fuzzer_loader = FuzzerLoader(Path(repo_root))
    trial_plans: list[TrialPlan] = []
    seen_trial_keys: set[str] = set()
    rep_count = int(campaign_config.settings.repetitions)
    prepared_entries = [
        _prepare_trial_entry(
            entry=entry,
            fuzzer_loader=fuzzer_loader,
            fuzz_binaries=fuzz_binaries,
            rep_count=rep_count,
        )
        for entry in campaign_config.cases
    ]
    max_rep_specs = max((len(prepared.rep_specs) for prepared in prepared_entries), default=0)

    for rep_pos in range(max_rep_specs):
        for prepared in prepared_entries:
            if rep_pos >= len(prepared.rep_specs):
                continue
            entry = prepared.entry
            rep, replay_trial_path = prepared.rep_specs[rep_pos]
            config = TrialConfig(
                fuzzer=entry.fuzzer_name,
                fuzzer_base=entry.fuzzer_base,
                benchmark=entry.benchmark,
                fuzz_target=entry.fuzz_target,
                input_mode=entry.input_mode,
                target_timeout_s=_target_timeout_s(entry.runtime_config),
                rep=rep,
                trial_key=f'{entry.fuzzer_name}__{entry.target_id}__rep{rep}',
                paths=TrialPathConfig(
                    live_out_root=Path('work'),
                    snapshots_root=Path('snapshots'),
                    logs_root=Path('logs'),
                    fuzzer_log=Path('logs/fuzzer.log'),
                    output_paths=prepared.output_paths,
                ),
                time_seconds=campaign_config.settings.time_seconds,
                snapshot_every_seconds=campaign_config.settings.snapshot_every_seconds,
                snapshot_preprocess_script=prepared.snapshot_preprocess_script,
                runner_image=prepared.images.runner,
                coverage_image=prepared.images.coverage,
                asan_image=prepared.images.asan,
                replay_trial_path=replay_trial_path,
                build_config=entry.build_config,
                runtime_config=entry.runtime_config,
            )
            if config.trial_key in seen_trial_keys:
                raise RuntimeError(f'Duplicate trial key: {config.trial_key}')
            seen_trial_keys.add(config.trial_key)
            trial_plans.append(TrialPlan(config=config, target_bin=prepared.target_bin))

    return trial_plans


def _target_timeout_s(runtime_config: dict) -> float | None:
    target_config = runtime_config.get('target') if isinstance(runtime_config, dict) else None
    if not isinstance(target_config, dict):
        return None
    value = target_config.get('timeout_s')
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _prepare_trial_entry(
    *,
    entry: CampaignCase,
    fuzzer_loader: FuzzerLoader,
    fuzz_binaries: dict[tuple[str, str], Path],
    rep_count: int,
) -> _PreparedTrialEntry:
    fuzzer_module = fuzzer_loader.load(entry.fuzzer_base)
    replay_trials = tuple(Path(path).resolve() for path in entry.replay_trials)
    rep_specs: tuple[tuple[int, Path | None], ...]
    if replay_trials:
        rep_specs = tuple((rep, path) for rep, path in enumerate(replay_trials))
    else:
        rep_specs = tuple((rep, None) for rep in range(rep_count))

    return _PreparedTrialEntry(
        entry=entry,
        output_paths=fuzzer_module.output_paths_relative(),
        images=TrialImages.for_trial(fuzzer_name=entry.fuzzer_name, target_id=entry.target_id),
        target_bin=_require_fuzz_binary(fuzz_binaries=fuzz_binaries, entry=entry),
        snapshot_preprocess_script=fuzzer_module.snapshot_preprocess_script(),
        rep_specs=rep_specs,
    )


def _require_fuzz_binary(*, fuzz_binaries: dict[tuple[str, str], Path], entry: CampaignCase) -> Path:
    try:
        return fuzz_binaries[(entry.fuzzer_name, entry.target_id)]
    except KeyError as exc:
        raise RuntimeError(f'Missing target binary for {entry.fuzzer_name}/{entry.target_id}') from exc
