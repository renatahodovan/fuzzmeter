# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Serve composite measurement discovery, view state, and report payloads.'''

from __future__ import annotations

import logging

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ...composite import (
    COMPATIBLE,
    COMPOSITE_ORIGIN_FRESH,
    COMPOSITE_ORIGIN_HISTORICAL,
    RISKY,
    CompositeViewExpired,
    compare_metadata,
)
from ...composite.discovery import read_measurements
from ...composite.models import CompositeMeasurement, CompositeMeasurementKey, CompositeSelection
from ...composite.registry import CompositeRegistry, CompositeViewStore, selection_from_key
from ...reporting import build_composite_payload
from .file_service import require_run_dir, resolve_run_dir

LOG = logging.getLogger(__name__)


def list_measurements(registry: CompositeRegistry) -> dict[str, Any]:
    '''Return discoverable measurements and invalid sources.'''
    return {
        'measurements': [measurement.to_json() for measurement in registry.measurements()],
        'invalid_sources': [source.to_json() for source in registry.invalid_sources()],
    }


def refresh_sources(registry: CompositeRegistry) -> dict[str, Any]:
    '''Refresh the serve-lifetime descriptor registry.'''
    registry.refresh()
    return list_measurements(registry)


def create_view(store: CompositeViewStore, data: dict[str, Any]) -> dict[str, Any]:
    '''Create a composite view from posted selections.'''
    view = store.create(_selections_from_payload(data, default_origin=COMPOSITE_ORIGIN_HISTORICAL))
    return view.to_json()


def create_view_from_run(run_dirs: Iterable[Path], store: CompositeViewStore, run_id: str) -> dict[str, Any]:
    '''Create a composite view seeded with all measurements from an active run.'''
    measurements = _run_measurements(run_dirs, run_id)
    selections = [
        selection_from_key(measurement.key, origin=COMPOSITE_ORIGIN_FRESH)
        for measurement in measurements
    ]
    return store.create(selections).to_json()


def add_measurements(store: CompositeViewStore, view_id: str, data: dict[str, Any]) -> dict[str, Any]:
    '''Add measurements to a composite view.'''
    return store.add(view_id, _selections_from_payload(data, default_origin=COMPOSITE_ORIGIN_HISTORICAL)).to_json()


def remove_measurement(store: CompositeViewStore, view_id: str, selection_id: str) -> dict[str, Any]:
    '''Remove one selected measurement from a composite view.'''
    return store.remove(view_id, selection_id).to_json()


def view_summary(
    run_dirs: Iterable[Path],
    registry: CompositeRegistry,
    store: CompositeViewStore,
    view_id: str,
) -> dict[str, Any]:
    '''Return selected measurement summaries for one view.'''
    view = _require_view(store, view_id)
    resolved = _resolve_summary_entries(run_dirs, registry, view.selections)
    return {
        **view.to_json(),
        'sources': [
            _missing_source_summary(selection) if measurement is None
            else _source_summary(selection, measurement)
            for selection, measurement in resolved
        ],
    }


def view_report_data(
    run_dirs: Iterable[Path],
    registry: CompositeRegistry,
    store: CompositeViewStore,
    view_id: str,
) -> dict[str, Any]:
    '''Build the full report payload for a composite view.'''
    view = _require_view(store, view_id)
    entries = _resolve_entries(run_dirs, registry, view.selections)
    payload = build_composite_payload(entries)
    payload['meta']['view_id'] = view.view_id
    if _has_historical(entries):
        measurements_by_selection = {selection.selection_id: measurement for selection, measurement in entries}
        for source in payload.get('sources') or []:
            measurement = measurements_by_selection.get(source.get('selection_id'))
            if measurement is not None and source.get('origin') == COMPOSITE_ORIGIN_HISTORICAL:
                source['compatibility'] = _compatibility_for(entries, measurement)
    _attach_fuzzer_source_metadata(payload)
    return payload


def _selections_from_payload(data: dict[str, Any], *, default_origin: str) -> list[CompositeSelection]:
    raw = data.get('measurements', data.get('selections', []))
    if not isinstance(raw, list):
        raise ValueError('measurements must be a list.')
    selections: list[CompositeSelection] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError('measurement selection must be an object.')
        key_data = item.get('key') if isinstance(item.get('key'), dict) else item
        key = CompositeMeasurementKey.from_json(key_data)
        _validate_key(key)
        origin = str(item.get('origin') or default_origin)
        display_fuzzer = item.get('display_fuzzer')
        selection_id = item.get('selection_id') or item.get('id')
        selections.append(
            selection_from_key(
                key,
                origin=origin,
                display_fuzzer=str(display_fuzzer) if display_fuzzer else None,
                selection_id=str(selection_id) if selection_id else None,
            )
        )
    return selections


