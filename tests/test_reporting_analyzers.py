# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Test reporting analyzer behavior before cleanup refactors.'''

from __future__ import annotations

import random
import unittest

from fuzzmeter.reporting.analyzers import bug_analysis, coverage_curves, target_matrices, trial_analysis
from fuzzmeter.reporting.metrics import median
from fuzzmeter.reporting.payload import _PayloadBuilder
from fuzzmeter.reporting.set_comparison import pairwise_matrix, relative_containment_matrix, trial_set_comparison
from tests.support.dbs import snapshot_row, telemetry_sample, trial_row

COV_METRICS = ('branches',)
CURVE_MAX_POINTS = 100


class TrialAnalysisTest(unittest.TestCase):
    '''Verify trial and time-series analysis behavior.'''

    def test_snapshot_coverage_detection_looks_for_covered_counters(self) -> None:
        self.assertTrue(trial_analysis.snapshot_has_coverage(snapshot_row(cov_branches_covered=1)))
        self.assertTrue(trial_analysis.snapshot_has_coverage(snapshot_row(cov_regions_covered=0)))
        self.assertFalse(trial_analysis.snapshot_has_coverage(snapshot_row(cov_branches_total=4)))
        self.assertFalse(trial_analysis.snapshot_has_coverage(snapshot_row(corpus_files=1)))

    def test_collect_trials_measures_running_trials_from_their_latest_snapshot(self) -> None:
        trials = trial_analysis.collect_trials(
            trial_rows=[
                trial_row(trial_id=1, rep='0', started_ts=100, ended_ts=None, time_seconds=86400, status='running')
            ],
            latest_snapshots={1: snapshot_row(snapshot_id=11, idx=2, ts=160)},
            bug_stats_by_trial={},
            rel_to_url=lambda path: None,
        )

        self.assertEqual(60, trials[0]['elapsed_seconds'])

    def test_collect_trials_reports_a_trial_that_has_no_snapshot_yet(self) -> None:
        trials = trial_analysis.collect_trials(
            trial_rows=[trial_row(trial_id=1, started_ts=100, ended_ts=None, time_seconds=50, status='running')],
            latest_snapshots={},
            bug_stats_by_trial={},
            rel_to_url=lambda path: f'url:{path}' if path else None,
        )

        self.assertIsNone(trials[0]['branches_cov'])
        self.assertIsNone(trials[0]['branches_pct'])
        self.assertIsNone(trials[0]['last_snapshot_ts'])
        self.assertIsNone(trials[0]['corpus_files_total'])
        self.assertIsNone(trials[0]['coverage_html'])
        self.assertEqual(0, trials[0]['elapsed_seconds'])

    def test_collect_trials_uses_latest_snapshot_and_clamps_elapsed_time(self) -> None:
        trials = trial_analysis.collect_trials(
            trial_rows=[
                trial_row(trial_id=1, rep='0', started_ts=100, ended_ts=190, time_seconds=50, jobs=1, status='done')
            ],
            latest_snapshots={
                1: snapshot_row(
                    snapshot_id=11,
                    idx=2,
                    ts=180,
                    corpus_files=4,
                    execs_done=50,
                    crashes=1,
                    coverage_html_dir='coverage/index.html',
                    coverage_sets_json_rel='coverage/coverage-sets.json',
                    cov_branches_covered=2,
                    cov_branches_total=4,
                )
            },
            bug_stats_by_trial={1: (3, 2)},
            rel_to_url=lambda path: f'url:{path}' if path else None,
        )

        self.assertEqual(1, len(trials))
        self.assertEqual(50, trials[0]['elapsed_seconds'])
        self.assertEqual(2, trials[0]['branches_cov'])
        self.assertEqual(50.0, trials[0]['branches_pct'])
        self.assertEqual('url:coverage/index.html', trials[0]['coverage_html'])
        self.assertEqual('coverage/coverage-sets.json', trials[0]['coverage_sets_json_rel'])
        self.assertEqual(3, trials[0]['bug_hits_total'])
        self.assertEqual(2, trials[0]['unique_bugs_total'])

    def test_collect_timeseries_merges_resources_and_cumulative_bug_counts(self) -> None:
        timeseries = trial_analysis.collect_timeseries(
            trials=[
                {
                    'trial_id': 1,
                    'fuzzer': 'fz',
                    'benchmark': 'bench',
                    'fuzz_target': 'target',
                    'started_ts': 100,
                    'time_seconds': 50,
                }
            ],
            snapshot_rows=[
                snapshot_row(
                    snapshot_id=10,
                    idx=1,
                    ts=120,
                    corpus_files=2,
                    execs_done=10,
                    crashes=1,
                    stats_json='{"execs_per_sec": "5.5"}',
                    cov_branches_covered=1,
                    cov_branches_total=2,
                ),
                snapshot_row(
                    snapshot_id=11,
                    idx=2,
                    ts=180,
                    corpus_files=4,
                    execs_done=30,
                    crashes=2,
                    cov_branches_covered=2,
                    cov_branches_total=4,
                ),
            ],
            resource_telemetry_rows=[
                telemetry_sample(
                    ts=121,
                    cpu_percent=12.5,
                    memory_percent=25.0,
                    memory_usage_bytes=2 * 1024 * 1024,
                    memory_limit_bytes=8 * 1024 * 1024,
                    corpus_disk_usage_bytes=3 * 1024 * 1024,
                )
            ],
            bug_hits_by_snapshot={10: 2, 11: 3},
            unique_bug_delta_by_snapshot={10: 1},
        )

        points = timeseries['per_trial']['1']['points']
        self.assertEqual([1, 2], [point['idx'] for point in points])
        self.assertEqual([20.0, 50.0], [point['elapsed_s'] for point in points])
        self.assertEqual([2, 5], [point['bug_hits_total'] for point in points])
        self.assertEqual([1, 1], [point['unique_bugs_total'] for point in points])
        self.assertEqual([1, 3], [point['crashes_total'] for point in points])
        self.assertEqual(2.0, points[0]['resource_memory_mib'])
        self.assertEqual(3.0, points[0]['resource_corpus_disk_mib'])
        self.assertEqual(50.0, points[1]['branches_pct'])


