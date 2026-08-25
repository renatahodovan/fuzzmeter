# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for composite measurement compatibility signals.'''

from __future__ import annotations

import unittest

from pathlib import Path

from fuzzmeter.composite import (
    COMPATIBLE,
    COMPOSITE_ORIGIN_FRESH,
    INCOMPATIBLE,
    RISKY,
    CompositeMeasurement,
    MetadataTriplet,
    compare_metadata,
)
from fuzzmeter.composite.registry import selection_from_key
from fuzzmeter.web.services.composite_service import _compatibility_for
from tests.support.composite import make_measurement

_MEASUREMENT_CONFIG = {
    'benchmark': 'bench',
    'fuzz_target': 'target',
    'input_mode': 'file',
    'timeout': 1.0,
}


class CompositeCompatibilityTest(unittest.TestCase):
    '''Verify the user-informing composite compatibility policy.'''

    def test_matching_triplets_are_compatible(self) -> None:
        '''Identical metadata has no risk signals.'''
        metadata = _metadata()

        result = compare_metadata(metadata, metadata)

        self.assertEqual(COMPATIBLE, result.level)
        self.assertEqual((), result.issues)

    def test_environment_diff_is_risky(self) -> None:
        '''Environment differences inform the user without blocking selection.'''
        result = compare_metadata(
            _metadata(environment={'host': {'kernel': '6.8'}}),
            _metadata(environment={'host': {'kernel': '6.9'}}),
        )

        self.assertEqual(RISKY, result.level)
        self.assertEqual('environment', result.issues[0].domain)
        self.assertEqual({'reference': '6.8', 'candidate': '6.9'}, result.environment_diff['host']['kernel'])

    def test_source_missing_is_risky(self) -> None:
        '''Missing user source metadata is a visible risk, not an incompatibility.'''
        result = compare_metadata(_metadata(source={}), _metadata())

        self.assertEqual(RISKY, result.level)
        self.assertEqual('source', result.issues[0].domain)
        self.assertEqual('present', result.diffs[0]['candidate'])

    def test_target_mismatch_is_incompatible(self) -> None:
        '''Different target identity is a hard incompatibility.'''
        result = compare_metadata(_metadata(), _metadata(config={'benchmark': 'zlib', 'fuzz_target': 'inflate'}))

        self.assertEqual(INCOMPATIBLE, result.level)
        self.assertEqual('config', result.issues[0].domain)

    def test_target_runtime_config_mismatch_is_incompatible(self) -> None:
        '''Different input mode or per-test timeout is a hard incompatibility.'''
        cases = [
            {'benchmark': 'zlib', 'fuzz_target': 'compress', 'input_mode': 'stdin', 'timeout': 1.0},
            {'benchmark': 'zlib', 'fuzz_target': 'compress', 'input_mode': 'file', 'timeout': 2.0},
        ]

        for config in cases:
            with self.subTest(config=config):
                result = compare_metadata(_metadata(), _metadata(config=config))

                self.assertEqual(INCOMPATIBLE, result.level)
                self.assertEqual('config', result.issues[0].domain)

    def test_fuzzer_source_metadata_is_not_a_compatibility_input(self) -> None:
        '''Different fuzzer source metadata alone is provenance, not risk.'''
        result = compare_metadata(
            _metadata(source=_source(target_revision='abc', fuzzer_revision='afl')),
            _metadata(source=_source(target_revision='abc', fuzzer_revision='grafl')),
        )

        self.assertEqual(COMPATIBLE, result.level)

    def test_benchmark_source_metadata_is_compared(self) -> None:
        '''Target source metadata differences are visible risk signals.'''
        result = compare_metadata(
            _metadata(source=_source(target_revision='abc', fuzzer_revision='same')),
            _metadata(source=_source(target_revision='def', fuzzer_revision='same')),
        )

        self.assertEqual(RISKY, result.level)
        self.assertEqual('source', result.issues[0].domain)
        self.assertEqual('benchmark_source.revision', result.diffs[0]['path'])

    def test_fresh_target_reference_is_preferred(self) -> None:
        '''Fresh measurements are the target reference for historical rows.'''
        fresh = make_measurement(
            source_id='fresh',
            source_path=Path('/tmp/fresh'),
            metadata=_metadata(environment={'host': {'kernel': '6.8'}}, config=_MEASUREMENT_CONFIG),
            runtime_seconds=0,
            repetitions=0,
            tags=(COMPOSITE_ORIGIN_FRESH,),
        )
        historical = make_measurement(
            source_id='hist',
            source_path=Path('/tmp/hist'),
            metadata=_metadata(environment={'host': {'kernel': '6.9'}}, config=_MEASUREMENT_CONFIG),
            runtime_seconds=0,
            repetitions=0,
            tags=('historical',),
        )

        result = _compatibility_for(_entries(fresh, historical), historical)

        self.assertEqual(RISKY, result['level'])
        self.assertEqual('fresh', result['reference']['source_id'])
        self.assertEqual('environment', result['diffs'][0]['domain'])

    def test_historical_target_reference_falls_back_to_first_selection(self) -> None:
        '''Historical-only comparisons use the first same-target selection as reference.'''
        first = make_measurement(
            source_id='hist-a',
            source_path=Path('/tmp/hist-a'),
            metadata=_metadata(environment={'host': {'kernel': '6.8'}}, config=_MEASUREMENT_CONFIG),
            runtime_seconds=0,
            repetitions=0,
            tags=('historical',),
        )
        second = make_measurement(
            source_id='hist-b',
            source_path=Path('/tmp/hist-b'),
            metadata=_metadata(environment={'host': {'kernel': '6.9'}}, config=_MEASUREMENT_CONFIG),
            runtime_seconds=0,
            repetitions=0,
            tags=('historical',),
        )

        result = _compatibility_for(_entries(first, second), second)

        self.assertEqual(RISKY, result['level'])
        self.assertEqual('hist-a', result['reference']['source_id'])

    def test_cross_fuzzer_source_metadata_does_not_make_candidate_risky(self) -> None:
        '''Fuzzer metadata differences do not create risk signals.'''
        fresh = make_measurement(
            source_id='fresh',
            source_path=Path('/tmp/fresh'),
            fuzzer='afl',
            metadata=_metadata(
                config=_MEASUREMENT_CONFIG,
                source=_source(target_revision='abc', fuzzer_revision='afl'),
            ),
            runtime_seconds=0,
            repetitions=0,
            tags=(COMPOSITE_ORIGIN_FRESH,),
        )
        historical = make_measurement(
            source_id='hist',
            source_path=Path('/tmp/hist'),
            fuzzer='grafl',
            metadata=_metadata(
                config=_MEASUREMENT_CONFIG,
                source=_source(target_revision='abc', fuzzer_revision='grafl'),
            ),
            runtime_seconds=0,
            repetitions=0,
            tags=('historical',),
        )

        result = _compatibility_for(_entries(fresh, historical), historical)

        self.assertEqual(COMPATIBLE, result['level'])
        self.assertNotIn('fuzzer_reference', result)
        self.assertEqual('', result['comparison_note'])

    def test_no_external_reference_is_reported_as_note(self) -> None:
        '''A single measurement has no external comparison basis.'''
        measurement = make_measurement(
            source_id='only',
            source_path=Path('/tmp/only'),
            metadata=_metadata(config=_MEASUREMENT_CONFIG),
            runtime_seconds=0,
            repetitions=0,
            tags=('historical',),
        )

        result = _compatibility_for(_entries(measurement), measurement)

        self.assertEqual(COMPATIBLE, result['level'])
        self.assertIsNone(result['reference'])
        self.assertEqual('No external comparison reference.', result['comparison_note'])


def _metadata(
    *,
    environment: dict | None = None,
    config: dict | None = None,
    source: dict | None = None,
) -> MetadataTriplet:
    return MetadataTriplet(
        environment=environment or {'host': {'kernel': '6.8'}},
        config=config or {'benchmark': 'zlib', 'fuzz_target': 'compress', 'input_mode': 'file', 'timeout': 1.0},
        source=source
        if source is not None
        else {
            'benchmark_source': {'status': 'ok', 'data': {'revision': 'abc'}},
            'fuzzer_version': {'status': 'ok', 'data': {'revision': 'def'}},
        },
    )


def _source(*, target_revision: str = 'abc', fuzzer_revision: str = 'def') -> dict:
    return {
        'benchmark_source': {'status': 'ok', 'data': {'revision': target_revision}},
        'fuzzer_version': {'status': 'ok', 'data': {'revision': fuzzer_revision}},
    }


def _entries(*measurements: CompositeMeasurement):
    return [
        (
            selection_from_key(measurement.key, origin=measurement.tags[0] if measurement.tags else 'historical'),
            measurement,
        )
        for measurement in measurements
    ]


if __name__ == '__main__':
    unittest.main()
