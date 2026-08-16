# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build temporary composite report payloads from selected measurement series.'''

from __future__ import annotations

import copy
import datetime

from pathlib import Path
from typing import Any

from ..composite import CompositeMeasurement, CompositeSelection
from .analyzers import coverage_matrices
from .analyzers.bug_analysis import BugAnalysis
from .data.coverage_data import CoverageData
from .keys import (
    BRANCH_A12_MATRIX_KEY,
    BRANCH_MWU_MATRIX_KEY,
    COV_METRICS,
    RELBUG_MATRIX_KEY,
    RELBUG_SCORE_BY_FUZZER_KEY,
    RELCOV_MATRIX_KEY,
    RELCOV_SCORE_BY_FUZZER_KEY,
    UNIQUE_BUG_MATRIX_KEY,
    UNIQUE_BUG_TABLE_KEY,
    UNIQUE_MATRIX_KEY,
)
from .metrics import dt
from .payload import build_payload
from .set_comparison import empty_trial_set_comparison, trial_set_index


def build_composite_payload(
    entries: list[tuple[CompositeSelection, CompositeMeasurement]],
) -> dict[str, Any]:
    '''Build a report payload for selected measurement series without copying source data.'''
    payload = _empty_payload()
    source_dirs: dict[tuple[str, str, str], Path] = {}
    used_names: dict[tuple[str, str], set[str]] = {}
    run_payloads: dict[tuple[Path, str, str], dict[str, Any]] = {}
    for selection, measurement in entries:
        cache_key = (measurement.source_path, measurement.key.run_id, measurement.key.source_id)
        run_payload = run_payloads.get(cache_key)
        if run_payload is None:
            run_payload = build_payload(
                measurement.source_path,
                run_id=measurement.key.run_id,
                file_url_prefix=f'/file/{measurement.key.source_id}/',
            )
            run_payloads[cache_key] = run_payload
        display_fuzzer = _display_fuzzer(selection, measurement, used_names)
        merged = _merge_measurement(payload, run_payload, selection, measurement, display_fuzzer)
        if merged:
            source_key = (measurement.key.benchmark, measurement.key.fuzz_target, display_fuzzer)
            source_dirs[source_key] = measurement.source_path
    _recompute_matrices(payload, source_dirs)
    return payload


def _empty_payload() -> dict[str, Any]:
    return {
        'meta': {
            'generated_at': dt(int(datetime.datetime.now(datetime.timezone.utc).timestamp())),
            'run_id': 'composite',
            'view': 'composite',
        },
        'overview': {'run_id': 'composite'},
        'sources': [],
        'targets': [],
        'trials': [],
        'timeseries': {},
        'bugs': [],
    }


def _display_fuzzer(
    selection: CompositeSelection,
    measurement: CompositeMeasurement,
    used_names: dict[tuple[str, str], set[str]],
) -> str:
    base = selection.display_fuzzer or measurement.key.fuzzer
    target_key = (measurement.key.benchmark, measurement.key.fuzz_target)
    used = used_names.setdefault(target_key, set())
    if base not in used:
        used.add(base)
        return base
    index = 2
    while f'{base} #{index}' in used:
        index += 1
    name = f'{base} #{index}'
    used.add(name)
    return name


def _merge_measurement(
    payload: dict[str, Any],
    run_payload: dict[str, Any],
    selection: CompositeSelection,
    measurement: CompositeMeasurement,
    display_fuzzer: str,
) -> bool:
    source_target = _find_target(run_payload, measurement.key.benchmark, measurement.key.fuzz_target)
    if source_target is None:
        _append_skipped_source(
            payload,
            selection,
            measurement,
            display_fuzzer,
            'Target data not found in source report payload.',
        )
        return False
    source_fuzzer = _find_fuzzer(source_target, measurement.key.fuzzer)
    if source_fuzzer is None:
        _append_skipped_source(
            payload,
            selection,
            measurement,
            display_fuzzer,
            'Fuzzer data not found in source report payload.',
        )
        return False

    target = _find_target(payload, measurement.key.benchmark, measurement.key.fuzz_target)
    if target is None:
        target = copy.deepcopy(source_target)
        target['fuzzers'] = []
        payload['targets'].append(target)

    entry = copy.deepcopy(source_fuzzer)
    _mark_origin(entry, selection, measurement, display_fuzzer)
    target.setdefault('fuzzers', []).append(entry)
    _append_trials(payload, run_payload, selection, measurement, display_fuzzer)
    _append_bugs(payload, run_payload, selection, measurement, display_fuzzer)
    _append_source(payload, selection, measurement, display_fuzzer)
    return True


