# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Read, write, and derive compact coverage set artifacts.'''

from __future__ import annotations

import base64
import hashlib
import json
import logging
import zlib

from pathlib import Path
from typing import Any, Iterable

LOG = logging.getLogger(__name__)

# This module also runs as a flat script inside the coverage container, where
# the fuzzmeter package is deliberately absent, so it keeps its own copy of the
# metric names instead of importing reporting.keys. A drift check in
# tests/test_coverage_worker.py keeps the two in step.
COVERAGE_METRICS = ('branches', 'lines', 'functions', 'regions')
COVERAGE_BUILD_METADATA_PATH = Path('/opt/fuzzmeter/meta/coverage-build.json')
COVERAGE_SETS_VERSION = 5
MEASUREMENT_PROVENANCE_VERSION = 2
REPORT_SCALAR_DEFINITION = 'llvm-cov-report-total'
BRANCH_SCALAR_DEFINITION = 'llvm-cov-export-per-instantiation-branches'
EXPORT_SUMMARY_DEFINITION = 'llvm-cov-export-totals'
SET_DEFINITIONS = {
    'branches': 'hashed-covered-branch-directions-by-mangled-function',
    'lines': 'hashed-covered-segment-start-lines',
    'functions': 'hashed-covered-functions',
    'regions': 'hashed-covered-segment-start-regions',
}


def coverage_metrics_from_export(export_obj: dict[str, Any]) -> dict[str, list[int]]:
    '''Return per-metric covered element hashes from an llvm-cov export object.'''

    return {metric: _covered_hashes(export_obj, metric) for metric in COVERAGE_METRICS}


def coverage_summary_from_export(
    export_obj: dict[str, Any],
) -> dict[str, int | None]:
    '''Return the summary counters reported by an llvm-cov export object.'''

    def nested_int(data: dict[str, Any], metric: str, key: str) -> int | None:
        metric_data = data.get(metric)
        if not isinstance(metric_data, dict):
            return None
        try:
            return int(metric_data.get(key))
        except Exception:
            return None

    data_items = export_obj.get('data')
    first_data = data_items[0] if isinstance(data_items, list) and data_items else {}
    totals = first_data.get('totals') if isinstance(first_data, dict) else {}
    if not isinstance(totals, dict):
        totals = {}

    return {
        key: nested_int(totals, metric, field)
        for metric in COVERAGE_METRICS
        for key, field in ((f'cov_{metric}_total', 'count'), (f'cov_{metric}_covered', 'covered'))
    }


def branch_summary_from_export(export_obj: dict[str, Any]) -> dict[str, int]:
    '''Count branch directions independently in every exported function record.'''

    covered = 0
    total = 0
    for data_item in export_obj.get('data') or []:
        if not isinstance(data_item, dict):
            raise ValueError('llvm-cov data record must be a mapping')
        for function in data_item.get('functions') or []:
            if not isinstance(function, dict):
                raise ValueError('llvm-cov function record must be a mapping')
            for branch in function.get('branches') or []:
                if not isinstance(branch, (list, tuple)) or len(branch) < 6:
                    raise ValueError('llvm-cov branch record is malformed')
                total += 2
                covered += int(_positive(branch[4])) + int(_positive(branch[5]))
    return {
        'cov_branches_covered': covered,
        'cov_branches_total': total,
    }


def read_covered_keys(path: Path, metric: str) -> set[str] | None:
    '''Read covered element hash keys for one metric from a coverage set artifact.'''

    try:
        doc = json.loads(path.read_text(encoding='utf-8', errors='replace') or '{}')
        if doc.get('version') != COVERAGE_SETS_VERSION or doc.get('type') != 'fuzzmeter.coverage.sets':
            LOG.warning(
                'Unsupported coverage set artifact version or type in %s: version=%r, type=%r.',
                path,
                doc.get('version'),
                doc.get('type'),
            )
            return None
        values = _metric_values(doc, metric)
        return {str(value) for value in values} if values is not None else None
    except Exception:
        LOG.warning('Could not read coverage set artifact %s.', path, exc_info=True)
        return None


