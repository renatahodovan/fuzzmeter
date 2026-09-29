# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Test frontend report data derivation helpers."""

from __future__ import annotations

import re
import subprocess
import unittest

from pathlib import Path
from typing import get_args

from fuzzmeter.reporting.keys import COV_METRICS, MATRIX_PAYLOAD_KEYS
from fuzzmeter.reporting.plugin_api import ChartType, SectionPlacement

REPO_ROOT = Path(__file__).resolve().parents[1]


def _javascript_constant_block(
    source: str,
    name: str,
    opener: str = '[',
    closer: str = '];',
) -> str:
    pattern = rf'export const {name} = {re.escape(opener)}(.*?){re.escape(closer)}'
    match = re.search(pattern, source, re.DOTALL)
    if match is None:
        raise AssertionError(f'Missing JavaScript constant: {name}')
    return match.group(1)


def _javascript_string_array(source: str, name: str) -> tuple[str, ...]:
    return tuple(re.findall(r"'([^']+)'", _javascript_constant_block(source, name)))


class ReportFrontendTest(unittest.TestCase):
    """Verify browser-side summary and ranking derivation."""

    def test_javascript_shared_constants_match_python_sources(self) -> None:
        report_data = (
            REPO_ROOT / 'src' / 'fuzzmeter' / 'web' / 'static' / 'report' / 'report-data.js'
        ).read_text(encoding='utf-8')
        extras = (
            REPO_ROOT / 'src' / 'fuzzmeter' / 'web' / 'static' / 'report' / 'extras.js'
        ).read_text(encoding='utf-8')
        page = (
            REPO_ROOT / 'src' / 'fuzzmeter' / 'web' / 'static' / 'report' / 'page.js'
        ).read_text(encoding='utf-8')

        coverage_block = _javascript_constant_block(report_data, 'COVERAGE_METRICS')
        coverage_metrics = tuple(re.findall(r"\[\s*'([^']+)'\s*,", coverage_block))
        matrix_block = _javascript_constant_block(report_data, 'MATRIX_PAYLOAD_KEYS', 'Object.freeze({', '});')
        matrix_keys = tuple(re.findall(r":\s*'([^']+)'", matrix_block))

        self.assertEqual(COV_METRICS, coverage_metrics)
        self.assertEqual(MATRIX_PAYLOAD_KEYS, matrix_keys)
        self.assertEqual(get_args(ChartType), _javascript_string_array(extras, 'ALLOWED_CHART_TYPES'))
        self.assertEqual(get_args(SectionPlacement), _javascript_string_array(extras, 'ALLOWED_PLACEMENTS'))
        self.assertIn('return COVERAGE_METRICS.find(([metric]) => hasMetricData(metric))', page)
        self.assertIn(
            'if (value === null || value === undefined || !Number.isFinite(Number(value))) return null;',
            page,
        )

    def test_comparison_mode_selects_payload_variants_without_losing_unknowns(self) -> None:
        script = r'''
            import assert from 'node:assert/strict';
            import { cloneMatrixForSelected } from './src/fuzzmeter/web/static/report/matrix.js';
            import { comparisonMatrix, comparisonMetric } from './src/fuzzmeter/web/static/report/report-data.js';

            const payload = {
              fuzzers: ['alpha', 'beta'],
              pairwise_unique_any: [[0, 2], [1, 0]],
              pairwise_unique_all: [[0, null], [1, 0]],
              pairwise_unique_all_bounds: [['exact', 'unknown'], ['upper', 'exact']],
              sample_sizes: [2, 2],
              usable_sample_sizes: [1, 2],
              unique_counts: [4, 3],
              exclusive: {
                exclusive_any: [2, 1],
                exclusive_all: [null, 1],
              },
            };
            const cloned = cloneMatrixForSelected(payload, new Set(['alpha', 'beta']));
            const betaOnly = cloneMatrixForSelected(payload, new Set(['beta']));
            assert.equal(cloned.pairwise_unique_all[0][1], null);
            assert.equal(cloned.exclusive.exclusive_all[0], null);
            assert.deepEqual(betaOnly.sample_sizes, [2]);
            assert.deepEqual(betaOnly.unique_counts, [3]);
            assert.deepEqual(comparisonMatrix(cloned, 'all').matrix, [[0, null], [1, 0]]);
            assert.deepEqual(
              comparisonMetric(
                {
                  exclusive_any: 2,
                  exclusive_all: null,
                  exclusive_any_bound: 'lower',
                  exclusive_all_bound: 'unknown',
                },
                'any',
              ),
              { value: 2, bound: 'lower' },
            );
            assert.deepEqual(comparisonMetric({ exclusive_all: null }, 'all'), { value: null, bound: 'unknown' });
        '''
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )
    def test_matrix_cells_render_bounds_and_unknown_values(self) -> None:
        script = r'''
            import assert from 'node:assert/strict';
            import { renderMatrixTable } from './src/fuzzmeter/web/static/report/charts.js';

            function node() {
              return {
                children: [],
                className: '',
                style: { cssText: '' },
                textContent: '',
                title: '',
                appendChild(child) { this.children.push(child); return child; },
              };
            }
            globalThis.document = { createElement() { return node(); } };
            const host = node();
            renderMatrixTable(
              host,
              {
                fuzzers: ['alpha', 'beta'],
                matrix: [[0, null], [2, 0]],
                cell_bounds: [['exact', 'unknown'], ['lower', 'exact']],
                sample_sizes: [2, 3],
              },
              { formatter: 'pct' },
            );

            const table = host.children[0];
            const firstDataRow = table.children[1].children[0];
            const unknownCell = firstDataRow.children[2];
            assert.equal(unknownCell.children[0].textContent, '?');
            const boundedCell = table.children[1].children[1].children[1];
            assert.equal(boundedCell.children[0].textContent, '≥2.0%');
            // Sample sizes belong in the matrix note, not in every cell, so a
            // uniform repetition count is not repeated once per fuzzer pair.
            assert.equal(unknownCell.children.length, 1);
            assert.equal(boundedCell.children.length, 1);
        '''
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

    def test_failed_tick_notice_marks_coverage_holes(self) -> None:
        script = r'''
            import assert from 'node:assert/strict';
            import { tickFailureNotice } from './src/fuzzmeter/web/static/report/report-data.js';

            assert.equal(tickFailureNotice({ failed_snapshot_ticks: 0 }), null);
            assert.equal(
              tickFailureNotice({ failed_snapshot_ticks: 2 }),
              'Warning: 2 snapshot ticks failed. Coverage and crash curves may contain unmeasured gaps.',
            );
        '''
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

    def test_bug_table_filter_orders_rows_by_visible_fuzzers(self) -> None:
        script = r'''
            import assert from 'node:assert/strict';
            import { cloneUniqueBugTableForSelected } from './src/fuzzmeter/web/static/report/filters.js';

            const table = cloneUniqueBugTableForSelected({
              fuzzers: ['hidden', 'visible'],
              rows: [
                { index: 1, bug_key: 'early-for-hidden', cells: [1, 100], hit_counts: [1, 1] },
                { index: 2, bug_key: 'early-for-visible', cells: [null, 10], hit_counts: [0, 1] },
                { index: 3, bug_key: 'hidden-only', cells: [5, null], hit_counts: [1, 0] },
              ],
            }, new Set(['visible']));

            assert.deepEqual(table.rows.map((row) => [row.index, row.bug_key]), [
              [1, 'early-for-visible'],
              [2, 'early-for-hidden'],
            ]);
        '''
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

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
                    branches_cov_auc_norm_median: 1.0,
                    accumulated_bug_count: 2,
                    execs_done_median: 100,
                  },
                  distribution: { regions_pct: [80, 90] },
                  exclusive_bugs: { exclusive_any: 1, exclusive_all: 0 },
                  exclusive_coverage: {
                    exclusive_any: 3,
                    exclusive_all: 2,
                    exclusive_any_bound: 'lower',
                    exclusive_all_bound: 'exact',
                  },
                },
                {
                  fuzzer: 'beta',
                  final: {
                    regions_pct_median: 40.0,
                    branches_cov_auc_median: 5.0,
                    branches_cov_auc_norm_median: 2.0,
                    accumulated_bug_count: 1,
                    execs_done_median: 50,
                  },
                  distribution: { regions_pct: [30, 50] },
                  exclusive_bugs: { exclusive_any: 0, exclusive_all: 0 },
                  exclusive_coverage: {
                    exclusive_any: 1,
                    exclusive_all: 1,
                    exclusive_any_bound: 'exact',
                    exclusive_all_bound: 'exact',
                  },
                },
              ],
            };

            const enriched = enrichTargetForSelection(target);
            assert.equal(enriched.fuzzers[0].rank_regions_median, 1);
            assert.equal(enriched.fuzzers[1].rank_regions_median, 2);
            assert.equal(enriched.significance_vs_best, undefined);

            const summary = computeSummary([enriched], 'any');
            assert.deepEqual(summary.rankings, [
              {
                fuzzer: 'alpha',
                coverage_score: 100,
                auc_score: 50,
                relcov_score: 2,
                relbug_score: 0,
                exclusive_coverage_count: 3,
                exclusive_coverage_count_bound: 'lower',
                unique_bug_count: 2,
                exclusive_bug_count: 1,
                exclusive_bug_count_bound: 'exact',
                median_execs_done: 100,
              },
              {
                fuzzer: 'beta',
                coverage_score: 50,
                auc_score: 100,
                relcov_score: 1,
                relbug_score: 1,
                exclusive_coverage_count: 1,
                exclusive_coverage_count_bound: 'exact',
                unique_bug_count: 1,
                exclusive_bug_count: 0,
                exclusive_bug_count_bound: 'exact',
                median_execs_done: 50,
              },
            ]);

            const strictSummary = computeSummary([enriched], 'all');
            assert.equal(strictSummary.rankings[0].exclusive_coverage_count, 2);
            assert.equal(strictSummary.rankings[0].exclusive_coverage_count_bound, 'exact');
            assert.equal(strictSummary.rankings[0].exclusive_bug_count, 0);

            // Run-wide scores stay visible when the filter leaves a single fuzzer.
            const alphaOnly = computeSummary([{ ...enriched, fuzzers: [enriched.fuzzers[0]] }], 'any');
            assert.equal(alphaOnly.rankings[0].relcov_score, 2);
            assert.equal(alphaOnly.rankings[0].relbug_score, 0);

            // Targets that not every fuzzer ran stay out of the ranking.
            const partial = computeSummary([
              { ...enriched, key: 'bench:t1' },
              { ...enriched, key: 'bench:t2', fuzzers: [enriched.fuzzers[1]] },
            ], 'any');
            assert.deepEqual(partial.ranked_target_keys, ['bench:t1']);
            assert.deepEqual(partial.unranked_targets, [{ key: 'bench:t2', missing: ['alpha'] }]);
            assert.equal(partial.rankings.find((row) => row.fuzzer === 'beta').unique_bug_count, 1);
            const disjoint = computeSummary([
              { ...enriched, key: 'bench:t1', fuzzers: [enriched.fuzzers[0]] },
              { ...enriched, key: 'bench:t2', fuzzers: [enriched.fuzzers[1]] },
            ], 'any');
            assert.deepEqual(disjoint.rankings, []);
        '''
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

    def test_runs_page_helpers_preserve_status_filter_and_selection_behavior(self) -> None:
        script = r'''
            import assert from 'node:assert/strict';
            import {
              matchesFilter,
              normalizedStatusCounts,
              refresh,
              statusBadge,
              toggleRunSelection,
              toggleVisibleSelection,
              visibleRunIds,
            } from './src/fuzzmeter/web/static/runs.js';
            import { formatDuration } from './src/fuzzmeter/web/static/report/format.js';

            const alpha = {
              run_id: 'alpha-run',
              directory_name: 'alpha-directory',
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
              directory_name: 'beta-directory',
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
            assert.equal(formatDuration(0), '0s');
            assert.equal(formatDuration(0, { coarse: true }), '—');
            assert.equal(formatDuration(300, { coarse: true }), '5m');
            assert.equal(formatDuration(3900, { coarse: true }), '1h 5m');
            assert.equal(formatDuration(90000, { coarse: true }), '1d 1h');
            assert.deepEqual(visibleRunIds([alpha, beta], 'HONG'), ['beta-directory']);

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
        '''
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

    def test_report_statistical_and_domain_helpers_are_dom_independent(self) -> None:
        script = r'''
            import assert from 'node:assert/strict';
            import { compareNumericRows } from './src/fuzzmeter/web/static/report/sort.js';
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
            const sortable = [
              { fuzzer: 'missing', value: null },
              { fuzzer: 'beta', value: 2 },
              { fuzzer: 'alpha', value: 2 },
              { fuzzer: 'low', value: 1 },
            ];
            assert.deepEqual(
              sortable.sort((left, right) => compareNumericRows(left, right, 'value', 'desc'))
                .map((row) => row.fuzzer),
              ['alpha', 'beta', 'low', 'missing'],
            );

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
        '''
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
        script = r'''
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
        '''
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

    def test_fuzzer_detail_modal_renders_metadata_tab(self) -> None:
        script = r'''
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
        '''
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )

    def test_composite_reload_selects_new_filter_entries(self) -> None:
        script = r'''
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
        '''
        subprocess.run(
            ['node', '--no-warnings', '--input-type=module', '-e', script],
            cwd=REPO_ROOT,
            check=True,
        )


if __name__ == '__main__':
    unittest.main()
