# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from typing import Any, Sequence

from .plugin_api import ChartSeries, ChartSpec, DataPoint, ExtraSection, MatrixData

ALLOWED_CHART_TYPES = {
    'bar',
    'distribution',
    'line',
    'line_shadow',
    'lines_with_shadows',
    'matrix',
    'stacked_area',
    'stacked_bar',
    'table',
}
ALLOWED_FILTER_MODES = {'series', 'recompute', 'static'}
ALLOWED_PLACEMENTS = {'after:coverage', 'after:performance', 'after:bugs', 'after:target'}
ALLOWED_SCOPES = {'target', 'fuzzer'}


def validate_extra_sections(sections: Any) -> tuple[list[ExtraSection], list[str]]:
    '''Return web-compatible extra sections and validation warnings.'''

    if sections is None:
        return [], []
    if not isinstance(sections, list):
        return [], ['plugin output is not a list']

    valid_sections = []
    warnings = []
    for index, section in enumerate(sections):
        warning = _section_warning(section)
        if warning:
            warnings.append(f'section[{index}]: {warning}')
            continue
        valid_sections.append(section)
    return valid_sections, warnings


def serialize_extra_sections(
    sections: Sequence[ExtraSection],
    *,
    default_owner_fuzzer: str | None = None,
) -> list[dict[str, Any]]:
    '''Serialize validated extra sections for the web report payload.'''

    return [
        {
            'id': section.id,
            'title': section.title,
            'scope': section.scope,
            'placement': section.placement,
            'owner_fuzzer': section.owner_fuzzer or (default_owner_fuzzer if section.scope == 'fuzzer' else None),
            'charts': [_serialize_chart(chart) for chart in section.charts],
        }
        for section in sections
    ]


def _section_warning(section: Any) -> str | None:
    if not isinstance(section, ExtraSection):
        return 'not an ExtraSection'
    if not _is_text(section.id):
        return 'missing section id'
    if not _is_text(section.title):
        return 'missing section title'
    if section.scope not in ALLOWED_SCOPES:
        return f'unsupported scope: {section.scope}'
    if section.placement not in ALLOWED_PLACEMENTS:
        return f'unsupported placement: {section.placement}'
    if not section.charts:
        return 'section has no charts'
    for index, chart in enumerate(section.charts):
        warning = _chart_warning(chart)
        if warning:
            return f'chart[{index}]: {warning}'
    return None


def _chart_warning(chart: Any) -> str | None:
    if not isinstance(chart, ChartSpec):
        return 'not a ChartSpec'
    if not _is_text(chart.id):
        return 'missing chart id'
    if not _is_text(chart.title):
        return 'missing chart title'
    if chart.type not in ALLOWED_CHART_TYPES:
        return f'unsupported chart type: {chart.type}'
    if chart.filter_mode not in ALLOWED_FILTER_MODES:
        return f'unsupported filter mode: {chart.filter_mode}'
    if chart.type == 'matrix':
        matrix_warning = _matrix_warning(chart.matrix)
        if matrix_warning:
            return matrix_warning
    if chart.type == 'table' and not chart.columns:
        return 'table chart has no columns'
    return None


def _matrix_warning(matrix: MatrixData | None) -> str | None:
    if matrix is None:
        return 'matrix chart has no matrix'
    if not matrix.fuzzers:
        return 'matrix chart has no labels'
    if len(matrix.matrix) != len(matrix.fuzzers):
        return 'matrix row count does not match labels'
    if any(len(row) != len(matrix.fuzzers) for row in matrix.matrix):
        return 'matrix column count does not match labels'
    return None


def _serialize_point(point: DataPoint) -> dict[str, Any]:
    return {
        'x': point.x,
        'y': point.y,
        'lo': point.lo,
        'hi': point.hi,
        'meta': dict(point.meta),
    }


def _serialize_series(series: ChartSeries) -> dict[str, Any]:
    return {
        'id': series.id,
        'label': series.label,
        'points': [_serialize_point(point) for point in series.points],
        'values': list(series.values),
        'color_hint': series.color_hint,
    }


def _serialize_matrix(matrix: MatrixData | None) -> dict[str, Any] | None:
    if matrix is None:
        return None
    return {
        'fuzzers': list(matrix.fuzzers),
        'matrix': [list(row) for row in matrix.matrix],
        'max_value': matrix.max_value,
        'note': matrix.note,
        'covered_counts': list(matrix.covered_counts) if matrix.covered_counts is not None else None,
        'unique_counts': list(matrix.unique_counts) if matrix.unique_counts is not None else None,
    }


def _serialize_chart(chart: ChartSpec) -> dict[str, Any]:
    return {
        'id': chart.id,
        'type': chart.type,
        'title': chart.title,
        'subtitle': chart.subtitle,
        'x_axis': chart.x_axis,
        'y_axis': chart.y_axis,
        'metric_key': chart.metric_key,
        'filter_mode': chart.filter_mode,
        'series': [_serialize_series(series) for series in chart.series],
        'matrix': _serialize_matrix(chart.matrix),
        'columns': [{'key': column.key, 'label': column.label, 'kind': column.kind} for column in chart.columns],
        'rows': [dict(row) for row in chart.rows],
    }


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
