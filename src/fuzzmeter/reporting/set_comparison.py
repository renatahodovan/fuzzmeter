# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build reusable set comparison matrices for report analyzers.'''

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .metrics import median


def empty_trial_set_comparison() -> dict[str, Any]:
    '''Return the empty strict/non-strict set-comparison payload shape.'''

    return trial_set_comparison([], {})


def trial_set_comparison(
    labels: list[str],
    trial_sets_by_label: Mapping[str, Sequence[set[str] | None]],
    *,
    note: str | None = None,
    strict_unknown_labels: set[str] | None = None,
    index: TrialSetIndex | None = None,
) -> dict[str, Any]:
    '''Return strict and non-strict pairwise and exclusive set counts.'''

    index = index or trial_set_index(labels, trial_sets_by_label)
    strict_unknown = strict_unknown_labels or set()
    (
        pairwise_any,
        pairwise_all,
        pairwise_any_bounds,
        pairwise_all_bounds,
        exclusive_any,
        exclusive_all,
        exclusive_any_bounds,
        exclusive_all_bounds,
    ) = _trial_set_counts(
        labels,
        index,
        strict_unknown,
    )

    numeric_values = [
        value
        for matrix in (pairwise_any, pairwise_all)
        for row in matrix
        for value in row
        if value is not None
    ]
    return {
        'fuzzers': labels,
        'pairwise_unique_any': pairwise_any,
        'pairwise_unique_all': pairwise_all,
        'pairwise_unique_any_bounds': pairwise_any_bounds,
        'pairwise_unique_all_bounds': pairwise_all_bounds,
        'exclusive': {
            'exclusive_any': exclusive_any,
            'exclusive_all': exclusive_all,
            'exclusive_any_bounds': exclusive_any_bounds,
            'exclusive_all_bounds': exclusive_all_bounds,
        },
        'covered_counts': [
            len(index.unions[label]) if index.reps[label] else None
            for label in labels
        ],
        'sample_sizes': index.sample_sizes,
        'usable_sample_sizes': index.usable_sample_sizes,
        'has_data': bool(index.owners),
        'note': ' '.join(filter(None, (
            note,
            _trial_set_comparison_note(labels, index.usable_sample_sizes, index.missing_by_label),
        ))) or None,
        'max_value': max(numeric_values, default=0),
    }


def _trial_set_comparison_note(
    labels: list[str],
    usable_sample_sizes: list[int],
    missing_by_label: Mapping[str, int],
) -> str | None:
    '''Describe missing trial sets and uneven repetition counts once per matrix.

    The counts depend on how many trials each fuzzer contributed, so an uneven
    split makes two cells incomparable. Reporting it here keeps that out of every
    individual cell, where a uniform count would only be noise.
    '''

    parts = []
    if any(missing_by_label.values()):
        parts.append(
            'One or more trial sets are missing: non-strict values are marked as bounds or degraded, '
            'and strict subject-side values are unknown.'
        )
    usable = [size for size in usable_sample_sizes if size]
    if usable and min(usable) != max(usable):
        uneven = ', '.join(
            f'{label} n={size}'
            for label, size in zip(labels, usable_sample_sizes, strict=True)
        )
        parts.append(f'Repetition counts differ, so counts are not directly comparable ({uneven}).')
    return ' '.join(parts) or None


@dataclass
class TrialSetIndex:
    '''Index trial-set ownership and per-label unions in one pass.'''

    owners: dict[str, dict[str, int]]
    reps: dict[str, int]
    sample_sizes: list[int]
    usable_sample_sizes: list[int]
    missing_by_label: dict[str, int]
    trials_by_label: dict[str, list[set[str]]]
    unions: dict[str, set[str]]


