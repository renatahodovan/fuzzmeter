# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for trial plan ordering.'''

from __future__ import annotations

import unittest

from pathlib import Path
from unittest.mock import patch

from fuzzmeter.config import Benchmark, CampaignCase, CampaignConfig, CampaignSettings
from fuzzmeter.config.models import Fuzzer, FuzzTarget
from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.trial.builder import plan_trials


class _FuzzerModuleStub:
    def output_paths_relative(self) -> OutputPaths:
        return OutputPaths(corpus_root=Path('queue'), crashes_root=Path('crashes'))

    def snapshot_preprocess_script(self) -> None:
        return None


class _FuzzerLoaderStub:
    def __init__(self, fuzzer_dirs: dict[str, Path]) -> None:
        self.fuzzer_dirs = fuzzer_dirs

    def load(self, _fuzzer_name: str) -> _FuzzerModuleStub:
        return _FuzzerModuleStub()


class _TrialBuilderTest(unittest.TestCase):
    '''Verify trial planning behavior.'''

    def test_plan_trials_orders_live_repetitions_by_rep_first(self) -> None:
        '''Verify that every case gets rep0 before any rep1 trial is scheduled.'''
        cases = [
            _campaign_case(fuzzer='fuzzer_a', fuzz_target='target_a'),
            _campaign_case(fuzzer='fuzzer_b', fuzz_target='target_b'),
        ]
        config = CampaignConfig(
            settings=CampaignSettings(repetitions=3),
            cases=cases,
        )

        with patch('fuzzmeter.trial.builder.FuzzerLoader', _FuzzerLoaderStub):
            plans = plan_trials(
                campaign_config=config,
                fuzz_binaries={
                    ('fuzzer_a', 'bench-target_a'): Path('/tmp/fuzzer_a'),
                    ('fuzzer_b', 'bench-target_b'): Path('/tmp/fuzzer_b'),
                },
            )

        self.assertEqual(
            [plan.trial_key for plan in plans],
            [
                'fuzzer_a__bench-target_a__rep0',
                'fuzzer_b__bench-target_b__rep0',
                'fuzzer_a__bench-target_a__rep1',
                'fuzzer_b__bench-target_b__rep1',
                'fuzzer_a__bench-target_a__rep2',
                'fuzzer_b__bench-target_b__rep2',
            ],
        )


def _campaign_case(*, fuzzer: str, fuzz_target: str) -> CampaignCase:
    return CampaignCase(
        fuzzer=Fuzzer(id=fuzzer, name=fuzzer, src_dir=Path('/fuzzers') / fuzzer),
        fuzz_target=FuzzTarget(
            benchmark=Benchmark(name='bench', src_dir=Path('/benchmarks/bench'), config_path=Path('/benchmarks/bench/benchmark.yaml')),
            fuzz_target=fuzz_target,
            input_mode='file',
        ),
    )


if __name__ == '__main__':
    unittest.main()
