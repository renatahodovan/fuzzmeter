# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build trial configurations from campaign cases and prepared artifacts.'''

from __future__ import annotations

from functools import partial
from pathlib import Path

from ..config import CampaignConfig
from ..fuzzers import FuzzerLoader
from .models import ReplayTrialConfig, TrialConfig


def plan_trials(
    *,
    campaign_config: CampaignConfig,
    fuzz_binaries: dict[tuple[str, str], Path],
) -> list[TrialConfig]:
    '''Create trial configs from campaign configuration and prepared artifacts.'''
    fuzzer_loader = FuzzerLoader(campaign_config.fuzzer_dirs)
    trial_configs: list[TrialConfig] = []
    seen_trial_keys: set[str] = set()
    rep_count = campaign_config.settings.repetitions
    configs_by_rep: dict[int, list[TrialConfig]] = {}

    for campaign_case in campaign_config.cases:
        fuzzer_module = fuzzer_loader.load(campaign_case.fuzzer.name)
        output_paths = fuzzer_module.output_paths_relative()
        replay_trials = campaign_case.replay_trials
        rep_specs = tuple(enumerate(replay_trials)) if replay_trials else tuple((rep, None) for rep in range(rep_count))
        snapshot_preprocess = fuzzer_module.snapshot_preprocess_script()
        fuzz_target_id = campaign_case.fuzz_target.ident
        target_bin = fuzz_binaries[(campaign_case.fuzzer.id, fuzz_target_id)]

        for rep_idx, replay_dir in rep_specs:
            trial_type = TrialConfig if replay_dir is None else partial(ReplayTrialConfig, replay_dir=replay_dir)
            config = trial_type(
                case=campaign_case,
                fuzz_target_bin=target_bin,
                rep_idx=rep_idx,
                trial_key=f'{campaign_case.fuzzer.id}__{fuzz_target_id}__rep{rep_idx}',
                output_paths=output_paths,
                trial_timeout=campaign_config.settings.time_seconds,
                snapshot_preprocess=snapshot_preprocess,
            )
            if config.trial_key in seen_trial_keys:
                raise RuntimeError(f'Duplicate trial key: {config.trial_key}')
            seen_trial_keys.add(config.trial_key)
            configs_by_rep.setdefault(rep_idx, []).append(config)

    for rep_idx in sorted(configs_by_rep):
        trial_configs.extend(configs_by_rep[rep_idx])

    return trial_configs