def _mark_origin(
    entry: dict[str, Any],
    selection: CompositeSelection,
    measurement: CompositeMeasurement,
    display_fuzzer: str,
) -> None:
    original_fuzzer = entry.get('fuzzer')
    entry['fuzzer'] = display_fuzzer
    entry['selection_id'] = selection.selection_id
    entry['origin'] = selection.origin
    entry['source_id'] = measurement.key.source_id
    entry['source_run_id'] = measurement.key.run_id
    entry['source_fuzzer'] = original_fuzzer
    entry['source_detail'] = {
        'source_id': measurement.key.source_id,
        'run_id': measurement.key.run_id,
        'source_fuzzer': original_fuzzer,
        'runtime_seconds': measurement.runtime_seconds,
        'repetitions': measurement.repetitions,
    }
    entry['metadata'] = measurement.metadata.to_json()
    for key in ('trials', 'curve', 'bugs'):
        for item in entry.get(key) or []:
            if isinstance(item, dict):
                item['fuzzer'] = display_fuzzer
                item['origin'] = selection.origin
                item['source_id'] = measurement.key.source_id
                item['source_run_id'] = measurement.key.run_id
                item['source_fuzzer'] = original_fuzzer


def _append_trials(
    payload: dict[str, Any],
    run_payload: dict[str, Any],
    selection: CompositeSelection,
    measurement: CompositeMeasurement,
    display_fuzzer: str,
) -> None:
    for trial in run_payload.get('trials') or []:
        if not _matches_measurement_row(trial, measurement):
            continue
        copied = copy.deepcopy(trial)
        copied['trial_id'] = _prefixed_id(measurement.key.source_id, copied.get('trial_id'))
        copied['fuzzer'] = display_fuzzer
        copied['origin'] = selection.origin
        copied['source_id'] = measurement.key.source_id
        copied['source_run_id'] = measurement.key.run_id
        payload['trials'].append(copied)


def _append_bugs(
    payload: dict[str, Any],
    run_payload: dict[str, Any],
    selection: CompositeSelection,
    measurement: CompositeMeasurement,
    display_fuzzer: str,
) -> None:
    for bug in run_payload.get('bugs') or []:
        if not _matches_measurement_row(bug, measurement):
            continue
        copied = copy.deepcopy(bug)
        copied['bug_id'] = _prefixed_id(measurement.key.source_id, copied.get('bug_id'))
        copied['fuzzer'] = display_fuzzer
        copied['origin'] = selection.origin
        copied['source_id'] = measurement.key.source_id
        copied['source_run_id'] = measurement.key.run_id
        payload['bugs'].append(copied)


def _append_source(
    payload: dict[str, Any],
    selection: CompositeSelection,
    measurement: CompositeMeasurement,
    display_fuzzer: str,
) -> None:
    payload['sources'].append(
        {
            'selection_id': selection.selection_id,
            'origin': selection.origin,
            'source_id': measurement.key.source_id,
            'run_id': measurement.key.run_id,
            'fuzzer': display_fuzzer,
            'source_fuzzer': measurement.key.fuzzer,
            'benchmark': measurement.key.benchmark,
            'fuzz_target': measurement.key.fuzz_target,
            'runtime_seconds': measurement.runtime_seconds,
            'repetitions': measurement.repetitions,
            'metadata': measurement.metadata.to_json(),
        }
    )


def _append_skipped_source(
    payload: dict[str, Any],
    selection: CompositeSelection,
    measurement: CompositeMeasurement,
    display_fuzzer: str,
    error: str,
) -> None:
    payload['sources'].append(
        {
            'selection_id': selection.selection_id,
            'origin': selection.origin,
            'source_id': measurement.key.source_id,
            'run_id': measurement.key.run_id,
            'fuzzer': display_fuzzer,
            'source_fuzzer': measurement.key.fuzzer,
            'benchmark': measurement.key.benchmark,
            'fuzz_target': measurement.key.fuzz_target,
            'runtime_seconds': measurement.runtime_seconds,
            'repetitions': measurement.repetitions,
            'metadata': measurement.metadata.to_json(),
            'status': 'skipped',
            'error': error,
        }
    )


def _matches_measurement_row(row: dict[str, Any], measurement: CompositeMeasurement) -> bool:
    return (
        str(row.get('fuzzer') or '') == measurement.key.fuzzer
        and str(row.get('benchmark') or '') == measurement.key.benchmark
        and str(row.get('fuzz_target') or '') == measurement.key.fuzz_target
    )