def _resolve_entries(
    run_dirs: Iterable[Path],
    registry: CompositeRegistry,
    selections: tuple[CompositeSelection, ...],
) -> list[tuple[CompositeSelection, CompositeMeasurement]]:
    entries: list[tuple[CompositeSelection, CompositeMeasurement]] = []
    for selection in selections:
        measurement = registry.get(selection.key)
        if measurement is None:
            measurement = _read_run_measurement(run_dirs, selection.key)
        if measurement is None:
            raise FileNotFoundError(f'Measurement not found: {selection.key.as_id()}')
        entries.append((selection, measurement))
    return entries


def _resolve_summary_entries(
    run_dirs: Iterable[Path],
    registry: CompositeRegistry,
    selections: tuple[CompositeSelection, ...],
) -> list[tuple[CompositeSelection, CompositeMeasurement | None]]:
    entries: list[tuple[CompositeSelection, CompositeMeasurement | None]] = []
    for selection in selections:
        try:
            measurement = registry.get(selection.key) or _read_run_measurement(run_dirs, selection.key)
        except Exception as exc:
            LOG.warning('Could not resolve composite selection %s: %s', selection.selection_id, exc)
            measurement = None
        entries.append((selection, measurement))
    return entries


def _run_measurements(run_dirs: Iterable[Path], run_id: str) -> list[CompositeMeasurement]:
    run_dir = require_run_dir(run_dirs, run_id)
    return read_measurements(run_dir / 'fuzzmeter.db', run_id)


def _read_run_measurement(run_dirs: Iterable[Path], key: CompositeMeasurementKey) -> CompositeMeasurement | None:
    try:
        run_dir = resolve_run_dir(run_dirs, key.source_id)
    except FileNotFoundError:
        return None
    if not run_dir.is_dir():
        return None
    for measurement in read_measurements(run_dir / 'fuzzmeter.db', key.source_id):
        if measurement.key == key:
            return measurement
    return None


def _compatibility_for(
    entries: list[tuple[CompositeSelection, CompositeMeasurement]],
    measurement: CompositeMeasurement,
) -> dict[str, Any]:
    target_reference = _reference_for(entries, measurement)
    if target_reference is None:
        return {
            'level': COMPATIBLE,
            'issues': [],
            'diffs': [],
            'reference': None,
            'comparison_note': 'No external comparison reference.',
        }
    if target_reference[1] is measurement:
        result = {
            'level': COMPATIBLE,
            'issues': [],
            'diffs': [],
            'reference': _source_identity(*target_reference),
            'comparison_note': 'Target reference source.',
        }
    else:
        comparison = compare_metadata(target_reference[1].metadata, measurement.metadata)
        result = comparison.to_json()
        result['reference'] = _source_identity(*target_reference)
        result['comparison_note'] = ''
        if target_reference[0].origin == COMPOSITE_ORIGIN_FRESH:
            _attach_policy_warnings(result, target_reference[1], measurement)
    return result


def _has_historical(entries: list[tuple[CompositeSelection, CompositeMeasurement]]) -> bool:
    return any(selection.origin == COMPOSITE_ORIGIN_HISTORICAL for selection, _ in entries)


def _reference_for(
    entries: list[tuple[CompositeSelection, CompositeMeasurement]],
    measurement: CompositeMeasurement,
) -> tuple[CompositeSelection, CompositeMeasurement] | None:
    candidates = [
        (selection, candidate)
        for selection, candidate in entries
        if (
            candidate.key.benchmark == measurement.key.benchmark
            and candidate.key.fuzz_target == measurement.key.fuzz_target
        )
    ]
    if len(candidates) == 1 and candidates[0][1] is measurement:
        return None
    for selection, candidate in candidates:
        if selection.origin == COMPOSITE_ORIGIN_FRESH:
            return selection, candidate
    return candidates[0] if candidates else None


