# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build reusable set comparison matrices for report analyzers.'''

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def unique_matrix(labels: list[str], sets: Mapping[str, set[str]], *, note: str | None = None) -> dict[str, Any]:
    '''Return pairwise row-minus-column set sizes and per-row unique counts.'''
    matrix = [
        [
            len(row_set - sets[col_label]) if row_set is not None and col_label in sets else 0
            for col_label in labels
        ]
        for row_label in labels
        for row_set in [sets.get(row_label)]
    ]
    return {
        'fuzzers': labels,
        'matrix': matrix,
        'covered_counts': [len(sets.get(label, set())) for label in labels],
        'unique_counts': [
            _exclusive_count(row_label, row_set, sets) if len(sets) == len(labels) else 0
            for row_label in labels
            for row_set in [sets.get(row_label)]
        ],
        'has_data': any(bool(values) for values in sets.values()),
        'note': note,
        'max_value': max((max(row, default=0) for row in matrix), default=0),
    }


def exclusive_total(label: str, sets: Mapping[str, set[str]]) -> int:
    '''Return the number of values that only the selected label contains.'''
    return _exclusive_count(label, sets.get(label), sets)


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

    matrix = [
        [
            float(cell) if cell is not None else float(missing_value)
            for col_label in labels
            for cell in [compare(values_by_label.get(row_label, []), values_by_label.get(col_label, []))]
        ]
        for row_label in labels
    ]
    return {
        'fuzzers': labels,
        'matrix': matrix,
        'sample_sizes': [len(values_by_label.get(label, [])) for label in labels],
        'has_data': any(values_by_label.get(label, []) for label in labels),
        'note': note,
        'max_value': float(max_value) if max_value is not None else max((max(row, default=0.0) for row in matrix), default=0.0),
    }


def _exclusive_count(label: str, values: set[str] | None, sets: Mapping[str, set[str]]) -> int:
    if values is None:
        return 0
    other_union = set().union(*(values for other, values in sets.items() if other != label))
    return len(values - other_union)