def _recompute_matrices(
    payload: dict[str, Any],
    source_dirs: dict[tuple[str, str, str], Path],
) -> None:
    bug_analysis = BugAnalysis()
    for target in payload.get('targets') or []:
        fuzzers = [str(entry.get('fuzzer') or '') for entry in target.get('fuzzers') or [] if entry.get('fuzzer')]
        if len(fuzzers) <= 1:
            _attach_empty_matrices(target)
            continue
        benchmark = str(target.get('benchmark') or '')
        fuzz_target = str(target.get('fuzz_target') or '')
        trials = _target_trials(target, benchmark, fuzz_target)
        coverage_sets_by_metric = _coverage_sets_by_metric(target, source_dirs)
        trial_coverage_sets_by_metric = _trial_coverage_sets_by_metric(target, source_dirs)
        trial_coverage_sets_by_metric, aggregate_fallback_fuzzers_by_metric = _with_aggregate_trial_fallback(
            trial_coverage_sets_by_metric,
            coverage_sets_by_metric,
            fuzzers,
        )
        trial_set_indexes_by_metric = {
            metric: trial_set_index(fuzzers, trial_coverage_sets_by_metric.get(metric, {}))
            for metric in COV_METRICS
        }
        target[UNIQUE_MATRIX_KEY] = coverage_matrices.compute_unique_matrix(
            cov_metrics=COV_METRICS,
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            trial_coverage_sets_by_metric=trial_coverage_sets_by_metric,
            aggregate_fallback_fuzzers_by_metric=aggregate_fallback_fuzzers_by_metric,
            trial_set_indexes_by_metric=trial_set_indexes_by_metric,
        )
        target[RELCOV_MATRIX_KEY], target[RELCOV_SCORE_BY_FUZZER_KEY] = coverage_matrices.compute_relcov_matrix(
            cov_metrics=COV_METRICS,
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            trial_coverage_sets_by_metric=trial_coverage_sets_by_metric,
            aggregate_fallback_fuzzers_by_metric=aggregate_fallback_fuzzers_by_metric,
            trial_set_indexes_by_metric=trial_set_indexes_by_metric,
        )
        target[BRANCH_MWU_MATRIX_KEY], target[BRANCH_A12_MATRIX_KEY] = coverage_matrices.compute_branch_stat_matrices(
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
        )
        coverage_matrices.attach_exclusive_coverage_stats(
            target=target,
            trial_coverage_sets_by_metric=trial_coverage_sets_by_metric,
            aggregate_fallback_fuzzers_by_metric=aggregate_fallback_fuzzers_by_metric,
        )
        target[UNIQUE_BUG_TABLE_KEY] = bug_analysis.compute_unique_bug_table(target)
        target[UNIQUE_BUG_MATRIX_KEY] = bug_analysis.compute_unique_bug_matrix(target)
        target[RELBUG_MATRIX_KEY], target[RELBUG_SCORE_BY_FUZZER_KEY] = bug_analysis.compute_rel_bug_matrix(target)
        bug_analysis.attach_exclusive_bug_stats(target)


def _attach_empty_matrices(target: dict[str, Any]) -> None:
    empty_metric_group = {'by_metric': {}, 'has_data': False, 'available_metrics': []}
    empty_matrix = {'fuzzers': [], 'matrix': [], 'max_value': 0, 'has_data': False}
    target[UNIQUE_MATRIX_KEY] = empty_metric_group
    target[RELCOV_MATRIX_KEY] = empty_metric_group
    target[BRANCH_MWU_MATRIX_KEY] = empty_metric_group
    target[BRANCH_A12_MATRIX_KEY] = empty_metric_group
    target[RELCOV_SCORE_BY_FUZZER_KEY] = {}
    target[UNIQUE_BUG_TABLE_KEY] = {'fuzzers': [], 'rows': [], 'has_data': False}
    target[UNIQUE_BUG_MATRIX_KEY] = empty_trial_set_comparison()
    target[RELBUG_MATRIX_KEY] = empty_matrix
    target[RELBUG_SCORE_BY_FUZZER_KEY] = {}


def _target_trials(target: dict[str, Any], benchmark: str, fuzz_target: str) -> list[dict[str, Any]]:
    trials: list[dict[str, Any]] = []
    for entry in target.get('fuzzers') or []:
        fuzzer = str(entry.get('fuzzer') or '')
        for trial in entry.get('trials') or []:
            if not isinstance(trial, dict):
                continue
            copied = dict(trial)
            copied['fuzzer'] = fuzzer
            copied['benchmark'] = benchmark
            copied['fuzz_target'] = fuzz_target
            trials.append(copied)
    return trials


