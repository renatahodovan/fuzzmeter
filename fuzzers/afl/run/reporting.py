# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Render report sections for metrics owned by the AFL adapter.'''

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from typing import Any

from fuzzmeter.reporting.metrics import safe_int
from fuzzmeter.reporting.plugin_api import ChartSeries, ChartSpec, DataPoint, ExtraSection, ReportingContext

MUTATOR_COLORS = [
    '#1F77B4', '#D62728', '#2CA02C', '#FF7F0E', '#9467BD',
    '#8C564B', '#E377C2', '#7F7F7F', '#BCBD22', '#17BECF',
    '#393B79', '#637939', '#8C6D31', '#843C39', '#7B4173',
]


def build_extra_sections(ctx: ReportingContext) -> list[ExtraSection]:
    '''Build the AFL mutator usefulness chart from persisted snapshot metrics.'''

    series, _ = _mutator_report(ctx)
    if not series:
        return []
    return [
        ExtraSection(
            id='afl-mutators',
            title='AFL mutators',
            charts=[
                ChartSpec(
                    id='mutator-usefulness-ratio',
                    type='stacked_area',
                    title='Mutator usefulness ratio',
                    subtitle='Percentage distribution of AFL custom mutators across snapshot corpora.',
                    x_axis='elapsed seconds',
                    y_axis='percent',
                    filter_mode='static',
                    series=series,
                )
            ],
        )
    ]


def build_debug_info(ctx: ReportingContext) -> dict[str, Any]:
    '''Describe AFL mutator chart bucketing and rendered series counts.'''

    _, debug = _mutator_report(ctx)
    return debug


def _mutator_report(ctx: ReportingContext) -> tuple[list[ChartSeries], dict[str, int | None]]:
    trial_histories = []
    for trial in ctx.trials:
        trial_history = []
        for point in ctx.timeseries(trial.trial_id).get('points') or []:
            metric = _custom_metrics_from_point(point)
            if metric is None:
                continue
            counts = _counter_map(metric)
            if not counts:
                continue
            elapsed_seconds = safe_int(point.get('elapsed_s')) or safe_int(point.get('idx')) or 0
            trial_history.append((int(elapsed_seconds), counts))
        if trial_history:
            trial_histories.append(trial_history)

    if not trial_histories:
        return [], {'bucket_size_seconds': None, 'time_points': 0, 'series_count': 0}
    return _mutator_series_from_histories(trial_histories)


def _custom_metrics_from_point(point: dict[str, Any]) -> dict[str, Any] | None:
    stats = point.get('stats')
    if not isinstance(stats, dict):
        return None
    metric = stats.get('custom_metrics')
    if not isinstance(metric, dict):
        return None
    return metric


def _counter_map(metric: dict[str, Any]) -> dict[str, int]:
    counts = metric.get('counts')
    if not isinstance(counts, dict):
        return {}
    out = {}
    for name, value in counts.items():
        text = str(name).strip()
        if not text:
            continue
        count = safe_int(value)
        if count is not None and count > 0:
            out[text] = int(count)
    return out


def _bucket_size(max_elapsed_seconds: int) -> int:
    if max_elapsed_seconds <= 0:
        return 300
    candidates = [60, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]
    minimum = max(60, int(max_elapsed_seconds / 32))
    for candidate in candidates:
        if candidate >= minimum:
            return candidate
    return candidates[-1]


def _bucket_boundaries(max_elapsed_seconds: int, step: int) -> list[int]:
    if max_elapsed_seconds <= 0:
        return [0]
    buckets = list(range(0, max_elapsed_seconds + 1, step))
    if buckets[-1] != max_elapsed_seconds:
        buckets.append(max_elapsed_seconds)
    return buckets


def _aggregate_trial_history(
    trial_history: list[tuple[int, dict[str, int]]],
    buckets: list[int],
    out: dict[int, dict[str, int]],
) -> None:
    for elapsed_seconds, counts in trial_history:
        bucket = buckets[min(bisect_left(buckets, elapsed_seconds), len(buckets) - 1)]
        for mutator, count in counts.items():
            out[bucket][mutator] += int(count)


def _mutator_series_from_histories(
    trial_histories: list[list[tuple[int, dict[str, int]]]],
) -> tuple[list[ChartSeries], dict[str, int]]:
    counts_by_time: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    max_elapsed_seconds = max(elapsed for history in trial_histories for elapsed, _ in history)
    bucket_size = _bucket_size(max_elapsed_seconds)
    buckets = _bucket_boundaries(max_elapsed_seconds, bucket_size)
    for trial_history in trial_histories:
        _aggregate_trial_history(trial_history, buckets, counts_by_time)

    mutator_totals: dict[str, int] = defaultdict(int)
    for time_counts in counts_by_time.values():
        for mutator, count in time_counts.items():
            mutator_totals[mutator] += int(count)

    mutators = [name for name, _ in sorted(mutator_totals.items(), key=lambda item: (-item[1], item[0]))]
    series = []
    for index, mutator in enumerate(mutators):
        points = []
        for elapsed_seconds in sorted(counts_by_time):
            time_counts = counts_by_time[elapsed_seconds]
            total = sum(time_counts.values())
            if total <= 0:
                continue
            points.append(
                DataPoint(
                    x=elapsed_seconds,
                    y=100.0 * time_counts.get(mutator, 0) / total,
                    meta={'elapsed_seconds': elapsed_seconds, 'mutator': mutator},
                )
            )
        if points:
            series.append(
                ChartSeries(
                    id=mutator,
                    label=mutator,
                    points=points,
                    color_hint=MUTATOR_COLORS[index % len(MUTATOR_COLORS)],
                )
            )
    return series, {
        'bucket_size_seconds': bucket_size,
        'time_points': len(counts_by_time),
        'series_count': len(series),
    }
