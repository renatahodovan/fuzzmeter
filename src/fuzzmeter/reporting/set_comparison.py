# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build reusable set comparison matrices for report analyzers.'''

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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
) -> dict[str, Any]:
    '''Return strict and non-strict pairwise and exclusive set counts.'''

    owners, reps, sample_sizes, usable_sample_sizes, missing_by_label = _trial_set_index(
        labels,
        trial_sets_by_label,
    )
    pairwise_any, pairwise_all, pairwise_any_bounds, pairwise_all_bounds = _pairwise_trial_set_counts(
        labels,
        owners,
        reps,
        missing_by_label,
    )
    exclusive_any, exclusive_all, exclusive_any_bounds, exclusive_all_bounds = _exclusive_trial_set_counts(
        labels,
        owners,
        reps,
        missing_by_label,
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
            sum(1 for owner_counts in owners.values() if owner_counts.get(label, 0) > 0)
            if reps[label] else None
            for label in labels
        ],
        'sample_sizes': sample_sizes,
        'usable_sample_sizes': usable_sample_sizes,
        'has_data': bool(owners),
        'note': note or _trial_set_comparison_note(labels, usable_sample_sizes, missing_by_label),
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


def _trial_set_index(
    labels: list[str],
    trial_sets_by_label: Mapping[str, Sequence[set[str] | None]],
) -> tuple[dict[str, dict[str, int]], dict[str, int], list[int], list[int], dict[str, int]]:
    owners: dict[str, dict[str, int]] = {}
    reps: dict[str, int] = {}
    sample_sizes: list[int] = []
    usable_sample_sizes: list[int] = []
    missing_by_label: dict[str, int] = {}
    for label in labels:
        trial_sets = list(trial_sets_by_label.get(label, []))
        usable = [values for values in trial_sets if values is not None]
        reps[label] = len(usable)
        sample_sizes.append(len(trial_sets))
        usable_sample_sizes.append(len(usable))
        missing_by_label[label] = len(trial_sets) - len(usable)
        for values in usable:
            for value in values:
                owner_counts = owners.setdefault(value, {})
                owner_counts[label] = owner_counts.get(label, 0) + 1
    return owners, reps, sample_sizes, usable_sample_sizes, missing_by_label


def _pairwise_trial_set_counts(
    labels: list[str],
    owners: Mapping[str, Mapping[str, int]],
    reps: Mapping[str, int],
    missing_by_label: Mapping[str, int],
) -> tuple[list[list[int | None]], list[list[int | None]], list[list[str]], list[list[str]]]:
    pairwise_any: list[list[int | None]] = []
    pairwise_all: list[list[int | None]] = []
    pairwise_any_bounds: list[list[str]] = []
    pairwise_all_bounds: list[list[str]] = []

    # Missing-set propagation:
    # subject     comparison   any/union                         all/intersection
    # complete    complete     exact                             exact
    # partial     complete     lower bound                       UNKNOWN
    # complete    partial      upper bound                       upper bound
    # partial     partial      degraded, direction indeterminate UNKNOWN
    # all missing any          UNKNOWN                           UNKNOWN
    for row_label in labels:
        any_row: list[int | None] = []
        all_row: list[int | None] = []
        any_bounds_row: list[str] = []
        all_bounds_row: list[str] = []
        for col_label in labels:
            row_missing = missing_by_label[row_label]
            col_missing = missing_by_label[col_label]
            if reps[row_label] == 0:
                any_row.append(None)
                any_bounds_row.append('unknown')
            else:
                any_row.append(sum(
                    1
                    for owner_counts in owners.values()
                    if owner_counts.get(row_label, 0) > 0 and owner_counts.get(col_label, 0) == 0
                ))
                any_bounds_row.append(
                    'indeterminate' if row_missing and col_missing
                    else 'lower' if row_missing
                    else 'upper' if col_missing
                    else 'exact'
                )
            if reps[row_label] == 0 or row_missing:
                all_row.append(None)
                all_bounds_row.append('unknown')
            else:
                all_row.append(sum(
                    1
                    for owner_counts in owners.values()
                    if owner_counts.get(row_label, 0) == reps[row_label] and owner_counts.get(col_label, 0) == 0
                ))
                all_bounds_row.append('upper' if col_missing else 'exact')
        pairwise_any.append(any_row)
        pairwise_all.append(all_row)
        pairwise_any_bounds.append(any_bounds_row)
        pairwise_all_bounds.append(all_bounds_row)
    return pairwise_any, pairwise_all, pairwise_any_bounds, pairwise_all_bounds


