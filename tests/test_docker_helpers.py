# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for Docker bake and runtime helpers.'''

from __future__ import annotations

import unittest

from pathlib import Path
from unittest.mock import patch

from fuzzmeter.docker.bake import _entry_args
from fuzzmeter.docker.runtime import DockerRuntime


class DockerHelperTest(unittest.TestCase):
    '''Verify Docker helper environment handling.'''

    def test_bake_log_level_uses_fm_log_level_default_and_escaping(self) -> None:
        with patch.dict('os.environ', {'FUZZMETER_LOG_LEVEL': 'DEBUG'}, clear=True):
            default_lines = _entry_args(
                fuzzer='fuzzer',
                build_config_json='{}',
                fuzzer_source_dirs=[],
                benchmark='bench',
                benchmark_workdir='/work',
                target_name='target',
            )

        with patch.dict('os.environ', {'FM_LOG_LEVEL': 'INFO"quoted', 'FUZZMETER_LOG_LEVEL': 'DEBUG'}, clear=True):
            escaped_lines = _entry_args(
                fuzzer='fuzzer',
                build_config_json='{}',
                fuzzer_source_dirs=[],
                benchmark='bench',
                benchmark_workdir='/work',
                target_name='target',
            )

        self.assertIn('  FM_LOG_LEVEL  = "INFO"', default_lines)
        self.assertIn('  FM_LOG_LEVEL  = "INFO\\"quoted"', escaped_lines)

    def test_hook_env_requires_fm_log_level_and_does_not_set_legacy_fallback(self) -> None:
        runtime = DockerRuntime(fuzzers_root=Path('/fuzzers'), out_src='/out', run_user=None)

        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(KeyError):
                runtime.hook_env()

        with patch.dict('os.environ', {'FM_LOG_LEVEL': 'WARNING', 'PYTHONPATH': '/existing'}, clear=True):
            env = runtime.hook_env(extra={'COUNT': 3})

        self.assertEqual('WARNING', env['FM_LOG_LEVEL'])
        self.assertNotIn('FUZZMETER_LOG_LEVEL', env)
        self.assertEqual('/existing', env['PYTHONPATH'])
        self.assertEqual('/fuzzers', env['FM_FUZZERS_ROOT'])
        self.assertEqual('3', env['COUNT'])


if __name__ == '__main__':
    unittest.main()
