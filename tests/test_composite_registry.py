# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for composite registry and view storage.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from fuzzmeter.composite import CompositeMeasurementKey
from fuzzmeter.composite.registry import CompositeRegistry, CompositeViewStore, selection_from_key
from tests.support.dbs import measurement_run_db


class CompositeRegistryTest(unittest.TestCase):
    '''Verify serve-lifetime descriptor and view state behavior.'''

    def test_registry_refreshes_discovered_measurements(self) -> None:
        '''Manual refresh picks up direct run directory descriptor changes.'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = CompositeRegistry(root)
            self.assertEqual((), registry.measurements())

            measurement_run_db(root / 'run-a', source_id='run-a')
            registry.refresh()

            self.assertEqual(1, len(registry.measurements()))

    def test_view_store_evicts_oldest_view(self) -> None:
        '''The view store keeps a simple bounded in-memory state.'''
        store = CompositeViewStore(max_views=1)
        key = CompositeMeasurementKey('src', 'run', 'fz', 'bench', 'target')

        first = store.create([selection_from_key(key, selection_id='first')])
        second = store.create([selection_from_key(key, selection_id='second')])

        self.assertIsNone(store.get(first.view_id))
        self.assertIsNotNone(store.get(second.view_id))

    def test_add_and_remove_selection(self) -> None:
        '''Selections can be changed without creating a persistent manifest.'''
        store = CompositeViewStore()
        key = CompositeMeasurementKey('src', 'run', 'fz', 'bench', 'target')
        view = store.create([])

        updated = store.add(view.view_id, [selection_from_key(key)])
        self.assertEqual(1, len(updated.selections))

        updated = store.remove(view.view_id, key.as_id())
        self.assertEqual(0, len(updated.selections))


if __name__ == '__main__':
    unittest.main()
