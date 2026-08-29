# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build trial configurations with stable test defaults.'''

from __future__ import annotations

from pathlib import Path
from typing import Any

from fuzzmeter.config.models import Benchmark, CampaignCase, Fuzzer, FuzzTarget
from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.trial.models import ReplayTrialConfig, TrialConfig

CASE_DEFAULTS = {
    'fuzzer': 'aflplusplus',
    'fuzzer_impl': 'aflplusplus',
    'benchmark': 'bench',
    'fuzz_target': 'target',
    'fuzz_target_input_mode': 'file',
    'fuzz_target_timeout': 1.0,
    'build_config': {},
    'runtime_config': {},
}


def make_campaign_case(**overrides: Any) -> CampaignCase:
    '''Build a campaign case from the flat identity fields tests care about.'''
    values = {**CASE_DEFAULTS, **overrides}
    return CampaignCase(
        fuzzer=Fuzzer(
            id=values['fuzzer'],
            name=values['fuzzer_impl'],
            src_dir=Path('fuzzers') / values['fuzzer_impl'],
        ),
        fuzz_target=FuzzTarget(
            benchmark=Benchmark(
                name=values['benchmark'],
                src_dir=Path('benchmarks') / values['benchmark'],
                config_path=Path('benchmarks') / values['benchmark'] / 'benchmark.yaml',
            ),
            fuzz_target=values['fuzz_target'],
            input_mode=values['fuzz_target_input_mode'],
            target_timeout_s=values['fuzz_target_timeout'],
        ),
        build_config=values['build_config'],
        run_config=values['runtime_config'],
    )


def make_trial_config(**overrides: Any) -> TrialConfig:
    '''Build a trial configuration while allowing tests to state relevant differences.'''
    case_overrides = {key: overrides.pop(key) for key in list(overrides) if key in CASE_DEFAULTS}
    values: dict[str, Any] = {
        'case': make_campaign_case(**case_overrides),
        'fuzz_target_bin': Path('target'),
        'rep_idx': 0,
        'trial_key': 'aflplusplus__bench-target__rep0',
        'output_paths': OutputPaths(
            corpus_root=Path('default/queue'),
            crashes_root=Path('default/crashes'),
        ),
        'trial_timeout': 300,
        'snapshot_preprocess': None,
    }
    values.update(overrides)
    replay_dir = values.pop('replay_dir', None)
    if replay_dir is None:
        return TrialConfig(**values)
    return ReplayTrialConfig(**values, replay_dir=replay_dir)
