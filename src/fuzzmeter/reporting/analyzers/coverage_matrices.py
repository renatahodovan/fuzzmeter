# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build coverage comparison matrices from trial and coverage-set data.'''

from __future__ import annotations

from typing import Any

from ..keys import (
    BRANCH_A12_MATRIX_KEY,
    BRANCH_COVERAGE_METRIC,
    BRANCH_MWU_MATRIX_KEY,
    RELCOV_MATRIX_KEY,
    RELCOV_SCORE_BY_FUZZER_KEY,
    UNIQUE_MATRIX_KEY,
)
from ..metrics import mann_whitney_u_pvalue, median, vargha_delaney_a12
from ..set_comparison import (
    TrialSetIndex,
    novelty_scores,
    pairwise_matrix,
    relative_containment_matrix,
    trial_set_comparison,
)


def with_aggregate_trial_fallback(
    *,
    cov_metrics: tuple[str, ...],
    trial_coverage_sets_by_metric: dict[str, dict[str, list[set[str] | None]]],
    coverage_sets_by_metric: dict[str, dict[str, set[str]]],
    fuzzers: list[str],
) -> tuple[dict[str, dict[str, list[set[str] | None]]], dict[str, set[str]]]:
    '''Use final aggregate coverage sets when trial compact sets are unavailable.'''

    out: dict[str, dict[str, list[set[str] | None]]] = {}
    fallback_fuzzers_by_metric: dict[str, set[str]] = {}
    for metric in cov_metrics:
        trial_sets = trial_coverage_sets_by_metric.get(metric, {})
        aggregate_sets = coverage_sets_by_metric.get(metric, {})
        merged = {
            fuzzer: [set(value) if value is not None else None for value in values]
            for fuzzer, values in trial_sets.items()
        }
        for fuzzer in fuzzers:
            if any(value is not None for value in merged.get(fuzzer, [])):
                continue
            aggregate_set = aggregate_sets.get(fuzzer)
            if aggregate_set is not None:
                merged[fuzzer] = [set(aggregate_set)]
                fallback_fuzzers_by_metric.setdefault(metric, set()).add(fuzzer)
        out[metric] = merged
    return out, fallback_fuzzers_by_metric


def attach_empty_coverage_matrices(target: dict[str, Any]) -> None:
    '''Attach placeholder coverage matrices to a target without comparable fuzzers.'''

    for key in (UNIQUE_MATRIX_KEY, RELCOV_MATRIX_KEY, BRANCH_MWU_MATRIX_KEY, BRANCH_A12_MATRIX_KEY):
        target[key] = {'by_metric': {}, 'has_data': False, 'available_metrics': []}
    target[RELCOV_SCORE_BY_FUZZER_KEY] = {}


def compute_unique_matrix(
    *,
    cov_metrics: tuple[str, ...],
    fuzzers: list[str],
    trial_coverage_sets_by_metric: dict[str, dict[str, list[set[str] | None]]],
    aggregate_fallback_fuzzers_by_metric: dict[str, set[str]] | None = None,
    trial_set_indexes_by_metric: dict[str, TrialSetIndex] | None = None,
) -> dict[str, Any]:
    '''Compute all unique coverage matrices for one target.'''

    by_metric = {
        metric: _compute_unique_matrix_for_metric(
            fuzzers=fuzzers,
            metric=metric,
            trial_coverage_sets=trial_coverage_sets_by_metric.get(metric, {}),
            aggregate_fallback_fuzzers=(aggregate_fallback_fuzzers_by_metric or {}).get(metric, set()),
            trial_set_index=(trial_set_indexes_by_metric or {}).get(metric),
        )
        for metric in cov_metrics
    }
    return {
        'by_metric': by_metric,
        'has_data': any(entry.get('has_data') for entry in by_metric.values()),
        'available_metrics': [metric for metric, entry in by_metric.items() if entry.get('has_data')],
    }


def _compute_unique_matrix_for_metric(
    *,
    fuzzers: list[str],
    metric: str,
    trial_coverage_sets: dict[str, list[set[str] | None]],
    aggregate_fallback_fuzzers: set[str],
    trial_set_index: TrialSetIndex | None,
) -> dict[str, Any]:
    '''Compute pairwise strict and non-strict coverage counts for one metric.'''

    fallback_fuzzers = sorted(aggregate_fallback_fuzzers)
    result = trial_set_comparison(
        fuzzers,
        trial_coverage_sets,
        note=(
            'Per-trial compact coverage sets are unavailable for '
            f'{", ".join(fallback_fuzzers)}; aggregate coverage sets are used for '
            'non-strict values, while strict subject-side values are unknown.'
        ) if fallback_fuzzers else None,
        strict_unknown_labels=aggregate_fallback_fuzzers,
        index=trial_set_index,
    )
    return {
        **result,
        'metric': metric,
        'format': 'int',
        'aggregation': 'per-fuzzer trial compact coverage sets',
        'uses_aggregate_fallback': bool(fallback_fuzzers),
        'aggregate_fallback_fuzzers': fallback_fuzzers,
    }


