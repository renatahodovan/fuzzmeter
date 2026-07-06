# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Test reporting analyzer behavior before cleanup refactors.'''

from __future__ import annotations

import unittest

from fuzzmeter.reporting.analyzers import coverage_curves
from fuzzmeter.reporting.analyzers.bug_analysis import BugAnalysis
from fuzzmeter.reporting.analyzers.trial_analysis import TrialAnalysis
from fuzzmeter.reporting.payload import _PayloadBuilder
from fuzzmeter.reporting.keys import SNAPSHOT_COVERAGE_FIELDS
from fuzzmeter.reporting.metrics import median

COV_METRICS = ('branches',)
FINAL_DIST_KEYS = (
    'branches_cov',
    'branches_total',
    'branches_pct',
    'execs_done',
    'execs_per_sec',
    'unique_bugs_total',
    'resource_memory_mib',
)
CURVE_MAX_POINTS = 100


class TrialAnalysisTest(unittest.TestCase):
    '''Verify trial and time-series analysis behavior.'''

    def test_collect_trials_uses_latest_snapshot_and_clamps_elapsed_time(self) -> None:
        analysis = _trial_analysis()

        trials = analysis.collect_trials(
            trial_rows=[
                {
                    'trial_id': 1,
                    'fuzzer': 'fz',
                    'benchmark': 'bench',
                    'fuzz_target': 'target',
                    'rep': '0',
                    'started_ts': 100,
                    'ended_ts': 190,
                    'time_seconds': 50,
                    'jobs': 1,
                    'status': 'done',
                }
            ],
            latest_snapshots={1: {'idx': 1, 'ts': 120, 'cov_branches_covered': 1, 'cov_branches_total': 2}},
            snapshot_rows=[
                {'trial_id': 1, 'snapshot_id': 10, 'idx': 1, 'ts': 120, 'cov_branches_covered': 1},
                {
                    'trial_id': 1,
                    'snapshot_id': 11,
                    'idx': 2,
                    'ts': 180,
                    'corpus_files': 4,
                    'execs_done': 50,
                    'crashes': 1,
                    'hangs': 0,
                    'coverage_html_dir': 'coverage/index.html',
                    'cov_branches_covered': 2,
                    'cov_branches_total': 4,
                },
            ],
            bug_stats_by_trial={1: (3, 2)},
            rel_to_url=lambda path: f'url:{path}' if path else None,
        )

        self.assertEqual(1, len(trials))
        self.assertEqual(50, trials[0]['elapsed_seconds'])
        self.assertEqual(2, trials[0]['coverage']['branches_covered'])
        self.assertEqual(50.0, trials[0]['coverage']['branches_pct'])
        self.assertEqual('url:coverage/index.html', trials[0]['coverage']['coverage_html'])
        self.assertEqual(3, trials[0]['bug_hits_total'])
        self.assertEqual(2, trials[0]['unique_bugs_total'])

    def test_collect_timeseries_merges_resources_and_cumulative_bug_counts(self) -> None:
        analysis = _trial_analysis()

        timeseries = analysis.collect_timeseries(
            trials=[{'trial_id': 1, 'fuzzer': 'fz', 'benchmark': 'bench', 'fuzz_target': 'target', 'started_ts': 100, 'time_seconds': 50}],
            snapshot_rows=[
                {
                    'trial_id': 1,
                    'snapshot_id': 10,
                    'idx': 1,
                    'ts': 120,
                    'corpus_files': 2,
                    'execs_done': 10,
                    'crashes': 1,
                    'hangs': 0,
                    'stats_json': '{"execs_per_sec": "5.5"}',
                    'cov_branches_covered': 1,
                    'cov_branches_total': 2,
                },
                {
                    'trial_id': 1,
                    'snapshot_id': 11,
                    'idx': 2,
                    'ts': 180,
                    'corpus_files': 4,
                    'execs_done': 30,
                    'crashes': 2,
                    'hangs': 0,
                    'cov_branches_covered': 2,
                    'cov_branches_total': 4,
                },
            ],
            resource_telemetry_rows=[
                {
                    'trial_id': 1,
                    'idx': 1,
                    'ts': 121,
                    'cpu_percent': 12.5,
                    'memory_percent': 25.0,
                    'memory_usage_bytes': 2 * 1024 * 1024,
                    'memory_limit_bytes': 8 * 1024 * 1024,
                    'corpus_disk_usage_bytes': 3 * 1024 * 1024,
                }
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

        BugAnalysis.attach_exclusive_bug_stats(target)

        self.assertEqual({'total': 1, 'min': 0, 'max': 1, 'median': 0.5}, target['fuzzers'][0]['exclusive_bugs'])
        self.assertEqual({'total': 0, 'min': 0, 'max': 0, 'median': 0.0}, target['fuzzers'][1]['exclusive_bugs'])

    def test_relative_bug_matrix_and_scores_use_trial_hit_rates(self) -> None:
        matrix, scores = BugAnalysis.compute_rel_bug_matrix(
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
        self.assertEqual([[100.0, 100.0], [50.0, 100.0]], matrix['matrix'])
        self.assertEqual({'alpha': 0.5, 'beta': 0.0}, scores)

    def test_integer_bug_median_matches_shared_metric_median_cases(self) -> None:
        for values in ([], [0], [0, 0], [1, 2, 3]):
            self.assertEqual(median(values), _bug_exclusive_median(values))


class CoverageAnalysisBehaviorTest(unittest.TestCase):
    '''Verify coverage analyzer aggregation and target view behavior.'''

    def test_aggregate_finals_collects_coverage_and_last_point_metrics(self) -> None:
        finals = coverage_curves.aggregate_finals(
            reps=[
                {
                    'trial_id': 1,
                    'elapsed_seconds': 10,
                    'coverage': {'branches_covered': 5, 'branches_total': 10, 'branches_pct': 50.0},
                }
            ],
            points_by_trial={
                1: [
                    {'idx': 1, 'execs_done': 10, 'unique_bugs_total': 1},
                    {'idx': 2, 'execs_done': 30, 'unique_bugs_total': 2, 'resource_memory_mib': 4},
                ]
            },
            cov_metrics=COV_METRICS,
            final_output_dist_keys=FINAL_DIST_KEYS,
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
                    'coverage': {'branches_covered': 10, 'branches_pct': 50.0, 'regions_covered': 5, 'regions_pct': 25.0},
                }
            ],
            points_by_trial={
                1: [
                    {'idx': 1, 'elapsed_s': 0, 'branches_cov': 4, 'branches_pct': 20.0, 'regions_cov': 2, 'regions_pct': 10.0},
                    {'idx': 2, 'elapsed_s': 10, 'branches_cov': 10, 'branches_pct': 50.0, 'regions_cov': 5, 'regions_pct': 25.0, 'execs_done': 100},
                ]
            },
        )

        self.assertEqual(10.0, rows[0]['execs_per_sec'])
        self.assertEqual(70.0, rows[0]['branches_cov_auc'])
        self.assertEqual(7.0, rows[0]['branches_cov_auc_norm'])
        self.assertEqual(70.0, rows[0]['convergence_pct'])

    def test_collect_target_view_groups_trials_bugs_versions_and_baselines(self) -> None:
        targets = coverage_curves.collect_target_view(
            cov_metrics=COV_METRICS,
            final_output_dist_keys=FINAL_DIST_KEYS,
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
                    'coverage': {'branches_covered': 5, 'branches_total': 10, 'branches_pct': 50.0},
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
        self.assertEqual({'fuzzer_image': 'image', 'build_config': {'opt': 'a'}, 'runtime_config': {'jobs': 1}}, fuzzer['versions'])
        self.assertEqual('bug', fuzzer['bugs'][0]['bug_key'])

    def test_create_matrices_attaches_coverage_then_bug_stats_to_shared_target(self) -> None:
        builder = _PayloadBuilder.__new__(_PayloadBuilder)
        builder._bug_analysis = BugAnalysis()
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
                {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'alpha', 'coverage': {'branches_covered': 2}},
                {'benchmark': 'bench', 'fuzz_target': 'target', 'fuzzer': 'beta', 'coverage': {'branches_covered': 1}},
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


def _trial_analysis() -> TrialAnalysis:
    return TrialAnalysis(
        snapshot_coverage_fields=SNAPSHOT_COVERAGE_FIELDS,
        trial_version_fields=('fuzzer_image',),
    )


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
    BugAnalysis.attach_exclusive_bug_stats(target)
    return target['fuzzers'][0]['exclusive_bugs']['median']


if __name__ == '__main__':
    unittest.main()