def trial_set_index(
    labels: list[str],
    trial_sets_by_label: Mapping[str, Sequence[set[str] | None]],
) -> TrialSetIndex:
    '''Build the shared ownership index for a collection of trial sets.'''

    owners: dict[str, dict[str, int]] = {}
    reps: dict[str, int] = {}
    sample_sizes: list[int] = []
    usable_sample_sizes: list[int] = []
    missing_by_label: dict[str, int] = {}
    trials_by_label: dict[str, list[set[str]]] = {}
    unions: dict[str, set[str]] = {label: set() for label in labels}
    for label in labels:
        trial_sets = list(trial_sets_by_label.get(label, []))
        usable = [values for values in trial_sets if values is not None]
        trials_by_label[label] = usable
        reps[label] = len(usable)
        sample_sizes.append(len(trial_sets))
        usable_sample_sizes.append(len(usable))
        missing_by_label[label] = len(trial_sets) - len(usable)
        owner_count_by_value: Counter[str] = Counter()
        for values in usable:
            owner_count_by_value.update(values)
        unions[label] = set(owner_count_by_value)
        for value, count in owner_count_by_value.items():
            owners.setdefault(value, {})[label] = count
    return TrialSetIndex(
        owners=owners,
        reps=reps,
        sample_sizes=sample_sizes,
        usable_sample_sizes=usable_sample_sizes,
        missing_by_label=missing_by_label,
        trials_by_label=trials_by_label,
        unions=unions,
    )


def _trial_set_counts(
    labels: list[str],
    index: TrialSetIndex,
    strict_unknown_labels: set[str],
) -> tuple[
    list[list[int | None]],
    list[list[int | None]],
    list[list[str]],
    list[list[str]],
    list[int | None],
    list[int | None],
    list[str],
    list[str],
]:
    label_indexes = {label: position for position, label in enumerate(labels)}
    pairwise_any_counts = [[0 for _ in labels] for _ in labels]
    pairwise_all_counts = [[0 for _ in labels] for _ in labels]
    exclusive_any_counts = [0 for _ in labels]
    exclusive_all_counts = [0 for _ in labels]

    for owner_counts in index.owners.values():
        if len(owner_counts) == 1:
            row_label, row_count = next(iter(owner_counts.items()))
            row_index = label_indexes[row_label]
            exclusive_any_counts[row_index] += 1
            if row_count == index.reps[row_label]:
                exclusive_all_counts[row_index] += 1
        for row_label, row_count in owner_counts.items():
            row_index = label_indexes[row_label]
            for col_index, col_label in enumerate(labels):
                if col_label in owner_counts:
                    continue
                pairwise_any_counts[row_index][col_index] += 1
                if row_count == index.reps[row_label]:
                    pairwise_all_counts[row_index][col_index] += 1

    pairwise_any: list[list[int | None]] = []
    pairwise_all: list[list[int | None]] = []
    pairwise_any_bounds: list[list[str]] = []
    pairwise_all_bounds: list[list[str]] = []
    exclusive_any: list[int | None] = []
    exclusive_all: list[int | None] = []
    exclusive_any_bounds: list[str] = []
    exclusive_all_bounds: list[str] = []

    # Missing-set propagation:
    # subject     comparison   any/union                         all/intersection
    # complete    complete     exact                             exact
    # partial     complete     lower bound                       UNKNOWN
    # complete    partial      upper bound                       upper bound
    # partial     partial      degraded, direction indeterminate UNKNOWN
    # all missing any          UNKNOWN                           UNKNOWN
    for row_index, row_label in enumerate(labels):
        any_row: list[int | None] = []
        all_row: list[int | None] = []
        any_bounds_row: list[str] = []
        all_bounds_row: list[str] = []
        for col_index, col_label in enumerate(labels):
            row_missing = index.missing_by_label[row_label]
            col_missing = index.missing_by_label[col_label]
            if index.reps[row_label] == 0:
                any_row.append(None)
                any_bounds_row.append('unknown')
            else:
                any_row.append(pairwise_any_counts[row_index][col_index])
                any_bounds_row.append(
                    'indeterminate' if row_missing and col_missing
                    else 'lower' if row_missing
                    else 'upper' if col_missing
                    else 'exact'
                )
            if index.reps[row_label] == 0 or row_missing or row_label in strict_unknown_labels:
                all_row.append(None)
                all_bounds_row.append('unknown')
            else:
                all_row.append(pairwise_all_counts[row_index][col_index])
                all_bounds_row.append('upper' if col_missing else 'exact')
        pairwise_any.append(any_row)
        pairwise_all.append(all_row)
        pairwise_any_bounds.append(any_bounds_row)
        pairwise_all_bounds.append(all_bounds_row)

    for row_index, row_label in enumerate(labels):
        row_missing = index.missing_by_label[row_label]
        other_missing = any(index.missing_by_label[label] for label in labels if label != row_label)
        if index.reps[row_label] == 0:
            exclusive_any.append(None)
            exclusive_any_bounds.append('unknown')
        else:
            exclusive_any.append(exclusive_any_counts[row_index])
            exclusive_any_bounds.append(
                'indeterminate' if row_missing and other_missing
                else 'lower' if row_missing
                else 'upper' if other_missing
                else 'exact'
            )
        if index.reps[row_label] == 0 or row_missing or row_label in strict_unknown_labels:
            exclusive_all.append(None)
            exclusive_all_bounds.append('unknown')
        else:
            exclusive_all.append(exclusive_all_counts[row_index])
            exclusive_all_bounds.append('upper' if other_missing else 'exact')
    return (
        pairwise_any,
        pairwise_all,
        pairwise_any_bounds,
        pairwise_all_bounds,
        exclusive_any,
        exclusive_all,
        exclusive_any_bounds,
        exclusive_all_bounds,
    )


