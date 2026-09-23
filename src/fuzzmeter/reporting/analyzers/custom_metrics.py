# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build custom report sections from metrics persisted in snapshot stats.'''

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from typing import Any

from ..metrics import safe_int
from ..plugin_api import ChartSeries, ChartSpec, DataPoint, ExtraSection
from ..web_payload import serialize_extra_sections

CUSTOM_METRICS_SCHEMA_VERSION = 1
MUTATOR_COLORS = [
    '#1F77B4',
    '#D62728',
    '#2CA02C',
    '#FF7F0E',
    '#9467BD',
    '#8C564B',
    '#E377C2',
    '#7F7F7F',
    '#BCBD22',
    '#17BECF',
    '#393B79',
    '#637939',
    '#8C6D31',
    '#843C39',
    '#7B4173',
]


def attach_custom_metric_sections(targets: list[dict[str, Any]], timeseries: dict[str, Any]) -> None:
    '''Attach DB-backed custom metric sections to target fuzzer entries.'''

    points_by_trial = {
        int(entry['trial_id']): list(entry.get('points') or [])
        for entry in (timeseries.get('per_trial') or {}).values()
        if entry.get('trial_id') is not None
    }
    for target in targets:
        for fuzzer_entry in target.get('fuzzers') or []:
            sections, debug = _sections_for_fuzzer(fuzzer_entry, points_by_trial)
            if sections:
                fuzzer_entry['extra_sections'] = [
                    *(fuzzer_entry.get('extra_sections') or []),
                    *serialize_extra_sections(sections, default_owner_fuzzer=str(fuzzer_entry.get('fuzzer') or '')),
                ]
            if debug:
                fuzzer_entry['extra_section_debug'] = [
                    *(fuzzer_entry.get('extra_section_debug') or []),
                    debug,
                ]


def has_custom_metric_sections(targets: list[dict[str, Any]]) -> bool:
    '''Return whether any target or fuzzer already has custom sections.'''

    return any(
        bool(target.get('extra_sections'))
        or any(bool(fuzzer.get('extra_sections')) for fuzzer in target.get('fuzzers') or [])
        for target in targets
    )


def _sections_for_fuzzer(
    fuzzer_entry: dict[str, Any],
    points_by_trial: dict[int, list[dict[str, Any]]],
) -> tuple[list[ExtraSection], dict[str, Any] | None]:
    trial_histories = []
    invalid_payloads = 0
    metric_points = 0
    raw_trial_histories = 0
    for trial in fuzzer_entry.get('trials') or []:
        trial_history = []
        for point in points_by_trial.get(int(trial.get('trial_id') or 0), []):
            for metric in _custom_metrics_from_point(point):
                if metric is None:
                    invalid_payloads += 1
                    continue
                if metric.get('id') != 'afl-mutator-counts':
                    continue
                counts = _counter_map(metric)
                if not counts:
                    continue
                elapsed_seconds = safe_int(point.get('elapsed_s')) or safe_int(point.get('idx')) or 0
                trial_history.append((int(elapsed_seconds), counts))
                metric_points += 1
        if trial_history:
            raw_trial_histories += 1
            trial_histories.append(trial_history)

    if not trial_histories:
        if invalid_payloads:
            return [], {
                'fuzzer': fuzzer_entry.get('fuzzer'),
                'status': 'invalid_custom_metrics',
                'invalid_payloads': invalid_payloads,
                'fuzzer_sections': 0,
            }
        return [], None

    series, debug = _mutator_series_from_histories(trial_histories)
    debug.update(
        {
            'fuzzer': fuzzer_entry.get('fuzzer'),
            'status': 'ok',
            'data_source': 'snapshot_stats_json',
            'metric_points': metric_points,
            'invalid_payloads': invalid_payloads,
            'raw_trial_histories': raw_trial_histories,
            'trial_histories': len(trial_histories),
            'fuzzer_sections': 1 if series else 0,
            'target_sections': 0,
        }
    )
    if not series:
        debug['reason'] = 'no_mutator_matches'
        return [], debug

    return [
        ExtraSection(
            id='afl-mutators',
            title='AFL mutators',
            scope='fuzzer',
            placement='after:target',
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
    ], debug


def _custom_metrics_from_point(point: dict[str, Any]) -> list[dict[str, Any] | None]:
    stats = point.get('stats')
    if not isinstance(stats, dict):
        return []
    if safe_int(stats.get('custom_metrics_schema_version')) != CUSTOM_METRICS_SCHEMA_VERSION:
        return []
    metrics = stats.get('custom_metrics')
    if not isinstance(metrics, list):
        return [None]
    return [metric if isinstance(metric, dict) else None for metric in metrics]


def _counter_map(metric: dict[str, Any]) -> dict[str, int]:
    if metric.get('kind') != 'counter_map':
        return {}
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
) -> tuple[list[ChartSeries], dict[str, Any]]:
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
    sorted_times = sorted(counts_by_time)
    series = []
    for index, mutator in enumerate(mutators):
        points = []
        for elapsed_seconds in sorted_times:
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
        'time_points': len(sorted_times),
        'mutator_count': len(mutators),
        'series_count': len(series),
        'top_mutators': mutators[:10],
        'aggregation': 'per_bucket_snapshot_counts',
    }
