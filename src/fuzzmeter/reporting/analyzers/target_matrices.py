# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Attach the complete set of comparison matrices to a report target.'''

from __future__ import annotations

from typing import Any

from ..keys import (
    BRANCH_A12_MATRIX_KEY,
    BRANCH_MWU_MATRIX_KEY,
    COV_METRICS,
    RELBUG_MATRIX_KEY,
    RELBUG_SCORE_BY_FUZZER_KEY,
    RELCOV_MATRIX_KEY,
    RELCOV_SCORE_BY_FUZZER_KEY,
    UNIQUE_BUG_MATRIX_KEY,
    UNIQUE_BUG_TABLE_KEY,
    UNIQUE_MATRIX_KEY,
)
from ..set_comparison import trial_set_index
from . import bug_analysis, coverage_matrices


def attach_target_matrices(
    *,
    target: dict[str, Any],
    fuzzers: list[str],
    trials_by_fuzzer: dict[str, list[dict[str, Any]]],
    coverage_sets_by_metric: dict[str, dict[str, set[str]]],
    trial_coverage_sets_by_metric: dict[str, dict[str, list[set[str] | None]]],
) -> None:
    '''Attach pairwise coverage and bug comparison matrices to one target.'''

    trial_coverage_sets_by_metric, aggregate_fallback_fuzzers_by_metric = (
        coverage_matrices.with_aggregate_trial_fallback(
            cov_metrics=COV_METRICS,
            trial_coverage_sets_by_metric=trial_coverage_sets_by_metric,
            coverage_sets_by_metric=coverage_sets_by_metric,
            fuzzers=fuzzers,
        )
    )
    trial_set_indexes_by_metric = {
        metric: trial_set_index(fuzzers, trial_coverage_sets_by_metric.get(metric, {}))
        for metric in COV_METRICS
    }
    target[UNIQUE_MATRIX_KEY] = coverage_matrices.compute_unique_matrix(
        cov_metrics=COV_METRICS,
        fuzzers=fuzzers,
        trial_coverage_sets_by_metric=trial_coverage_sets_by_metric,
        aggregate_fallback_fuzzers_by_metric=aggregate_fallback_fuzzers_by_metric,
        trial_set_indexes_by_metric=trial_set_indexes_by_metric,
    )
    target[RELCOV_MATRIX_KEY], target[RELCOV_SCORE_BY_FUZZER_KEY] = coverage_matrices.compute_relcov_matrix(
        cov_metrics=COV_METRICS,
        fuzzers=fuzzers,
        trial_coverage_sets_by_metric=trial_coverage_sets_by_metric,
        aggregate_fallback_fuzzers_by_metric=aggregate_fallback_fuzzers_by_metric,
        trial_set_indexes_by_metric=trial_set_indexes_by_metric,
    )
    target[BRANCH_MWU_MATRIX_KEY], target[BRANCH_A12_MATRIX_KEY] = coverage_matrices.compute_branch_stat_matrices(
        fuzzers=fuzzers,
        trials_by_fuzzer=trials_by_fuzzer,
    )
    coverage_matrices.attach_exclusive_coverage_stats(
        target=target,
        trial_coverage_sets_by_metric=trial_coverage_sets_by_metric,
        aggregate_fallback_fuzzers_by_metric=aggregate_fallback_fuzzers_by_metric,
    )
    bug_fuzzers, trial_bug_sets = bug_analysis.trial_bug_sets(target)
    bug_index = trial_set_index(bug_fuzzers, trial_bug_sets)
    target[UNIQUE_BUG_TABLE_KEY] = bug_analysis.compute_unique_bug_table(target)
    target[UNIQUE_BUG_MATRIX_KEY] = bug_analysis.compute_unique_bug_matrix(
        fuzzers=bug_fuzzers,
        trial_bug_sets=trial_bug_sets,
        index=bug_index,
    )
    target[RELBUG_MATRIX_KEY], target[RELBUG_SCORE_BY_FUZZER_KEY] = bug_analysis.compute_rel_bug_matrix(
        fuzzers=bug_fuzzers,
        trial_bug_sets=trial_bug_sets,
        index=bug_index,
    )
    bug_analysis.attach_exclusive_bug_stats(target, fuzzers=bug_fuzzers, trial_bug_sets=trial_bug_sets)


def attach_empty_target_matrices(target: dict[str, Any]) -> None:
    '''Attach placeholder matrices to a target without comparable fuzzers.'''

    coverage_matrices.attach_empty_coverage_matrices(target)
    bug_analysis.attach_empty_bug_matrices(target)