def pairwise_matrix(
    labels: list[str],
    values_by_label: Mapping[str, list[float]],
    *,
    compare: Callable[[list[float], list[float]], float | None],
    max_value: float | None = None,
    missing_value: float = 0.0,
    note: str | None = None,
) -> dict[str, Any]:
    '''Return a pairwise matrix derived from per-label numeric distributions.'''

    matrix: list[list[float]] = []
    for row_label in labels:
        row: list[float] = []
        for col_label in labels:
            cell = compare(
                values_by_label.get(row_label, []),
                values_by_label.get(col_label, []),
            )
            row.append(float(cell) if cell is not None else float(missing_value))
        matrix.append(row)

    return {
        'fuzzers': labels,
        'matrix': matrix,
        'sample_sizes': [len(values_by_label.get(label, [])) for label in labels],
        'has_data': any(values_by_label.get(label, []) for label in labels),
        'note': note,
        'max_value': (
            float(max_value)
            if max_value is not None
            else max((max(row, default=0.0) for row in matrix), default=0.0)
        ),
    }


def relative_containment_matrix(
    labels: list[str],
    trial_sets_by_label: Mapping[str, Sequence[set[str] | None]],
    *,
    note: str | None = None,
    index: TrialSetIndex | None = None,
) -> dict[str, Any]:
    '''Return row trial median containment against each column union set.'''

    index = index or trial_set_index(labels, trial_sets_by_label)
    matrix: list[list[float | None]] = []
    for row_label in labels:
        row_trials = index.trials_by_label[row_label]
        row_values: list[float | None] = []
        for col_label in labels:
            col_union = index.unions[col_label]
            denominator = len(col_union)
            values = (
                [
                    100.0 * len(row_set & col_union) / denominator
                    for row_set in row_trials
                ]
                if denominator > 0
                else []
            )
            value = median(values)
            row_values.append(value)
        matrix.append(row_values)

    numeric_values = [value for row in matrix for value in row if value is not None]

    return {
        'fuzzers': labels,
        'matrix': matrix,
        'covered_counts': [len(index.unions[label]) for label in labels],
        'has_data': bool(index.owners),
        'note': note,
        'max_value': max(numeric_values, default=0.0),
    }


def novelty_scores(
    labels: list[str],
    trial_sets_by_label: Mapping[str, Sequence[set[str] | None]],
    *,
    index: TrialSetIndex | None = None,
) -> dict[str, float]:
    '''Score labels by values that fewer peers contain, averaged over trials.'''

    index = index or trial_set_index(labels, trial_sets_by_label)
    scores: dict[str, float] = {}
    for label in labels:
        trial_sets = index.trials_by_label[label]
        denominator = sum(1 for values in trial_sets if values)
        if denominator <= 0:
            continue
        scores[label] = sum(
            float(len(labels) - len(owner_counts))
            * owner_counts.get(label, 0)
            / denominator
            for owner_counts in index.owners.values()
        )
    return scores