def _source_identity(selection: CompositeSelection, measurement: CompositeMeasurement) -> dict[str, Any]:
    return {
        'selection_id': selection.selection_id,
        'origin': selection.origin,
        'source_id': measurement.key.source_id,
        'run_id': measurement.key.run_id,
        'fuzzer': selection.display_fuzzer or measurement.key.fuzzer,
        'source_fuzzer': measurement.key.fuzzer,
        'benchmark': measurement.key.benchmark,
        'fuzz_target': measurement.key.fuzz_target,
    }


def _attach_policy_warnings(
    result: dict[str, Any],
    reference: CompositeMeasurement,
    candidate: CompositeMeasurement,
) -> None:
    if candidate.repetitions and reference.repetitions and candidate.repetitions < reference.repetitions:
        _append_policy_warning(
            result,
            'Historical measurement has fewer repetitions than the target reference.',
            'repetitions',
            reference.repetitions,
            candidate.repetitions,
        )
    runtime_is_shorter = (
        candidate.runtime_seconds
        and reference.runtime_seconds
        and candidate.runtime_seconds < reference.runtime_seconds
    )
    if runtime_is_shorter:
        _append_policy_warning(
            result,
            'Historical measurement runtime is shorter than the target reference.',
            'runtime_seconds',
            reference.runtime_seconds,
            candidate.runtime_seconds,
        )


def _append_policy_warning(
    result: dict[str, Any],
    message: str,
    path: str,
    reference: int,
    candidate: int,
) -> None:
    result.setdefault('issues', []).append(
        {
            'domain': 'policy',
            'severity': 'warning',
            'message': message,
            'details': {path: {'reference': reference, 'candidate': candidate}},
        }
    )
    result.setdefault('diffs', []).append(
        {
            'domain': 'policy',
            'path': path,
            'severity': 'warning',
            'message': message,
            'reference': reference,
            'candidate': candidate,
        }
    )
    if result.get('level') == COMPATIBLE:
        result['level'] = RISKY


def _attach_fuzzer_source_metadata(payload: dict[str, Any]) -> None:
    sources = {
        source.get('selection_id'): source
        for source in payload.get('sources') or []
        if isinstance(source, dict) and source.get('compatibility') is not None
    }
    if not sources:
        return
    for target in payload.get('targets') or []:
        for fuzzer in target.get('fuzzers') or []:
            source = sources.get(fuzzer.get('selection_id'))
            if source:
                fuzzer['compatibility'] = source.get('compatibility')


def _source_summary(
    selection: CompositeSelection,
    measurement: CompositeMeasurement,
) -> dict[str, Any]:
    return {
        'selection_id': selection.selection_id,
        'key': measurement.key.to_json(),
        'origin': selection.origin,
        'source_id': measurement.key.source_id,
        'run_id': measurement.key.run_id,
        'fuzzer': measurement.key.fuzzer,
        'benchmark': measurement.key.benchmark,
        'fuzz_target': measurement.key.fuzz_target,
        'runtime_seconds': measurement.runtime_seconds,
        'repetitions': measurement.repetitions,
        'metadata': measurement.metadata.to_json(),
        'display_fuzzer': selection.display_fuzzer or measurement.key.fuzzer,
        'status': 'ok',
    }


def _missing_source_summary(selection: CompositeSelection) -> dict[str, Any]:
    return {
        'selection_id': selection.selection_id,
        'key': selection.key.to_json(),
        'origin': selection.origin,
        'source_id': selection.key.source_id,
        'run_id': selection.key.run_id,
        'fuzzer': selection.key.fuzzer,
        'benchmark': selection.key.benchmark,
        'fuzz_target': selection.key.fuzz_target,
        'display_fuzzer': selection.display_fuzzer or selection.key.fuzzer,
        'status': 'missing',
        'error': f'Measurement not found: {selection.key.as_id()}',
        'compatibility': {'level': 'incompatible', 'issues': []},
    }


def _validate_key(key: CompositeMeasurementKey) -> None:
    if not all((key.source_id, key.run_id, key.fuzzer, key.benchmark, key.fuzz_target)):
        raise ValueError('measurement key must include source_id, run_id, fuzzer, benchmark, and fuzz_target.')
    if _has_path_separator(key.source_id) or key.source_id in {'.', '..'}:
        raise ValueError('measurement key source_id must be a direct run directory name.')


def _has_path_separator(value: str) -> bool:
    return '/' in value or '\\' in value


def _require_view(store: CompositeViewStore, view_id: str):
    view = store.get(view_id)
    if view is None:
        raise CompositeViewExpired(str(view_id))
    return view
