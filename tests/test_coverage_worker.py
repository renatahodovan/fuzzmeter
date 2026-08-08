# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for the coverage replay worker.'''

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fuzzmeter.reporting.keys import COV_METRICS
from fuzzmeter.resources.instrumentation.coverage import build as coverage_build
from tests.support.entrypoints import load_entrypoint

coverage_sets = load_entrypoint('coverage_sets')
coverage_worker = load_entrypoint('coverage_worker')


class CoverageWorkerTest(unittest.TestCase):
    '''Verify coverage worker batch execution behavior.'''

    def test_coverage_metrics_match_reporting_keys(self) -> None:
        '''Verify the container copy of the metric names has not drifted.'''
        # The container entrypoint cannot import reporting.keys, so the two are
        # separate literals kept equal by this check rather than by an import.
        self.assertEqual(COV_METRICS, coverage_sets.COVERAGE_METRICS)

    def test_container_entrypoints_import_with_only_shipped_files(self) -> None:
        '''Verify the workers load from the file set the runtime image receives.'''
        shipped = ('coverage_sets.py', 'coverage_worker.py', 'crash_worker.py', 'run_fuzzer.py')
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_dir = Path(coverage_sets.__file__).parent
            for name in shipped:
                shutil.copy2(source_dir / name, root / name)
            result = subprocess.run(
                [sys.executable, '-E', '-S', '-c', 'import coverage_worker, crash_worker'],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(
            0,
            result.returncode,
            f'Container entrypoints need a file the runtime image does not ship:\n{result.stderr}',
        )

    def test_coverage_set_observes_requested_counter_mode_from_build(self) -> None:
        '''Verify coverage artifacts derive provenance from coverage build output.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            metadata_path = root / 'coverage-build.json'
            artifact_path = root / 'coverage-sets.json'
            with patch.dict('os.environ', {}, clear=True), \
                 patch.object(coverage_build, 'COVERAGE_BUILD_METADATA_PATH', metadata_path), \
                 patch.object(coverage_sets, 'COVERAGE_BUILD_METADATA_PATH', metadata_path), \
                 patch.object(coverage_build.subprocess, 'check_output', return_value='clang version 18.1.3\n'), \
                 patch.object(coverage_build.utils, 'get_build_env', return_value={}), \
                 patch.object(coverage_build.utils, 'apply_configured_env'), \
                 patch.object(coverage_build.utils, 'build_benchmark'):
                coverage_build.build()
                coverage_sets.write_coverage_sets(artifact_path, {}, {})
            artifact = json.loads(artifact_path.read_text(encoding='utf-8'))

        provenance = artifact['measurement_provenance']
        self.assertEqual('atomic', provenance['requested_counter_update_mode'])
        self.assertEqual('explicit_flag', provenance['requested_counter_update_mode_source'])
        self.assertEqual('recorded', provenance['coverage_build']['status'])
        self.assertEqual(' '.join(coverage_build.COVERAGE_CFLAGS), provenance['coverage_build']['cflags'])
        self.assertEqual(' '.join(coverage_build.COVERAGE_CFLAGS), provenance['coverage_build']['cxxflags'])
        self.assertEqual('clang version 18.1.3', provenance['coverage_build']['clang_version'])

    def test_coverage_set_records_unknown_when_build_provenance_is_missing(self) -> None:
        '''Verify missing build metadata warns and never claims atomic counters.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            artifact_path = root / 'coverage-sets.json'
            with patch.object(coverage_sets, 'COVERAGE_BUILD_METADATA_PATH', root / 'missing.json'), \
                 self.assertLogs(coverage_sets.LOG, level='WARNING') as logs:
                coverage_sets.write_coverage_sets(artifact_path, {}, {})
            artifact = json.loads(artifact_path.read_text(encoding='utf-8'))

        provenance = artifact['measurement_provenance']
        self.assertEqual('unknown', provenance['requested_counter_update_mode'])
        self.assertEqual('unavailable', provenance['requested_counter_update_mode_source'])
        self.assertEqual('unknown', provenance['coverage_build']['status'])
        self.assertIn('Coverage build provenance is unavailable', logs.output[0])

    def test_coverage_set_identifies_clang_default_counter_mode(self) -> None:
        '''Verify absent profile update flags are recorded as Clang's single default.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            metadata_path = root / 'coverage-build.json'
            metadata_path.write_text(
                json.dumps(
                    {
                        'requested_cflags': '-O3',
                        'requested_cxxflags': '-O3',
                        'clang_version': 'clang version 18.1.3',
                    }
                ),
                encoding='utf-8',
            )
            artifact_path = root / 'coverage-sets.json'
            with patch.object(coverage_sets, 'COVERAGE_BUILD_METADATA_PATH', metadata_path):
                coverage_sets.write_coverage_sets(artifact_path, {}, {})
            artifact = json.loads(artifact_path.read_text(encoding='utf-8'))

        provenance = artifact['measurement_provenance']
        self.assertEqual('single', provenance['requested_counter_update_mode'])
        self.assertEqual('clang_default', provenance['requested_counter_update_mode_source'])

    def test_coverage_summary_uses_real_total_after_total_prefixed_file(self) -> None:
        report = '''
Filename                               Regions    Missed Regions     Cover   Functions  Missed Functions  Executed       Lines      Missed Lines     Cover    Branches   Missed Branches     Cover
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
/src/alpha.c                                 10                 1    90.00%           4                 1    75.00%          20                 2    90.00%           8                 3    62.50%
/src/TOTALS.c                                99                88    11.11%          77                66    14.29%          55                44    20.00%          33                22    33.33%
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
TOTAL                                        31                 5    83.87%           8                 2    75.00%         100                25    75.00%          40                30    25.00%
'''

        summary = coverage_worker._coverage_summary_from_report(report)

        self.assertEqual(31, summary['cov_regions_total'])
        self.assertEqual(26, summary['cov_regions_covered'])

    def test_coverage_summary_rejects_extra_total_column(self) -> None:
        report = '''
Filename    Regions    Missed Regions    Cover    Functions    Missed Functions    Executed    Lines    Missed Lines    Cover    Branches    Missed Branches    Cover
TOTAL       31         5                 83.87%   8            2                   75.00%      100      25              75.00%   40          30                 25.00%   999
'''

        with self.assertRaisesRegex(ValueError, 'TOTAL row has 13 columns, expected 12'):
            coverage_worker._coverage_summary_from_report(report)

    def test_coverage_summary_parses_all_counts_from_real_header(self) -> None:
        report = '''
Filename                               Regions    Missed Regions     Cover   Functions  Missed Functions  Executed       Lines      Missed Lines     Cover    Branches   Missed Branches     Cover
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
/src/alpha.c                                 10                 1    90.00%           4                 1    75.00%          20                 2    90.00%           8                 3    62.50%
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
TOTAL                                        31                 5    83.87%           8                 2    75.00%         100                25    75.00%          40                30    25.00%
'''

        summary = coverage_worker._coverage_summary_from_report(report)

        self.assertEqual(
            {
                'cov_regions_total': 31,
                'cov_regions_covered': 26,
                'cov_functions_total': 8,
                'cov_functions_covered': 6,
                'cov_lines_total': 100,
                'cov_lines_covered': 75,
                'cov_branches_total': 40,
                'cov_branches_covered': 10,
            },
            summary,
        )

    def test_execute_one_input_preserves_binary_stdin(self) -> None:
        input_bytes = b'\xff\xfe\x00\x80abc'
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_path = root / 'input'
            input_path.write_bytes(input_bytes)
            replayed_path = root / 'replayed'
            target = root / 'target'
            target.write_text(
                f'#!{sys.executable}\n'
                'import pathlib\n'
                'import sys\n'
                f'pathlib.Path({str(replayed_path)!r}).write_bytes(sys.stdin.buffer.read())\n'
                'sys.stdout.buffer.write(b"\\xfflog")\n',
                encoding='utf-8',
            )
            target.chmod(target.stat().st_mode | 0o111)
            profraws_dir = root / 'profraws'
            profraws_dir.mkdir()
            cfg = coverage_worker.WorkerConfig(
                cov_bin=target,
                input_mode='stdin',
                out_dir=root / 'out',
                work_dir=root / 'work',
                input_list=Path(),
                profdata=root / 'merged.profdata',
                timeout_s=5.0,
            )

            result = coverage_worker._execute_one_input(cfg, str(input_path), 0, profraws_dir)
            replayed_bytes = replayed_path.read_bytes()

        self.assertEqual(input_bytes, replayed_bytes)
        self.assertEqual(0, result['returncode'])
        self.assertEqual('\ufffdlog', result['stdout'])

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
                     return_value=subprocess.CompletedProcess(
                         args=['llvm-cov'],
                         returncode=0,
                         stdout=(
                             'Filename    Regions    Missed Regions    Cover    Functions    '
                             'Missed Functions    Executed    Lines    Missed Lines    Cover    '
                             'Branches    Missed Branches    Cover\n'
                             'TOTAL       1          0                 100.00%   1            '
                             '0                   100.00%      1        0               100.00%   '
                             '0           0                  -\n'
                         ),
                         stderr='',
                     ),
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

    def test_run_persists_successful_tool_stderr_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            tool = bin_dir / 'llvm-profdata'
            tool.write_text(
                f'#!{sys.executable}\n'
                'import sys\n'
                'sys.stderr.write("malformed instrumentation profile data\\n")\n',
                encoding='utf-8',
            )
            tool.chmod(tool.stat().st_mode | 0o111)
            out_dir = root / 'out'
            out_dir.mkdir()

            with patch.dict(os.environ, {'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}'}):
                coverage_worker._run(
                    ['llvm-profdata', 'merge'],
                    out_dir=out_dir,
                    label='llvm_profdata_merge_test',
                )

            stderr = (out_dir / 'llvm_profdata_merge_test.stderr.txt').read_text(encoding='utf-8')
            diagnostics = json.loads((out_dir / 'tool_diagnostics.json').read_text(encoding='utf-8'))

        self.assertEqual('malformed instrumentation profile data\n', stderr)
        self.assertEqual(
            {
                'command': ['llvm-profdata', 'merge'],
                'returncode': 0,
                'stderr_line_count': 1,
                'warnings': ['malformed instrumentation profile data'],
            },
            diagnostics['llvm_profdata_merge_test'],
        )

    def test_run_records_timeout_before_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            timeout = subprocess.TimeoutExpired(
                cmd=['llvm-cov', 'show'],
                timeout=12,
                output='partial output',
                stderr='partial warning\n',
            )

            with patch.dict(os.environ, {'FM_LLVM_TOOL_TIMEOUT_S': '12'}), \
                 patch.object(coverage_worker.subprocess, 'run', side_effect=timeout):
                with self.assertRaisesRegex(RuntimeError, 'llvm_cov_show timed out after 12 seconds'):
                    coverage_worker._run(
                        ['llvm-cov', 'show'],
                        out_dir=out_dir,
                        label='llvm_cov_show',
                        check=False,
                    )

            diagnostics = json.loads((out_dir / 'tool_diagnostics.json').read_text(encoding='utf-8'))

        self.assertEqual(
            {
                'command': ['llvm-cov', 'show'],
                'returncode': None,
                'stderr_line_count': 1,
                'warnings': ['partial warning'],
                'timed_out': True,
            },
            diagnostics['llvm_cov_show'],
        )

    def test_run_truncates_rollup_warnings_and_skips_empty_stderr_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            stderr = ''.join(f'warning {index}\n' for index in range(201))

            with patch.object(
                coverage_worker.subprocess,
                'run',
                side_effect=[
                    subprocess.CompletedProcess(args=['tool'], returncode=0, stdout='', stderr=stderr),
                    subprocess.CompletedProcess(args=['quiet-tool'], returncode=0, stdout='', stderr=''),
                ],
            ):
                coverage_worker._run(['tool'], out_dir=out_dir, label='tool')
                coverage_worker._run(['quiet-tool'], out_dir=out_dir, label='quiet_tool')

            diagnostics = json.loads((out_dir / 'tool_diagnostics.json').read_text(encoding='utf-8'))
            quiet_stderr_exists = (out_dir / 'quiet_tool.stderr.txt').exists()

        self.assertEqual(201, diagnostics['tool']['stderr_line_count'])
        self.assertEqual(200, len(diagnostics['tool']['warnings']))
        self.assertTrue(diagnostics['tool']['truncated'])
        self.assertFalse(quiet_stderr_exists)
        self.assertEqual([], diagnostics['quiet_tool']['warnings'])

    def test_run_logs_unchecked_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)

            with patch.object(
                coverage_worker.subprocess,
                'run',
                return_value=subprocess.CompletedProcess(args=['llvm-cov'], returncode=1, stdout='', stderr='failed'),
            ), self.assertLogs(coverage_worker.LOG, level='WARNING') as logs:
                coverage_worker._run(
                    ['llvm-cov', 'show'],
                    out_dir=out_dir,
                    label='llvm_cov_show',
                    check=False,
                )

        self.assertIn('llvm_cov_show failed rc=1', logs.output[0])


if __name__ == '__main__':
    unittest.main()
