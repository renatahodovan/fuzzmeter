# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Read and write coverage set artifacts derived from llvm-cov exports.'''

from __future__ import annotations

import base64
import hashlib
import json
import zlib

from functools import lru_cache
from pathlib import Path
from typing import Any

METRICS = ('lines', 'branches', 'functions', 'regions')


class CoverageSetStore:
    '''Convert llvm-cov exports to per-metric coverage set artifacts.'''

    @staticmethod
    def write(path: Path, export_obj: dict[str, Any], summary: dict[str, Any]) -> None:
        '''Write a coverage set artifact.'''
        metrics = {metric: _covered_hashes(export_obj, metric) for metric in METRICS}
        fixed_summary = dict(summary)
        for metric, values in metrics.items():
            fixed_summary[f'cov_{metric}_covered'] = len(values)
        doc = {
            'type': 'fuzzmeter.coverage.sets',
            'summary': fixed_summary,
            'metrics': metrics,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(doc, separators=(',', ':')), encoding='utf-8')

    @staticmethod
    def read(path: Path, metric: str) -> set[str]:
        '''Return covered element hash keys for one metric.'''
        try:
            stat = Path(path).stat()
            return {
                str(value)
                for value in _read_metric(str(Path(path)), int(stat.st_mtime_ns), int(stat.st_size), metric)
            }
        except Exception:
            return set()


def covered_element_keys_from_compact_sets(path: Path, metric: str) -> set[str]:
    '''Return covered element hash keys for a metric from a coverage set artifact.'''
    return CoverageSetStore.read(path, metric)


def coverage_summary_from_export(export_obj: dict[str, Any]) -> dict[str, int | None]:
    '''Return fuzzmeter coverage counters from an llvm-cov export object.'''
    totals = (((export_obj.get('data') or [{}])[0] or {}).get('totals') or {}) if isinstance(export_obj.get('data'), list) else {}
    return {
        key: _nested_int(totals, metric, field)
        for metric in METRICS
        for key, field in ((f'cov_{metric}_total', 'count'), (f'cov_{metric}_covered', 'covered'))
    }


@lru_cache(maxsize=512)
def _read_doc(path: str, mtime_ns: int, size: int) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding='utf-8', errors='replace') or '{}')


@lru_cache(maxsize=1024)
def _read_metric(path: str, mtime_ns: int, size: int, metric: str) -> list[int]:
    doc = _read_doc(path, mtime_ns, size)
    metrics = doc.get('metrics')
    values = metrics.get(metric) if isinstance(metrics, dict) else None
    if isinstance(values, list):
        return [int(value) for value in values]
    if isinstance(values, dict):
        decoded_values = _decode_compact_metric(values)
        if decoded_values is not None:
            return decoded_values
    export_obj = doc.get('export') if isinstance(doc.get('export'), dict) else doc
    return _covered_hashes(export_obj, metric)


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
                hashes.add(_stable_hash(_safe_text(filename, segment[0], None if metric == 'lines' else segment[1])))
        return
    entries = file_item.get('branches') if metric == 'branches' else file_item.get('functions') if metric == 'functions' else []
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
    region_parts = list(regions[0][:4]) if isinstance(regions, list) and regions and _tuple_like(regions[0]) else []
    name = function.get('name') or function.get('demangled') or ordinal
    return _safe_text(_function_filename(default_filename, function), name, *region_parts)


def _function_filename(default_filename: str, function: dict[str, Any]) -> str:
    filenames = function.get('filenames')
    if isinstance(filenames, list) and filenames:
        return str(filenames[0])
    return str(function.get('filename') or default_filename)


def _safe_text(*parts: Any) -> str:
    return ':'.join(str(part).strip() for part in parts if part is not None and str(part).strip())


def _covered_tuple(values: Any, start: int, end: int | None = None) -> bool:
    return _tuple_like(values) and len(values) > start and any(_positive(value) for value in list(values)[start:end])


def _tuple_like(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def _positive(value: Any) -> bool:
    try:
        return float(value) > 0
    except Exception:
        return False


def _stable_hash(value: str) -> int:
    digest = hashlib.blake2b(value.encode('utf-8', errors='replace'), digest_size=8).digest()
    return int.from_bytes(digest, byteorder='big', signed=False)


def _nested_int(data: dict[str, Any], metric: str, key: str) -> int | None:
    try:
        return int((data.get(metric) or {}).get(key))
    except Exception:
        return None


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
        current = int(delta) if not values else current + int(delta)
        values.append(current)
    return values


def _decode_uvarint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    index = int(offset)

    while index < len(data):
        byte = data[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, index
        shift += 7

    raise ValueError('Truncated uvarint payload')
