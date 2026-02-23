# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from typing import Any, Callable


def _median(values: list[float]) -> float | None:
    '''Return the median of numeric values.'''

    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


class SummaryAnalysis:
    '''Build fuzzer ranking and campaign-level summary scores.'''

    def __init__(
        self,
        *,
        cov_metrics: tuple[str, ...],
        mean: Callable[[Any], float | None],
        rankdata_desc: Callable[[list[float | None]], list[float | None]],
        mann_whitney_u_pvalue: Callable[[list[float], list[float]], float | None],
        cliffs_delta: Callable[[list[float], list[float]], float | None],
    ) -> None:
        self._cov_metrics = cov_metrics
        self._mean = mean
        self._rankdata_desc = rankdata_desc
        self._mann_whitney_u_pvalue = mann_whitney_u_pvalue
        self._cliffs_delta = cliffs_delta

    def enrich_targets(self, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        '''Add ranking and significance metrics to target entries.'''

        for target in targets:
            for metric in self._cov_metrics:
                cov_vals = [entry['final'].get(f'{metric}_pct_median') for entry in target['fuzzers']]
                cov_ranks = self._rankdata_desc(cov_vals)
                for idx, entry in enumerate(target['fuzzers']):
                    entry[f'rank_{metric}_median'] = cov_ranks[idx]
            for entry in target['fuzzers']:
                entry.setdefault('rank_regions_median', entry.get('rank_regions_median'))
            best_entry = max(
                (entry for entry in target['fuzzers'] if isinstance(entry['final'].get('regions_pct_median'), (int, float))),
                key=lambda entry: float(entry['final'].get('regions_pct_median') or -1),
                default=None,
            )
            significance: list[dict[str, Any]] = []
            if best_entry is not None:
                best_dist = best_entry['distribution'].get('regions_pct', [])
                best_fuzzer = best_entry['fuzzer']
                for entry in target['fuzzers']:
                    if entry['fuzzer'] == best_fuzzer:
                        continue
                    significance.append(
                        {
                            'vs': best_fuzzer,
                            'fuzzer': entry['fuzzer'],
                            'p_value': self._mann_whitney_u_pvalue(best_dist, entry['distribution'].get('regions_pct', [])),
                            'cliffs_delta': self._cliffs_delta(best_dist, entry['distribution'].get('regions_pct', [])),
                        }
                    )
            target['significance_vs_best'] = significance
        return targets

    def collect_summary_scores(self, targets: list[dict[str, Any]]) -> dict[str, Any]:
        '''Collect campaign-level ranking summaries.'''

        fuzzers = sorted({entry['fuzzer'] for target in targets for entry in (target.get('fuzzers') or [])})
        per_fuzzer_scores: dict[str, list[float]] = {fuzzer: [] for fuzzer in fuzzers}
        per_fuzzer_auc_scores: dict[str, list[float]] = {fuzzer: [] for fuzzer in fuzzers}
        per_fuzzer_relcov_scores: dict[str, list[float]] = {fuzzer: [] for fuzzer in fuzzers}
        per_fuzzer_relbug_scores: dict[str, list[float]] = {fuzzer: [] for fuzzer in fuzzers}
        per_fuzzer_unique_bugs: dict[str, float] = {fuzzer: 0.0 for fuzzer in fuzzers}
        per_fuzzer_exclusive_bugs: dict[str, float] = {fuzzer: 0.0 for fuzzer in fuzzers}
        per_fuzzer_execs: dict[str, list[float]] = {fuzzer: [] for fuzzer in fuzzers}
        for target in targets:
            medians = [entry['final'].get('regions_pct_median') for entry in target.get('fuzzers') or []]
            numeric = [float(v) for v in medians if isinstance(v, (int, float))]
            best = max(numeric) if numeric else None
            auc_medians = [entry['final'].get('branches_cov_auc_median') for entry in target.get('fuzzers') or []]
            auc_numeric = [float(v) for v in auc_medians if isinstance(v, (int, float))]
            best_auc = max(auc_numeric) if auc_numeric else None
            for entry in target.get('fuzzers') or []:
                fuzzer = entry['fuzzer']
                median_value = entry['final'].get('regions_pct_median')
                if best is not None and best > 0 and isinstance(median_value, (int, float)):
                    per_fuzzer_scores[fuzzer].append(100.0 * float(median_value) / best)
                branches_cov_auc_median = entry['final'].get('branches_cov_auc_median')
                if best_auc is not None and best_auc > 0 and isinstance(branches_cov_auc_median, (int, float)):
                    per_fuzzer_auc_scores[fuzzer].append(100.0 * float(branches_cov_auc_median) / best_auc)
                relcov_score = (target.get('relcov_score_by_fuzzer') or {}).get(fuzzer)
                if isinstance(relcov_score, (int, float)):
                    per_fuzzer_relcov_scores[fuzzer].append(float(relcov_score))
                relbug_score = (target.get('relbug_score_by_fuzzer') or {}).get(fuzzer)
                if isinstance(relbug_score, (int, float)):
                    per_fuzzer_relbug_scores[fuzzer].append(float(relbug_score))
                accumulated_bug_count = entry['final'].get('accumulated_bug_count')
                if isinstance(accumulated_bug_count, (int, float)):
                    per_fuzzer_unique_bugs[fuzzer] += float(accumulated_bug_count)
                exclusive_bug_count = (entry.get('exclusive_bugs') or {}).get('total')
                if isinstance(exclusive_bug_count, (int, float)):
                    per_fuzzer_exclusive_bugs[fuzzer] += float(exclusive_bug_count)
                execs_done_median = entry['final'].get('execs_done_median')
                if isinstance(execs_done_median, (int, float)):
                    per_fuzzer_execs[fuzzer].append(float(execs_done_median))
        summary = {'rankings': []}
        for fuzzer in fuzzers:
            summary['rankings'].append(
                {
                    'fuzzer': fuzzer,
                    'coverage_score': self._mean(per_fuzzer_scores[fuzzer]),
                    'auc_score': self._mean(per_fuzzer_auc_scores[fuzzer]),
                    'relcov_score': self._mean(per_fuzzer_relcov_scores[fuzzer]),
                    'relbug_score': self._mean(per_fuzzer_relbug_scores[fuzzer]),
                    'unique_bug_count': per_fuzzer_unique_bugs[fuzzer],
                    'exclusive_bug_count': per_fuzzer_exclusive_bugs[fuzzer],
                    'median_execs_done': _median(per_fuzzer_execs[fuzzer]),
                }
            )
        summary['rankings'].sort(key=lambda row: (row['coverage_score'] is None, -(row['coverage_score'] or -1)))
        return summary
