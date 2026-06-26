# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for the crash reproduction worker.'''

from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPRO_DIR = Path(__file__).resolve().parents[1] / 'src' / 'fuzzmeter' / 'repro'
if str(REPRO_DIR) not in sys.path:
    sys.path.insert(0, str(REPRO_DIR))

crash_worker = importlib.import_module('crash_worker')


class CrashWorkerTest(unittest.TestCase):
    '''Verify crash worker environment and result mapping behavior.'''

    def test_main_requires_target_name_env(self) -> None:
        with patch.dict(crash_worker.os.environ, {}, clear=True):
            with self.assertRaises(KeyError):
                crash_worker.main()

    def test_main_overwrites_sanitizer_env_and_writes_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            crash_input = root / 'crash.txt'
            crash_input.write_text('boom\n', encoding='utf-8')
            input_list = root / 'inputs.txt'
            input_list.write_text(f'{crash_input}\n', encoding='utf-8')
            output_json = root / 'out' / 'results.json'

            env = {
                'FM_TARGET_NAME': 'target',
                'FM_INPUT_MODE': 'file',
                'FM_TIMEOUT_S': '3.5',
                'FM_CRASH_INPUT_LIST': str(input_list),
                'FM_CRASH_OUTPUT_JSON': str(output_json),
                'ASAN_OPTIONS': 'custom',
                'UBSAN_OPTIONS': 'custom',
            }
            completed = subprocess.CompletedProcess(
                args=['/out/target', str(crash_input)],
                returncode=77,
                stdout='stdout text',
                stderr='stderr text',
            )

            with patch.dict(crash_worker.os.environ, env, clear=True), \
                 patch.object(crash_worker.subprocess, 'run', return_value=completed) as run:
                crash_worker.main()

            run_kwargs = run.call_args.kwargs
            results = json.loads(output_json.read_text(encoding='utf-8'))

        self.assertEqual(['/out/target', str(crash_input)], run.call_args.args[0])
        self.assertEqual(3.5, run_kwargs['timeout'])
        self.assertEqual('symbolize=1:abort_on_error=1:disable_coredump=1:detect_leaks=0:handle_abort=1', run_kwargs['env']['ASAN_OPTIONS'])
        self.assertEqual('print_stacktrace=1:halt_on_error=1', run_kwargs['env']['UBSAN_OPTIONS'])
        self.assertEqual(
            [
                {
                    'returncode': 77,
                    'stdout': 'stdout text',
                    'stderr': 'stderr text',
                    'timeout': False,
                }
            ],
            results,
        )

    def test_run_one_maps_timeout_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            crash_input = Path(tmp_dir) / 'crash.txt'
            crash_input.write_text('boom\n', encoding='utf-8')

            with patch.object(
                crash_worker.subprocess,
                'run',
                side_effect=subprocess.TimeoutExpired(cmd=['target'], timeout=1.0, output=b'out', stderr=b'err'),
            ):
                result = crash_worker._run_one(
                    asan_bin=Path('/out/target'),
                    crash_input=crash_input,
                    input_mode='stdin',
                    timeout_s=1.0,
                    env={},
                )

        self.assertEqual(
            {
                'returncode': 124,
                'stdout': 'out',
                'stderr': 'err',
                'timeout': True,
            },
            result,
        )


if __name__ == '__main__':
    unittest.main()
