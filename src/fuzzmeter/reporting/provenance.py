# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.

'''Expose coverage measurement provenance and comparison warnings in reports.'''

from __future__ import annotations

import json

from collections import Counter
from typing import Any

from ..db.snapshot import AggSnapshotRow

_PROFILE_FLAG_FIELDS = ('report_flags', 'branch_export_flags', 'export_flags')


def attach_measurement_provenance(
    *,
    targets: list[dict[str, Any]],
    agg_snapshots: dict[tuple[str, str, str], AggSnapshotRow],
) -> dict[str, Any]:
    '''Attach provenance to coverage rows and return a generated run summary.'''

    records = []
    records_by_target = []
    for target in targets:
        benchmark = str(target.get('benchmark') or '')
        fuzz_target = str(target.get('fuzz_target') or '')
        target_records = []
        for fuzzer in target.get('fuzzers') or []:
            name = str(fuzzer.get('fuzzer') or '')
            row = agg_snapshots.get((name, benchmark, fuzz_target))
            provenance = None if row is None else row.measurement_provenance
            fuzzer['measurement_provenance'] = provenance
            target_records.append((name, provenance))
            records.append(provenance)

        records_by_target.append((target, target_records))

    signatures = [
        signature
        for record in records
        if (signature := _comparison_signature(record)) is not None
    ]
    run_default = Counter(signatures).most_common(1)[0][0] if signatures else None
    for target, target_records in records_by_target:
        target_signatures = {_comparison_signature(record) for _, record in target_records}
        if len(target_records) > 1 and (len(target_signatures) > 1 or None in target_signatures):
            warning = (
                'Coverage rankings and statistical tests combine measurements with '
                'different or unavailable provenance; interpret comparisons cautiously.'
            )
            target['provenance_warning'] = warning
        badges = [
            {
                'fuzzer': name,
                'status': _badge_status(record, run_default),
                'label': _badge_label(record),
            }
            for name, record in target_records
        ]
        if any(badge['status'] != 'consistent' for badge in badges):
            target['provenance_badges'] = badges

    return {
        'schema_version': 1,
        'record_count': len(records),
        'consistency': 'consistent' if _all_same(records) else 'mixed_or_unavailable',
        'warning': (
            None
            if _all_same(records)
            else 'Run-level rankings combine coverage with mixed or unavailable provenance.'
        ),
        'threats_table': _threats_table(records),
    }


def _comparable_record(record: dict[str, Any]) -> dict[str, Any]:
    '''Return the record without the values that differ per fuzzer by construction.

    The profile paths and the replay restart and batch counts are outcomes of measuring
    one fuzzer, not settings shared by the run, so comparing them across fuzzers would
    report every healthy run as mixed.
    '''

    comparable = dict(record)
    if record.get('llvm_cov'):
        comparable['llvm_cov'] = {
            key: (
                [_flag_without_profile_path(flag) for flag in value]
                if key in _PROFILE_FLAG_FIELDS and value is not None
                else value
            )
            for key, value in record['llvm_cov'].items()
        }
    if record.get('measurement'):
        comparable['measurement'] = {
            key: value
            for key, value in record['measurement'].items()
            if key not in ('artificial_restarts', 'batch_size')
        }
    return comparable


def _flag_without_profile_path(flag: Any) -> Any:
    return '-instr-profile' if str(flag).startswith('-instr-profile=') else flag


def _comparison_signature(record: dict[str, Any] | None) -> str | None:
    if not record:
        return None
    record = _comparable_record(record)
    comparable = {
        'schema_version': record.get('schema_version'),
        'counter_update_mode': record.get('requested_counter_update_mode'),
        'branch_definition_version': record.get('branch_definition_version'),
        'branch_counting_definition': record.get('branch_counting_definition'),
        'measurement': record.get('measurement'),
        'clang_version': (record.get('coverage_build') or {}).get('clang_version'),
        'target_image_digest': (record.get('images') or {}).get('target_digest'),
        'llvm_cov': record.get('llvm_cov'),
    }
    return json.dumps(comparable, sort_keys=True, separators=(',', ':'))


