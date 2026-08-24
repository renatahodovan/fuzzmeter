# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Serve-lifetime registry and temporary composite view store.'''

from __future__ import annotations

import logging
import threading
import time
import uuid

from collections import OrderedDict
from collections.abc import Iterable
from pathlib import Path

from .discovery import discover_measurements
from .models import (
    COMPOSITE_ORIGIN_HISTORICAL,
    CompositeDiscovery,
    CompositeMeasurement,
    CompositeMeasurementKey,
    CompositeSelection,
    CompositeSource,
    CompositeView,
    CompositeViewExpired,
)

DEFAULT_MAX_VIEWS = 50
LOG = logging.getLogger(__name__)


class CompositeRegistry:
    '''Cache discovered composite measurement descriptors for one serve process.'''

    def __init__(self, run_dirs: Iterable[Path]):
        self.run_dirs = tuple(Path(run_dir).resolve() for run_dir in run_dirs)
        self._discovery = CompositeDiscovery()
        self._by_key: dict[CompositeMeasurementKey, CompositeMeasurement] = {}
        self.refresh()

    def refresh(self) -> CompositeDiscovery:
        '''Refresh descriptors from configured run directories.'''
        self._discovery = discover_measurements(self.run_dirs)
        self._by_key = {measurement.key: measurement for measurement in self._discovery.measurements}
        LOG.info(
            'Composite registry refreshed: %d measurements, %d invalid sources',
            len(self._discovery.measurements),
            len(self._discovery.invalid_sources),
        )
        return self._discovery

    def measurements(self) -> tuple[CompositeMeasurement, ...]:
        '''Return discovered measurement descriptors.'''
        return self._discovery.measurements

    def invalid_sources(self) -> tuple[CompositeSource, ...]:
        '''Return invalid discovered sources.'''
        return self._discovery.invalid_sources

    def get(self, key: CompositeMeasurementKey) -> CompositeMeasurement | None:
        '''Return one measurement descriptor by key.'''
        return self._by_key.get(key)


class CompositeViewStore:
    '''Keep temporary composite selections until the serve process exits.'''

    def __init__(self, *, max_views: int = DEFAULT_MAX_VIEWS):
        self.max_views = int(max_views)
        self._views: OrderedDict[str, CompositeView] = OrderedDict()
        self._lock = threading.RLock()

    def create(self, selections: list[CompositeSelection]) -> CompositeView:
        '''Create a new temporary composite view.'''
        with self._lock:
            now = int(time.time())
            view = CompositeView(
                view_id=_new_view_id(),
                selections=tuple(selections),
                created_at=now,
                updated_at=now,
            )
            self._views[view.view_id] = view
            self._enforce_limit()
            return view

    def get(self, view_id: str) -> CompositeView | None:
        '''Return one view and mark it as recently used.'''
        with self._lock:
            view = self._views.get(view_id)
            if view is None:
                return None
            self._views.move_to_end(view_id)
            return view

    def replace(self, view_id: str, selections: list[CompositeSelection]) -> CompositeView:
        '''Replace all selections in an existing view.'''
        with self._lock:
            current = self._require(view_id)
            view = CompositeView(
                view_id=current.view_id,
                selections=tuple(selections),
                created_at=current.created_at,
                updated_at=int(time.time()),
            )
            self._views[view.view_id] = view
            self._views.move_to_end(view.view_id)
            return view

    def add(self, view_id: str, selections: list[CompositeSelection]) -> CompositeView:
        '''Add selections to an existing view, replacing duplicate selection ids.'''
        with self._lock:
            current = self._require(view_id)
            by_id = {selection.selection_id: selection for selection in current.selections}
            for selection in selections:
                by_id[selection.selection_id] = selection
            return self.replace(view_id, list(by_id.values()))

    def remove(self, view_id: str, selection_id: str) -> CompositeView:
        '''Remove one selection from a view.'''
        with self._lock:
            current = self._require(view_id)
            return self.replace(
                view_id,
                [selection for selection in current.selections if selection.selection_id != selection_id],
            )

    def _require(self, view_id: str) -> CompositeView:
        view = self.get(view_id)
        if view is None:
            raise CompositeViewExpired(view_id)
        return view

    def _enforce_limit(self) -> None:
        while len(self._views) > self.max_views:
            self._views.popitem(last=False)


def selection_from_key(
    key: CompositeMeasurementKey,
    *,
    origin: str = COMPOSITE_ORIGIN_HISTORICAL,
    display_fuzzer: str | None = None,
    selection_id: str | None = None,
) -> CompositeSelection:
    '''Create a stable selection for a measurement key.'''
    return CompositeSelection(
        selection_id=selection_id or key.as_id(),
        key=key,
        origin=origin,
        display_fuzzer=display_fuzzer,
    )


def _new_view_id() -> str:
    return uuid.uuid4().hex[:16]
