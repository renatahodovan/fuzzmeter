# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for campaign coverage report wiring.'''

from __future__ import annotations

import json
import math
import tempfile
import unittest

from pathlib import Path
from unittest.mock import Mock

from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.db.snapshot import (
    CoverageSummary,
    insert_tick,
    mark_tick_completed,
    update_agg_snapshot_coverage,
    upsert_agg_snapshot,
)
from fuzzmeter.reporting.analyzers import coverage_curves, coverage_matrices
from fuzzmeter.reporting.metrics import (
    clean_floats,
    dt,
    mann_whitney_u_pvalue,
    maximum,
    mean,
    median,
    minimum,
    pct,
    safe_int,
    trapezoid_auc,
    vargha_delaney_a12,
)
from fuzzmeter.reporting.payload import _PayloadBuilder
from tests.support.dbs import agg_snapshot_row, run_data_snapshot, snapshot_row, trial_report, trial_row


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


class ReportingMetricsTest(unittest.TestCase):
    '''Characterize reporting metric helper behavior.'''

    def test_basic_conversion_helpers_keep_current_error_handling(self) -> None:
        self.assertEqual('1970-01-01 00:00:00 UTC', dt(0))
        self.assertIsNone(dt(None))
        self.assertIsNone(dt('not-a-timestamp'))

        self.assertEqual(7, safe_int('7'))
        self.assertEqual(3, safe_int(3.9))
        self.assertIsNone(safe_int(None))
        self.assertIsNone(safe_int('3.5'))

        self.assertEqual(25.0, pct(1, 4))
        self.assertIsNone(pct(None, 4))
        self.assertIsNone(pct(1, None))
        self.assertIsNone(pct(1, 0))

    def test_collection_stats_ignore_none_non_numbers_and_nan(self) -> None:
        values = [None, '4', 1, 3.0, math.nan, True, math.inf]

        cleaned = clean_floats(values)

        self.assertEqual([math.inf, 1.0], clean_floats([math.inf, math.nan, None, 1.0]))
        self.assertEqual([1.0, 3.0, 1.0, math.inf], cleaned)
        self.assertEqual(math.inf, mean(values))
        self.assertEqual(2.0, median(values))
        self.assertEqual(1.0, minimum(values))
        self.assertEqual(math.inf, maximum(values))
        self.assertIsNone(mean([None, '4', math.nan]))
        self.assertIsNone(median([None, '4', math.nan]))
        self.assertIsNone(minimum([None, '4', math.nan]))
        self.assertIsNone(maximum([None, '4', math.nan]))

    def test_trapezoid_auc_sorts_collapses_and_extends_points(self) -> None:
        self.assertEqual(
            115.0,
            trapezoid_auc(
                [
                    (10, 2),
                    (5, 4),
                    (5, 8),
                    (-1, 100),
                    (20, math.nan),
                    (15, 6),
                ],
                duration_s=20,
            ),
        )
        self.assertEqual(30.0, trapezoid_auc([(5, 3)], duration_s=10))
        self.assertEqual(15.0, trapezoid_auc([(5, 3)]))
        self.assertEqual(0.0, trapezoid_auc([(0, 7)]))
        self.assertIsNone(trapezoid_auc([]))

    def test_pairwise_statistics_preserve_tie_behavior(self) -> None:
        self.assertAlmostEqual(0.12118327283746333, mann_whitney_u_pvalue([1, 2, 3], [3, 4, 5]))
        self.assertAlmostEqual(0.6192567541768622, mann_whitney_u_pvalue([1, 1, 2], [1, 2, 2]))
        self.assertEqual(1.0, mann_whitney_u_pvalue([1, 4], [2, 3]))
        self.assertIsNone(mann_whitney_u_pvalue([1], [2, 3]))
        self.assertIsNone(mann_whitney_u_pvalue([1, 1], [1, 1]))

        self.assertEqual(0.5, vargha_delaney_a12([1, 2, 3], [2, 2]))
        self.assertIsNone(vargha_delaney_a12([], [2]))


