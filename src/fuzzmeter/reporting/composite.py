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
from .analyzers import target_matrices
from .data.coverage_data import CoverageData
from .keys import COV_METRICS
from .metrics import dt, safe_int
from .payload import build_payload


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


def _recompute_matrices(
    payload: dict[str, Any],
    source_dirs: dict[tuple[str, str, str], Path],
) -> None:
    for target in payload.get('targets') or []:
        fuzzers = [str(entry.get('fuzzer') or '') for entry in target.get('fuzzers') or [] if entry.get('fuzzer')]
        if len(fuzzers) <= 1:
            target_matrices.attach_empty_target_matrices(target)
            continue
        target_matrices.attach_target_matrices(
            target=target,
            fuzzers=fuzzers,
            branch_coverage_by_fuzzer=_branch_coverage_by_fuzzer(target),
            coverage_sets_by_metric=_coverage_sets_by_metric(target, source_dirs),
            trial_coverage_sets_by_metric=_trial_coverage_sets_by_metric(target, source_dirs),
        )


def _branch_coverage_by_fuzzer(target: dict[str, Any]) -> dict[str, list[int | None]]:
    """Return the final branch coverage of every merged trial, by the fuzzer it is shown under."""

    return {
        str(entry.get('fuzzer') or ''): [
            safe_int(trial.get('branches_cov')) for trial in entry.get('trials') or []
        ]
        for entry in target.get('fuzzers') or []
        if entry.get('fuzzer')
    }


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
