# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for the coverage replay worker.'''

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

REPRO_DIR = Path(__file__).resolve().parents[1] / 'src' / 'fuzzmeter' / 'repro'
if str(REPRO_DIR) not in sys.path:
    sys.path.insert(0, str(REPRO_DIR))

coverage_worker = importlib.import_module('coverage_worker')


class CoverageWorkerTest(unittest.TestCase):
    '''Verify coverage worker batch execution behavior.'''

    def test_batch_mode_runs_inputs_sequentially_and_writes_diagnostics_without_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_list = root / 'inputs.txt'
            input_list.write_text('/inputs/a\n/inputs/b\n', encoding='utf-8')
            out_dir = root / 'out'
            out_dir.mkdir()
            work_dir = root / 'work'
            cfg = coverage_worker.WorkerConfig(
                cov_bin=root / 'target',
                input_mode='file',
                out_dir=out_dir,
                work_dir=work_dir,
                input_list=input_list,
                prof_list=Path(),
                profdata=root / 'merged.profdata',
                batch_profdata=root / 'batch.profdata',
                coverage_sets=None,
                timeout_s=2.5,
            )
            calls = []

            def execute_one(_cfg, input_path, index, profraws_dir):
                calls.append((input_path, index, profraws_dir))
                return {
                    'index': index,
                    'input': input_path,
                    'status': 'missing_profraw',
                    'returncode': 0,
                    'profraws': [],
                    'stdout': '',
                    'stderr': '',
                }

            with patch.object(coverage_worker, '_execute_one_input', side_effect=execute_one), \
                 patch.object(coverage_worker, '_merge_profiles') as merge_profiles:
                coverage_worker._run_batch_mode(cfg)

            diagnostics = json.loads((out_dir / 'input_exec_diagnostics.json').read_text(encoding='utf-8'))

        self.assertEqual(
            [
                ('/inputs/a', 0, work_dir / 'worker_tmp'),
                ('/inputs/b', 1, work_dir / 'worker_tmp'),
            ],
            calls,
        )
        self.assertEqual(2, diagnostics['attempted'])
        self.assertEqual(2.5, diagnostics['timeout_s'])
        self.assertNotIn('jobs', diagnostics)
        self.assertEqual({'missing_profraw': 2}, diagnostics['status_counts'])
        merge_profiles.assert_not_called()

    def test_finalize_mode_without_profdata_writes_empty_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            out_dir = root / 'out'
            out_dir.mkdir()
            work_dir = root / 'work'
            work_dir.mkdir()
            prof_list = root / 'profiles.txt'
            prof_list.write_text('\n', encoding='utf-8')
            cfg = coverage_worker.WorkerConfig(
                cov_bin=root / 'target',
                out_dir=out_dir,
                work_dir=work_dir,
                input_list=Path(),
                profdata=root / 'missing.profdata',
                coverage_sets=None,
                prof_list=prof_list,
            )

            coverage_worker._run_finalize_mode(cfg)

            summary = (out_dir / 'summary.json').read_text(encoding='utf-8')

        self.assertEqual('{}', summary)

    def test_write_coverage_outputs_skips_html_when_skip_env_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            out_dir = root / 'out'
            out_dir.mkdir()
            profdata = root / 'merged.profdata'
            profdata.write_text('profile\n', encoding='utf-8')
            cfg = coverage_worker.WorkerConfig(
                cov_bin=root / 'target',
                out_dir=out_dir,
                work_dir=root / 'work',
                input_list=Path(),
                profdata=profdata,
                coverage_sets=None,
            )

            with patch.dict(coverage_worker.os.environ, {'FM_SKIP_HTML': '0'}, clear=False), \
                 patch.object(
                     coverage_worker,
                     '_run',
                     return_value=subprocess.CompletedProcess(args=['llvm-cov'], returncode=0, stdout='', stderr=''),
                 ) as run:
                coverage_worker._write_coverage_outputs(cfg)

            commands = [call.args[0] for call in run.call_args_list]

        self.assertEqual(1, len(commands))
        self.assertEqual(['llvm-cov', 'report'], commands[0][:2])

    def test_run_raises_runtime_error_and_writes_command_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)

            with patch.object(
                coverage_worker.subprocess,
                'run',
                return_value=subprocess.CompletedProcess(args=['tool'], returncode=2, stdout='out', stderr='err'),
            ):
                with self.assertRaises(RuntimeError):
                    coverage_worker._run(['tool'], out_dir=out_dir, label='tool')

            stdout = (out_dir / 'tool.stdout.txt').read_text(encoding='utf-8')
            stderr = (out_dir / 'tool.stderr.txt').read_text(encoding='utf-8')

        self.assertEqual('out', stdout)
        self.assertEqual('err', stderr)


if __name__ == '__main__':
    unittest.main()
