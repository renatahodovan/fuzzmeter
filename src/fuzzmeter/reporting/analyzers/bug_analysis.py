# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build bug-centric report sections and derived comparison data.'''

from __future__ import annotations

import json
from typing import Any

from ..metrics import dt, median, safe_int
from ..set_comparison import exclusive_total, novelty_scores, relative_containment_matrix


class BugAnalysis:
    '''Build bug summary and uniqueness report data.'''

    def collect_bugs(
        self,
        *,
        bugs: list[dict[str, Any]],
        bug_hits_by_bug: dict[int, int],
        bug_trials_by_bug: dict[int, list[int]],
    ) -> list[dict[str, Any]]:
        '''Collect normalized bug rows with total hit counts.'''

        out = [dict(row) for row in bugs]
        for bug in out:
            bug['first_seen_at'] = dt(safe_int(bug.get('first_seen_ts')))
            bug['hits_total'] = int(bug_hits_by_bug.get(int(bug['bug_id']), 0))
            bug['trial_ids'] = sorted({int(trial_id) for trial_id in bug_trials_by_bug.get(int(bug['bug_id']), [])})
            bug['frames'] = self._parse_frames(bug.get('frames_json'))
            bug['output'] = self._normalize_text(bug.get('output'))
        return out

    @staticmethod
    def _normalize_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        return text or None

    @staticmethod
    def _parse_frames(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(frame) for frame in value if str(frame).strip()]
        if not value:
            return []
        try:
            parsed = json.loads(str(value))
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        return [str(frame) for frame in parsed if str(frame).strip()]

    @staticmethod
    def attach_exclusive_bug_stats(target: dict[str, Any]) -> dict[str, Any]:
        '''Attach per-fuzzer exclusive bug totals and trial distributions to a target.'''

        entries = target.get('fuzzers') or []
        bug_sets_by_fuzzer: dict[str, set[str]] = {}
        trial_bug_sets_by_fuzzer: dict[str, dict[int, set[str]]] = {}

        for entry in entries:
            fuzzer = str(entry.get('fuzzer') or '')
            if not fuzzer:
                continue
            bug_sets_by_fuzzer[fuzzer] = set()
            trial_bug_sets_by_fuzzer[fuzzer] = {}
            for bug in entry.get('bugs') or []:
                bug_key = str(bug.get('bug_key') or '')
                if not bug_key:
                    continue
                bug_sets_by_fuzzer[fuzzer].add(bug_key)
                for trial_id in bug.get('trial_ids') or []:
                    if not isinstance(trial_id, int):
                        continue
                    trial_bug_sets_by_fuzzer[fuzzer].setdefault(trial_id, set()).add(bug_key)

        for entry in entries:
            fuzzer = str(entry.get('fuzzer') or '')
            other_bug_union = set().union(
                *(bug_sets for other_fuzzer, bug_sets in bug_sets_by_fuzzer.items() if other_fuzzer != fuzzer)
            )
            trial_counts: list[int] = []
            for trial in entry.get('trials') or []:
                trial_id = trial.get('trial_id')
                if not isinstance(trial_id, int):
                    continue
                own_trial_bugs = trial_bug_sets_by_fuzzer.get(fuzzer, {}).get(trial_id, set())
                trial_counts.append(len(own_trial_bugs - other_bug_union))
            entry['exclusive_bugs'] = {
                'total': exclusive_total(fuzzer, bug_sets_by_fuzzer),
                'min': min(trial_counts) if trial_counts else None,
                'max': max(trial_counts) if trial_counts else None,
                'median': median(trial_counts),
            }
        return target

    @staticmethod
    def compute_unique_bug_matrix(target: dict[str, Any]) -> dict[str, Any]:
        '''Compute pairwise unique bug counts between fuzzers.'''

        fuzzers = sorted({entry.get('fuzzer') for entry in (target.get('fuzzers') or []) if entry.get('fuzzer')})
        bug_sets: dict[str, set[str]] = {fuzzer: set() for fuzzer in fuzzers}
        for entry in target.get('fuzzers') or []:
            fuzzer = entry.get('fuzzer')
            if not fuzzer:
                continue
            for bug in entry.get('bugs') or []:
                bug_key = bug.get('bug_key')
                if bug_key:
                    bug_sets[fuzzer].add(str(bug_key))
        matrix: list[list[int]] = []
        max_value = 0
        for row_fuzzer in fuzzers:
            row_set = bug_sets.get(row_fuzzer, set())
            row_vals = [len(row_set - bug_sets.get(col_fuzzer, set())) for col_fuzzer in fuzzers]
            if row_vals:
                max_value = max(max_value, max(row_vals))
            matrix.append(row_vals)
        return {
            'fuzzers': fuzzers,
            'matrix': matrix,
            'has_data': any(bool(values) for values in bug_sets.values()),
            'note': None,
            'max_value': max_value,
        }

    @staticmethod
    def compute_unique_bug_table(target: dict[str, Any]) -> dict[str, Any]:
        '''Compute bug-by-fuzzer first-discovery table data.'''

        fuzzers = [str(entry.get('fuzzer')) for entry in (target.get('fuzzers') or []) if entry.get('fuzzer')]
        trials = [
            trial
            for entry in (target.get('fuzzers') or [])
            for trial in (entry.get('trials') or [])
            if isinstance(trial, dict)
        ]
        started_candidates = [
            int(trial.get('started_ts'))
            for trial in trials
            if isinstance(trial.get('started_ts'), int)
        ]
        planned_duration_candidates = [
            int(trial.get('time_seconds'))
            for trial in trials
            if isinstance(trial.get('time_seconds'), int) and int(trial.get('time_seconds')) > 0
        ]
        target_started_ts = min(started_candidates) if started_candidates else None
        planned_duration_seconds = max(planned_duration_candidates) if planned_duration_candidates else None

        bugs_by_key: dict[str, dict[str, Any]] = {}
        for entry in target.get('fuzzers') or []:
            fuzzer = str(entry.get('fuzzer') or '')
            if not fuzzer:
                continue
            for bug in entry.get('bugs') or []:
                bug_key = str(bug.get('bug_key') or '')
                if not bug_key:
                    continue
                first_seen_ts = bug.get('first_seen_ts')
                if not isinstance(first_seen_ts, int):
                    continue
                row = bugs_by_key.setdefault(
                    bug_key,
                    {
                        'bug_key': bug_key,
                        'issue_type': bug.get('issue_type'),
                        'top_func': bug.get('top_func'),
                        'frames': list(bug.get('frames') or []),
                        'output': bug.get('output'),
                        'global_first_seen_ts': first_seen_ts,
                        'global_first_seen_at': bug.get('first_seen_at'),
                        'found_by_fuzzer': {},
                        'hits_by_fuzzer': {},
                    },
                )
                if first_seen_ts < int(row['global_first_seen_ts']):
                    row['global_first_seen_ts'] = first_seen_ts
                    row['global_first_seen_at'] = bug.get('first_seen_at')
                    row['issue_type'] = bug.get('issue_type')
                    row['top_func'] = bug.get('top_func')
                    row['frames'] = list(bug.get('frames') or [])
                    row['output'] = bug.get('output')
                current_fuzzer_ts = row['found_by_fuzzer'].get(fuzzer)
                if current_fuzzer_ts is None or first_seen_ts < current_fuzzer_ts:
                    row['found_by_fuzzer'][fuzzer] = first_seen_ts
                row['hits_by_fuzzer'][fuzzer] = int(bug.get('hits_total') or 0)

        if target_started_ts is None:
            first_seen_candidates = [row['global_first_seen_ts'] for row in bugs_by_key.values()]
            target_started_ts = min(first_seen_candidates) if first_seen_candidates else None
        last_snapshot_elapsed_seconds = max(
            [
                int(trial.get('elapsed_seconds'))
                for entry in target.get('fuzzers') or []
                for trial in entry.get('trials') or []
                if isinstance(trial.get('elapsed_seconds'), (int, float))
            ],
            default=0,
        )

        rows: list[dict[str, Any]] = []
        max_elapsed_seconds = 0
        ordered_bugs = sorted(
            bugs_by_key.values(),
            key=lambda row: (int(row['global_first_seen_ts']), str(row['bug_key'])),
        )
        for index, bug in enumerate(ordered_bugs, start=1):
            cells: list[int | None] = []
            hit_counts: list[int] = []
            for fuzzer in fuzzers:
                first_seen_ts = bug['found_by_fuzzer'].get(fuzzer)
                elapsed_seconds = None
                if target_started_ts is not None and first_seen_ts is not None:
                    elapsed_seconds = max(0, int(first_seen_ts) - int(target_started_ts))
                    max_elapsed_seconds = max(max_elapsed_seconds, elapsed_seconds)
                cells.append(elapsed_seconds)
                hit_counts.append(int(bug.get('hits_by_fuzzer', {}).get(fuzzer, 0)))
            rows.append(
                {
                    'index': index,
                    'bug_key': bug['bug_key'],
                    'issue_type': bug.get('issue_type'),
                    'top_func': bug.get('top_func'),
                    'frames': list(bug.get('frames') or []),
                    'output': bug.get('output'),
                    'global_first_seen_ts': int(bug['global_first_seen_ts']),
                    'global_first_seen_at': bug.get('global_first_seen_at'),
                    'cells': cells,
                    'hit_counts': hit_counts,
                }
            )

        return {
            'target_key': target.get('key'),
            'fuzzers': fuzzers,
            'rows': rows,
            'has_data': bool(rows),
            'last_snapshot_elapsed_seconds': last_snapshot_elapsed_seconds or max_elapsed_seconds,
            'planned_duration_seconds': planned_duration_seconds,
            'started_ts': target_started_ts,
            'max_elapsed_seconds': max_elapsed_seconds,
        }

    @staticmethod
    def compute_rel_bug_matrix(target: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float]]:
        '''Compute pairwise relative bug containment and novelty-weighted bug scores.'''

        fuzzers = sorted({entry.get('fuzzer') for entry in (target.get('fuzzers') or []) if entry.get('fuzzer')})
        trial_bug_sets_by_fuzzer: dict[str, dict[int, set[str]]] = {fuzzer: {} for fuzzer in fuzzers}

        for entry in target.get('fuzzers') or []:
            fuzzer = entry.get('fuzzer')
            if not fuzzer:
                continue
            trial_ids = {
                int(trial.get('trial_id'))
                for trial in entry.get('trials') or []
                if isinstance(trial.get('trial_id'), int)
            }
            trial_bug_sets_by_fuzzer[fuzzer] = {trial_id: set() for trial_id in sorted(trial_ids)}
            for bug in entry.get('bugs') or []:
                bug_key = bug.get('bug_key')
                if not bug_key:
                    continue
                key = str(bug_key)
                for trial_id in bug.get('trial_ids') or []:
                    if isinstance(trial_id, int) and trial_id in trial_bug_sets_by_fuzzer[fuzzer]:
                        trial_bug_sets_by_fuzzer[fuzzer][trial_id].add(key)

        trial_bug_sets = {
            fuzzer: list(trial_bug_sets_by_fuzzer.get(fuzzer, {}).values())
            for fuzzer in fuzzers
        }
        missing_any = any(not trial_bug_sets.get(fuzzer) for fuzzer in fuzzers)
        matrix = relative_containment_matrix(
            fuzzers,
            trial_bug_sets,
            note=(
                'Trial unique bug sets missing for one or more fuzzers; '
                'relative bug coverage may be partial.'
            ) if missing_any else None,
        )

        return (
            {
                **matrix,
                'format': 'pct',
                'aggregation': 'per-trial median unique bug sets',
            },
            novelty_scores(fuzzers, trial_bug_sets),
        )
