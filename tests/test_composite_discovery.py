# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for composite measurement discovery.'''

from __future__ import annotations

import tempfile
import unittest
import sqlite3

from pathlib import Path

from fuzzmeter.composite.discovery import discover_measurements
from fuzzmeter.db import ensure_schema, metadata as db_metadata, open_db
from fuzzmeter.db import runs as db_runs


class CompositeDiscoveryTest(unittest.TestCase):
    '''Verify read-only direct run discovery behavior.'''

    def test_discovers_direct_child_measurements_and_invalid_sources(self) -> None:
        '''Only direct child run directories are scanned and invalid DBs are isolated.'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run_db(root / 'run-a', source_id='run-a')
            (root / 'broken').mkdir()
            nested_parent = root / 'nested'
            nested_parent.mkdir()
            _write_run_db(nested_parent / 'run-b', source_id='run-b')

            discovery = discover_measurements(root)

        self.assertEqual(['run-a'], [measurement.key.source_id for measurement in discovery.measurements])
        self.assertEqual(['broken', 'nested'], [source.source_id for source in discovery.invalid_sources])

    def test_incompatible_metadata_table_reports_actionable_error(self) -> None:
        '''Old metadata schemas are reported with a user-facing recovery hint.'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / 'old-run'
            run_dir.mkdir()
            con = sqlite3.connect(run_dir / 'fuzzmeter.db')
            try:
                con.execute('CREATE TABLE metadata(metadata_json TEXT NOT NULL)')
                con.execute('INSERT INTO metadata(metadata_json) VALUES (?)', ('{}',))
                con.commit()
            finally:
                con.close()

            discovery = discover_measurements(root)

        self.assertEqual((), discovery.measurements)
        self.assertEqual(1, len(discovery.invalid_sources))
        self.assertIn('Incompatible metadata table', discovery.invalid_sources[0].error)
        self.assertIn('re-run the measurement', discovery.invalid_sources[0].error)


def _write_run_db(run_dir: Path, *, source_id: str, fuzzer: str = 'libfuzzer') -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with open_db(run_dir / 'fuzzmeter.db') as db:
        ensure_schema(db)
        db_runs.upsert_run(db, run_id=source_id, created_ts=100, config_src='config')
        db_metadata.upsert_metadata(
            db,
            db_metadata.MetadataRecord(
                run_id=source_id,
                fuzzer=fuzzer,
                benchmark='zlib',
                fuzz_target='compress',
                repetitions=1,
                runtime_seconds=60,
                environment_digest='env',
                config_digest='cfg',
                source_digest='src',
                metadata={
                    'environment': {'host': {'system': 'test'}},
                    'config': {'benchmark': 'zlib', 'fuzz_target': 'compress'},
                    'source': {},
                    'digests': {'environment': 'env', 'config': 'cfg', 'source': 'src'},
                },
                created_at=100,
            ),
        )


if __name__ == '__main__':
    unittest.main()