def _all_same(records: list[dict[str, Any] | None]) -> bool:
    signatures = {_comparison_signature(record) for record in records}
    return bool(records) and len(signatures) == 1 and None not in signatures


def _badge_status(
    record: dict[str, Any] | None,
    run_default: str | None,
) -> str:
    if record is None:
        return 'unavailable'
    if run_default is None:
        return 'unavailable'
    return 'consistent' if _comparison_signature(record) == run_default else 'deviation'


def _badge_label(record: dict[str, Any] | None) -> str:
    if not record:
        return 'provenance unavailable'
    measurement = record.get('measurement') or {}
    freshness = (record.get('coverage_sets') or {}).get('freshness') or 'unknown set age'
    return f'{measurement.get("mode") or "unknown mode"}; {freshness}'


def _threats_table(records: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    fields = [
        ('validity', lambda item: (item.get('validity') or {}).get('status'), 'Invalid or degraded replay data can bias coverage.'),
        ('validity diagnostics', lambda item: _compact((item.get('validity') or {}).get('diagnostics')), 'Diagnostics explain known losses and degraded measurements.'),
        ('counter update', lambda item: item.get('requested_counter_update_mode'), 'Different counter semantics are not directly comparable.'),
        ('branch definition', lambda item: item.get('branch_definition_version'), 'Different branch populations can change rankings.'),
        ('branch counting', lambda item: item.get('branch_counting_definition'), 'Different scalar definitions can change ranking inputs.'),
        ('measurement mode', lambda item: _compact(item.get('measurement')), 'State, ordering, batching, and restart behavior can change reached coverage.'),
        ('llvm-cov report flags', lambda item: _compact((item.get('llvm_cov') or {}).get('report_flags')), 'Flag changes can select a different source population.'),
        ('llvm-cov branch export flags', lambda item: _compact((item.get('llvm_cov') or {}).get('branch_export_flags')), 'Branch export flags define the scalar population.'),
        ('llvm-cov set export flags', lambda item: _compact((item.get('llvm_cov') or {}).get('export_flags')), 'Set export flags define unique-coverage inputs.'),
        ('clang version', lambda item: (item.get('coverage_build') or {}).get('clang_version'), 'Toolchain changes can alter mappings and totals.'),
        ('image digests', lambda item: _compact(item.get('images')), 'Different binaries invalidate direct coverage comparison.'),
        ('coverage-set age', lambda item: (item.get('coverage_sets') or {}).get('freshness'), 'Carried sets lag behind current scalar coverage.'),
        ('repetitions', lambda item: _compact(item.get('repetitions')), 'Low, unequal, or below-threshold samples weaken statistical claims.'),
        ('input outcomes', lambda item: _compact(item.get('inputs')), 'Timeouts, failures, and batch-mate losses undercount coverage.'),
    ]
    comparable = [None if record is None else _comparable_record(record) for record in records]
    rows = []
    for name, getter, threat in fields:
        values = ['unavailable' if item is None else getter(item) for item in comparable]
        normalized = ['unavailable' if value is None else str(value) for value in values]
        unique = sorted(set(normalized))
        status = (
            'consistent'
            if len(unique) == 1 and unique != ['unavailable']
            else 'mixed_or_unavailable'
        )
        rows.append({
            'field': name,
            'status': status,
            'affected': _is_affected(name, unique, status),
            'values': unique,
            'threat': threat,
        })
    return rows


def _compact(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _is_affected(name: str, values: list[str], status: str) -> bool:
    if status != 'consistent':
        return True
    value = values[0].lower()
    if name == 'validity':
        return value != 'valid'
    if name == 'counter update':
        return value != 'atomic'
    if name == 'coverage-set age':
        return value != 'fresh'
    if name == 'measurement mode':
        return '"mode":"stateless"' not in value
    if name == 'image digests':
        return '"fuzzer_target_digest":null' in value
    if name == 'input outcomes':
        return any(
            f'"{field}":0' not in value
            for field in ('timeout', 'failed', 'missing_profraw', 'profiles_lost_to_batch_mate_crash')
        )
    if name == 'repetitions':
        return '"threshold_met":true' not in value
    return False
