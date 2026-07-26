'''Build trial configurations with stable test defaults.'''

from __future__ import annotations

from pathlib import Path
from typing import Any

from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.trial.models import TrialConfig, TrialImages


def make_trial_config(**overrides: Any) -> TrialConfig:
    '''Build a trial configuration while allowing tests to state relevant differences.'''
    values = {
        'fuzzer': 'aflplusplus',
        'fuzzer_impl': 'aflplusplus',
        'benchmark': 'bench',
        'fuzz_target': 'target',
        'fuzz_target_bin': Path('target'),
        'fuzz_target_input_mode': 'file',
        'fuzz_target_timeout': 1.0,
        'rep_idx': 0,
        'trial_key': 'aflplusplus__bench-target__rep0',
        'output_paths': OutputPaths(
            corpus_root=Path('default/queue'),
            crashes_root=Path('default/crashes'),
        ),
        'trial_timeout': 300,
        'snapshot_preprocess': None,
        'images': TrialImages(fuzzer_name='aflplusplus', target_key='bench-target'),
        'replay_dir': None,
        'build_config': {},
        'runtime_config': {},
    }
    values.update(overrides)
    return TrialConfig(**values)
