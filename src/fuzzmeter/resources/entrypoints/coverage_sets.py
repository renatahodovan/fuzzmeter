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

COVERAGE_METRICS = ('lines', 'branches', 'functions', 'regions')


def coverage_metrics_from_export(export_obj: dict[str, Any]) -> dict[str, list[int]]:
    '''Return per-metric covered element hashes from an llvm-cov export object.'''

    return {metric: _covered_hashes(export_obj, metric) for metric in COVERAGE_METRICS}


def coverage_summary_from_export(
    export_obj: dict[str, Any],
    *,
    metrics: dict[str, list[int]] | None = None,
) -> dict[str, int | None]:
    '''Return fuzzmeter coverage counters from an llvm-cov export object.'''

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

    summary = {
        key: nested_int(totals, metric, field)
        for metric in COVERAGE_METRICS
        for key, field in ((f'cov_{metric}_total', 'count'), (f'cov_{metric}_covered', 'covered'))
    }
    for metric, values in (metrics or {}).items():
        summary[f'cov_{metric}_covered'] = len(values)
    return summary


def read_covered_keys(path: Path, metric: str) -> set[str]:
    '''Read covered element hash keys for one metric from a coverage set artifact.'''

    try:
        doc = json.loads(path.read_text(encoding='utf-8', errors='replace') or '{}')
        return {str(value) for value in _metric_values(doc, metric)}
    except Exception:
        return set()


def write_coverage_sets(path: Path, summary: dict[str, Any], metrics: dict[str, list[int]]) -> None:
    '''Write a compact coverage set artifact.'''

    doc = {
        'version': 1,
        'type': 'fuzzmeter.coverage.sets',
        'encoding': 'blake2b64-delta-uvarint-zlib-base64',
        'metrics': {
            metric: {
                'covered_count': len(metrics.get(metric, [])),
                'total_count': summary.get(f'cov_{metric}_total'),
                'payload': base64.b64encode(
                    zlib.compress(_encode_delta_varints(metrics.get(metric, [])), level=9),
                ).decode('ascii'),
            }
            for metric in COVERAGE_METRICS
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, separators=(',', ':')), encoding='utf-8')


def _metric_values(doc: dict[str, Any], metric: str) -> list[int]:
    metrics = doc.get('metrics')
    if not isinstance(metrics, dict):
        LOG.warning('Coverage set document has no metrics mapping; reading %s as empty.', metric)
        return []

    values = metrics.get(metric)

    if isinstance(values, list):
        return [int(value) for value in values]

    if isinstance(values, dict):
        decoded_values = _decode_compact_metric(values)
        if decoded_values is not None:
            return decoded_values
        LOG.warning('Could not decode the compact coverage set of %s; reading it as empty.', metric)
        return []

    # write_coverage_sets always emits every COVERAGE_METRICS entry, and an empty
    # metric still decodes to an empty list, so reaching here means a broken file.
    LOG.warning('Coverage set of %s is missing or has type %s; reading it as empty.', metric, type(values).__name__)
    return []


def _covered_hashes(export_obj: dict[str, Any], metric: str) -> list[int]:
    hashes: set[int] = set()
    for data_item in export_obj.get('data') or []:
        if not isinstance(data_item, dict):
            continue
        for file_item in data_item.get('files') or []:
            _collect_file_hashes(hashes, file_item, metric)
        if metric == 'functions':
            for ordinal, function in enumerate(data_item.get('functions') or []):
                if _function_covered(function):
                    hashes.add(_stable_hash(_function_key('', function, ordinal)))
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
    entries = {'branches': file_item.get('branches'), 'functions': file_item.get('functions')}.get(metric, [])
    for ordinal, entry in enumerate(entries or []):
        if metric == 'branches' and _covered_tuple(entry, 4, 6):
            hashes.add(_stable_hash(_safe_text(filename, *list(entry)[:4], ordinal)))
        elif metric == 'functions' and _function_covered(entry):
            hashes.add(_stable_hash(_function_key(filename, entry, ordinal)))


def _function_covered(function: Any) -> bool:
    if not isinstance(function, dict):
        return False
    return _positive(function.get('count')) or any(
        _covered_tuple(region, 4)
        for region in function.get('regions') or []
    )


def _function_key(default_filename: str, function: Any, ordinal: int) -> str:
    regions = function.get('regions') if isinstance(function, dict) else None
    region_parts = (
        list(regions[0][:4])
        if isinstance(regions, list) and regions and isinstance(regions[0], (list, tuple))
        else []
    )
    name = function.get('name') or function.get('demangled') or ordinal
    filenames = function.get('filenames')
    filename = (
        str(filenames[0])
        if isinstance(filenames, list) and filenames
        else str(function.get('filename') or default_filename)
    )
    return _safe_text(filename, name, *region_parts)


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
        return False
    return any(_positive(value) for value in values[start:end])


def _positive(value: Any) -> bool:
    try:
        return float(value) > 0
    except Exception:
        return False


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
