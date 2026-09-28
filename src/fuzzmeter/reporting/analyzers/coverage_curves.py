# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build coverage curves and fuzzer entries from trial and snapshot data.'''

from __future__ import annotations

from typing import Any

from ..keys import FINAL_DIST_KEYS, SNAPSHOT_COVERAGE_FIELDS
from ..metrics import (
    dt,
    maximum,
    mean,
    median,
    minimum,
    pct,
    safe_int,
    trapezoid_auc,
)
from .trial_analysis import TrialReport


def empty_covered_counts(cov_metrics: tuple[str, ...]) -> dict[str, int | None]:
    '''Return empty covered-count fields for all coverage metrics.'''

    return {f'{metric}_covered': None for metric in cov_metrics}


def _build_aggregate_summary(
    *,
    finals: dict[str, list[float]],
    bugs: list[dict[str, Any]],
    aggregated_coverage: dict[str, int | None],
) -> dict[str, float | None]:
    '''Build aggregate metrics across all trials of one fuzzer-target entry.'''

    execs_done = sum(finals.get('execs_done') or []) or None
    elapsed_seconds = sum(finals.get('elapsed_seconds') or []) or None
    execs_per_sec = None
    if execs_done is not None and elapsed_seconds not in (None, 0):
        execs_per_sec = execs_done / elapsed_seconds
    aggregate = {
        'execs_done': execs_done,
        'elapsed_seconds': elapsed_seconds,
        'execs_per_sec': execs_per_sec,
        'corpus_files_total': sum(finals.get('corpus_files_total') or []) or None,
        'unique_bugs_total': float(len({str(bug.get('bug_key')) for bug in bugs if bug.get('bug_key')})) or None,
        'bug_hits_total': sum(finals.get('bug_hits_total') or []) or None,
    }
    aggregate.update(aggregated_coverage)
    return aggregate


def _add_mean_median(out: dict[str, float | None], key: str, values: list[float]) -> None:
    '''Add mean and median fields for a metric distribution.'''

    out[f'{key}_mean'] = mean(values)
    out[f'{key}_median'] = median(values)


def _build_final_summary(
    *,
    finals: dict[str, list[float]],
    trial_rows: list[dict[str, Any]],
    bugs: list[dict[str, Any]],
) -> dict[str, float | None]:
    '''Build final per-trial metric summaries for one fuzzer-target entry.'''

    final_summary: dict[str, float | None] = {}
    for key in FINAL_DIST_KEYS:
        _add_mean_median(final_summary, key, finals.get(key) or [])
    for key in (
        'regions_pct_auc',
        'regions_pct_auc_norm',
        'branches_cov_auc',
        'branches_cov_auc_norm',
        'branches_pct_auc',
        'branches_pct_auc_norm',
        'convergence_pct',
    ):
        values = [float(row[key]) for row in trial_rows if isinstance(row.get(key), (int, float))]
        _add_mean_median(final_summary, key, values)
    _add_mean_median(final_summary, 'elapsed_seconds', finals.get('elapsed_seconds') or [])
    bug_keys = {str(bug.get('bug_key')) for bug in bugs if bug.get('bug_key')}
    final_summary['accumulated_bug_count'] = float(len(bug_keys))
    return final_summary


def _convergence_pct(auc: float | None, max_coverage: float | None, duration_s: int | None) -> float | None:
    '''Return normalized coverage convergence percentage.'''

    if auc is None or max_coverage is None or duration_s is None:
        return None
    if max_coverage <= 0 or duration_s <= 0:
        return None
    return 100.0 * auc / (max_coverage * duration_s)


