# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import json
import re

from collections import defaultdict
from pathlib import Path

from fuzzmeter.reporting.plugin_api import ChartSeries, ChartSpec, DataPoint, ExtraSection, ReportingContext


MUTATOR_MANIFEST = ".fuzzmeter_mutators.json"
MUTATOR_COLORS = [
    "#1F77B4",
    "#D62728",
    "#2CA02C",
    "#FF7F0E",
    "#9467BD",
    "#8C564B",
    "#E377C2",
    "#7F7F7F",
    "#BCBD22",
    "#17BECF",
    "#393B79",
    "#637939",
    "#8C6D31",
    "#843C39",
    "#7B4173",
]


def _snapshot_idx(snapshot_dir: Path) -> int | None:
    match = re.match(r"snap_(\d+)$", snapshot_dir.name)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _point_by_idx(timeseries_entry: dict) -> dict[int, dict]:
    points = timeseries_entry.get("points") or []
    return {
        int(point.get("idx")): point
        for point in points
        if point.get("idx") is not None
    }


def _elapsed_seconds_for_point(trial: dict, point: dict) -> int | None:
    started_ts = trial.get("started_ts")
    point_ts = point.get("ts")
    try:
        if started_ts is None or point_ts is None:
            elapsed_s = point.get("elapsed_s")
            if elapsed_s is None:
                return None
            elapsed = int(float(elapsed_s))
            return elapsed if elapsed >= 0 else None
        elapsed = int(point_ts) - int(started_ts)
        return elapsed if elapsed >= 0 else None
    except Exception:
        return None


