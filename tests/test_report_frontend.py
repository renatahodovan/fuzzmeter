# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Test frontend report data derivation helpers.'''

from __future__ import annotations

import subprocess
import unittest

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class ReportFrontendTest(unittest.TestCase):
    '''Verify browser-side summary and ranking derivation.'''

    def test_frontend_derives_summary_scores_and_metric_ranks(self) -> None:
        script = r'''
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
            assert.equal(enriched.significance_vs_best[0].vs, 'alpha');
            assert.equal(enriched.significance_vs_best[0].fuzzer, 'beta');

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
        '''
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )


if __name__ == '__main__':
    unittest.main()