class BugAnalysisBehaviorTest(unittest.TestCase):
    '''Verify bug comparison and exclusivity behavior.'''

    def test_exclusive_bug_stats_use_other_fuzzer_union(self) -> None:
        target = {
            'fuzzers': [
                {
                    'fuzzer': 'alpha',
                    'trials': [{'trial_id': 1}, {'trial_id': 2}],
                    'bugs': [
                        {'bug_key': 'a', 'trial_ids': [1]},
                        {'bug_key': 'b', 'trial_ids': [1, 2]},
                    ],
                },
                {
                    'fuzzer': 'beta',
                    'trials': [{'trial_id': 3}],
                    'bugs': [{'bug_key': 'b', 'trial_ids': [3]}],
                },
            ]
        }

        matrix = bug_analysis.compute_unique_bug_matrix(target)
        target['unique_bug_matrix'] = matrix
        bug_analysis.attach_exclusive_bug_stats(target)

        self.assertEqual([[0, 1], [0, 0]], matrix['pairwise_unique_any'])
        self.assertEqual([[0, 0], [0, 0]], matrix['pairwise_unique_all'])
        self.assertEqual(
            {
                'exclusive_any': 1,
                'exclusive_all': 0,
                'exclusive_any_bound': 'exact',
                'exclusive_all_bound': 'exact',
                'min': 0,
                'max': 1,
                'median': 0.5,
                'sample_size': 2,
                'usable_sample_size': 2,
            },
            target['fuzzers'][0]['exclusive_bugs'],
        )
        self.assertEqual(
            {
                'exclusive_any': 0,
                'exclusive_all': 0,
                'exclusive_any_bound': 'exact',
                'exclusive_all_bound': 'exact',
                'min': 0,
                'max': 0,
                'median': 0.0,
                'sample_size': 1,
                'usable_sample_size': 1,
            },
            target['fuzzers'][1]['exclusive_bugs'],
        )

    def test_missing_bug_trial_propagates_unknown_and_degraded_states(self) -> None:
        target = {
            'fuzzers': [
                {
                    'fuzzer': 'alpha',
                    'trials': [{'trial_id': 1}, {'trial_id': 2, 'bug_set_missing': True}],
                    'bugs': [{'bug_key': 'a', 'trial_ids': [1]}],
                },
                {
                    'fuzzer': 'beta',
                    'trials': [{'trial_id': 3}, {'trial_id': 4}],
                    'bugs': [{'bug_key': 'b', 'trial_ids': [3, 4]}],
                },
            ]
        }

        target['unique_bug_matrix'] = bug_analysis.compute_unique_bug_matrix(target)
        bug_analysis.attach_exclusive_bug_stats(target)

        alpha = target['fuzzers'][0]['exclusive_bugs']
        beta = target['fuzzers'][1]['exclusive_bugs']
        self.assertEqual((1, 'lower'), (alpha['exclusive_any'], alpha['exclusive_any_bound']))
        self.assertEqual((None, 'unknown'), (alpha['exclusive_all'], alpha['exclusive_all_bound']))
        self.assertEqual((1, 'upper'), (beta['exclusive_any'], beta['exclusive_any_bound']))
        self.assertEqual((1, 'upper'), (beta['exclusive_all'], beta['exclusive_all_bound']))

    def test_relative_bug_matrix_and_scores_use_trial_sets(self) -> None:
        matrix, scores = bug_analysis.compute_rel_bug_matrix(
            {
                'fuzzers': [
                    {
                        'fuzzer': 'alpha',
                        'trials': [{'trial_id': 1}, {'trial_id': 2}],
                        'bugs': [
                            {'bug_key': 'a', 'trial_ids': [1]},
                            {'bug_key': 'b', 'trial_ids': [1, 2]},
                        ],
                    },
                    {
                        'fuzzer': 'beta',
                        'trials': [{'trial_id': 3}],
                        'bugs': [{'bug_key': 'b', 'trial_ids': [3]}],
                    },
                ]
            }
        )

        self.assertEqual(['alpha', 'beta'], matrix['fuzzers'])
        self.assertEqual([[75.0, 100.0], [50.0, 100.0]], matrix['matrix'])
        self.assertEqual({'alpha': 0.5, 'beta': 0.0}, scores)

    def test_integer_bug_median_matches_shared_metric_median_cases(self) -> None:
        for values in ([], [0], [0, 0], [1, 2, 3]):
            self.assertEqual(median(values), _bug_exclusive_median(values))


