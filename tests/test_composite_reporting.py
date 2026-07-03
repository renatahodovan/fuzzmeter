# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for composite report payload assembly.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from fuzzmeter.composite import (
    COMPOSITE_ORIGIN_FRESH,
    COMPOSITE_ORIGIN_HISTORICAL,
    CompositeMeasurement,
    CompositeMeasurementKey,
    MetadataTriplet,
)
from fuzzmeter.composite.registry import selection_from_key
from fuzzmeter.reporting.composite import build_composite_payload
from tests.test_reporting_payload import _build_run_fixture


class CompositeReportingTest(unittest.TestCase):
    '''Verify selected measurements render as full report series.'''

    def test_build_composite_payload_merges_selected_series(self) -> None:
        '''Two selected run series appear together under one target.'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_a = root / 'run-a'
            run_b = root / 'run-b'
            run_a.mkdir()
            run_b.mkdir()
            _build_run_fixture(run_a)
            _build_run_fixture(run_b)

            first = _measurement(run_a, source_id='run-a')
            second = _measurement(run_b, source_id='run-b')
            payload = build_composite_payload(
                [
                    (selection_from_key(first.key, origin=COMPOSITE_ORIGIN_FRESH), first),
                    (selection_from_key(second.key, origin=COMPOSITE_ORIGIN_HISTORICAL), second),
                ]
            )

        self.assertEqual(1, len(payload['targets']))
        self.assertEqual(['fz', 'fz #2'], [entry['fuzzer'] for entry in payload['targets'][0]['fuzzers']])
        self.assertEqual(['fresh', 'historical'], [source['origin'] for source in payload['sources']])
        self.assertNotIn('source', payload['sources'][0])
        self.assertEqual(first.key.as_id(), payload['sources'][0]['selection_id'])
        self.assertEqual(['run-a:1', 'run-b:1'], [trial['trial_id'] for trial in payload['trials']])
        self.assertTrue(payload['targets'][0]['relbug_matrix']['has_data'] is False)


def _measurement(run_dir: Path, *, source_id: str) -> CompositeMeasurement:
    key = CompositeMeasurementKey(
        source_id=source_id,
        run_id='run',
        fuzzer='fz',
        benchmark='bench',
        fuzz_target='target',
    )
    return CompositeMeasurement(
        key=key,
        source_path=run_dir,
        db_path=run_dir / 'fuzzmeter.db',
        metadata=MetadataTriplet(config={'benchmark': 'bench', 'fuzz_target': 'target'}),
        runtime_seconds=60,
        repetitions=1,
    )


if __name__ == '__main__':
    unittest.main()
