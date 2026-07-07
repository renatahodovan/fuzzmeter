# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build coverage comparison matrices from trial and coverage-set data.'''

from __future__ import annotations

from typing import Any

from ..metrics import mann_whitney_u_pvalue, safe_int, vargha_delaney_a12
from ..set_comparison import novelty_scores, pairwise_matrix, relative_containment_matrix, unique_matrix


def compute_unique_matrix(
    *,
    cov_metrics: tuple[str, ...],
    trials: list[dict[str, Any]],
    benchmark: str,
    fuzz_target: str,
    coverage_sets_by_metric: dict[str, dict[str, set[str]]],
) -> dict[str, Any]:
    '''Compute all unique coverage matrices for one target.'''

    by_metric = {
        metric: _compute_unique_matrix_for_metric(
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            metric=metric,
            coverage_sets=coverage_sets_by_metric.get(metric, {}),
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
    trials: list[dict[str, Any]],
    benchmark: str,
    fuzz_target: str,
    metric: str,
    coverage_sets: dict[str, set[str]],
) -> dict[str, Any]:
    '''Compute pairwise unique union coverage matrix for one coverage metric.'''

    fuzzers = sorted(
        {
            str(trial.get('fuzzer'))
            for trial in trials
            if (
                trial.get('benchmark') == benchmark
                and trial.get('fuzz_target') == fuzz_target
                and trial.get('fuzzer')
            )
        }
    )
    result = unique_matrix(
        fuzzers,
        coverage_sets,
        note=(
            'Compact coverage sets missing for one or more fuzzers; '
            'the matrix may be partial.'
        ) if len(coverage_sets) != len(fuzzers) else None,
    )
    return {
        **result,
        'metric': metric,
        'aggregation': 'per-fuzzer aggregate compact coverage sets',
    }


def compute_branch_stat_matrices(
    *,
    trials: list[dict[str, Any]],
    benchmark: str,
    fuzz_target: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    '''Compute pairwise branch-coverage Mann-Whitney and A12 matrices.'''

    fuzzers = sorted(
        {
            str(trial.get('fuzzer'))
            for trial in trials
            if (
                trial.get('benchmark') == benchmark
                and trial.get('fuzz_target') == fuzz_target
                and trial.get('fuzzer')
            )
        }
    )
    distributions, missing_any = _branch_coverage_distributions(
        trials=trials,
        benchmark=benchmark,
        fuzz_target=fuzz_target,
        fuzzers=fuzzers,
    )
    note = (
        'Final branch coverage missing for one or more trials; '
        'pairwise branch statistics may be partial.'
    ) if missing_any else None
    p_value_matrix = pairwise_matrix(
        fuzzers,
        distributions,
        compare=mann_whitney_u_pvalue,
        max_value=1.0,
        missing_value=1.0,
        note=note,
    )
    a12_matrix = pairwise_matrix(
        fuzzers,
        distributions,
        compare=vargha_delaney_a12,
        max_value=1.0,
        missing_value=0.5,
        note=note,
    )
    p_value_matrix.update(
        {
            'format': 'float',
            'aggregation': 'per-trial final branch coverage',
            'metric': 'branches',
            'statistic': 'mann_whitney_u_pvalue',
        }
    )
    a12_matrix.update(
        {
            'format': 'float',
            'aggregation': 'per-trial final branch coverage',
            'metric': 'branches',
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
    metric: str = 'branches',
) -> dict[str, Any]:
    '''Attach per-fuzzer exclusive coverage totals to a target.'''

    entries = target.get('fuzzers') or []
    unique_matrix = ((target.get('unique_matrix') or {}).get('by_metric') or {}).get(metric) or {}
    fuzzers = [str(fuzzer) for fuzzer in unique_matrix.get('fuzzers') or []]
    unique_counts = unique_matrix.get('unique_counts') or []
    note = unique_matrix.get('note')

    for entry in entries:
        fuzzer = str(entry.get('fuzzer') or '')
        idx = fuzzers.index(fuzzer) if fuzzer in fuzzers else -1
        total = unique_counts[idx] if idx >= 0 and idx < len(unique_counts) else None
        entry['exclusive_coverage'] = {
            'metric': metric,
            'total': int(total) if isinstance(total, (int, float)) else None,
            'min': None,
            'max': None,
            'median': None,
            'note': note,
        }
    return target


def compute_relcov_matrix(
    *,
    cov_metrics: tuple[str, ...],
    trials: list[dict[str, Any]],
    benchmark: str,
    fuzz_target: str,
    trial_coverage_sets_by_metric: dict[str, dict[str, list[set[str]]]],
) -> tuple[dict[str, Any], dict[str, float]]:
    '''Compute pairwise relative coverage and novelty-weighted branch scores.'''

    fuzzers = sorted(
        {
            str(trial.get('fuzzer'))
            for trial in trials
            if (
                trial.get('benchmark') == benchmark
                and trial.get('fuzz_target') == fuzz_target
                and trial.get('fuzzer')
            )
        }
    )
    by_metric = {
        metric: _compute_relcov_matrix_for_metric(
            fuzzers=fuzzers,
            metric=metric,
            trial_coverage_sets=trial_coverage_sets_by_metric.get(metric, {}),
        )
        for metric in cov_metrics
    }
    branch_trial_sets = trial_coverage_sets_by_metric.get('branches', {})
    score_by_fuzzer = _relcov_scores(
        fuzzers=fuzzers,
        trial_coverage_sets=branch_trial_sets,
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
    trial_coverage_sets: dict[str, list[set[str]]],
) -> dict[str, Any]:
    missing_any = len(trial_coverage_sets) != len(fuzzers) or any(
        not trial_coverage_sets.get(fuzzer)
        for fuzzer in fuzzers
    )
    matrix = relative_containment_matrix(
        fuzzers,
        trial_coverage_sets,
        note=(
            'Trial compact coverage sets missing for one or more fuzzers; '
            'relative coverage may be partial.'
        ) if missing_any else None,
    )
    return {
        **matrix,
        'format': 'pct',
        'aggregation': f'per-trial median compact {metric} coverage sets',
    }


def _coverage_by_fuzzer(
    fuzzers: list[str],
    trial_coverage_sets: dict[str, list[set[str]]],
) -> dict[str, list[set[str]]]:
    out: dict[str, list[set[str]]] = {}
    for fuzzer in fuzzers:
        trial_sets = [set(value) for value in trial_coverage_sets.get(fuzzer, [])]
        if trial_sets:
            out[fuzzer] = trial_sets
    return out


def _single_metric_matrix_group(matrix: dict[str, Any]) -> dict[str, Any]:
    '''Wrap a branch matrix in the report metric-group shape.'''

    return {
        'by_metric': {'branches': matrix},
        'has_data': bool(matrix.get('has_data')),
        'available_metrics': ['branches'] if matrix.get('has_data') else [],
    }


def _branch_coverage_distributions(
    *,
    trials: list[dict[str, Any]],
    benchmark: str,
    fuzz_target: str,
    fuzzers: list[str],
) -> tuple[dict[str, list[float]], bool]:
    distributions = {fuzzer: [] for fuzzer in fuzzers}
    missing_any = False
    for trial in trials:
        if trial.get('benchmark') != benchmark or trial.get('fuzz_target') != fuzz_target:
            continue
        fuzzer = str(trial.get('fuzzer') or '')
        if fuzzer not in distributions:
            continue
        value = safe_int((trial.get('coverage') or {}).get('branches_covered'))
        if value is None:
            missing_any = True
            continue
        distributions[fuzzer].append(float(value))
    return distributions, missing_any


def _relcov_scores(
    *,
    fuzzers: list[str],
    trial_coverage_sets: dict[str, list[set[str]]],
) -> dict[str, float]:
    '''Score each fuzzer by coverage elements that fewer peers cover.'''
    return novelty_scores(fuzzers, trial_coverage_sets)