class TrialSetComparisonTest(unittest.TestCase):
    '''Verify strict/non-strict set comparison semantics and uncertainty.'''

    def test_pairwise_matrix_skips_diagonal_and_preserves_missing_cells(self) -> None:
        calls: list[tuple[list[float], list[float]]] = []

        def compare(left: list[float], right: list[float]) -> float | None:
            calls.append((left, right))
            if len(left) < 2 or len(right) < 2:
                return None
            return left[0] + right[0]

        result = pairwise_matrix(
            ['alpha', 'beta', 'gamma'],
            {'alpha': [1.0], 'beta': [2.0, 3.0], 'gamma': [4.0, 5.0]},
            compare=compare,
        )

        self.assertEqual(
            [[None, None, None], [None, None, 6.0], [None, 6.0, None]],
            result['matrix'],
        )
        self.assertEqual(6.0, result['max_value'])
        self.assertEqual(6, len(calls))

    def test_disagreeing_trials_exclude_flaky_values_from_strict_counts(self) -> None:
        result = trial_set_comparison(
            ['alpha', 'beta'],
            {
                'alpha': [{'a', 'shared', 'flaky'}, {'a', 'shared'}],
                'beta': [{'shared', 'b'}, {'shared', 'b'}],
            },
        )

        self.assertEqual([[0, 2], [1, 0]], result['pairwise_unique_any'])
        self.assertEqual([[0, 1], [1, 0]], result['pairwise_unique_all'])
        self.assertEqual([2, 1], result['exclusive']['exclusive_any'])
        self.assertEqual([1, 1], result['exclusive']['exclusive_all'])

    def test_single_repetition_makes_strict_and_non_strict_identical(self) -> None:
        result = trial_set_comparison(
            ['alpha', 'beta'],
            {'alpha': [{'a', 'shared'}], 'beta': [{'b', 'shared'}]},
        )

        self.assertEqual(result['pairwise_unique_any'], result['pairwise_unique_all'])
        self.assertEqual(
            result['exclusive']['exclusive_any'],
            result['exclusive']['exclusive_all'],
        )

    def test_randomized_strict_counts_never_exceed_non_strict_counts(self) -> None:
        rng = random.Random(1234)
        for _ in range(100):
            trial_sets = {
                label: [
                    {str(value) for value in range(12) if rng.random() < 0.35}
                    for _ in range(rng.randint(1, 5))
                ]
                for label in ('alpha', 'beta', 'gamma')
            }
            result = trial_set_comparison(list(trial_sets), trial_sets)
            for any_row, all_row in zip(
                result['pairwise_unique_any'],
                result['pairwise_unique_all'],
                strict=True,
            ):
                self.assertTrue(all(strict <= non_strict for non_strict, strict in zip(any_row, all_row, strict=True)))
            self.assertTrue(all(
                strict <= non_strict
                for non_strict, strict in zip(
                    result['exclusive']['exclusive_any'],
                    result['exclusive']['exclusive_all'],
                    strict=True,
                )
            ))

    def test_missing_trial_keeps_degraded_any_but_makes_strict_unknown(self) -> None:
        result = trial_set_comparison(
            ['alpha', 'beta'],
            {'alpha': [{'a'}, None], 'beta': [{'b'}, {'b'}]},
        )

        self.assertEqual([1, 1], result['exclusive']['exclusive_any'])
        self.assertEqual(['lower', 'upper'], result['exclusive']['exclusive_any_bounds'])
        self.assertEqual([None, 1], result['exclusive']['exclusive_all'])
        self.assertEqual(['unknown', 'upper'], result['exclusive']['exclusive_all_bounds'])
        self.assertEqual([None, None], trial_set_comparison(
            ['alpha', 'beta'],
            {'alpha': [None], 'beta': [{'b'}]},
        )['pairwise_unique_any'][0])

    def test_comparison_side_always_uses_union(self) -> None:
        result = trial_set_comparison(
            ['alpha', 'beta'],
            {
                'alpha': [{'shared'}, {'shared'}],
                'beta': [{'shared'} for _ in range(9)] + [set()],
            },
        )

        self.assertEqual(0, result['pairwise_unique_any'][0][1])
        self.assertEqual(0, result['pairwise_unique_all'][0][1])
        self.assertEqual(0, result['exclusive']['exclusive_any'][0])
        self.assertEqual(0, result['exclusive']['exclusive_all'][0])

    def test_relative_containment_preserves_measured_zero(self) -> None:
        result = relative_containment_matrix(
            ['alpha', 'beta'],
            {'alpha': [set()], 'beta': [{'beta-only'}]},
        )

        self.assertEqual(0.0, result['matrix'][0][1])
        self.assertIsNotNone(result['matrix'][0][1])

    def test_relative_containment_is_unknown_for_empty_column_union(self) -> None:
        result = relative_containment_matrix(
            ['alpha', 'beta'],
            {'alpha': [{'alpha-only'}], 'beta': [set()]},
        )

        self.assertIsNone(result['matrix'][0][1])
        self.assertEqual(100.0, result['max_value'])

    def test_relative_containment_is_unknown_without_usable_row_trials(self) -> None:
        result = relative_containment_matrix(
            ['alpha', 'beta'],
            {'alpha': [None], 'beta': [{'beta-only'}]},
        )

        self.assertIsNone(result['matrix'][0][1])


