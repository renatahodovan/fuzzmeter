# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build trial configurations from campaign cases and prepared artifacts.'''

from __future__ import annotations

from pathlib import Path

from ..config import CampaignConfig
from ..fuzzers import FuzzerLoader
from .models import TrialConfig, TrialImages


def plan_trials(
    *,
    campaign_config: CampaignConfig,
    repo_root: Path,
    fuzz_binaries: dict[tuple[str, str], Path],
) -> list[TrialConfig]:
    '''Create trial configs from campaign configuration and prepared artifacts.'''
    fuzzer_loader = FuzzerLoader(Path(repo_root))
    trial_configs: list[TrialConfig] = []
    seen_trial_keys: set[str] = set()
    rep_count = int(campaign_config.settings.repetitions)

    for campaign_case in campaign_config.cases:
        fuzzer_module = fuzzer_loader.load(campaign_case.fuzzer_base)
        images = TrialImages(fuzzer_name=campaign_case.fuzzer_name, target_id=campaign_case.target_id)
        output_paths = fuzzer_module.output_paths_relative()
        replay_trials = tuple(Path(path).resolve() for path in campaign_case.replay_trials)
        rep_specs = tuple(enumerate(replay_trials)) if replay_trials else tuple((rep, None) for rep in range(rep_count))
        snapshot_preprocess = fuzzer_module.snapshot_preprocess_script()
        target_bin = fuzz_binaries[(campaign_case.fuzzer_name, campaign_case.target_id)]

        for rep_idx, replay_dir in rep_specs:
            config = TrialConfig(
                fuzzer=campaign_case.fuzzer_name,
                fuzzer_base=campaign_case.fuzzer_base,
                benchmark=campaign_case.benchmark,
                fuzz_target=campaign_case.fuzz_target,
                fuzz_target_bin=target_bin,
                fuzz_target_input_mode=campaign_case.input_mode,
                fuzz_target_timeout=campaign_case.target_timeout_s,
                rep_idx=rep_idx,
                trial_key=f'{campaign_case.fuzzer_name}__{campaign_case.target_id}__rep{rep_idx}',
                output_paths=output_paths,
                trial_timeout=campaign_config.settings.time_seconds,
                snapshot_preprocess=snapshot_preprocess,
                images=images,
                replay_dir=replay_dir,
                build_config=campaign_case.build_config,
                runtime_config=campaign_case.runtime_config,
            )
            if config.trial_key in seen_trial_keys:
                raise RuntimeError(f'Duplicate trial key: {config.trial_key}')
            seen_trial_keys.add(config.trial_key)
            trial_configs.append(config)

    return trial_configs
