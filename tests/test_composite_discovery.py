# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for composite measurement discovery.'''

from __future__ import annotations

import sqlite3
import tempfile
import unittest

from pathlib import Path

from fuzzmeter.composite.discovery import discover_measurements
from tests.support.dbs import measurement_run_db


class CompositeDiscoveryTest(unittest.TestCase):
    '''Verify read-only direct run discovery behavior.'''

    def test_discovers_explicit_measurements_and_invalid_sources(self) -> None:
        '''Configured run directories are scanned and invalid DBs are isolated.'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            measurement_run_db(root / 'run-a', source_id='run-a')
            (root / 'broken').mkdir()
            nested_parent = root / 'nested'
            nested_parent.mkdir()
            measurement_run_db(nested_parent / 'run-b', source_id='run-b')

            discovery = discover_measurements([root / 'run-a', root / 'broken', nested_parent])

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

            discovery = discover_measurements([run_dir])

        self.assertEqual((), discovery.measurements)
        self.assertEqual(1, len(discovery.invalid_sources))
        self.assertIn('Incompatible metadata table', discovery.invalid_sources[0].error)
        self.assertIn('re-run the measurement', discovery.invalid_sources[0].error)

    def test_unsupported_metadata_schema_version_is_invalid_source(self) -> None:
        '''Unsupported explicit metadata versions are reported instead of guessed from columns.'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            measurement_run_db(root / 'future-run', source_id='future-run')
            with sqlite3.connect(root / 'future-run' / 'fuzzmeter.db') as con:
                con.execute('UPDATE metadata SET metadata_schema_version=?', (999,))
                con.commit()

            discovery = discover_measurements([root / 'future-run'])

        self.assertEqual((), discovery.measurements)
        self.assertEqual(1, len(discovery.invalid_sources))
        self.assertIn('Unsupported composite metadata schema version: 999', discovery.invalid_sources[0].error)


if __name__ == '__main__':
    unittest.main()