class CoverageReportingTest(unittest.TestCase):
    '''Verify fuzzer-level campaign coverage artifacts are exposed in reports.'''

    def test_aggregate_scalars_use_report_counts_without_set_reconciliation(self) -> None:
        builder = _PayloadBuilder.__new__(_PayloadBuilder)
        builder._data = run_data_snapshot(latest_agg_snapshots={
            ('fz', 'bench', 'target'): agg_snapshot_row(
                cov_branches_covered=3,
                cov_lines_covered=4,
                cov_functions_covered=5,
                cov_regions_covered=6,
            )
        })
        builder._coverage_data = Mock()
        builder._coverage_data.covered_counts.return_value = {
            'branches_covered': 99,
            'lines_covered': 99,
            'functions_covered': 99,
            'regions_covered': 99,
        }

        result = builder._aggregated_coverage_for_fuzzer('fz', 'bench', 'target')

        self.assertEqual(
            {
                'branches_covered': 3,
                'lines_covered': 4,
                'functions_covered': 5,
                'regions_covered': 6,
            },
            result,
        )
        builder._coverage_data.covered_counts.assert_not_called()

    def test_exclusive_coverage_stats_use_other_fuzzer_union(self) -> None:
        target = {
            'fuzzers': [
                {'fuzzer': 'left'},
                {'fuzzer': 'right'},
            ],
            'unique_matrix': {
                'by_metric': {
                    'branches': {
                        'fuzzers': ['left', 'right'],
                        'exclusive': {
                            'exclusive_any': [1, 1],
                            'exclusive_all': [0, 1],
                            'exclusive_any_bounds': ['exact', 'exact'],
                            'exclusive_all_bounds': ['exact', 'exact'],
                        },
                        'note': None,
                    }
                }
            },
        }

        coverage_matrices.attach_exclusive_coverage_stats(
            target=target,
            trial_coverage_sets_by_metric={
                'branches': {
                    'left': [{'left-only', 'shared'}, {'shared'}],
                    'right': [{'right-only', 'shared'}],
                }
            },
        )

        self.assertEqual(
            {
                'metric': 'branches',
                'exclusive_any': 1,
                'exclusive_all': 0,
                'exclusive_any_bound': 'exact',
                'exclusive_all_bound': 'exact',
                'min': 0,
                'max': 1,
                'median': 0.5,
                'sample_size': 2,
                'usable_sample_size': 2,
                'note': None,
            },
            target['fuzzers'][0]['exclusive_coverage'],
        )
        self.assertEqual(
            {
                'metric': 'branches',
                'exclusive_any': 1,
                'exclusive_all': 1,
                'exclusive_any_bound': 'exact',
                'exclusive_all_bound': 'exact',
                'min': 1,
                'max': 1,
                'median': 1.0,
                'sample_size': 1,
                'usable_sample_size': 1,
                'note': None,
            },
            target['fuzzers'][1]['exclusive_coverage'],
        )

    def test_unique_coverage_uses_trial_variants_and_missing_bounds(self) -> None:
        group = coverage_matrices.compute_unique_matrix(
            cov_metrics=('branches',),
            fuzzers=['alpha', 'beta'],
            trial_coverage_sets_by_metric={
                'branches': {
                    'alpha': [{'alpha-only'}, None],
                    'beta': [{'beta-only'}, {'beta-only'}],
                }
            },
        )

        matrix = group['by_metric']['branches']
        self.assertEqual([[0, 1], [1, 0]], matrix['pairwise_unique_any'])
        self.assertEqual([[None, None], [1, 0]], matrix['pairwise_unique_all'])
        self.assertEqual(['lower', 'upper'], matrix['exclusive']['exclusive_any_bounds'])
        self.assertEqual([None, 1], matrix['exclusive']['exclusive_all'])
        self.assertNotIn(0, matrix['pairwise_unique_all'][0])

    def test_report_curve_preserves_cumulative_metric_decreases(self) -> None:
        curve = coverage_curves.build_curve(
            [trial_report(trial_id=1)],
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
        curve = coverage_curves.build_curve(
            [trial_report(trial_id=1), trial_report(trial_id=2)],
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
        trials = [
            {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'alpha', 'branches_cov': 100},
            {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'alpha', 'branches_cov': 101},
            {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'beta', 'branches_cov': 10},
            {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'beta', 'branches_cov': 11},
        ]

        branch_mwu_matrix, branch_a12_matrix = coverage_matrices.compute_branch_stat_matrices(
            fuzzers=['alpha', 'beta'],
            branch_coverage_by_fuzzer={
                'alpha': [trial['branches_cov'] for trial in trials if trial['fuzzer'] == 'alpha'],
                'beta': [trial['branches_cov'] for trial in trials if trial['fuzzer'] == 'beta'],
            },
        )

        mwu = branch_mwu_matrix['by_metric']['branches']
        a12 = branch_a12_matrix['by_metric']['branches']
        self.assertEqual(['alpha', 'beta'], mwu['fuzzers'])
        self.assertEqual([2, 2], mwu['sample_sizes'])
        self.assertAlmostEqual(mann_whitney_u_pvalue([100, 101], [10, 11]), mwu['matrix'][0][1])
        self.assertAlmostEqual(1.0, a12['matrix'][0][1])
        self.assertAlmostEqual(0.0, a12['matrix'][1][0])

    def test_relcov_matrix_uses_trial_median_against_column_union(self) -> None:
        matrix_group, scores = coverage_matrices.compute_relcov_matrix(
            cov_metrics=('branches',),
            fuzzers=['alpha', 'beta'],
            trial_coverage_sets_by_metric={
                'branches': {
                    'alpha': [{'a', 'b'}, set()],
                    'beta': [{'a', 'b', 'c'}],
                }
            },
        )

        matrix = matrix_group['by_metric']['branches']
        self.assertEqual(['alpha', 'beta'], matrix['fuzzers'])
        self.assertEqual([[50.0, 33.333333333333336], [100.0, 100.0]], matrix['matrix'])
        self.assertEqual({'alpha': 0.0, 'beta': 1.0}, scores)

    def test_overview_elapsed_uses_trial_time_not_snapshot_wall_time(self) -> None:
        builder = _PayloadBuilder.__new__(_PayloadBuilder)
        builder._data = run_data_snapshot(
            overview_raw={'created_ts': 50},
            trial_rows=[
                trial_row(started_ts=100, ended_ts=450, time_seconds=300),
                trial_row(started_ts=500, ended_ts=850, time_seconds=300),
            ],
            snapshot_rows=[snapshot_row(ts=900)],
        )

        overview = builder.collect_overview([trial_report(elapsed_seconds=300), trial_report(elapsed_seconds=300)])

        self.assertEqual(300, overview['elapsed_seconds'])
        self.assertEqual(800, overview['wall_elapsed_seconds'])

    def test_overview_elapsed_reuses_the_measured_trial_runtimes(self) -> None:
        builder = _PayloadBuilder.__new__(_PayloadBuilder)
        builder._data = run_data_snapshot(
            overview_raw={'created_ts': 50},
            trial_rows=[trial_row(started_ts=100, ended_ts=None, time_seconds=86400)],
            snapshot_rows=[snapshot_row(ts=160)],
        )

        overview = builder.collect_overview([trial_report(elapsed_seconds=60)])

        self.assertEqual(60, overview['elapsed_seconds'])
        self.assertEqual(60, overview['wall_elapsed_seconds'])

    def test_overview_surfaces_failed_snapshot_tick_count(self) -> None:
        builder = _PayloadBuilder.__new__(_PayloadBuilder)
        builder._data = run_data_snapshot(overview_raw={'created_ts': 50, 'failed_snapshot_ticks': 2})

        overview = builder.collect_overview([])

        self.assertEqual(2, overview['failed_snapshot_ticks'])

    def test_report_links_campaign_coverage_per_fuzzer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            db = DB.open(run_dir / 'fuzzmeter.db')
            try:
                ensure_schema(db)
                db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run', 1, 'config'))
                db.exec(
                    '''
                    INSERT INTO trials(
                      run_id, fuzzer, benchmark, fuzz_target, rep, time_seconds, started_ts, ended_ts, status
                    )
                    VALUES(?,?,?,?,?,?,?,?,?)
                    ''',
                    ('run', 'fz', 'bench', 'target', 1, 2, 1, 3, 'done'),
                )
                trial_id = int(db.scalar('SELECT trial_id FROM trials'))
                insert_tick(db, run_id='run', idx=1, ts=3)
                mark_tick_completed(db, run_id='run', idx=1)
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
                    coverage=CoverageSummary.from_mapping(
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
                    ),
                )
                db.commit()
            finally:
                db.close()

            payload = _PayloadBuilder(run_dir, run_id='run').build()
            fuzzer = payload['targets'][0]['fuzzers'][0]
            self.assertEqual('../coverage/fz/bench/target/campaign/html/index.html', fuzzer['coverage_report'])
            self.assertEqual(1, fuzzer['aggregate']['branches_covered'])

    def test_single_fuzzer_report_skips_pairwise_matrices(self) -> None:
        builder = _PayloadBuilder.__new__(_PayloadBuilder)
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
