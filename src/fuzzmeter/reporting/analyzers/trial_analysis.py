# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build per-trial and per-snapshot report structures from database rows.'''

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from ...db.resource_telemetry import TelemetrySample
from ...db.snapshot import CoverageSummary, SnapshotRow
from ...db.trials import TrialRow
from ..keys import SNAPSHOT_COVERAGE_FIELDS
from ..metrics import dt, pct, safe_int


@dataclass(frozen=True)
class TrialReport:
    """Describe one trial of a run as the report reads it."""

    trial_id: int
    fuzzer: str
    benchmark: str
    fuzz_target: str
    rep: int
    time_seconds: int
    status: str
    fuzzer_image: str
    build_config: dict[str, Any] | None
    runtime_config: dict[str, Any] | None
    started_ts: int
    ended_ts: int | None
    elapsed_seconds: int | None
    bug_hits_total: int
    unique_bugs_total: int
    corpus_files_total: int | None
    execs_done: int | None
    crashes: int | None
    hangs: int | None
    coverage_html: str | None
    coverage_html_rel: str | None
    coverage_sets_json_rel: str | None
    branches_cov: int | None
    branches_total: int | None
    branches_pct: float | None
    lines_cov: int | None
    lines_total: int | None
    lines_pct: float | None
    functions_cov: int | None
    functions_total: int | None
    functions_pct: float | None
    regions_cov: int | None
    regions_total: int | None
    regions_pct: float | None


def snapshot_has_coverage(row: SnapshotRow) -> bool:
    '''Return whether a snapshot row contains coverage counters.'''

    return any(
        getattr(row.coverage, covered_key) is not None
        for covered_key, _ in SNAPSHOT_COVERAGE_FIELDS.values()
    )


def coverage_summary_from_snapshot(latest: SnapshotRow | None) -> dict[str, Any]:
    '''Build a coverage summary from the snapshot that represents a trial, if it has one.'''

    measured = CoverageSummary() if latest is None else latest.coverage
    coverage: dict[str, Any] = {}
    for metric, (covered_key, total_key) in SNAPSHOT_COVERAGE_FIELDS.items():
        covered = getattr(measured, covered_key)
        total = getattr(measured, total_key)
        coverage[f'{metric}_covered'] = covered
        coverage[f'{metric}_total'] = total
        coverage[f'{metric}_pct'] = pct(covered, total)
    coverage['last_snapshot_ts'] = None if latest is None else latest.ts
    coverage['last_snapshot_at'] = dt(coverage['last_snapshot_ts'])
    coverage['corpus_files_total'] = None if latest is None else latest.corpus_files
    coverage['execs_done'] = None if latest is None else latest.execs_done
    coverage['crashes'] = None if latest is None else latest.crashes
    coverage['hangs'] = None if latest is None else latest.hangs
    return coverage


def _elapsed_seconds(row: TrialRow, coverage: dict[str, Any]) -> int | None:
    started_ts = row.started_ts
    ended_ts = safe_int(coverage.get('last_snapshot_ts')) or row.ended_ts or started_ts
    if ended_ts < started_ts:
        return None
    elapsed_seconds = int(ended_ts - started_ts)
    if row.time_seconds > 0:
        elapsed_seconds = min(elapsed_seconds, row.time_seconds)
    return elapsed_seconds


def collect_trials(
    *,
    trial_rows: list[TrialRow],
    latest_snapshots: dict[int, SnapshotRow],
    bug_stats_by_trial: dict[int, tuple[int, int]],
    rel_to_url: Callable[[str | None], str | None],
) -> list[TrialReport]:
    '''Collect the report view of every trial from its database rows and latest snapshot.'''

    trials: list[TrialReport] = []
    for row in trial_rows:
        latest = latest_snapshots.get(row.trial_id)
        coverage_html_rel = (
            latest.coverage.coverage_html_dir
            if latest is not None and snapshot_has_coverage(latest)
            else None
        )
        coverage = coverage_summary_from_snapshot(latest)
        bug_hits_total, unique_bugs_total = bug_stats_by_trial.get(row.trial_id, (0, 0))
        trials.append(TrialReport(
            trial_id=row.trial_id,
            fuzzer=row.fuzzer,
            benchmark=row.benchmark,
            fuzz_target=row.fuzz_target,
            rep=row.rep,
            time_seconds=row.time_seconds,
            status=row.status,
            fuzzer_image=row.fuzzer_image,
            build_config=row.build_config,
            runtime_config=row.runtime_config,
            started_ts=row.started_ts,
            ended_ts=row.ended_ts,
            elapsed_seconds=_elapsed_seconds(row, coverage),
            bug_hits_total=int(bug_hits_total),
            unique_bugs_total=int(unique_bugs_total),
            corpus_files_total=coverage['corpus_files_total'],
            execs_done=coverage['execs_done'],
            crashes=coverage['crashes'],
            hangs=coverage['hangs'],
            coverage_html=rel_to_url(coverage_html_rel),
            coverage_html_rel=coverage_html_rel,
            coverage_sets_json_rel=None if latest is None else latest.coverage_sets_json_rel,
            **{
                f'{metric}_{report_suffix}': coverage[f'{metric}_{coverage_suffix}']
                for metric in SNAPSHOT_COVERAGE_FIELDS
                for report_suffix, coverage_suffix in (('cov', 'covered'), ('total', 'total'), ('pct', 'pct'))
            },
        ))
    return trials