def _exclusive_trial_set_counts(
    labels: list[str],
    owners: Mapping[str, Mapping[str, int]],
    reps: Mapping[str, int],
    missing_by_label: Mapping[str, int],
) -> tuple[list[int | None], list[int | None], list[str], list[str]]:
    exclusive_any: list[int | None] = []
    exclusive_all: list[int | None] = []
    exclusive_any_bounds: list[str] = []
    exclusive_all_bounds: list[str] = []
    for row_label in labels:
        row_missing = missing_by_label[row_label]
        other_missing = any(missing_by_label[label] for label in labels if label != row_label)
        if reps[row_label] == 0:
            exclusive_any.append(None)
            exclusive_any_bounds.append('unknown')
        else:
            exclusive_any.append(sum(
                1
                for owner_counts in owners.values()
                if (
                    owner_counts.get(row_label, 0) > 0
                    and not any(owner_counts.get(label, 0) > 0 for label in labels if label != row_label)
                )
            ))
            exclusive_any_bounds.append(
                'indeterminate' if row_missing and other_missing
                else 'lower' if row_missing
                else 'upper' if other_missing
                else 'exact'
            )
        if reps[row_label] == 0 or row_missing:
            exclusive_all.append(None)
            exclusive_all_bounds.append('unknown')
        else:
            exclusive_all.append(sum(
                1
                for owner_counts in owners.values()
                if (
                    owner_counts.get(row_label, 0) == reps[row_label]
                    and not any(owner_counts.get(label, 0) > 0 for label in labels if label != row_label)
                )
            ))
            exclusive_all_bounds.append('upper' if other_missing else 'exact')
    return exclusive_any, exclusive_all, exclusive_any_bounds, exclusive_all_bounds


def unique_matrix(labels: list[str], sets: Mapping[str, set[str]], *, note: str | None = None) -> dict[str, Any]:
    '''Return pairwise row-minus-column set sizes and per-row unique counts.'''

    matrix: list[list[int]] = []
    unique_counts: list[int] = []
    has_all_labels = len(sets) == len(labels)
    for row_label in labels:
        row_set = sets.get(row_label)
        row: list[int] = []
        for col_label in labels:
            if row_set is None or col_label not in sets:
                row.append(0)
            else:
                row.append(len(row_set - sets[col_label]))
        matrix.append(row)
        unique_counts.append(exclusive_total(row_label, sets) if has_all_labels else 0)

    return {
        'fuzzers': labels,
        'matrix': matrix,
        'covered_counts': [len(sets.get(label, set())) for label in labels],
        'unique_counts': unique_counts,
        'has_data': any(bool(values) for values in sets.values()),
        'note': note,
        'max_value': max((max(row, default=0) for row in matrix), default=0),
    }


def exclusive_total(label: str, sets: Mapping[str, set[str]]) -> int:
    '''Return the number of values that only the selected label contains.'''
    values = sets.get(label)
    if values is None:
        return 0
    other_union = set().union(*(other_values for other, other_values in sets.items() if other != label))
    return len(values - other_union)


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
    trial_sets_by_label: Mapping[str, list[set[str]]],
    *,
    note: str | None = None,
) -> dict[str, Any]:
    '''Return row trial median containment against each column union set.'''

    normalized = _sets_by_label(labels, trial_sets_by_label)
    matrix: list[list[float]] = []
    max_value = 0.0
    for row_label in labels:
        row_trials = normalized.get(row_label, [])
        row_values = []
        for col_label in labels:
            col_union = set().union(*normalized.get(col_label, []))
            denominator = len(col_union)
            values = [
                100.0 * len(row_set & col_union) / denominator
                for row_set in row_trials
                if denominator > 0
            ]
            value = median(values) or 0.0
            row_values.append(value)
            max_value = max(max_value, value)
        matrix.append(row_values)

    return {
        'fuzzers': labels,
        'matrix': matrix,
        'covered_counts': [len(set().union(*normalized.get(label, []))) for label in labels],
        'has_data': any(any(bool(value) for value in values) for values in normalized.values()),
        'note': note,
        'max_value': max_value,
    }


def novelty_scores(labels: list[str], trial_sets_by_label: Mapping[str, list[set[str]]]) -> dict[str, float]:
    '''Score labels by values that fewer peers contain, averaged over trials.'''

    normalized = _sets_by_label(labels, trial_sets_by_label)
    union_by_label = {
        label: set().union(*normalized.get(label, []))
        for label in labels
    }
    all_values = set().union(*union_by_label.values()) if union_by_label else set()
    missing_labels = {
        value: sum(1 for label in labels if value not in union_by_label.get(label, set()))
        for value in all_values
    }
    scores: dict[str, float] = {}
    for label in labels:
        trial_sets = normalized.get(label, [])
        denominator = sum(1 for values in trial_sets if values)
        if denominator <= 0:
            continue
        scores[label] = sum(
            float(missing_labels[value])
            * sum(1 for values in trial_sets if value in values)
            / denominator
            for value in all_values
        )
    return scores


def _sets_by_label(labels: list[str], trial_sets_by_label: Mapping[str, list[set[str]]]) -> dict[str, list[set[str]]]:
    out: dict[str, list[set[str]]] = {}
    for label in labels:
        values = [set(value) for value in trial_sets_by_label.get(label, [])]
        if values:
            out[label] = values
    return out
