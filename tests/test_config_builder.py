# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for campaign configuration loading.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from fuzzmeter.config import load_campaign_config


class ConfigBuilderTest(unittest.TestCase):
    '''Verify campaign config expansion rules.'''

    def test_allowed_benchmarks_limits_fuzzer_targets(self) -> None:
        '''Verify that fuzzer-level benchmark allowlists filter campaign cases.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'limited', 'allowed_benchmarks:\n  - jerryscript:jerry\n')
            _write_fuzzer(root, 'plain', '')
            _write_target(root, 'jerryscript', 'jerry')
            _write_target(root, 'sqlite3', 'ossfuzz')

            config = load_campaign_config(
                root,
                '''
fuzzers:
  - limited
  - plain
targets:
  - jerryscript:jerry
  - sqlite3:ossfuzz
''',
            )

        self.assertEqual(
            [
                ('limited', 'jerryscript', 'jerry'),
                ('plain', 'jerryscript', 'jerry'),
                ('plain', 'sqlite3', 'ossfuzz'),
            ],
            [(case.fuzzer_name, case.benchmark, case.fuzz_target) for case in config.cases],
        )

    def test_allowed_benchmarks_are_inherited_from_parent_fuzzer(self) -> None:
        '''Verify that derived fuzzer entries keep parent benchmark allowlists.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'limited_base', 'allowed_benchmarks:\n  - jerryscript:jerry\n')
            _write_target(root, 'jerryscript', 'jerry')
            _write_target(root, 'sqlite3', 'ossfuzz')

            config = load_campaign_config(
                root,
                '''
fuzzers:
  - fuzzer: limited_child
    parent: limited_base
targets:
  - jerryscript:jerry
  - sqlite3:ossfuzz
''',
            )

        self.assertEqual(
            [('limited_child', 'jerryscript', 'jerry')],
            [(case.fuzzer_name, case.benchmark, case.fuzz_target) for case in config.cases],
        )

    def test_target_timeout_becomes_runtime_target_default(self) -> None:
        '''Verify that target-level timeouts feed fuzzer runtime target config.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_target(root, 'jerryscript', 'jerry', timeout_s=10)

            config = load_campaign_config(
                root,
                '''
fuzzers:
  - plain
targets:
  - jerryscript:jerry
''',
            )

        self.assertEqual({'target': {'timeout_s': 10}}, config.cases[0].runtime_config)

    def test_runtime_target_timeout_overrides_target_default(self) -> None:
        '''Verify that suite/fuzzer runtime config can override target defaults.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_target(root, 'jerryscript', 'jerry', timeout_s=10)

            config = load_campaign_config(
                root,
                '''
fuzzers:
  - fuzzer: plain
    runtime:
      target:
        timeout_s: 3
targets:
  - jerryscript:jerry
''',
            )

        self.assertEqual({'target': {'timeout_s': 3}}, config.cases[0].runtime_config)

    def test_snapshot_export_interval_defaults_to_ten_percent_of_ticks(self) -> None:
        '''Verify that LLVM export defaults to roughly every 10% of the snapshot grid.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_target(root, 'jerryscript', 'jerry')

            config = load_campaign_config(
                root,
                '''
run:
  time_seconds: 14400
  snapshot:
    every_seconds: 300
fuzzers:
  - plain
targets:
  - jerryscript:jerry
''',
            )

        self.assertEqual(5, config.settings.snapshot_export_every_ticks)

    def test_snapshot_export_interval_can_be_configured(self) -> None:
        '''Verify that suites can override the LLVM export cadence.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_target(root, 'jerryscript', 'jerry')

            config = load_campaign_config(
                root,
                '''
run:
  time_seconds: 14400
  snapshot:
    every_seconds: 300
    export_every_ticks: 7
fuzzers:
  - plain
targets:
  - jerryscript:jerry
''',
            )

        self.assertEqual(7, config.settings.snapshot_export_every_ticks)


def _write_fuzzer(root: Path, name: str, text: str) -> None:
    fuzzer_dir = root / 'fuzzers' / name / 'build'
    fuzzer_dir.mkdir(parents=True)
    fuzzer_dir.joinpath('build.yaml').write_text(text, encoding='utf-8')


def _write_target(root: Path, project: str, fuzz_target: str, *, timeout_s: int | None = None) -> None:
    target_dir = root / 'targets' / project
    target_dir.mkdir(parents=True)
    timeout_line = f'timeout_s: {timeout_s}\n' if timeout_s is not None else ''
    target_dir.joinpath('benchmark.yaml').write_text(
        f'project: {project}\nfuzz_target: {fuzz_target}\ninput_mode: file\n{timeout_line}',
        encoding='utf-8',
    )


if __name__ == '__main__':
    unittest.main()