def downsample_curve(curve: list[dict[str, Any]], *, curve_max_points: int) -> list[dict[str, Any]]:
    '''Return a curve with at most the configured number of points.'''

    if len(curve) <= curve_max_points:
        return curve
    if curve_max_points < 3:
        return [curve[0], curve[-1]]
    selected = [curve[0]]
    interior = curve[1:-1]
    buckets = curve_max_points - 2
    for bucket_idx in range(buckets):
        start = int(bucket_idx * len(interior) / buckets)
        end = int((bucket_idx + 1) * len(interior) / buckets)
        if start >= len(interior):
            break
        chunk = interior[start:max(start + 1, end)]
        selected.append(chunk[len(chunk) // 2])
    selected.append(curve[-1])
    deduped: list[dict[str, Any]] = []
    seen_idx: set[int] = set()
    for point in selected:
        idx = safe_int(point.get('idx'))
        if idx is not None and idx in seen_idx:
            continue
        if idx is not None:
            seen_idx.add(idx)
        deduped.append(point)
    return deduped


def aggregate_finals(
    reps: list[TrialReport],
    points_by_trial: dict[int, list[dict[str, Any]]],
    *,
    cov_metrics: tuple[str, ...],
) -> dict[str, list[float]]:
    '''Collect final metric distributions for a fuzzer entry.'''

    finals: dict[str, list[float]] = {key: [] for key in FINAL_DIST_KEYS}
    for trial in reps:
        for metric in cov_metrics:
            cov_value = getattr(trial, f'{metric}_cov')
            total_value = getattr(trial, f'{metric}_total')
            pct_value = getattr(trial, f'{metric}_pct')
            if cov_value is not None:
                finals[f'{metric}_cov'].append(float(cov_value))
            if total_value is not None:
                finals[f'{metric}_total'].append(float(total_value))
            if pct_value is not None:
                finals[f'{metric}_pct'].append(float(pct_value))
        trial_points = points_by_trial.get(trial.trial_id, [])
        if not trial_points:
            continue
        # The last point can be telemetry of a tick without snapshot data; the trial holds the final measurement.
        for key in ('corpus_files_total', 'execs_done', 'unique_bugs_total', 'bug_hits_total'):
            value = getattr(trial, key)
            if value is not None:
                finals[key].append(float(value))
        last_point = trial_points[-1]
        for key in (
            'crashes_total',
            'resource_cpu_percent',
            'resource_memory_mib',
            'resource_memory_percent',
            'resource_corpus_disk_mib',
        ):
            value = last_point.get(key)
            if value is not None:
                finals[key].append(float(value))
        elapsed_seconds = trial.elapsed_seconds
        if elapsed_seconds is not None:
            finals.setdefault('elapsed_seconds', []).append(float(elapsed_seconds))
            if trial.execs_done is not None and elapsed_seconds > 0:
                finals['execs_per_sec'].append(trial.execs_done / elapsed_seconds)
    return finals


def build_curve(
    reps: list[TrialReport],
    points_by_trial: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    '''Build an aggregate fuzzer curve across repetitions.'''

    trial_series: list[tuple[int, dict[float, dict[str, Any]]]] = []
    all_elapsed: set[float] = set()
    for trial in reps:
        points = sorted(
            points_by_trial.get(trial.trial_id, []),
            key=lambda point: (
                float(point.get('elapsed_s'))
                if isinstance(point.get('elapsed_s'), (int, float))
                else float(point.get('ordinal') or point.get('idx') or 0)
            ),
        )
        point_map: dict[float, dict[str, Any]] = {}
        for point in points:
            elapsed_s = point.get('elapsed_s')
            if not isinstance(elapsed_s, (int, float)):
                continue
            elapsed_key = max(0.0, float(elapsed_s))
            point_map[elapsed_key] = point
            all_elapsed.add(elapsed_key)
        trial_series.append((trial.trial_id, point_map))

    last_seen_per_trial: dict[int, dict[str, Any]] = {}
    curve: list[dict[str, Any]] = []
    for idx, elapsed_key in enumerate(sorted(all_elapsed), start=1):
        curve_item: dict[str, Any] = {'idx': idx, 'elapsed_s': elapsed_key}
        ts_values: list[float] = []
        values: dict[str, list[float]] = {key: [] for key in FINAL_DIST_KEYS}

        for trial_id, point_map in trial_series:
            state = last_seen_per_trial.setdefault(trial_id, {})
            point = point_map.get(elapsed_key)
            if point is not None:
                ts = safe_int(point.get('ts'))
                if ts is not None:
                    ts_values.append(float(ts))
                for key in FINAL_DIST_KEYS:
                    value = point.get(key)
                    if value is not None:
                        state[key] = value
            if not state:
                continue
            for key in FINAL_DIST_KEYS:
                if key in state:
                    values[key].append(float(state[key]))

        if ts_values:
            ts_median = median(ts_values)
            curve_item['ts_median'] = ts_median
            if ts_median is not None:
                curve_item['t'] = dt(int(ts_median))

        for key, clean in values.items():
            if not clean:
                continue
            curve_item[f'{key}_mean'] = mean(clean)
            curve_item[f'{key}_median'] = median(clean)
            curve_item[f'{key}_min'] = minimum(clean)
            curve_item[f'{key}_max'] = maximum(clean)

        curve.append(curve_item)
    return curve


def _trial_auc(
    trial_points: list[dict[str, Any]],
    *,
    y_key: str,
    duration_s: int | None,
    start_value: float,
) -> tuple[float | None, float | None]:
    points: list[tuple[float, float]] = []
    for point in trial_points:
        x = point.get('elapsed_s')
        y = point.get(y_key)
        if x is None or y is None:
            continue
        points.append((float(x), float(y)))
    if points and all(x > 0 for x, _ in points):
        points.insert(0, (0.0, start_value))
    auc = trapezoid_auc(points, duration_s=float(duration_s) if duration_s is not None else None)
    if auc is None:
        return None, None
    if duration_s is None or duration_s <= 0:
        return auc, None
    return auc, auc / duration_s


def build_trial_rows(
    *,
    reps: list[TrialReport],
    points_by_trial: dict[int, list[dict[str, Any]]],
    seed_baseline: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    '''Build per-trial metric rows for a fuzzer entry.'''

    rows: list[dict[str, Any]] = []
    # Trials start from the measured seed corpus coverage, or from nothing without seeds.
    start_values: dict[str, float] = {}
    for metric in ('regions', 'branches'):
        covered_key, total_key = SNAPSHOT_COVERAGE_FIELDS[metric]
        covered = (seed_baseline or {}).get(covered_key)
        total = (seed_baseline or {}).get(total_key)
        start_values[f'{metric}_cov'] = float(covered or 0)
        start_values[f'{metric}_pct'] = pct(covered, total) or 0.0

    def sort_key(row: dict[str, Any]) -> tuple[str, int, int]:
        return (
            row.fuzzer,
            row.rep,
            row.trial_id,
        )

    for trial in sorted(reps, key=sort_key):
        trial_id = trial.trial_id
        points = sorted(points_by_trial.get(trial_id, []), key=lambda point: int(point.get('idx') or 0))
        last_point = points[-1] if points else {}
        elapsed_seconds = trial.elapsed_seconds
        execs_done = trial.execs_done
        execs_per_sec = None
        if execs_done is not None and elapsed_seconds is not None and elapsed_seconds > 0:
            execs_per_sec = execs_done / elapsed_seconds

        regions_cov_auc, regions_cov_auc_norm = _trial_auc(
            points,
            y_key='regions_cov',
            duration_s=elapsed_seconds,
            start_value=start_values['regions_cov'],
        )
        branches_cov_auc, branches_cov_auc_norm = _trial_auc(
            points,
            y_key='branches_cov',
            duration_s=elapsed_seconds,
            start_value=start_values['branches_cov'],
        )
        regions_pct_auc, regions_pct_auc_norm = _trial_auc(
            points,
            y_key='regions_pct',
            duration_s=elapsed_seconds,
            start_value=start_values['regions_pct'],
        )
        branches_pct_auc, branches_pct_auc_norm = _trial_auc(
            points,
            y_key='branches_pct',
            duration_s=elapsed_seconds,
            start_value=start_values['branches_pct'],
        )
        convergence_pct = _convergence_pct(
            branches_cov_auc,
            trial.branches_cov,
            elapsed_seconds,
        )

        rows.append(
            {
                'trial_id': trial_id,
                'fuzzer': trial.fuzzer,
                'benchmark': trial.benchmark,
                'fuzz_target': trial.fuzz_target,
                'rep': trial.rep,
                'started_ts': trial.started_ts,
                'ended_ts': trial.ended_ts,
                'time_seconds': trial.time_seconds,
                'status': trial.status,
                'elapsed_seconds': elapsed_seconds,
                'execs_done': execs_done,
                'execs_per_sec': execs_per_sec,
                'regions_cov': trial.regions_cov,
                'regions_pct': trial.regions_pct,
                'branches_cov': trial.branches_cov,
                'branches_pct': trial.branches_pct,
                'coverage_html': trial.coverage_html,
                'coverage_html_rel': trial.coverage_html_rel,
                'regions_cov_auc': regions_cov_auc,
                'regions_cov_auc_norm': regions_cov_auc_norm,
                'branches_cov_auc': branches_cov_auc,
                'branches_cov_auc_norm': branches_cov_auc_norm,
                'regions_pct_auc': regions_pct_auc,
                'regions_pct_auc_norm': regions_pct_auc_norm,
                'branches_pct_auc': branches_pct_auc,
                'branches_pct_auc_norm': branches_pct_auc_norm,
                'convergence_pct': convergence_pct,
                'corpus_files_total': trial.corpus_files_total,
                'unique_bugs_total': trial.unique_bugs_total,
                'bug_hits_total': trial.bug_hits_total,
                'crashes_total': safe_int(last_point.get('crashes_total')),
            }
        )
    return rows


def build_fuzzer_entry(
    *,
    cov_metrics: tuple[str, ...],
    curve_max_points: int,
    fuzzer: str,
    reps: list[TrialReport],
    bugs: list[dict[str, Any]],
    versions: dict[str, Any],
    points_by_trial: dict[int, list[dict[str, Any]]],
    aggregated_coverage: dict[str, int | None],
    seed_baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    '''Build one fuzzer entry inside a target report.'''

    finals = aggregate_finals(
        reps,
        points_by_trial,
        cov_metrics=cov_metrics,
    )
    curve = downsample_curve(
        build_curve(reps, points_by_trial),
        curve_max_points=curve_max_points,
    )
    trial_rows = build_trial_rows(reps=reps, points_by_trial=points_by_trial, seed_baseline=seed_baseline)
    final_summary = _build_final_summary(
        finals=finals,
        trial_rows=trial_rows,
        bugs=bugs,
    )
    aggregate_summary = _build_aggregate_summary(
        finals=finals,
        bugs=bugs,
        aggregated_coverage=dict(aggregated_coverage),
    )
    return {
        'fuzzer': fuzzer,
        'final': final_summary,
        'aggregate': aggregate_summary,
        'distribution': finals,
        'curve': curve,
        'trials': trial_rows,
        'seed_baseline': seed_baseline,
        'bugs': sorted(bugs, key=lambda bug: (-(int(bug.get('hits_total') or 0)), str(bug.get('bug_key') or ''))),
        'versions': versions,
        'extra_sections': [],
        'extra_section_debug': [],
    }


def collect_target_view(
    *,
    cov_metrics: tuple[str, ...],
    curve_max_points: int,
    trials: list[TrialReport],
    timeseries: dict[str, Any],
    bugs: list[dict[str, Any]],
    aggregated_coverage_by_fuzzer: dict[tuple[str, str, str], dict[str, int | None]],
    seed_baseline_by_fuzzer: dict[tuple[str, str, str], dict[str, Any] | None],
) -> list[dict[str, Any]]:
    '''Collect all target report entries from trials, time series, and bugs.'''

    points_by_trial = {
        int(entry['trial_id']): list(entry.get('points') or [])
        for entry in (timeseries.get('per_trial') or {}).values()
    }
    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    def merge_version_config(dst: dict[str, Any], key: str, value: Any) -> None:
        if value is None:
            return
        if not isinstance(value, dict):
            dst[key] = value
            return
        current = dst.get(key)
        if not isinstance(current, dict):
            dst[key] = dict(value)
            return
        merged = dict(current)
        merged.update(value)
        dst[key] = merged

    for trial in trials:
        target_group = grouped.setdefault(
            (trial.benchmark, trial.fuzz_target),
            {'benchmark': trial.benchmark, 'fuzz_target': trial.fuzz_target, 'fuzzers': {}},
        )
        fuzzer_group = target_group['fuzzers'].setdefault(
            trial.fuzzer,
            {'reps': [], 'bugs': [], 'versions': {}},
        )
        fuzzer_group['reps'].append(trial)
        if trial.fuzzer_image:
            fuzzer_group['versions']['fuzzer_image'] = trial.fuzzer_image
        merge_version_config(fuzzer_group['versions'], 'build_config', trial.build_config)
        merge_version_config(fuzzer_group['versions'], 'runtime_config', trial.runtime_config)

    for bug in bugs:
        key = (bug.get('benchmark'), bug.get('fuzz_target'))
        fuzzer = bug.get('fuzzer')
        if key not in grouped or not fuzzer:
            continue
        grouped[key]['fuzzers'].setdefault(
            fuzzer,
            {'reps': [], 'bugs': [], 'versions': {}},
        )['bugs'].append(bug)

    targets: list[dict[str, Any]] = []
    for (benchmark, fuzz_target), target_group in sorted(grouped.items()):
        target = {
            'benchmark': benchmark,
            'fuzz_target': fuzz_target,
            'key': f'{benchmark}:{fuzz_target}',
            'fuzzers': [],
            'extra_sections': [],
            'extra_section_debug': [],
        }
        for fuzzer, group in sorted(target_group['fuzzers'].items()):
            coverage_key = (str(fuzzer), str(benchmark), str(fuzz_target))
            target['fuzzers'].append(
                build_fuzzer_entry(
                    cov_metrics=cov_metrics,
                    curve_max_points=curve_max_points,
                    fuzzer=fuzzer,
                    reps=group['reps'],
                    bugs=group['bugs'],
                    versions=group['versions'],
                    points_by_trial=points_by_trial,
                    aggregated_coverage=aggregated_coverage_by_fuzzer.get(
                        coverage_key,
                        empty_covered_counts(cov_metrics),
                    ),
                    seed_baseline=seed_baseline_by_fuzzer.get(coverage_key),
                )
            )
        targets.append(target)
    return targets
