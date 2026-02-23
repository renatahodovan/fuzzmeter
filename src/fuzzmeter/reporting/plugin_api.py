# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

ChartType = Literal[
    'bar',
    'distribution',
    'line',
    'line_shadow',
    'lines_with_shadows',
    'matrix',
    'stacked_area',
    'stacked_bar',
    'table',
]
ChartFilterMode = Literal['series', 'recompute', 'static']
SectionScope = Literal['target', 'fuzzer']
SectionPlacement = Literal['after:coverage', 'after:performance', 'after:bugs', 'after:target']


@dataclass(frozen=True)
class DataPoint:
    '''Describe one chart data point.'''

    x: int | float | str | None
    y: int | float | None
    lo: int | float | None = None
    hi: int | float | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChartSeries:
    '''Describe one chart series.'''

    id: str
    label: str
    points: list[DataPoint] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    color_hint: str | None = None


@dataclass(frozen=True)
class TableColumn:
    '''Describe one report table column.'''

    key: str
    label: str
    kind: str = 'text'


@dataclass(frozen=True)
class MatrixData:
    '''Describe a square fuzzer comparison matrix.'''

    fuzzers: list[str]
    matrix: list[list[int]]
    max_value: int
    note: str | None = None
    covered_counts: list[int] | None = None
    unique_counts: list[int] | None = None


@dataclass(frozen=True)
class ChartSpec:
    '''Describe one chart rendered by the web report.'''

    id: str
    type: ChartType
    title: str
    subtitle: str | None = None
    x_axis: str | None = None
    y_axis: str | None = None
    metric_key: str | None = None
    filter_mode: ChartFilterMode = 'series'
    series: list[ChartSeries] = field(default_factory=list)
    matrix: MatrixData | None = None
    columns: list[TableColumn] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ExtraSection:
    '''Describe one plugin-provided report section.'''

    id: str
    title: str
    scope: SectionScope
    placement: SectionPlacement
    owner_fuzzer: str | None = None
    charts: list[ChartSpec] = field(default_factory=list)


@dataclass(frozen=True)
class ReportingContext:
    '''Provide fuzzer reporting plugins with data for one fuzzer-target report section.'''

    run_id: str
    run_dir: Path
    benchmark: str
    fuzz_target: str
    fuzzer: str
    trials: list[dict[str, Any]]
    timeseries_by_trial: dict[int, dict[str, Any]]
    bugs: list[dict[str, Any]]
    snapshot_dirs_by_trial: dict[int, list[Path]]

    def timeseries(self, trial_id: int) -> dict[str, Any]:
        '''Return the collected time series for a trial.'''

        return self.timeseries_by_trial.get(int(trial_id), {'trial_id': int(trial_id), 'points': []})


class ReportingPlugin(Protocol):
    '''Build optional report sections for a fuzzer.'''

    def build_extra_sections(self, ctx: ReportingContext) -> list[ExtraSection]:
        '''Return additional report sections for the current fuzzer-target pair.'''

        ...


__all__ = [
    'ChartFilterMode',
    'ChartSeries',
    'ChartSpec',
    'ChartType',
    'DataPoint',
    'ExtraSection',
    'MatrixData',
    'ReportingContext',
    'ReportingPlugin',
    'SectionPlacement',
    'SectionScope',
    'TableColumn',
]