def compute_branch_stat_matrices(
    *,
    fuzzers: list[str],
    branch_coverage_by_fuzzer: dict[str, list[int | None]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    '''Compute pairwise branch-coverage Mann-Whitney and A12 matrices.'''

    distributions = {
        fuzzer: [float(value) for value in branch_coverage_by_fuzzer.get(fuzzer, []) if value is not None]
        for fuzzer in fuzzers
    }
    missing_any = any(
        value is None
        for fuzzer in fuzzers
        for value in branch_coverage_by_fuzzer.get(fuzzer, [])
    )
    missing_note = (
        'Final branch coverage missing for one or more trials; '
        'pairwise branch statistics may be partial.'
    ) if missing_any else None
    sample_sizes = {fuzzer: len(distribution) for fuzzer, distribution in distributions.items()}
    mwu_note = ' '.join(filter(None, (
        missing_note,
        (
            'Mann-Whitney U requires at least two measured trials per fuzzer; '
            f'sample sizes: {", ".join(f"{fuzzer} n={size}" for fuzzer, size in sample_sizes.items())}.'
        ) if any(size < 2 for size in sample_sizes.values()) else None,
    ))) or None
    p_value_matrix = pairwise_matrix(
        fuzzers,
        distributions,
        compare=mann_whitney_u_pvalue,
        max_value=1.0,
        note=mwu_note,
    )
    a12_matrix = pairwise_matrix(
        fuzzers,
        distributions,
        compare=vargha_delaney_a12,
        max_value=1.0,
        note=missing_note,
    )
    p_value_matrix.update(
        {
            'format': 'float',
            'aggregation': 'per-trial final branch coverage',
            'metric': BRANCH_COVERAGE_METRIC,
            'statistic': 'mann_whitney_u_pvalue',
        }
    )
    a12_matrix.update(
        {
            'format': 'float',
            'aggregation': 'per-trial final branch coverage',
            'metric': BRANCH_COVERAGE_METRIC,
            'statistic': 'vargha_delaney_a12',
        }
    )
    return (
        _single_metric_matrix_group(p_value_matrix),
        _single_metric_matrix_group(a12_matrix),
    )


def attach_exclusive_coverage_stats(
    *,
    target: dict[str, Any],
    trial_coverage_sets_by_metric: dict[str, dict[str, list[set[str] | None]]] | None = None,
    aggregate_fallback_fuzzers_by_metric: dict[str, set[str]] | None = None,
    metric: str = BRANCH_COVERAGE_METRIC,
) -> dict[str, Any]:
    '''Attach aggregate exclusive coverage and per-trial distributions.'''

    entries = target.get('fuzzers') or []
    matrix = ((target.get('unique_matrix') or {}).get('by_metric') or {}).get(metric) or {}
    fuzzers = [str(fuzzer) for fuzzer in matrix.get('fuzzers') or []]
    exclusive = matrix.get('exclusive') or {}
    any_values = exclusive.get('exclusive_any') or []
    all_values = exclusive.get('exclusive_all') or []
    any_bounds = exclusive.get('exclusive_any_bounds') or []
    all_bounds = exclusive.get('exclusive_all_bounds') or []
    sets_by_fuzzer = (trial_coverage_sets_by_metric or {}).get(metric, {})
    fallback_fuzzers = (aggregate_fallback_fuzzers_by_metric or {}).get(metric, set())
    index_by_fuzzer = {fuzzer: index for index, fuzzer in enumerate(fuzzers)}
    unions = {
        fuzzer: set().union(*(values for values in sets_by_fuzzer.get(fuzzer, []) if values is not None))
        for fuzzer in fuzzers
    }
    prefixes: list[set[str]] = []
    all_union: set[str] = set()
    for fuzzer in fuzzers:
        prefixes.append(all_union)
        all_union = all_union | unions[fuzzer]
    other_unions: dict[str, set[str]] = {}
    suffix: set[str] = set()
    for index in range(len(fuzzers) - 1, -1, -1):
        fuzzer = fuzzers[index]
        other_unions[fuzzer] = prefixes[index] | suffix
        suffix.update(unions[fuzzer])

    for entry in entries:
        fuzzer = str(entry.get('fuzzer') or '')
        idx = index_by_fuzzer.get(fuzzer, -1)
        other_union = other_unions.get(fuzzer, all_union)
        trial_sets = sets_by_fuzzer.get(fuzzer, [])
        trial_counts = (
            []
            if fuzzer in fallback_fuzzers
            else [len(values - other_union) for values in trial_sets if values is not None]
        )
        entry['exclusive_coverage'] = {
            'metric': metric,
            'exclusive_any': any_values[idx] if 0 <= idx < len(any_values) else None,
            'exclusive_all': all_values[idx] if 0 <= idx < len(all_values) else None,
            'exclusive_any_bound': any_bounds[idx] if 0 <= idx < len(any_bounds) else 'unknown',
            'exclusive_all_bound': all_bounds[idx] if 0 <= idx < len(all_bounds) else 'unknown',
            'min': min(trial_counts) if trial_counts else None,
            'max': max(trial_counts) if trial_counts else None,
            'median': median(trial_counts),
            'sample_size': 0 if fuzzer in fallback_fuzzers else len(trial_sets),
            'usable_sample_size': len(trial_counts),
            'note': matrix.get('note'),
        }
    return target


def compute_relcov_matrix(
    *,
    cov_metrics: tuple[str, ...],
    fuzzers: list[str],
    trial_coverage_sets_by_metric: dict[str, dict[str, list[set[str] | None]]],
    aggregate_fallback_fuzzers_by_metric: dict[str, set[str]] | None = None,
    trial_set_indexes_by_metric: dict[str, TrialSetIndex] | None = None,
) -> tuple[dict[str, Any], dict[str, float]]:
    '''Compute pairwise relative coverage and novelty-weighted branch scores.'''

    by_metric = {
        metric: _compute_relcov_matrix_for_metric(
            fuzzers=fuzzers,
            metric=metric,
            trial_coverage_sets=trial_coverage_sets_by_metric.get(metric, {}),
            aggregate_fallback_fuzzers=(
                aggregate_fallback_fuzzers_by_metric or {}
            ).get(metric, set()),
            trial_set_index=(trial_set_indexes_by_metric or {}).get(metric),
        )
        for metric in cov_metrics
    }
    branch_trial_sets = trial_coverage_sets_by_metric.get(BRANCH_COVERAGE_METRIC, {})
    score_by_fuzzer = _relcov_scores(
        fuzzers=fuzzers,
        trial_coverage_sets=branch_trial_sets,
        trial_set_index=(trial_set_indexes_by_metric or {}).get(BRANCH_COVERAGE_METRIC),
    )
    return (
        {
            'by_metric': by_metric,
            'has_data': any(entry.get('has_data') for entry in by_metric.values()),
            'available_metrics': [metric for metric, entry in by_metric.items() if entry.get('has_data')],
        },
        score_by_fuzzer,
    )


def _compute_relcov_matrix_for_metric(
    *,
    fuzzers: list[str],
    metric: str,
    trial_coverage_sets: dict[str, list[set[str] | None]],
    aggregate_fallback_fuzzers: set[str],
    trial_set_index: TrialSetIndex | None,
) -> dict[str, Any]:
    missing_any = len(trial_coverage_sets) != len(fuzzers) or any(
        not trial_coverage_sets.get(fuzzer)
        or any(values is None for values in trial_coverage_sets.get(fuzzer, []))
        for fuzzer in fuzzers
    )
    fallback_fuzzers = sorted(aggregate_fallback_fuzzers)
    note_parts = []
    if fallback_fuzzers:
        note_parts.append(
            'Trial compact coverage sets are unavailable for '
            f'{", ".join(fallback_fuzzers)}; aggregate coverage sets are used instead.'
        )
    if missing_any:
        note_parts.append(
            'Coverage sets are missing for one or more fuzzers; '
            'relative coverage may be partial.'
        )
    matrix = relative_containment_matrix(
        fuzzers,
        trial_coverage_sets,
        note=' '.join(note_parts) or None,
        index=trial_set_index,
    )
    if not fallback_fuzzers:
        aggregation = f'per-trial median compact {metric} coverage sets'
    elif len(fallback_fuzzers) == len(fuzzers):
        aggregation = (
            f'per-fuzzer aggregate compact {metric} coverage sets '
            '(per-trial sets unavailable)'
        )
    else:
        aggregation = (
            f'mixed per-trial median and per-fuzzer aggregate compact {metric} coverage sets '
            '(per-trial sets partially unavailable)'
        )
    return {
        **matrix,
        'format': 'pct',
        'aggregation': aggregation,
        'uses_aggregate_fallback': bool(fallback_fuzzers),
        'aggregate_fallback_fuzzers': fallback_fuzzers,
    }


def _single_metric_matrix_group(matrix: dict[str, Any]) -> dict[str, Any]:
    '''Wrap a branch matrix in the report metric-group shape.'''

    return {
        'by_metric': {BRANCH_COVERAGE_METRIC: matrix},
        'has_data': bool(matrix.get('has_data')),
        'available_metrics': [BRANCH_COVERAGE_METRIC] if matrix.get('has_data') else [],
    }


def _relcov_scores(
    *,
    fuzzers: list[str],
    trial_coverage_sets: dict[str, list[set[str] | None]],
    trial_set_index: TrialSetIndex | None = None,
) -> dict[str, float]:
    '''Score each fuzzer by coverage elements that fewer peers cover.'''
    return novelty_scores(fuzzers, trial_coverage_sets, index=trial_set_index)
