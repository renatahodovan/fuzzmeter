# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build per-trial and per-snapshot report structures from database rows.'''

from __future__ import annotations

import json

from typing import Any, Callable, Dict, Optional

from ..metrics import dt, pct, safe_int


def _parse_json_text(value: Any) -> dict | None:
    if not value:
        return None
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


class TrialAnalysis:
    '''Build trial and snapshot time-series report data.'''

    def __init__(
        self,
        *,
        snapshot_coverage_fields: dict[str, tuple[str, str]],
        trial_version_fields: tuple[str, ...],
    ) -> None:
        self._snapshot_coverage_fields = snapshot_coverage_fields
        self._trial_version_fields = trial_version_fields

    def snapshot_has_coverage(self, row: dict[str, Any]) -> bool:
        '''Return whether a snapshot row contains coverage counters.'''

        return any(
            safe_int(row.get(covered_key)) is not None
            for covered_key, _ in self._snapshot_coverage_fields.values()
        )

    def latest_effective_snapshot_for_trial(
        self,
        trial_id: int,
        snapshot_rows: list[dict[str, Any]],
        latest_snapshots: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        '''Return the latest snapshot row that should represent a trial.'''

        rows = [row for row in snapshot_rows if int(row.get('trial_id') or 0) == int(trial_id)]
        if not rows:
            return latest_snapshots.get(int(trial_id), {})
        rows = sorted(rows, key=lambda row: int(row.get('idx') or 0))
        return rows[-1]

    def coverage_summary_from_snapshot(self, latest: dict[str, Any]) -> dict[str, Any]:
        '''Build a coverage summary from a snapshot row.'''

        coverage: dict[str, Any] = {}
        for metric, (covered_key, total_key) in self._snapshot_coverage_fields.items():
            covered = safe_int(latest.get(covered_key))
            total = safe_int(latest.get(total_key))
            coverage[f'{metric}_covered'] = covered
            coverage[f'{metric}_total'] = total
            coverage[f'{metric}_pct'] = pct(covered, total)
        coverage['last_snapshot_idx'] = safe_int(latest.get('idx'))
        coverage['last_snapshot_ts'] = safe_int(latest.get('ts'))
        coverage['last_snapshot_at'] = dt(coverage['last_snapshot_ts'])
        coverage['corpus_files_delta'] = safe_int(latest.get('corpus_files'))
        coverage['corpus_files_total'] = safe_int(latest.get('corpus_files'))
        coverage['execs_done'] = safe_int(latest.get('execs_done'))
        coverage['crashes'] = safe_int(latest.get('crashes'))
        coverage['hangs'] = safe_int(latest.get('hangs'))
        return coverage

    def _elapsed_seconds(self, row: dict[str, Any], coverage: dict[str, Any]) -> int | None:
        started_ts = safe_int(row.get('started_ts'))
        ended_ts = (
            safe_int(coverage.get('last_snapshot_ts'))
            or safe_int(row.get('ended_ts'))
            or started_ts
        )
        if started_ts is None or ended_ts is None or ended_ts < started_ts:
            return None
        elapsed_seconds = int(ended_ts - started_ts)
        time_seconds = safe_int(row.get('time_seconds'))
        if time_seconds is not None and time_seconds > 0:
            elapsed_seconds = min(elapsed_seconds, int(time_seconds))
        return elapsed_seconds

    def collect_trials(
        self,
        *,
        trial_rows: list[dict[str, Any]],
        latest_snapshots: dict[int, dict[str, Any]],
        snapshot_rows: list[dict[str, Any]],
        bug_stats_by_trial: dict[int, tuple[int, int]],
        rel_to_url: Callable[[str | None], str | None],
    ) -> list[dict[str, Any]]:
        '''Collect report trial rows from database rows and snapshot summaries.'''

        trials: list[dict[str, Any]] = []
        for row in trial_rows:
            trial_id = int(row['trial_id'])
            latest = self.latest_effective_snapshot_for_trial(trial_id, snapshot_rows, latest_snapshots)
            coverage_html_rel = None
            if self.snapshot_has_coverage(latest):
                coverage_html_rel = latest.get('coverage_html_dir')
            coverage = self.coverage_summary_from_snapshot(latest)
            coverage['coverage_html'] = rel_to_url(coverage_html_rel)
            coverage['coverage_html_rel'] = coverage_html_rel
            coverage['coverage_sets_json_rel'] = latest.get('coverage_sets_json_rel')
            started_ts = safe_int(row.get('started_ts'))
            ended_ts = safe_int(row.get('ended_ts'))
            time_seconds = safe_int(row.get('time_seconds'))
            bug_hits_total, unique_bugs_total = bug_stats_by_trial.get(trial_id, (0, 0))
            trial = {
                'trial_id': trial_id,
                'fuzzer': row.get('fuzzer'),
                'benchmark': row.get('benchmark'),
                'fuzz_target': row.get('fuzz_target'),
                'rep': safe_int(row.get('rep')),
                'time_seconds': time_seconds,
                'jobs': safe_int(row.get('jobs')),
                'status': row.get('status'),
                'started_ts': started_ts,
                'ended_ts': ended_ts,
                'started_at': dt(started_ts),
                'ended_at': dt(ended_ts),
                'elapsed_seconds': self._elapsed_seconds(row, coverage),
                'bug_hits_total': int(bug_hits_total),
                'unique_bugs_total': int(unique_bugs_total),
                **{
                    f'{metric}_cov': coverage.get(f'{metric}_covered')
                    for metric in self._snapshot_coverage_fields
                },
                **{
                    f'{metric}_{suffix}': coverage.get(f'{metric}_{suffix}')
                    for metric in self._snapshot_coverage_fields
                    for suffix in ('total', 'pct')
                },
                **{
                    key: coverage.get(key)
                    for key in (
                        'last_snapshot_idx',
                        'last_snapshot_ts',
                        'last_snapshot_at',
                        'corpus_files_delta',
                        'corpus_files_total',
                        'execs_done',
                        'crashes',
                        'hangs',
                        'coverage_html',
                        'coverage_html_rel',
                    )
                },
            }
            if coverage.get('coverage_sets_json_rel'):
                trial['coverage_sets_json_rel'] = coverage['coverage_sets_json_rel']
            for key in self._trial_version_fields:
                trial[key] = row.get(key)
            trial['build_config'] = _parse_json_text(row.get('build_config_json'))
            trial['runtime_config'] = _parse_json_text(row.get('runtime_config_json'))
            trials.append(trial)
        return trials

    def collect_timeseries(
        self,
        *,
        trials: list[dict[str, Any]],
        snapshot_rows: list[dict[str, Any]],
        resource_telemetry_rows: list[dict[str, Any]],
        bug_hits_by_snapshot: dict[int, int],
        unique_bug_delta_by_snapshot: dict[int, int],
    ) -> dict[str, Any]:
        '''Collect per-trial time-series points from snapshot rows.'''

        started_ts_by_trial = {
            int(trial['trial_id']): safe_int(trial.get('started_ts'))
            for trial in trials
            if trial.get('trial_id') is not None
        }
        time_seconds_by_trial = {
            int(trial['trial_id']): safe_int(trial.get('time_seconds'))
            for trial in trials
            if trial.get('trial_id') is not None
        }
        per_trial: Dict[str, Dict[str, Any]] = {
            str(int(trial['trial_id'])): {
                'trial_id': int(trial['trial_id']),
                'fuzzer': trial.get('fuzzer'),
                'benchmark': trial.get('benchmark'),
                'fuzz_target': trial.get('fuzz_target'),
                'points': [],
            }
            for trial in trials
        }
        point_by_trial_idx: Dict[str, Dict[int, Dict[str, Any]]] = {trial_key: {} for trial_key in per_trial}

        def ensure_point(trial_key: str, idx: Optional[int], ts: Optional[int] = None) -> Dict[str, Any] | None:
            if idx is None:
                return None
            entry = per_trial.get(trial_key)
            if not entry:
                return None
            point_map = point_by_trial_idx.setdefault(trial_key, {})
            point = point_map.get(idx)
            if point is None:
                point = {'idx': idx}
                point_map[idx] = point
                entry['points'].append(point)
            if ts is not None:
                point.setdefault('ts', ts)
                point.setdefault('t', dt(ts))
            return point

        for row in snapshot_rows:
            trial_key = str(int(row['trial_id']))
            idx = safe_int(row.get('idx'))
            point = ensure_point(trial_key, idx, safe_int(row.get('ts')))
            if point is None:
                continue
            snapshot_id = int(row['snapshot_id'])
            point.update(
                {
                    'corpus_files_delta': safe_int(row.get('corpus_files')),
                    'corpus_files_total': safe_int(row.get('corpus_files')),
                    'execs_done': safe_int(row.get('execs_done')),
                    'crashes': safe_int(row.get('crashes')),
                    'hangs': safe_int(row.get('hangs')),
                    'bug_hits': int(bug_hits_by_snapshot.get(snapshot_id, 0)),
                    'unique_bugs_delta': int(unique_bug_delta_by_snapshot.get(snapshot_id, 0)),
                }
            )
            stats = _parse_json_text(row.get('stats_json'))
            if stats:
                point['stats'] = stats
                execs_per_sec = self._safe_float(stats.get('execs_per_sec'))
                if execs_per_sec is not None:
                    point['execs_per_sec'] = execs_per_sec
            for metric, (covered_key, total_key) in self._snapshot_coverage_fields.items():
                point[f'{metric}_cov'] = safe_int(row.get(covered_key))
                point[f'{metric}_total'] = safe_int(row.get(total_key))

        for row in resource_telemetry_rows:
            trial_key = str(int(row['trial_id']))
            idx = safe_int(row.get('idx'))
            point = ensure_point(trial_key, idx, safe_int(row.get('ts')))
            if point is None:
                continue
            memory_bytes = safe_int(row.get('memory_usage_bytes'))
            disk_bytes = safe_int(row.get('corpus_disk_usage_bytes'))
            point['resource_cpu_percent'] = row.get('cpu_percent')
            point['resource_memory_percent'] = row.get('memory_percent')
            point['resource_memory_bytes'] = memory_bytes
            point['resource_memory_mib'] = (memory_bytes / (1024 * 1024)) if memory_bytes is not None else None
            point['resource_memory_limit_bytes'] = safe_int(row.get('memory_limit_bytes'))
            point['resource_corpus_disk_bytes'] = disk_bytes
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
                for metric in self._snapshot_coverage_fields:
                    point[f'{metric}_pct'] = pct(point.get(f'{metric}_cov'), point.get(f'{metric}_total'))
            entry['points'] = points
        return {'per_trial': per_trial}

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
