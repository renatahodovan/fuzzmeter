# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build bug-centric report sections and derived comparison data.'''

from __future__ import annotations

from typing import Any

from ...db.bug import BugRow
from ..keys import (
    RELBUG_MATRIX_KEY,
    RELBUG_SCORE_BY_FUZZER_KEY,
    UNIQUE_BUG_MATRIX_KEY,
    UNIQUE_BUG_TABLE_KEY,
)
from ..metrics import dt, median
from ..set_comparison import (
    empty_trial_set_comparison,
    novelty_scores,
    relative_containment_matrix,
    trial_set_comparison,
)


def collect_bugs(
    *,
    bugs: list[BugRow],
    bug_hits_by_bug: dict[int, int],
    bug_trials_by_bug: dict[int, list[int]],
) -> list[dict[str, Any]]:
    '''Collect normalized bug rows with total hit counts.'''

    return [
        {
            'bug_id': bug.bug_id,
            'run_id': bug.run_id,
            'fuzzer': bug.fuzzer,
            'benchmark': bug.benchmark,
            'fuzz_target': bug.fuzz_target,
            'bug_key': bug.bug_key,
            'issue_type': bug.issue_type,
            'top_func': bug.top_func,
            'frames': bug.frames,
            'output': bug.output,
            'first_seen_ts': bug.first_seen_ts,
            'first_seen_snapshot_id': bug.first_seen_snapshot_id,
            'first_seen_at': dt(bug.first_seen_ts),
            'hits_total': int(bug_hits_by_bug.get(bug.bug_id, 0)),
            'trial_ids': sorted({int(trial_id) for trial_id in bug_trials_by_bug.get(bug.bug_id, [])}),
        }
        for bug in bugs
    ]


def attach_exclusive_bug_stats(target: dict[str, Any]) -> dict[str, Any]:
    '''Attach per-fuzzer exclusive bug totals and trial distributions to a target.'''

    entries = target.get('fuzzers') or []
    fuzzers, trial_bug_sets = _trial_bug_sets(target)
    comparison = target.get('unique_bug_matrix') or trial_set_comparison(fuzzers, trial_bug_sets)
    exclusive = comparison.get('exclusive') or {}
    index_by_fuzzer = {fuzzer: index for index, fuzzer in enumerate(comparison.get('fuzzers') or [])}
    unions = {
        fuzzer: set().union(*(values for values in trial_bug_sets.get(fuzzer, []) if values is not None))
        for fuzzer in fuzzers
    }
    prefixes: list[set[str]] = []
    all_bug_union: set[str] = set()
    for fuzzer in fuzzers:
        prefixes.append(all_bug_union)
        all_bug_union = all_bug_union | unions[fuzzer]
    other_unions: dict[str, set[str]] = {}
    suffix: set[str] = set()
    for index in range(len(fuzzers) - 1, -1, -1):
        fuzzer = fuzzers[index]
        other_unions[fuzzer] = prefixes[index] | suffix
        suffix.update(unions[fuzzer])

    for entry in entries:
        fuzzer = str(entry.get('fuzzer') or '')
        other_bug_union = other_unions.get(fuzzer, all_bug_union)
        trial_counts = [
            len(values - other_bug_union)
            for values in trial_bug_sets.get(fuzzer, [])
            if values is not None
        ]
        index = index_by_fuzzer.get(fuzzer, -1)
        any_values = exclusive.get('exclusive_any') or []
        all_values = exclusive.get('exclusive_all') or []
        any_bounds = exclusive.get('exclusive_any_bounds') or []
        all_bounds = exclusive.get('exclusive_all_bounds') or []
        entry['exclusive_bugs'] = {
            'exclusive_any': any_values[index] if 0 <= index < len(any_values) else None,
            'exclusive_all': all_values[index] if 0 <= index < len(all_values) else None,
            'exclusive_any_bound': any_bounds[index] if 0 <= index < len(any_bounds) else 'unknown',
            'exclusive_all_bound': all_bounds[index] if 0 <= index < len(all_bounds) else 'unknown',
            'min': min(trial_counts) if trial_counts else None,
            'max': max(trial_counts) if trial_counts else None,
            'median': median(trial_counts),
            'sample_size': len(trial_bug_sets.get(fuzzer, [])),
            'usable_sample_size': len(trial_counts),
        }
    return target


def compute_unique_bug_matrix(target: dict[str, Any]) -> dict[str, Any]:
    '''Compute pairwise unique bug counts between fuzzers.'''

    fuzzers, trial_bug_sets = _trial_bug_sets(target)
    comparison = trial_set_comparison(fuzzers, trial_bug_sets)
    return {
        **comparison,
        'format': 'int',
        'aggregation': 'per-fuzzer trial bug sets',
    }


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


def compute_rel_bug_matrix(target: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float]]:
    '''Compute pairwise relative bug containment and novelty-weighted bug scores.'''

    fuzzers, trial_bug_sets = _trial_bug_sets(target)
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


def attach_empty_bug_matrices(target: dict[str, Any]) -> None:
    '''Attach placeholder bug matrices to a target without comparable fuzzers.'''

    target[UNIQUE_BUG_TABLE_KEY] = {'fuzzers': [], 'rows': [], 'has_data': False}
    target[UNIQUE_BUG_MATRIX_KEY] = empty_trial_set_comparison()
    target[RELBUG_MATRIX_KEY] = {'fuzzers': [], 'matrix': [], 'max_value': 0, 'has_data': False}
    target[RELBUG_SCORE_BY_FUZZER_KEY] = {}


def _trial_bug_sets(target: dict[str, Any]) -> tuple[list[str], dict[str, list[set[str] | None]]]:
    '''Return ordered per-trial bug sets for every fuzzer in a target.'''

    fuzzers = sorted({str(entry.get('fuzzer')) for entry in target.get('fuzzers') or [] if entry.get('fuzzer')})
    by_fuzzer: dict[str, dict[int, set[str] | None]] = {fuzzer: {} for fuzzer in fuzzers}
    for entry in target.get('fuzzers') or []:
        fuzzer = str(entry.get('fuzzer') or '')
        if not fuzzer:
            continue
        for trial in entry.get('trials') or []:
            trial_id = trial.get('trial_id')
            if isinstance(trial_id, int):
                by_fuzzer[fuzzer][trial_id] = None if trial.get('bug_set_missing') is True else set()
        for bug in entry.get('bugs') or []:
            bug_key = str(bug.get('bug_key') or '')
            if not bug_key:
                continue
            for trial_id in bug.get('trial_ids') or []:
                trial_set = by_fuzzer[fuzzer].get(trial_id)
                if isinstance(trial_set, set):
                    trial_set.add(bug_key)
    return fuzzers, {
        fuzzer: [values for _, values in sorted(by_fuzzer[fuzzer].items())]
        for fuzzer in fuzzers
    }