def _manifest_counts(snapshot_dir: Path) -> dict[str, int]:
    manifest = snapshot_dir / MUTATOR_MANIFEST
    if not manifest.is_file():
        return {}
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return {}
    counts = payload.get("mutator_counts")
    if not isinstance(counts, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in counts.items():
        try:
            out[str(key)] = int(value)
        except Exception:
            continue
    return out


def _bucket_size(max_elapsed_seconds: int) -> int:
    if max_elapsed_seconds <= 0:
        return 300
    candidates = [
        60,
        300,
        600,
        900,
        1800,
        3600,
        7200,
        10800,
        21600,
        43200,
        86400,
    ]
    target_points = 32
    minimum = max(60, int(max_elapsed_seconds / target_points))
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


def _normalize_mutator_name(name: str) -> str:
    text = str(name).strip()
    if not text:
        return ""
    if text.startswith("orig:"):
        return ""
    return text


def _aggregate_trial_history(
    trial_history: list[tuple[int, dict[str, int]]],
    buckets: list[int],
    out: dict[int, dict[str, int]],
) -> None:
    if not trial_history:
        return
    history = sorted(trial_history, key=lambda entry: entry[0])
    cursor = 0
    current_counts: dict[str, int] | None = None
    for bucket in buckets:
        while cursor < len(history) and history[cursor][0] <= bucket:
            current_counts = history[cursor][1]
            cursor += 1
        if not current_counts:
            continue
        for mutator, count in current_counts.items():
            out[bucket][mutator] += int(count)


def _cumulative_positive_delta_history(
    trial_history: list[tuple[int, dict[str, int]]],
) -> list[tuple[int, dict[str, int]]]:
    if not trial_history:
        return []
    history = sorted(trial_history, key=lambda entry: entry[0])
    prev_counts: dict[str, int] = {}
    cumulative_counts: dict[str, int] = defaultdict(int)
    out: list[tuple[int, dict[str, int]]] = []
    for elapsed_seconds, current_counts in history:
        for mutator in set(prev_counts) | set(current_counts):
            delta = int(current_counts.get(mutator, 0)) - int(prev_counts.get(mutator, 0))
            if delta > 0:
                cumulative_counts[mutator] += delta
        if cumulative_counts:
            out.append((elapsed_seconds, dict(cumulative_counts)))
        prev_counts = current_counts
    return out


def _build_payload(ctx: ReportingContext) -> tuple[list[ChartSeries], dict[str, object]]:
    counts_by_time: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    trial_histories: list[list[tuple[int, dict[str, int]]]] = []
    raw_trial_histories = 0
    manifest_snapshot_count = 0
    scanned_snapshot_count = 0
    matched_file_count = 0
    snapshot_point_count = 0

    for trial in ctx.trials:
        trial_id = int(trial.get("trial_id") or 0)
        timeseries_entry = ctx.timeseries_by_trial.get(trial_id) or {"points": []}
        points_by_idx = _point_by_idx(timeseries_entry)
        trial_history: list[tuple[int, dict[str, int]]] = []

        for snapshot_dir in ctx.snapshot_dirs_by_trial.get(trial_id, []):
            # print("Processing snapshot dir:", snapshot_dir)
            idx = _snapshot_idx(snapshot_dir)
            if idx is None:
                continue

            point = points_by_idx.get(idx) or {}
            time_key = _elapsed_seconds_for_point(trial, point)
            if time_key is None:
                time_key = idx

            counts = _manifest_counts(snapshot_dir)
            if not counts:
                continue

            manifest_snapshot_count += 1
            scanned_snapshot_count += 1
            snapshot_point_count += 1
            matched_file_count += sum(counts.values())
            normalized_counts: dict[str, int] = {}
            for mutator, count in counts.items():
                normalized_name = _normalize_mutator_name(mutator)
                if not normalized_name:
                    continue
                normalized_counts[normalized_name] = int(count)
            if normalized_counts:
                trial_history.append((int(time_key), normalized_counts))

        if trial_history:
            raw_trial_histories += 1
            cumulative_history = _cumulative_positive_delta_history(trial_history)
            if cumulative_history:
                trial_histories.append(cumulative_history)

    if not trial_histories:
        return [], {
            "data_source": "manifest_or_snapshot_names",
            "manifest_snapshot_count": manifest_snapshot_count,
            "scanned_snapshot_count": scanned_snapshot_count,
            "matched_file_count": matched_file_count,
            "snapshot_points": 0,
            "time_points": 0,
            "mutator_count": 0,
            "series_count": 0,
            "reason": "no_mutator_matches",
        }

    max_elapsed_seconds = max(
        elapsed_seconds
        for history in trial_histories
        for elapsed_seconds, _ in history
    )
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
    series: list[ChartSeries] = []
    for index, mutator in enumerate(mutators):
        points: list[DataPoint] = []
        for elapsed_seconds in sorted_times:
            time_counts = counts_by_time[elapsed_seconds]
            total = sum(time_counts.values())
            if total <= 0:
                continue
            percent = 100.0 * time_counts.get(mutator, 0) / total
            points.append(
                DataPoint(
                    x=elapsed_seconds,
                    y=percent,
                    meta={"elapsed_seconds": elapsed_seconds, "mutator": mutator},
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
        "data_source": "manifest_or_snapshot_names",
        "manifest_snapshot_count": manifest_snapshot_count,
        "scanned_snapshot_count": scanned_snapshot_count,
        "matched_file_count": matched_file_count,
        "snapshot_points": snapshot_point_count,
        "time_points": len(sorted_times),
        "bucket_size_seconds": bucket_size,
        "mutator_count": len(mutators),
        "series_count": len(series),
        "top_mutators": mutators[:10],
        "trial_histories": len(trial_histories),
        "raw_trial_histories": raw_trial_histories,
        "aggregation": "cumulative_positive_deltas",
    }


class AFLReportingPlugin:
    '''Build AFL-specific extra report sections.'''

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str, tuple[int, ...]], tuple[list[ChartSeries], dict[str, object]]] = {}

    @staticmethod
    def _cache_key(ctx: ReportingContext) -> tuple[str, str, str, tuple[int, ...]]:
        trial_ids = tuple(sorted(int(trial.get("trial_id") or 0) for trial in ctx.trials))
        return (ctx.run_id, ctx.benchmark, ctx.fuzz_target, trial_ids)

    def _resolve(self, ctx: ReportingContext) -> tuple[list[ChartSeries], dict[str, object]]:
        key = self._cache_key(ctx)
        if key not in self._cache:
            self._cache[key] = _build_payload(ctx)
        return self._cache[key]

    def build_extra_sections(self, ctx: ReportingContext) -> list[ExtraSection]:
        '''Return AFL mutator statistics if snapshot manifests are available.'''

        series, _ = self._resolve(ctx)
        if not series:
            return []

        chart = ChartSpec(
            id="mutator-usefulness-ratio",
            type="stacked_area",
            title="Mutator usefulness ratio",
            subtitle="Percentage distribution of AFL custom mutators across snapshot corpora.",
            x_axis="elapsed seconds",
            y_axis="percent",
            filter_mode="static",
            series=series,
        )
        return [
            ExtraSection(
                id="afl-mutators",
                title="AFL mutators",
                scope="fuzzer",
                placement="after:target",
                charts=[chart],
            )
        ]

    def build_debug_info(self, ctx: ReportingContext) -> dict[str, object]:
        '''Return debug counters for the AFL reporting plugin.'''

        _, debug = self._resolve(ctx)
        return debug


def get_reporting_plugin() -> AFLReportingPlugin:
    '''Return the AFL reporting plugin instance.'''

    return AFLReportingPlugin()