def collect_timeseries(
    *,
    trials: list[TrialReport],
    snapshot_rows: list[SnapshotRow],
    resource_telemetry_rows: list[TelemetrySample],
    bug_hits_by_snapshot: dict[int, int],
    unique_bug_delta_by_snapshot: dict[int, int],
) -> dict[str, Any]:
    '''Collect per-trial time-series points from snapshot rows.'''

    started_ts_by_trial = {trial.trial_id: trial.started_ts for trial in trials}
    time_seconds_by_trial = {trial.trial_id: trial.time_seconds for trial in trials}
    per_trial: Dict[str, Dict[str, Any]] = {
        str(trial.trial_id): {
            'trial_id': trial.trial_id,
            'fuzzer': trial.fuzzer,
            'benchmark': trial.benchmark,
            'fuzz_target': trial.fuzz_target,
            'points': [],
        }
        for trial in trials
    }
    point_by_trial_idx: Dict[str, Dict[int, Dict[str, Any]]] = {trial_key: {} for trial_key in per_trial}

    def ensure_point(trial_key: str, idx: int, ts: int) -> Dict[str, Any] | None:
        entry = per_trial.get(trial_key)
        if not entry:
            return None
        point_map = point_by_trial_idx.setdefault(trial_key, {})
        point = point_map.get(idx)
        if point is None:
            point = {'idx': idx}
            point_map[idx] = point
            entry['points'].append(point)
        point.setdefault('ts', ts)
        point.setdefault('t', dt(ts))
        return point

    for row in snapshot_rows:
        point = ensure_point(str(row.trial_id), row.idx, row.ts)
        if point is None:
            continue
        point.update(
            {
                'corpus_files_total': row.corpus_files,
                'execs_done': row.execs_done,
                'crashes': row.crashes,
                'hangs': row.hangs,
                'bug_hits': int(bug_hits_by_snapshot.get(row.snapshot_id, 0)),
                'unique_bugs_delta': int(unique_bug_delta_by_snapshot.get(row.snapshot_id, 0)),
            }
        )
        if row.stats:
            point['stats'] = row.stats
            execs_per_sec = _safe_float(row.stats.get('execs_per_sec'))
            if execs_per_sec is not None:
                point['execs_per_sec'] = execs_per_sec
        for metric, (covered_key, total_key) in SNAPSHOT_COVERAGE_FIELDS.items():
            point[f'{metric}_cov'] = getattr(row.coverage, covered_key)
            point[f'{metric}_total'] = getattr(row.coverage, total_key)

    for sample in resource_telemetry_rows:
        point = ensure_point(str(sample.trial_id), sample.idx, sample.ts)
        if point is None:
            continue
        memory_bytes = sample.memory_usage_bytes
        disk_bytes = sample.corpus_disk_usage_bytes
        point['resource_cpu_percent'] = sample.cpu_percent
        point['resource_memory_percent'] = sample.memory_percent
        point['resource_memory_mib'] = (memory_bytes / (1024 * 1024)) if memory_bytes is not None else None
        point['resource_corpus_disk_mib'] = (disk_bytes / (1024 * 1024)) if disk_bytes is not None else None

    for entry in per_trial.values():
        points = sorted(entry['points'], key=lambda point: int(point.get('idx') or 0))
        trial_started_ts = started_ts_by_trial.get(int(entry['trial_id']))
        first_ts = None
        for point in points:
            ts = safe_int(point.get('ts'))
            if ts is not None:
                first_ts = ts
                break
        total_bug_hits = 0
        total_unique_bugs = 0
        total_crashes = 0
        for ordinal, point in enumerate(points, start=1):
            point['ordinal'] = ordinal
            ts = safe_int(point.get('ts'))
            base_ts = trial_started_ts if trial_started_ts is not None else first_ts
            if ts is not None and base_ts is not None and ts >= base_ts:
                elapsed_s = ts - base_ts
                time_seconds = time_seconds_by_trial.get(int(entry['trial_id']))
                if time_seconds is not None and time_seconds > 0:
                    elapsed_s = min(elapsed_s, time_seconds)
                point['elapsed_s'] = float(elapsed_s)
            total_bug_hits += safe_int(point.get('bug_hits')) or 0
            total_unique_bugs += safe_int(point.get('unique_bugs_delta')) or 0
            total_crashes += safe_int(point.get('crashes')) or 0
            point['bug_hits_total'] = int(total_bug_hits)
            point['unique_bugs_total'] = int(total_unique_bugs)
            point['crashes_total'] = int(total_crashes)
            for metric in SNAPSHOT_COVERAGE_FIELDS:
                point[f'{metric}_pct'] = pct(point.get(f'{metric}_cov'), point.get(f'{metric}_total'))
        entry['points'] = points
    return {'per_trial': per_trial}


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
