# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Test frontend report data derivation helpers."""

from __future__ import annotations

from pathlib import Path
import subprocess
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]


class ReportFrontendTest(unittest.TestCase):
    """Verify browser-side summary and ranking derivation."""

    def test_frontend_derives_summary_scores_and_metric_ranks(self) -> None:
        script = r"""
            import assert from 'node:assert/strict';
            import { computeSummary, enrichTargetForSelection } from './src/fuzzmeter/web/static/report/filters.js';

            const target = {
              relcov_score_by_fuzzer: { alpha: 2.0, beta: 1.0 },
              relbug_score_by_fuzzer: { alpha: 0.0, beta: 1.0 },
              fuzzers: [
                {
                  fuzzer: 'alpha',
                  final: {
                    regions_pct_median: 80.0,
                    branches_cov_auc_median: 10.0,
                    accumulated_bug_count: 2,
                    execs_done_median: 100,
                  },
                  distribution: { regions_pct: [80, 90] },
                  exclusive_bugs: { total: 1 },
                  exclusive_coverage: { total: 3 },
                },
                {
                  fuzzer: 'beta',
                  final: {
                    regions_pct_median: 40.0,
                    branches_cov_auc_median: 5.0,
                    accumulated_bug_count: 1,
                    execs_done_median: 50,
                  },
                  distribution: { regions_pct: [30, 50] },
                  exclusive_bugs: { total: 0 },
                  exclusive_coverage: { total: 1 },
                },
              ],
            };

            const enriched = enrichTargetForSelection(target);
            assert.equal(enriched.fuzzers[0].rank_regions_median, 1);
            assert.equal(enriched.fuzzers[1].rank_regions_median, 2);
            assert.equal(enriched.significance_vs_best, undefined);

            const summary = computeSummary([enriched]);
            assert.deepEqual(summary.rankings, [
              {
                fuzzer: 'alpha',
                coverage_score: 100,
                auc_score: 100,
                relcov_score: 2,
                relbug_score: 0,
                exclusive_coverage_count: 3,
                unique_bug_count: 2,
                exclusive_bug_count: 1,
                median_execs_done: 100,
              },
              {
                fuzzer: 'beta',
                coverage_score: 50,
                auc_score: 50,
                relcov_score: 1,
                relbug_score: 1,
                exclusive_coverage_count: 1,
                unique_bug_count: 1,
                exclusive_bug_count: 0,
                median_execs_done: 50,
              },
            ]);
        """
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

    def test_runs_page_helpers_preserve_status_filter_and_selection_behavior(self) -> None:
        script = r"""
            import assert from 'node:assert/strict';
            import {
              formatDuration,
              matchesFilter,
              normalizedStatusCounts,
              statusBadge,
              toggleRunSelection,
              toggleVisibleSelection,
              visibleRunIds,
            } from './src/fuzzmeter/web/static/runs.js';

            const alpha = {
              run_id: 'alpha-run',
              error: '',
              summary: {
                trials: 6,
                status_counts: {
                  done: 2,
                  failed_build: 1,
                  interrupted: 1,
                  queued: 2,
                  running: 3,
                },
                config: {
                  fuzzers: ['afl', 'libfuzzer'],
                  targets: ['sqlite'],
                },
              },
            };
            const beta = {
              run_id: 'beta-run',
              error: 'metadata failed',
              summary: {
                trials: 2,
                status_counts: { done: 2 },
                config: { fuzzers: ['honggfuzz'], targets: ['json'] },
              },
            };

            assert.deepEqual(
              normalizedStatusCounts(alpha),
              { running: 3, interrupted: 1, failed: 1, done: 2, other: 2 },
            );
            assert.deepEqual(statusBadge(alpha), ['running', 'Running']);
            assert.deepEqual(statusBadge(beta), ['done', 'Done']);
            assert.equal(matchesFilter(alpha, 'sqlite'), true);
            assert.equal(matchesFilter(alpha, 'missing'), false);
            assert.equal(formatDuration(0), '—');
            assert.equal(formatDuration(300), '5m');
            assert.equal(formatDuration(3900), '1h 5m');
            assert.equal(formatDuration(90000), '1d 1h');
            assert.deepEqual(visibleRunIds([alpha, beta], 'HONG'), ['beta-run']);

            const state = { selectedRuns: new Set() };
            toggleRunSelection(state, 'alpha-run');
            assert.deepEqual(Array.from(state.selectedRuns), ['alpha-run']);
            toggleRunSelection(state, 'alpha-run');
            assert.deepEqual(Array.from(state.selectedRuns), []);

            toggleVisibleSelection(state, ['alpha-run', 'beta-run']);
            assert.deepEqual(Array.from(state.selectedRuns).sort(), ['alpha-run', 'beta-run']);
            toggleVisibleSelection(state, ['alpha-run', 'beta-run']);
            assert.deepEqual(Array.from(state.selectedRuns), []);
        """
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

    def test_report_statistical_and_domain_helpers_are_dom_independent(self) -> None:
        script = r"""
            import assert from 'node:assert/strict';
            import { cleanFloats, cliffsDelta, median, quantile } from './src/fuzzmeter/web/static/report/stats.js';
            import {
              distributionDensitySegments,
              shouldDrawDistributionViolin,
            } from './src/fuzzmeter/web/static/report/charts.js';
            import {
              buildCurveSeries,
              distributionValues,
              finalMetricValue,
              pctValue,
            } from './src/fuzzmeter/web/static/report/report-data.js';

            assert.deepEqual(cleanFloats([1, '2', null, Number.NaN, 'x']), [1, 2]);
            assert.equal(quantile([1, 3, 5], 0.5), 3);
            assert.equal(median([5, 1, 3]), 3);
            assert.equal(cliffsDelta([3, 4], [1, 2]), 1);
            assert.equal(pctValue(3, 4), 75);

            const fuzzer = {
              fuzzer: 'alpha',
              curve: [
                { idx: 1, elapsed_s: 10, execs_done_median: 100, execs_done_min: 80, execs_done_max: 120 },
              ],
              distribution: { branches_cov: [3, 4, null], branches_pct: [30, 40, 'x'] },
              final: { branches_cov_median: 4, branches_pct_median: 40 },
            };

            assert.equal(finalMetricValue(fuzzer, 'branches', 'abs'), 4);
            assert.deepEqual(distributionValues(fuzzer, 'branches', 'pct'), [30, 40]);
            assert.deepEqual(buildCurveSeries([fuzzer], 'execs_done')[0].points, [
              { x: 10, y: 100, lo: 80, hi: 120, idx: 1, ts: null, tooltipLabel: null },
            ]);

            const sparseSegments = distributionDensitySegments([16263, 16780], 15900, 20600, 18);
            assert.equal(sparseSegments.length, 2);
            assert.ok(sparseSegments.every((segment) => segment.length === 1));
            assert.ok(sparseSegments.every((segment) => segment[0].low > 15900));
            assert.ok(sparseSegments.every((segment) => segment[0].high < 20600));
            assert.equal(shouldDrawDistributionViolin([1, 2, 3, 4]), false);
            assert.equal(shouldDrawDistributionViolin([1, 2, 3, 4, 5]), true);
        """
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )


if __name__ == '__main__':
    unittest.main()
