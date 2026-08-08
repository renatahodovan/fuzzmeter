# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Regression tests for benchmark target resolution in fuzzer utils."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from fuzzers import utils
from fuzzmeter.resources.entrypoints import campaign_build
from fuzzmeter.resources.instrumentation.coverage import build as coverage_build


class FuzzerUtilsTest(unittest.TestCase):
    """Verify benchmark target resolution helpers."""

    def test_get_active_target_config_supports_legacy_benchmark_yaml(self) -> None:
        """Verify that legacy single-target benchmark configs still load."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            benchmark_path = Path(tmp_dir) / 'benchmark.yaml'
            benchmark_path.write_text(
                'project: demo\nfuzz_target: legacy\ninput_mode: file\n',
                encoding='utf-8',
            )

            with patch.object(utils, 'BENCHMARK_CONFIG_PATH', str(benchmark_path)):
                resolved = utils.get_active_target_config()

        self.assertEqual('legacy', resolved['name'])
        self.assertEqual('file', resolved['config']['input_mode'])

    def test_get_active_target_config_uses_target_name_for_multi_target_yaml(self) -> None:
        """Verify that multi-target benchmark configs resolve the active target from TARGET_NAME."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            benchmark_path = Path(tmp_dir) / 'benchmark.yaml'
            benchmark_path.write_text(
                '''
project: demo
fuzz_targets:
  one:
    input_mode: in_process
    fuzzers:
      afl:
        build:
          env:
            MODE: one
  two:
    input_mode: file
    fuzzers:
      afl:
        build:
          env:
            MODE: two
'''.lstrip(),
                encoding='utf-8',
            )

            with patch.object(utils, 'BENCHMARK_CONFIG_PATH', str(benchmark_path)):
                resolved = utils.get_active_target_config({'TARGET_NAME': 'two'})

        self.assertEqual('two', resolved['name'])
        self.assertEqual('file', resolved['config']['input_mode'])
        self.assertEqual('two', resolved['config']['fuzzers']['afl']['build']['env']['MODE'])

    def test_get_benchmark_fuzzer_config_reads_selected_target_override(self) -> None:
        """Verify that fuzzer overrides are read from the selected multi-target entry."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            benchmark_path = Path(tmp_dir) / 'benchmark.yaml'
            benchmark_path.write_text(
                '''
project: demo
fuzz_targets:
  first:
    input_mode: in_process
    fuzzers:
      afl:
        build:
          env:
            MODE: first
  second:
    input_mode: file
    fuzzers:
      afl:
        build:
          env:
            MODE: second
'''.lstrip(),
                encoding='utf-8',
            )

            with patch.object(utils, 'BENCHMARK_CONFIG_PATH', str(benchmark_path)):
                with patch.dict('os.environ', {'TARGET_NAME': 'second'}, clear=True):
                    config = utils.get_benchmark_fuzzer_config('afl')

        self.assertEqual({'build': {'env': {'MODE': 'second'}}}, config)

    def test_set_fuzz_target_copies_target_name_from_environment(self) -> None:
        """Verify that FUZZ_TARGET is derived from the runtime target env, not benchmark YAML."""
        env = {'TARGET_NAME': 'chosen-target'}

        campaign_build.initialize_env(env)

        self.assertEqual('chosen-target', env['FUZZ_TARGET'])

    def test_initialize_env_preserves_env_selected_target_for_builds(self) -> None:
        """Verify that build initialization propagates TARGET_NAME into FUZZ_TARGET."""
        env = {'TARGET_NAME': 'chosen-target'}

        campaign_build.initialize_env(env)

        self.assertEqual('chosen-target', env['FUZZ_TARGET'])

    def test_coverage_build_uses_atomic_profile_updates(self) -> None:
        """Verify that coverage binaries use thread-safe profile counters."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            metadata_path = Path(tmp_dir) / 'coverage-build.json'
            with patch.dict('os.environ', {}, clear=True), \
                 patch.object(coverage_build, 'COVERAGE_BUILD_METADATA_PATH', metadata_path), \
                 patch.object(coverage_build.subprocess, 'check_output', return_value='clang version 18.1.3\n'), \
                 patch.object(coverage_build.utils, 'get_build_env', return_value={}), \
                 patch.object(coverage_build.utils, 'apply_configured_env'), \
                 patch.object(coverage_build.utils, 'build_benchmark'):
                coverage_build.build()
                cflags = os.environ['CFLAGS'].split()
                cxxflags = os.environ['CXXFLAGS'].split()
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))

        self.assertIn('-fprofile-update=atomic', cflags)
        self.assertIn('-fprofile-update=atomic', cxxflags)
        self.assertEqual(' '.join(cflags), metadata['requested_cflags'])
        self.assertEqual(' '.join(cxxflags), metadata['requested_cxxflags'])
        self.assertEqual('clang version 18.1.3', metadata['clang_version'])

    def test_multi_target_yaml_requires_target_name(self) -> None:
        """Verify that multi-target benchmark configs fail without an active target env."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            benchmark_path = Path(tmp_dir) / 'benchmark.yaml'
            benchmark_path.write_text(
                'project: demo\nfuzz_targets:\n  one:\n    input_mode: file\n',
                encoding='utf-8',
            )

            with patch.object(utils, 'BENCHMARK_CONFIG_PATH', str(benchmark_path)):
                with self.assertRaisesRegex(RuntimeError, 'TARGET_NAME must be set'):
                    utils.get_active_target_config({})

    def test_multi_target_yaml_rejects_root_level_fuzzers(self) -> None:
        """Verify that multi-target benchmark configs reject root-level fuzzer overrides."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            benchmark_path = Path(tmp_dir) / 'benchmark.yaml'
            benchmark_path.write_text(
                '''
project: demo
fuzzers:
  afl:
    build:
      env:
        MODE: root
fuzz_targets:
  one:
    input_mode: file
'''.lstrip(),
                encoding='utf-8',
            )

            with patch.object(utils, 'BENCHMARK_CONFIG_PATH', str(benchmark_path)):
                with self.assertRaisesRegex(ValueError, 'root-level fuzzers'):
                    utils.get_active_target_config({'TARGET_NAME': 'one'})


if __name__ == '__main__':
    unittest.main()