class CoverageAnalysisBehaviorTest(unittest.TestCase):
    '''Verify coverage analyzer aggregation and target view behavior.'''

    def test_aggregate_finals_collects_coverage_and_last_point_metrics(self) -> None:
        finals = coverage_curves.aggregate_finals(
            reps=[
                {
                    'trial_id': 1,
                    'elapsed_seconds': 10,
                    'branches_cov': 5,
                    'branches_total': 10,
                    'branches_pct': 50.0,
                }
            ],
            points_by_trial={
                1: [
                    {'idx': 1, 'execs_done': 10, 'unique_bugs_total': 1},
                    {'idx': 2, 'execs_done': 30, 'unique_bugs_total': 2, 'resource_memory_mib': 4},
                ]
            },
            cov_metrics=COV_METRICS,
        )

        self.assertEqual([5.0], finals['branches_cov'])
        self.assertEqual([10.0], finals['branches_total'])
        self.assertEqual([50.0], finals['branches_pct'])
        self.assertEqual([30.0], finals['execs_done'])
        self.assertEqual([3.0], finals['execs_per_sec'])
        self.assertEqual([4.0], finals['resource_memory_mib'])

    def test_build_trial_rows_computes_auc_and_execution_rate(self) -> None:
        rows = coverage_curves.build_trial_rows(
            reps=[
                {
                    'trial_id': 1,
                    'fuzzer': 'fz',
                    'benchmark': 'bench',
                    'fuzz_target': 'target',
                    'rep': 0,
                    'elapsed_seconds': 10,
                    'branches_cov': 10,
                    'branches_pct': 50.0,
                    'regions_cov': 5,
                    'regions_pct': 25.0,
                    'coverage_html_rel': 'coverage/trial/html/index.html',
                }
            ],
            points_by_trial={
                1: [
                    {
                        'idx': 1,
                        'elapsed_s': 0,
                        'branches_cov': 4,
                        'branches_pct': 20.0,
                        'regions_cov': 2,
                        'regions_pct': 10.0,
                    },
                    {
                        'idx': 2,
                        'elapsed_s': 10,
                        'branches_cov': 10,
                        'branches_pct': 50.0,
                        'regions_cov': 5,
                        'regions_pct': 25.0,
                        'execs_done': 100,
                    },
                ]
            },
        )

        self.assertEqual(10.0, rows[0]['execs_per_sec'])
        self.assertEqual(70.0, rows[0]['branches_cov_auc'])
        self.assertEqual(7.0, rows[0]['branches_cov_auc_norm'])
        self.assertEqual(70.0, rows[0]['convergence_pct'])
        self.assertEqual('coverage/trial/html/index.html', rows[0]['coverage_html_rel'])

    def test_collect_target_view_groups_trials_bugs_versions_and_baselines(self) -> None:
        targets = coverage_curves.collect_target_view(
            cov_metrics=COV_METRICS,
            curve_max_points=CURVE_MAX_POINTS,
            trials=[
                {
                    'trial_id': 1,
                    'fuzzer': 'fz',
                    'benchmark': 'bench',
                    'fuzz_target': 'target',
                    'build_config': {'opt': 'a'},
                    'runtime_config': {'jobs': 1},
                    'fuzzer_image': 'image',
                    'branches_cov': 5,
                    'branches_total': 10,
                    'branches_pct': 50.0,
                }
            ],
            timeseries={'per_trial': {1: {'trial_id': 1, 'points': [{'idx': 1, 'execs_done': 10}]}}},
            bugs=[{'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'fz', 'bug_key': 'bug', 'hits_total': 2}],
            trial_version_fields=('fuzzer_image',),
            aggregated_coverage_by_fuzzer={('fz', 'bench', 'target'): {'branches_covered': 7}},
            seed_baseline_by_fuzzer={('fz', 'bench', 'target'): {'branches_covered': 1}},
        )

        fuzzer = targets[0]['fuzzers'][0]
        self.assertEqual('bench:target', targets[0]['key'])
        self.assertEqual(
            {
                'execs_done': 10.0,
                'elapsed_seconds': None,
                'execs_per_sec': None,
                'corpus_files_total': None,
                'unique_bugs_total': 1.0,
                'bug_hits_total': None,
                'branches_covered': 7,
            },
            fuzzer['aggregate'],
        )
        self.assertEqual({'branches_covered': 1}, fuzzer['seed_baseline'])
        self.assertEqual(
            {'fuzzer_image': 'image', 'build_config': {'opt': 'a'}, 'runtime_config': {'jobs': 1}},
            fuzzer['versions'],
        )
        self.assertEqual('bug', fuzzer['bugs'][0]['bug_key'])

    def test_empty_target_matrices_are_separate_objects(self) -> None:
        target: dict = {}

        target_matrices.attach_empty_target_matrices(target)

        groups = [target['unique_matrix'], target['relcov_matrix'],
                  target['branch_mwu_matrix'], target['branch_a12_matrix']]
        self.assertEqual(4, len({id(group) for group in groups}))

    def test_create_matrices_attaches_coverage_then_bug_stats_to_shared_target(self) -> None:
        builder = _PayloadBuilder.__new__(_PayloadBuilder)
        builder._coverage_sets_by_metric = lambda fuzzers, benchmark, fuzz_target: {
            'branches': {'alpha': {'a', 'b'}, 'beta': {'b'}}
        }
        builder._trial_coverage_sets_by_metric = lambda trials, fuzzers, benchmark, fuzz_target: {
            'branches': {'alpha': [{'a', 'b'}], 'beta': [{'b'}]}
        }
        target = {
            'benchmark': 'bench',
            'fuzz_target': 'target',
            'fuzzers': [
                {
                    'fuzzer': 'alpha',
                    'trials': [{'trial_id': 1, 'elapsed_seconds': 30}],
                    'bugs': [{'bug_key': 'bug-a', 'first_seen_ts': 110, 'hits_total': 2, 'trial_ids': [1]}],
                },
                {
                    'fuzzer': 'beta',
                    'trials': [{'trial_id': 2, 'elapsed_seconds': 20}],
                    'bugs': [{'bug_key': 'bug-b', 'first_seen_ts': 120, 'hits_total': 3, 'trial_ids': [2]}],
                },
            ],
        }

        result = builder.create_matrices(
            [target],
            [
                {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'alpha', 'branches_cov': 2},
                {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'beta', 'branches_cov': 1},
            ],
        )

        self.assertIs(target, result[0])
        self.assertEqual(
            [
                'benchmark',
                'fuzz_target',
                'fuzzers',
                'unique_matrix',
                'relcov_matrix',
                'relcov_score_by_fuzzer',
                'branch_mwu_matrix',
                'branch_a12_matrix',
                'unique_bug_table',
                'unique_bug_matrix',
                'relbug_matrix',
                'relbug_score_by_fuzzer',
            ],
            list(target),
        )
        self.assertIn('exclusive_coverage', target['fuzzers'][0])
        self.assertIn('exclusive_bugs', target['fuzzers'][0])
        self.assertTrue(target['unique_matrix']['has_data'])
        self.assertTrue(target['unique_bug_table']['has_data'])
        self.assertEqual([[0, 1], [1, 0]], target['unique_bug_matrix']['pairwise_unique_any'])
        self.assertEqual([[0, 1], [1, 0]], target['unique_bug_matrix']['pairwise_unique_all'])

    def test_create_matrices_uses_aggregate_relcov_fallback_when_trial_sets_missing(self) -> None:
        builder = _PayloadBuilder.__new__(_PayloadBuilder)
        builder._coverage_sets_by_metric = lambda fuzzers, benchmark, fuzz_target: {
            'branches': {'alpha': {'a', 'b'}, 'beta': {'b', 'c'}}
        }
        builder._trial_coverage_sets_by_metric = lambda trials, fuzzers, benchmark, fuzz_target: {'branches': {}}
        target = {
            'benchmark': 'bench',
            'fuzz_target': 'target',
            'fuzzers': [
                {'fuzzer': 'alpha', 'trials': [{'trial_id': 1}], 'bugs': []},
                {'fuzzer': 'beta', 'trials': [{'trial_id': 2}], 'bugs': []},
            ],
        }

        builder.create_matrices(
            [target],
            [
                {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'alpha'},
                {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'beta'},
            ],
        )

        relcov = target['relcov_matrix']['by_metric']['branches']
        self.assertTrue(relcov['has_data'])
        self.assertEqual([[100.0, 50.0], [50.0, 100.0]], relcov['matrix'])
        self.assertEqual(
            'per-fuzzer aggregate compact branches coverage sets (per-trial sets unavailable)',
            relcov['aggregation'],
        )
        self.assertTrue(relcov['uses_aggregate_fallback'])
        self.assertEqual(['alpha', 'beta'], relcov['aggregate_fallback_fuzzers'])
        self.assertEqual({'alpha': 1.0, 'beta': 1.0}, target['relcov_score_by_fuzzer'])
        unique = target['unique_matrix']['by_metric']['branches']
        self.assertEqual([[0, 1], [1, 0]], unique['pairwise_unique_any'])
        self.assertEqual([[None, None], [None, None]], unique['pairwise_unique_all'])
        self.assertEqual([None, None], unique['exclusive']['exclusive_all'])
        self.assertEqual('unknown', target['fuzzers'][0]['exclusive_coverage']['exclusive_all_bound'])
        self.assertEqual(0, target['fuzzers'][0]['exclusive_coverage']['sample_size'])


def _bug_exclusive_median(values: list[int]) -> float | None:
    target = {
        'fuzzers': [
            {
                'fuzzer': 'fz',
                'trials': [{'trial_id': idx} for idx in range(len(values))],
                'bugs': [
                    {'bug_key': f'bug-{idx}-{bug_idx}', 'trial_ids': [idx]}
                    for idx, count in enumerate(values)
                    for bug_idx in range(count)
                ],
            }
        ]
    }
    bug_analysis.attach_exclusive_bug_stats(target)
    return target['fuzzers'][0]['exclusive_bugs']['median']


if __name__ == '__main__':
    unittest.main()
