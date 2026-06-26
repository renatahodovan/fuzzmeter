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
from pathlib import Path
import sys
import tempfile
import unittest
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


if __name__ == '__main__':
    unittest.main()
