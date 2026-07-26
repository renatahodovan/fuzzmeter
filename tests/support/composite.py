'''Build composite measurements with stable test defaults.'''

from __future__ import annotations

from pathlib import Path
from typing import Any

from fuzzmeter.composite import CompositeMeasurement, CompositeMeasurementKey, MetadataTriplet


def make_measurement(**overrides: Any) -> CompositeMeasurement:
    '''Build a composite measurement while exposing meaningful test differences.'''
    source_id = overrides.pop('source_id', 'source')
    run_id = overrides.pop('run_id', 'run')
    fuzzer = overrides.pop('fuzzer', 'fz')
    benchmark = overrides.pop('benchmark', 'bench')
    fuzz_target = overrides.pop('fuzz_target', 'target')
    source_path = overrides.pop('source_path', Path('/runs') / source_id)
    metadata = overrides.pop('metadata', None)
    if metadata is None:
        metadata = MetadataTriplet(
            environment=overrides.pop('environment', {}),
            config=overrides.pop(
                'config',
                {'benchmark': benchmark, 'fuzz_target': fuzz_target},
            ),
            source=overrides.pop(
                'source',
                {
                    'target_source': {'status': 'ok', 'data': {'revision': 'target'}},
                    'fuzzer_version': {'status': 'ok', 'data': {'revision': 'fuzzer'}},
                },
            ),
        )
    values = {
        'key': CompositeMeasurementKey(
            source_id=source_id,
            run_id=run_id,
            fuzzer=fuzzer,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
        ),
        'source_path': source_path,
        'db_path': source_path / 'fuzzmeter.db',
        'metadata': metadata,
        'runtime_seconds': 3600,
        'repetitions': 3,
        'created_at': None,
        'tags': (),
        'display_name': None,
    }
    values.update(overrides)
    return CompositeMeasurement(**values)