def write_coverage_sets(
    path: Path,
    report_summary: dict[str, Any],
    export_summary: dict[str, Any],
    metrics: dict[str, list[int]],
    *,
    branch_summary: dict[str, Any] | None = None,
    report_flags: list[str] | None = None,
    branch_export_flags: list[str] | None = None,
    export_flags: list[str] | None = None,
    measurement_context: dict[str, Any] | None = None,
) -> None:
    '''Write a compact coverage set artifact.'''

    measurement_provenance = build_measurement_provenance(
        report_flags=report_flags,
        branch_export_flags=branch_export_flags,
        export_flags=export_flags,
        measurement_context=measurement_context,
    )

    doc = {
        'version': COVERAGE_SETS_VERSION,
        'type': 'fuzzmeter.coverage.sets',
        'encoding': 'blake2b64-delta-uvarint-zlib-base64',
        'measurement_provenance': measurement_provenance,
        'metrics': {
            metric: {
                'authoritative_scalar': {
                    'definition': (
                        BRANCH_SCALAR_DEFINITION
                        if metric == 'branches'
                        else REPORT_SCALAR_DEFINITION
                    ),
                    'covered_count': (
                        branch_summary or {}
                        if metric == 'branches'
                        else report_summary
                    ).get(f'cov_{metric}_covered'),
                    'total_count': (
                        branch_summary or {}
                        if metric == 'branches'
                        else report_summary
                    ).get(f'cov_{metric}_total'),
                },
                'report_scalar': {
                    'definition': REPORT_SCALAR_DEFINITION,
                    'covered_count': report_summary.get(f'cov_{metric}_covered'),
                    'total_count': report_summary.get(f'cov_{metric}_total'),
                },
                'export_summary': {
                    'definition': EXPORT_SUMMARY_DEFINITION,
                    'covered_count': export_summary.get(f'cov_{metric}_covered'),
                    'total_count': export_summary.get(f'cov_{metric}_total'),
                },
                'element_set': {
                    'definition': SET_DEFINITIONS[metric],
                    'element_count': len(metrics.get(metric, [])),
                    'payload': base64.b64encode(
                        zlib.compress(_encode_delta_varints(metrics.get(metric, [])), level=9),
                    ).decode('ascii'),
                },
            }
            for metric in COVERAGE_METRICS
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, separators=(',', ':')), encoding='utf-8')


