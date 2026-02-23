# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for campaign coverage report wiring.'''

from __future__ import annotations

import json
import tempfile
import unittest

from pathlib import Path

from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.db.snapshot import upsert_agg_snapshot, update_agg_snapshot_coverage
from fuzzmeter.reporting.analyzers.coverage_analysis import CoverageAnalysis
from fuzzmeter.reporting.generate import ReportBuilder
from fuzzmeter.reporting.metrics import mann_whitney_u_pvalue, vargha_delaney_a12
from fuzzmeter.snapshot.aggregate import SnapshotAggregateUpdater


def _coverage_export(branch_line: int) -> dict:
    return {
        'type': 'llvm.coverage.json.export',
        'version': '2.0.1',
        'data': [
            {
                'files': [
                    {
                        'filename': '/src/target.c',
                        'branches': [[branch_line, 1, branch_line, 2, 1, 0, 0]],
                        'segments': [[branch_line, 1, 1]],
                    }
                ],
                'functions': [],
                'totals': {
                    'branches': {'count': 1, 'covered': 1},
                    'functions': {'count': 0, 'covered': 0},
                    'lines': {'count': 1, 'covered': 1},
                    'regions': {'count': 1, 'covered': 1},
                },
            }
        ],
    }


class CoverageReportingTest(unittest.TestCase):
    '''Verify fuzzer-level campaign coverage artifacts are exposed in reports.'''

    def test_exclusive_coverage_stats_use_other_fuzzer_union(self) -> None:
        analysis = CoverageAnalysis(
            cov_metrics=('branches',),
            final_output_dist_keys=('branches_cov',),
            curve_max_points=100,
            safe_int=lambda value: None if value is None else int(value),
            mean=lambda values: sum(values) / len(values) if values else None,
            median=lambda values: sorted(values)[len(values) // 2] if values else None,
            minimum=lambda values: min(values) if values else None,
            maximum=lambda values: max(values) if values else None,
            mann_whitney_u_pvalue=mann_whitney_u_pvalue,
            vargha_delaney_a12=vargha_delaney_a12,
            dt=lambda value: None if value is None else str(value),
        )

        target = {
            'fuzzers': [
                {'fuzzer': 'left'},
                {'fuzzer': 'right'},
            ],
            'unique_matrix': {
                'by_metric': {
                    'branches': {
                        'fuzzers': ['left', 'right'],
                        'matrix': [[0, 2], [1, 0]],
                        'unique_counts': [2, 1],
                        'note': None,
                    }
                }
            },
        }

        analysis.attach_exclusive_coverage_stats(target=target)

        self.assertEqual(
            {'metric': 'branches', 'total': 2, 'min': None, 'max': None, 'median': None, 'note': None},
            target['fuzzers'][0]['exclusive_coverage'],
        )
        self.assertEqual(
            {'metric': 'branches', 'total': 1, 'min': None, 'max': None, 'median': None, 'note': None},
            target['fuzzers'][1]['exclusive_coverage'],
        )

    def test_report_curve_preserves_cumulative_metric_decreases(self) -> None:
        analysis = CoverageAnalysis(
            cov_metrics=('branches',),
            final_output_dist_keys=('branches_cov', 'execs_done'),
            curve_max_points=100,
            safe_int=lambda value: None if value is None else int(value),
            mean=lambda values: sum(values) / len(values) if values else None,
            median=lambda values: sorted(values)[len(values) // 2] if values else None,
            minimum=lambda values: min(values) if values else None,
            maximum=lambda values: max(values) if values else None,
            mann_whitney_u_pvalue=mann_whitney_u_pvalue,
            vargha_delaney_a12=vargha_delaney_a12,
            dt=lambda value: None if value is None else str(value),
        )

        curve = analysis.build_curve(
            [{'trial_id': 1}],
            {
                1: [
                    {'idx': 1, 'ordinal': 1, 'elapsed_s': 10, 'branches_cov': 5, 'execs_done': 100},
                    {'idx': 2, 'ordinal': 2, 'elapsed_s': 20, 'branches_cov': 4, 'execs_done': 90},
                ]
            },
        )

        self.assertEqual(5, curve[0]['branches_cov_mean'])
        self.assertEqual(4, curve[1]['branches_cov_mean'])
        self.assertEqual(100, curve[0]['execs_done_mean'])
        self.assertEqual(90, curve[1]['execs_done_mean'])

    def test_report_curve_aligns_repetitions_by_elapsed_time(self) -> None:
        analysis = CoverageAnalysis(
            cov_metrics=('branches',),
            final_output_dist_keys=('branches_cov',),
            curve_max_points=100,
            safe_int=lambda value: None if value is None else int(value),
            mean=lambda values: sum(values) / len(values) if values else None,
            median=lambda values: sorted(values)[len(values) // 2] if values else None,
            minimum=lambda values: min(values) if values else None,
            maximum=lambda values: max(values) if values else None,
            mann_whitney_u_pvalue=mann_whitney_u_pvalue,
            vargha_delaney_a12=vargha_delaney_a12,
            dt=lambda value: None if value is None else str(value),
        )

        curve = analysis.build_curve(
            [{'trial_id': 1}, {'trial_id': 2}],
            {
                1: [
                    {'idx': 1, 'ordinal': 1, 'elapsed_s': 60, 'branches_cov': 10},
                    {'idx': 2, 'ordinal': 2, 'elapsed_s': 300, 'branches_cov': 20},
                ],
                2: [
                    {'idx': 29, 'ordinal': 1, 'elapsed_s': 300, 'branches_cov': 30},
                ],
            },
        )

        self.assertEqual(60, curve[0]['elapsed_s'])
        self.assertEqual(10, curve[0]['branches_cov_mean'])
        self.assertEqual(300, curve[1]['elapsed_s'])
        self.assertEqual(25, curve[1]['branches_cov_mean'])

    def test_branch_stat_matrices_use_final_trial_branch_coverage(self) -> None:
        analysis = CoverageAnalysis(
            cov_metrics=('branches',),
            final_output_dist_keys=('branches_cov',),
            curve_max_points=100,
            safe_int=lambda value: None if value is None else int(value),
            mean=lambda values: sum(values) / len(values) if values else None,
            median=lambda values: sorted(values)[len(values) // 2] if values else None,
            minimum=lambda values: min(values) if values else None,
            maximum=lambda values: max(values) if values else None,
            mann_whitney_u_pvalue=mann_whitney_u_pvalue,
            vargha_delaney_a12=vargha_delaney_a12,
            dt=lambda value: None if value is None else str(value),
        )

        trials = [
            {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'alpha', 'coverage': {'branches_covered': 100}},
            {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'alpha', 'coverage': {'branches_covered': 101}},
            {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'beta', 'coverage': {'branches_covered': 10}},
            {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'beta', 'coverage': {'branches_covered': 11}},
        ]

        branch_mwu_matrix, branch_a12_matrix = analysis.compute_branch_stat_matrices(
            trials=trials,
            benchmark='bench',
            fuzz_target='target',
        )

        mwu = branch_mwu_matrix['by_metric']['branches']
        a12 = branch_a12_matrix['by_metric']['branches']
        self.assertEqual(['alpha', 'beta'], mwu['fuzzers'])
        self.assertEqual([2, 2], mwu['sample_sizes'])
        self.assertAlmostEqual(mann_whitney_u_pvalue([100, 101], [10, 11]), mwu['matrix'][0][1])
        self.assertAlmostEqual(1.0, a12['matrix'][0][1])
        self.assertAlmostEqual(0.0, a12['matrix'][1][0])

    def test_overview_elapsed_uses_trial_time_not_snapshot_wall_time(self) -> None:
        builder = ReportBuilder.__new__(ReportBuilder)
        builder._overview_raw = {'created_ts': 50}
        builder._trial_rows = [
            {'started_ts': 100, 'ended_ts': 450, 'time_seconds': 300},
            {'started_ts': 500, 'ended_ts': 850, 'time_seconds': 300},
        ]
        builder._snapshot_rows = [{'ts': 900}]

        overview = builder.collect_overview()

        self.assertEqual(300, overview['elapsed_seconds'])
        self.assertEqual(800, overview['wall_elapsed_seconds'])

    def test_campaign_profdata_paths_include_inactive_repetitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            db = DB.open(run_dir / 'fuzzmeter.db')
            try:
                ensure_schema(db)
                db.exec('INSERT INTO runs(run_id, created_ts, suite_yaml) VALUES(?,?,?)', ('run', 1, 'suite'))
                for rep in (0, 1, 2):
                    db.exec(
                        '''
                        INSERT INTO trials(run_id, fuzzer, benchmark, fuzz_target, rep, status)
                        VALUES(?,?,?,?,?,?)
                        ''',
                        ('run', 'libfuzzer', 'jerryscript', 'jerry', rep, 'done'),
                    )
                    profdata = (
                        run_dir
                        / 'trials'
                        / f'libfuzzer__jerryscript-jerry__rep{rep}'
                        / 'coverage_state'
                        / 'merged.profdata'
                    )
                    profdata.parent.mkdir(parents=True)
                    profdata.write_bytes(b'x' * 128)

                paths = SnapshotAggregateUpdater._campaign_profdata_paths(
                    db=db,
                    run_dir=run_dir,
                    run_id='run',
                    fuzzer='libfuzzer',
                    benchmark='jerryscript',
                    fuzz_target='jerry',
                )
            finally:
                db.close()

            self.assertEqual(3, len(paths))
            self.assertTrue(all(path.exists() for path in paths))
            self.assertTrue(str(paths[-1]).endswith('libfuzzer__jerryscript-jerry__rep2/coverage_state/merged.profdata'))

    def test_report_links_campaign_coverage_per_fuzzer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            db = DB.open(run_dir / 'fuzzmeter.db')
            try:
                ensure_schema(db)
                db.exec('INSERT INTO runs(run_id, created_ts, suite_yaml) VALUES(?,?,?)', ('run', 1, 'suite'))
                db.exec(
                    '''
                    INSERT INTO trials(run_id, fuzzer, benchmark, fuzz_target, rep, started_ts, ended_ts, status)
                    VALUES(?,?,?,?,?,?,?,?)
                    ''',
                    ('run', 'fz', 'bench', 'target', 1, 1, 3, 'done'),
                )
                trial_id = int(db.scalar('SELECT trial_id FROM trials'))
                db.exec(
                    '''
                    INSERT INTO snapshots(
                      trial_id, idx, ts, corpus_files, cov_branches_covered, cov_branches_total,
                      cov_lines_covered, cov_lines_total, cov_regions_covered, cov_regions_total,
                      cov_functions_covered, cov_functions_total
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    ''',
                    (trial_id, 1, 3, 1, 1, 1, 1, 1, 1, 1, 0, 0),
                )

                campaign_root = run_dir / 'coverage' / 'fz' / 'bench' / 'target' / 'campaign'
                html_index = campaign_root / 'html' / 'index.html'
                html_index.parent.mkdir(parents=True)
                html_index.write_text('<!doctype html>', encoding='utf-8')
                (campaign_root / 'coverage.json').write_text(json.dumps(_coverage_export(10)), encoding='utf-8')

                agg_id = upsert_agg_snapshot(
                    db,
                    run_id='run',
                    fuzzer='fz',
                    benchmark='bench',
                    fuzz_target='target',
                    idx=1,
                    ts=3,
                )
                update_agg_snapshot_coverage(
                    db,
                    agg_snapshot_id=agg_id,
                    coverage_html_dir=str(html_index.relative_to(run_dir)),
                    summary={
                        'cov_branches_covered': 1,
                        'cov_branches_total': 1,
                        'cov_lines_covered': 1,
                        'cov_lines_total': 1,
                        'cov_regions_covered': 1,
                        'cov_regions_total': 1,
                        'cov_functions_covered': 0,
                        'cov_functions_total': 0,
                    },
                )
                db.commit()
            finally:
                db.close()

            payload = ReportBuilder(run_dir, run_id='run').build()
            fuzzer = payload['targets'][0]['fuzzers'][0]
            self.assertEqual('../coverage/fz/bench/target/campaign/html/index.html', fuzzer['coverage_report'])
            self.assertEqual(1, fuzzer['aggregate']['branches_covered'])

    def test_single_fuzzer_report_skips_pairwise_matrices(self) -> None:
        builder = ReportBuilder.__new__(ReportBuilder)
        target = {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzers': [{'fuzzer': 'fz'}]}

        result = builder.create_matrices([target], [])

        self.assertFalse(result[0]['unique_matrix']['has_data'])
        self.assertFalse(result[0]['relcov_matrix']['has_data'])
        self.assertFalse(result[0]['branch_mwu_matrix']['has_data'])
        self.assertFalse(result[0]['branch_a12_matrix']['has_data'])
        self.assertEqual({}, result[0]['relcov_score_by_fuzzer'])
        self.assertFalse(result[0]['unique_bug_table']['has_data'])
        self.assertFalse(result[0]['unique_bug_matrix']['has_data'])
        self.assertFalse(result[0]['relbug_matrix']['has_data'])
        self.assertEqual({}, result[0]['relbug_score_by_fuzzer'])


if __name__ == '__main__':
    unittest.main()
