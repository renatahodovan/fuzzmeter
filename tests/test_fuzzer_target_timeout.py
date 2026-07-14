# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Unit tests for forwarding target timeouts into live fuzzer adapters.'''

from __future__ import annotations

import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from fuzzers.afl.run import fuzz as afl_fuzzer
from fuzzers.blackbox.run import fuzz as blackbox_fuzzer
from fuzzers.libfuzzer.run import fuzz as libfuzzer_fuzzer


class FuzzerTargetTimeoutTest(unittest.TestCase):
    '''Verify live fuzzer commands use the FuzzMeter target timeout.'''

    def test_blackbox_uses_fuzz_target_timeout_env(self) -> None:
        with patch.dict(
            'os.environ',
            {
                'FM_FUZZ_TARGET_TIMEOUT': '2.5',
                'FM_FUZZER_RUNTIME_CONFIG_JSON': json.dumps({'generator': {'command': ['gen']}}),
            },
            clear=True,
        ), patch.object(blackbox_fuzzer, 'BlackBoxFuzzer') as fuzzer_cls:
            blackbox_fuzzer.fuzz_blackbox(
                input_corpus='in',
                output_corpus='out',
                target_binary='target',
                input_mode='file',
            )

        self.assertEqual(2.5, fuzzer_cls.call_args.kwargs['target_timeout_s'])

    def test_libfuzzer_adds_target_timeout_flag_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            target = root / 'target'
            target.write_text('', encoding='utf-8')
            with patch.dict(
                'os.environ',
                {
                    'FUZZER': 'libfuzzer',
                    'FM_FUZZ_TARGET_TIMEOUT': '2.2',
                    'FM_FUZZER_RUNTIME_CONFIG_JSON': json.dumps({'args': []}),
                },
                clear=True,
            ), patch('fuzzers.libfuzzer.run.fuzz.subprocess.check_output') as check_output:
                libfuzzer_fuzzer.run_fuzzer(str(root / 'in'), str(root / 'out'), str(target))

        command = check_output.call_args.args[0]
        self.assertIn('-timeout=3', command)

    def test_libfuzzer_keeps_explicit_timeout_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            target = root / 'target'
            target.write_text('', encoding='utf-8')
            with patch.dict(
                'os.environ',
                {
                    'FUZZER': 'libfuzzer',
                    'FM_FUZZ_TARGET_TIMEOUT': '2.2',
                    'FM_FUZZER_RUNTIME_CONFIG_JSON': json.dumps({'args': ['-timeout=9']}),
                },
                clear=True,
            ), patch('fuzzers.libfuzzer.run.fuzz.subprocess.check_output') as check_output:
                libfuzzer_fuzzer.run_fuzzer(str(root / 'in'), str(root / 'out'), str(target))

        command = check_output.call_args.args[0]
        self.assertIn('-timeout=9', command)
        self.assertNotIn('-timeout=3', command)

    def test_afl_adds_target_timeout_in_milliseconds(self) -> None:
        with patch.dict(
            'os.environ',
            {
                'FUZZER': 'afl',
                'FM_FUZZ_TARGET_TIMEOUT': '2.5',
                'FM_FUZZER_RUNTIME_CONFIG_JSON': json.dumps({}),
            },
            clear=True,
        ), patch('fuzzers.afl.run.fuzz.subprocess.run') as run:
            afl_fuzzer.run_afl_fuzz('in', 'out', 'target')

        command = run.call_args.args[0]
        timeout_index = command.index('-t')
        self.assertEqual('2500', command[timeout_index + 1])

    def test_afl_keeps_explicit_timeout_flag(self) -> None:
        with patch.dict(
            'os.environ',
            {
                'FUZZER': 'afl',
                'FM_FUZZ_TARGET_TIMEOUT': '2.5',
                'FM_FUZZER_RUNTIME_CONFIG_JSON': json.dumps({}),
            },
            clear=True,
        ), patch('fuzzers.afl.run.fuzz.subprocess.run') as run:
            afl_fuzzer.run_afl_fuzz('in', 'out', 'target', additional_flags=['-t', '777'])

        command = run.call_args.args[0]
        self.assertEqual(1, command.count('-t'))
        self.assertEqual('777', command[command.index('-t') + 1])


if __name__ == '__main__':
    unittest.main()