def build_measurement_provenance(
    *,
    report_flags: list[str] | None,
    branch_export_flags: list[str] | None,
    export_flags: list[str] | None,
    measurement_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    '''Build the versioned provenance record shared by scalar and set coverage.'''

    try:
        build_metadata = json.loads(COVERAGE_BUILD_METADATA_PATH.read_text(encoding='utf-8'))
        requested_cflags = build_metadata['requested_cflags']
        requested_cxxflags = build_metadata['requested_cxxflags']
        clang_version = build_metadata['clang_version']
        if not all(isinstance(value, str) for value in (requested_cflags, requested_cxxflags, clang_version)):
            raise TypeError('coverage build metadata fields must be strings')
        requested_flags = [*requested_cflags.split(), *requested_cxxflags.split()]
        profile_update_modes = [
            flag.partition('=')[2]
            for flag in requested_flags
            if flag.startswith('-fprofile-update=') and flag.partition('=')[2]
        ]
        if profile_update_modes:
            requested_counter_update_mode = profile_update_modes[-1]
            requested_counter_update_mode_source = 'explicit_flag'
        else:
            requested_counter_update_mode = 'single'
            requested_counter_update_mode_source = 'clang_default'
        measurement_provenance: dict[str, Any] = {
            'schema_version': MEASUREMENT_PROVENANCE_VERSION,
            'requested_counter_update_mode': requested_counter_update_mode,
            'requested_counter_update_mode_source': requested_counter_update_mode_source,
            'coverage_build': {
                'status': 'recorded',
                'cflags': requested_cflags,
                'cxxflags': requested_cxxflags,
                'clang_version': clang_version,
            },
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        LOG.warning('Coverage build provenance is unavailable from %s: %s', COVERAGE_BUILD_METADATA_PATH, exc)
        measurement_provenance = {
            'schema_version': MEASUREMENT_PROVENANCE_VERSION,
            'requested_counter_update_mode': 'unknown',
            'requested_counter_update_mode_source': 'unavailable',
            'coverage_build': {
                'status': 'unknown',
                'cflags': None,
                'cxxflags': None,
                'clang_version': None,
            },
        }

    measurement_provenance['llvm_cov'] = {
        'report_flags': list(report_flags) if report_flags is not None else None,
        'branch_export_flags': list(branch_export_flags) if branch_export_flags is not None else None,
        'export_flags': list(export_flags) if export_flags is not None else None,
        'branch_population_aligned': (
            report_flags is not None
            and branch_export_flags is not None
            and report_flags == branch_export_flags
        ),
        'populations_aligned': (
            report_flags is not None
            and export_flags is not None
            and report_flags == export_flags
        ),
        'population_note': (
            'The export uses a filtered function and expansion population; '
            'its summaries and hashed element sets are not interchangeable with report scalars.'
        ),
    }
    context = measurement_context if isinstance(measurement_context, dict) else {}
    measurement_provenance.update({
        'branch_definition_version': COVERAGE_SETS_VERSION,
        'branch_counting_definition': BRANCH_SCALAR_DEFINITION,
        'measurement': context.get('measurement') or {
            'mode': 'unknown',
            'batch_size': None,
            'ordering': 'unknown',
            'artificial_restarts': None,
        },
        'validity': context.get('validity') or {
            'status': 'degraded',
            'diagnostics': ['measurement context unavailable'],
        },
        'repetitions': context.get('repetitions') or {
            'n': None,
            'threshold': None,
            'threshold_met': None,
        },
        'images': context.get('images') or {
            'coverage': None,
            'fuzzer_target_digest': None,
            'digest_scope': 'combined-fuzzer-target-coverage-image',
            'fuzzer_digest': None,
            'target_digest': None,
        },
        'inputs': context.get('inputs') or {
            'scope': 'unavailable',
            'status_counts': {
                'ok': 0,
                'timeout': 0,
                'failed': 0,
                'missing_profraw': 0,
            },
            'profiles_lost_to_batch_mate_crash': 0,
        },
        'coverage_sets': context.get('coverage_sets') or {
            'freshness': 'unavailable',
            'source_tick': None,
            'source_profdata_sha256': None,
        },
    })
    return measurement_provenance


def _metric_values(doc: dict[str, Any], metric: str) -> list[int] | None:
    metrics = doc.get('metrics')
    if not isinstance(metrics, dict):
        LOG.warning('Coverage set document has no metrics mapping; %s is unknown.', metric)
        return None

    metric_data = metrics.get(metric)
    if isinstance(metric_data, dict):
        element_set = metric_data.get('element_set')
        decoded_values = _decode_compact_metric(element_set) if isinstance(element_set, dict) else None
        if decoded_values is not None:
            return decoded_values
        LOG.warning('Could not decode the compact coverage set of %s; treating it as unknown.', metric)
        return None

    # write_coverage_sets always emits every COVERAGE_METRICS entry, and an empty
    # metric still decodes to an empty list, so reaching here means a broken file.
    LOG.warning(
        'Coverage set of %s is missing or has type %s; treating it as unknown.',
        metric,
        type(metric_data).__name__,
    )
    return None


def _covered_hashes(export_obj: dict[str, Any], metric: str) -> list[int]:
    hashes: set[int] = set()
    for data_item in export_obj.get('data') or []:
        if not isinstance(data_item, dict):
            continue
        for file_item in data_item.get('files') or []:
            _collect_file_hashes(hashes, file_item, metric)
        if metric in {'branches', 'functions'}:
            for function in data_item.get('functions') or []:
                if _function_covered(function):
                    if metric == 'functions':
                        hashes.add(_stable_hash(_function_key(function)))
                    else:
                        _collect_function_branch_hashes(hashes, function)
    return sorted(hashes)


def _collect_file_hashes(hashes: set[int], file_item: Any, metric: str) -> None:
    if not isinstance(file_item, dict):
        return

    filename = str(file_item.get('filename') or '')
    if not filename:
        return

    if metric in {'lines', 'regions'}:
        for segment in file_item.get('segments') or []:
            if _covered_tuple(segment, 2):
                hashes.add(
                    _stable_hash(
                        _safe_text(filename, segment[0], None if metric == 'lines' else segment[1]),
                    )
                )
        return


def _collect_function_branch_hashes(hashes: set[int], function: Any) -> None:
    if not isinstance(function, dict):
        raise ValueError('llvm-cov function record must be a mapping')

    function_key = _function_key(function)
    filenames = function.get('filenames')
    if not isinstance(filenames, list) or not filenames:
        raise ValueError('llvm-cov function record must define non-empty filenames')
    for branch in function.get('branches') or []:
        if not isinstance(branch, (list, tuple)) or len(branch) < 7:
            raise ValueError('llvm-cov branch record is malformed')
        try:
            filename = str(filenames[int(branch[6])])
        except (IndexError, TypeError, ValueError):
            filename = str(filenames[0])
        branch_key = _safe_text(function_key, filename, *branch[:4])
        if _positive(branch[4]):
            hashes.add(_stable_hash(f'{branch_key}:true'))
        if _positive(branch[5]):
            hashes.add(_stable_hash(f'{branch_key}:false'))


def _function_covered(function: Any) -> bool:
    if not isinstance(function, dict):
        raise ValueError('llvm-cov function record must be a mapping')
    return _positive(function.get('count')) or any(
        _covered_tuple(region, 4)
        for region in function.get('regions') or []
    )


def _function_key(function: dict[str, Any]) -> str:
    regions = function.get('regions')
    region_parts = (
        list(regions[0][:4])
        if isinstance(regions, list) and regions and isinstance(regions[0], (list, tuple))
        else []
    )
    name = function.get('name') or function.get('demangled')
    filenames = function.get('filenames')
    if not name or not isinstance(filenames, list) or not filenames:
        raise ValueError('llvm-cov function identity is missing its name or filename')
    return _safe_text(filenames[0], name, *region_parts)


def _safe_text(*parts: Any) -> str:
    out = []
    for part in parts:
        if part is None:
            continue
        text = str(part).strip()
        if text:
            out.append(text)
    return ':'.join(out)


def _covered_tuple(values: Any, start: int, end: int | None = None) -> bool:
    if not isinstance(values, (list, tuple)) or len(values) <= start:
        raise ValueError('llvm-cov coverage tuple is malformed')
    return any(_positive(value) for value in values[start:end])


def _positive(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError) as exc:
        raise ValueError(f'llvm-cov count is not numeric: {value!r}') from exc


def _stable_hash(value: str) -> int:
    digest = hashlib.blake2b(value.encode('utf-8', errors='replace'), digest_size=8).digest()
    return int.from_bytes(digest, byteorder='big', signed=False)


def _decode_compact_metric(metric_data: dict[str, Any]) -> list[int] | None:
    payload = metric_data.get('payload')
    if not isinstance(payload, str) or not payload:
        return None

    try:
        compressed = base64.b64decode(payload)
        raw = zlib.decompress(compressed)
    except Exception:
        return None

    values: list[int] = []
    current = 0
    offset = 0
    while offset < len(raw):
        delta, offset = _decode_uvarint(raw, offset)
        current = delta if not values else current + delta
        values.append(current)
    return values


def _decode_uvarint(data: bytes, offset: int) -> tuple[int, int]:
    value, shift = 0, 0

    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7

    raise ValueError('Truncated uvarint payload')


def _encode_uvarint(value: int) -> bytes:
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _encode_delta_varints(values: Iterable[int]) -> bytes:
    payload = bytearray()
    prev = None
    for value in values:
        payload.extend(_encode_uvarint(value if prev is None else value - prev))
        prev = value
    return bytes(payload)
