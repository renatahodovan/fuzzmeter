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

    def test_failed_tick_notice_marks_coverage_holes(self) -> None:
        script = r"""
            import assert from 'node:assert/strict';
            import { tickFailureNotice } from './src/fuzzmeter/web/static/report/report-data.js';

            assert.equal(tickFailureNotice({ failed_snapshot_ticks: 0 }), null);
            assert.equal(
              tickFailureNotice({ failed_snapshot_ticks: 2 }),
              'Warning: 2 snapshot ticks failed. Coverage and crash curves may contain unmeasured gaps.',
            );
        """
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

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
              refresh,
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

            const calls = [];
            const elements = new Map();
            function node() {
              return {
                textContent: '',
                disabled: false,
                dataset: {},
                classList: { toggle() {} },
                appendChild() {},
                addEventListener() {},
              };
            }
            globalThis.document = {
              createElement() { return node(); },
              querySelectorAll() { return []; },
              getElementById(id) {
                if (!elements.has(id)) elements.set(id, node());
                return elements.get(id);
              },
            };
            globalThis.fetch = async (url, opts = {}) => {
              calls.push([url, opts.method || 'GET']);
              return {
                ok: true,
                async json() {
                  if (url === '/api/runs') return { runs: [] };
                  if (url === '/api/composite/sources/refresh') return { measurements: [], invalid_sources: [] };
                  throw new Error(`Unexpected URL: ${url}`);
                },
              };
            };
            await refresh({
              runs: [],
              measurements: [],
              invalidSources: [],
              filterText: '',
              selectedRuns: new Set(),
              selectedMeasurements: new Set(),
            });
            assert.deepEqual(calls, [
              ['/api/runs', 'GET'],
              ['/api/composite/sources/refresh', 'POST'],
            ]);
        """
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

    def test_report_statistical_and_domain_helpers_are_dom_independent(self) -> None:
        script = r"""
            import assert from 'node:assert/strict';
            import { cleanFloats, median, quantile } from './src/fuzzmeter/web/static/report/stats.js';
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
            assert.equal(shouldDrawDistributionViolin([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]), false);
            assert.equal(shouldDrawDistributionViolin(Array.from({ length: 20 }, (_, index) => index)), true);
        """
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

    def test_target_page_source_appends_per_trial_block_and_nav(self) -> None:
        page_js = REPO_ROOT / 'src' / 'fuzzmeter' / 'web' / 'static' / 'report' / 'page.js'
        text = page_js.read_text(encoding='utf-8')

        self.assertIn('blocks.appendChild(perTrialBlock);', text)
        self.assertIn("['Trials', `#t-${targetId}-trials`]", text)
        self.assertIn('relcovMatrix?.uses_aggregate_fallback', text)
        self.assertIn('aggregate coverage fallback is shown', text)

    def test_report_source_compatibility_helpers_render_modal_details(self) -> None:
        script = r"""
            import assert from 'node:assert/strict';

            class Node {
              constructor(tag = 'div') {
                this.tag = tag;
                this.children = [];
                this.dataset = {};
                this.hidden = false;
                this.title = '';
                this.type = '';
                this._text = '';
                this.classes = new Set();
                this.classList = {
                  add: (...names) => names.forEach((name) => this.classes.add(name)),
                  remove: (...names) => names.forEach((name) => this.classes.delete(name)),
                  toggle: (name, force) => {
                    if (force === false) this.classes.delete(name);
                    else this.classes.add(name);
                  },
                };
              }
              appendChild(child) {
                this.children.push(child);
                return child;
              }
              addEventListener() {}
              set className(value) {
                this.classes = new Set(String(value || '').split(/\s+/).filter(Boolean));
              }
              get className() {
                return Array.from(this.classes).join(' ');
              }
              set textContent(value) {
                this._text = String(value || '');
                if (value === '') this.children = [];
              }
              get textContent() {
                return this._text;
              }
            }

            function textOf(node) {
              return [node.textContent, ...node.children.map(textOf)].join(' ');
            }

            const elements = new Map([
              ['compatibilityModal', new Node()],
              ['compatibilityModalTitle', new Node()],
              ['compatibilityModalSubtitle', new Node()],
              ['compatibilityModalBody', new Node()],
              ['compatibilityModalClose', new Node('button')],
            ]);
            elements.get('compatibilityModal').classList.add('hidden');
            globalThis.document = {
              addEventListener() {},
              createElement(tag) { return new Node(tag); },
              getElementById(id) { return elements.get(id) || null; },
            };

            const {
              openCompatibilityModal,
              shouldShowCompatibilityColumn,
              shouldShowSourceColumn,
            } = await import('./src/fuzzmeter/web/static/report/page.js');

            const target = {
              benchmark: 'bench',
              fuzz_target: 'target',
              fuzzers: [
                { fuzzer: 'fresh-fz', origin: 'fresh', compatibility: { level: 'compatible' } },
                {
                  fuzzer: 'hist-fz',
                  origin: 'historical',
                  source_id: 'run-b',
                  source_run_id: 'run',
                  source_fuzzer: 'fz',
                  compatibility: {
                    level: 'risky',
                    comparison_note: '',
                    reference: { origin: 'fresh', source_id: 'run-a', run_id: 'run', fuzzer: 'fz' },
                    diffs: [
                      {
                        domain: 'environment',
                        path: 'host.kernel',
                        reference: '6.8',
                        candidate: '6.9',
                        message: 'Environment metadata differs.',
                      },
                    ],
                  },
                },
              ],
            };

            assert.equal(shouldShowSourceColumn(target, { targets: [target] }), true);
            assert.equal(shouldShowCompatibilityColumn(target), true);
            assert.equal(shouldShowSourceColumn({
              fuzzers: [
                { fuzzer: 'fresh-a', origin: 'fresh' },
                { fuzzer: 'fresh-b', origin: 'fresh' },
              ],
            }, { sources: [{ origin: 'historical' }] }), false);
            assert.equal(shouldShowCompatibilityColumn({
              fuzzers: [
                { fuzzer: 'fresh-a', origin: 'fresh' },
                { fuzzer: 'fresh-b', origin: 'fresh' },
              ],
            }), false);
            openCompatibilityModal(target, target.fuzzers[1]);

            assert.equal(elements.get('compatibilityModal').classes.has('hidden'), false);
            assert.match(elements.get('compatibilityModalTitle').textContent, /hist-fz compatibility: risky/);
            const bodyText = textOf(elements.get('compatibilityModalBody'));
            assert.match(bodyText, /Environment/);
            assert.match(bodyText, /host\.kernel/);
            assert.match(bodyText, /6\.8/);
            assert.match(bodyText, /6\.9/);
        """
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

    def test_fuzzer_detail_modal_renders_metadata_tab(self) -> None:
        script = r"""
            import assert from 'node:assert/strict';

            class Node {
              constructor(tag = 'div') {
                this.tag = tag;
                this.children = [];
                this.dataset = {};
                this.disabled = false;
                this.attributes = {};
                this._text = '';
                this.classes = new Set();
                this.classList = {
                  add: (...names) => names.forEach((name) => this.classes.add(name)),
                  remove: (...names) => names.forEach((name) => this.classes.delete(name)),
                  toggle: (name, force) => {
                    if (force === false) this.classes.delete(name);
                    else this.classes.add(name);
                  },
                };
              }
              appendChild(child) {
                this.children.push(child);
                return child;
              }
              addEventListener() {}
              setAttribute(name, value) {
                this.attributes[name] = String(value);
              }
              set className(value) {
                this.classes = new Set(String(value || '').split(/\s+/).filter(Boolean));
              }
              get className() {
                return Array.from(this.classes).join(' ');
              }
              set textContent(value) {
                this._text = String(value || '');
                if (value === '') this.children = [];
              }
              get textContent() {
                return this._text;
              }
            }

            const elements = new Map([
              ['configModal', new Node()],
              ['configModalTitle', new Node()],
              ['configModalBody', new Node('pre')],
              ['configModalRuntimeTab', new Node('button')],
              ['configModalMetadataTab', new Node('button')],
              ['configModalClose', new Node('button')],
            ]);
            elements.get('configModal').classList.add('hidden');
            globalThis.document = {
              addEventListener() {},
              createElement(tag) { return new Node(tag); },
              getElementById(id) { return elements.get(id) || null; },
            };
            globalThis.localStorage = { getItem() { return null; }, setItem() {} };
            globalThis.window = { matchMedia() { return { matches: false }; } };

            const { openConfigModal } = await import('./src/fuzzmeter/web/static/report/ui.js');

            openConfigModal({
              fuzzer: 'hist-fz',
              metadata: {
                config: {
                  benchmark: 'bench',
                },
                source: {
                  fuzzer_version: {
                    status: 'ok',
                    data: { revision: 'fuzzer-abc' },
                  },
                },
                environment: { host: { machine: 'arm64' } },
                digests: { source: 'digest' },
              },
            });

            assert.equal(elements.get('configModal').classes.has('hidden'), false);
            assert.equal(elements.get('configModalTitle').textContent, 'hist-fz details');
            assert.equal(elements.get('configModalRuntimeTab').disabled, true);
            assert.equal(elements.get('configModalMetadataTab').classes.has('active'), true);
            assert.match(elements.get('configModalBody').textContent, /bench/);
            assert.match(elements.get('configModalBody').textContent, /fuzzer-abc/);
            assert.match(elements.get('configModalBody').textContent, /arm64/);
        """
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

    def test_composite_reload_selects_new_filter_entries(self) -> None:
        script = r"""
            import assert from 'node:assert/strict';
            import { FM_APP } from './src/fuzzmeter/web/static/report/state.js';
            import { selectNewFilterEntries } from './src/fuzzmeter/web/static/report/filters.js';

            FM_APP.state.selectedFuzzers = new Set(['fresh']);
            FM_APP.state.selectedBenchmarks = new Set(['bench']);

            const previous = {
              targets: [
                { benchmark: 'bench', fuzzers: [{ fuzzer: 'fresh' }] },
              ],
            };
            const next = {
              targets: [
                { benchmark: 'bench', fuzzers: [{ fuzzer: 'fresh' }, { fuzzer: 'historical' }] },
                { benchmark: 'other-bench', fuzzers: [{ fuzzer: 'other-historical' }] },
              ],
            };

            selectNewFilterEntries(previous, next);

            assert.deepEqual(Array.from(FM_APP.state.selectedFuzzers).sort(), [
              'fresh',
              'historical',
              'other-historical',
            ]);
            assert.deepEqual(Array.from(FM_APP.state.selectedBenchmarks).sort(), [
              'bench',
              'other-bench',
            ]);
        """
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )


if __name__ == '__main__':
    unittest.main()