def _coverage_sets_by_metric(
    target: dict[str, Any],
    source_dirs: dict[tuple[str, str, str], Path],
) -> dict[str, dict[str, set[str]]]:
    benchmark = str(target.get('benchmark') or '')
    fuzz_target = str(target.get('fuzz_target') or '')
    caches: dict[Path, CoverageData] = {}
    out = {metric: {} for metric in COV_METRICS}
    for entry in target.get('fuzzers') or []:
        fuzzer = str(entry.get('fuzzer') or '')
        source_dir = source_dirs.get((benchmark, fuzz_target, fuzzer))
        coverage_rel = _coverage_report_relpath(entry.get('coverage_report'))
        if not fuzzer or source_dir is None or coverage_rel is None:
            continue
        coverage_data = caches.setdefault(Path(source_dir), CoverageData(source_dir))
        coverage_path = coverage_data.coverage_sets_from_coverage_html_rel(coverage_rel)
        if coverage_path is None:
            continue
        for metric in COV_METRICS:
            values = coverage_data.covered_elements(coverage_path, metric)
            if values is not None:
                out[metric][fuzzer] = values
    return out


def _trial_coverage_sets_by_metric(
    target: dict[str, Any],
    source_dirs: dict[tuple[str, str, str], Path],
) -> dict[str, dict[str, list[set[str] | None]]]:
    benchmark = str(target.get('benchmark') or '')
    fuzz_target = str(target.get('fuzz_target') or '')
    caches: dict[Path, CoverageData] = {}
    out: dict[str, dict[str, list[set[str] | None]]] = {metric: {} for metric in COV_METRICS}
    for entry in target.get('fuzzers') or []:
        fuzzer = str(entry.get('fuzzer') or '')
        source_dir = source_dirs.get((benchmark, fuzz_target, fuzzer))
        if not fuzzer or source_dir is None:
            continue
        coverage_data = caches.setdefault(Path(source_dir), CoverageData(source_dir))
        for trial in entry.get('trials') or []:
            coverage_path = coverage_data.coverage_sets_from_coverage_html_rel(
                (trial or {}).get('coverage_html_rel')
            )
            for metric in COV_METRICS:
                out[metric].setdefault(fuzzer, []).append(
                    coverage_data.covered_elements(coverage_path, metric)
                    if coverage_path is not None
                    else None
                )
    return out


def _with_aggregate_trial_fallback(
    trial_coverage_sets_by_metric: dict[str, dict[str, list[set[str] | None]]],
    coverage_sets_by_metric: dict[str, dict[str, set[str]]],
    fuzzers: list[str],
) -> tuple[dict[str, dict[str, list[set[str] | None]]], dict[str, set[str]]]:
    '''Use final aggregate coverage sets when trial compact sets are unavailable.'''

    out: dict[str, dict[str, list[set[str] | None]]] = {}
    fallback_fuzzers_by_metric: dict[str, set[str]] = {}
    for metric in COV_METRICS:
        trial_sets = trial_coverage_sets_by_metric.get(metric, {})
        aggregate_sets = coverage_sets_by_metric.get(metric, {})
        merged = {
            fuzzer: [set(value) if value is not None else None for value in values]
            for fuzzer, values in trial_sets.items()
        }
        for fuzzer in fuzzers:
            if any(value is not None for value in merged.get(fuzzer, [])):
                continue
            aggregate_set = aggregate_sets.get(fuzzer)
            if aggregate_set is not None:
                merged[fuzzer] = [set(aggregate_set)]
                fallback_fuzzers_by_metric.setdefault(metric, set()).add(fuzzer)
        out[metric] = merged
    return out, fallback_fuzzers_by_metric


def _coverage_report_relpath(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if text.startswith('/file/'):
        parts = text.split('/', 3)
        return parts[3] if len(parts) > 3 else None
    if text.startswith('../'):
        return text[3:]
    return text


def _find_target(payload: dict[str, Any], benchmark: str, fuzz_target: str) -> dict[str, Any] | None:
    for target in payload.get('targets') or []:
        if str(target.get('benchmark') or '') == benchmark and str(target.get('fuzz_target') or '') == fuzz_target:
            return target
    return None


def _find_fuzzer(target: dict[str, Any], fuzzer: str) -> dict[str, Any] | None:
    for entry in target.get('fuzzers') or []:
        if str(entry.get('fuzzer') or '') == fuzzer:
            return entry
    return None


def _prefixed_id(source_id: str, value: Any) -> str:
    return f'{source_id}:{value}'
