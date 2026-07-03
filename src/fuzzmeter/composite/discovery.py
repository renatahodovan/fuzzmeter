# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Discover composite measurement descriptors in direct run directories.'''

from __future__ import annotations

import logging
import sqlite3

from pathlib import Path

from ..db import metadata as db_metadata
from ..db.base import DB, open_readonly_connection
from .models import (
    CompositeDiscovery,
    CompositeMeasurement,
    CompositeMeasurementKey,
    CompositeSource,
    MetadataTriplet,
)

LOG = logging.getLogger(__name__)


def discover_sources(runs_root: Path) -> list[CompositeSource]:
    '''Return direct child run sources below runs_root.'''
    root = Path(runs_root).resolve()
    if not root.is_dir():
        return []
    sources: list[CompositeSource] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        db_path = path / 'fuzzmeter.db'
        if not db_path.is_file():
            sources.append(
                CompositeSource(
                    source_id=path.name,
                    path=path,
                    db_path=db_path,
                    status='invalid',
                    error='Missing fuzzmeter.db.',
                )
            )
            continue
        sources.append(CompositeSource(source_id=path.name, path=path, db_path=db_path))
    return sources


def discover_measurements(runs_root: Path) -> CompositeDiscovery:
    '''Read all composite descriptors from discovered run sources.'''
    measurements: list[CompositeMeasurement] = []
    invalid_sources: list[CompositeSource] = []
    for source in discover_sources(runs_root):
        if source.status != 'ok':
            invalid_sources.append(source)
            continue
        try:
            measurements.extend(read_measurements(source.db_path, source.source_id))
        except Exception as exc:
            LOG.warning('Skipping invalid composite source %s: %s', source.db_path, exc)
            invalid_sources.append(
                CompositeSource(
                    source_id=source.source_id,
                    path=source.path,
                    db_path=source.db_path,
                    status='invalid',
                    error=str(exc),
                )
            )
    return CompositeDiscovery(measurements=tuple(measurements), invalid_sources=tuple(invalid_sources))


def read_measurements(db_path: Path, source_id: str) -> list[CompositeMeasurement]:
    '''Read descriptor rows from one run database.'''
    con = open_readonly_connection(Path(db_path))
    try:
        try:
            records = db_metadata.list_metadata(DB(con))
        except sqlite3.OperationalError as exc:
            raise ValueError(_metadata_table_error(exc)) from exc
        except (KeyError, IndexError) as exc:
            raise ValueError(
                'Incompatible metadata table created by an older Fuzzmeter version; re-run the measurement.'
            ) from exc
    finally:
        con.close()
    return [
        _record_to_measurement(record, Path(db_path), source_id)
        for record in sorted(records, key=lambda item: (item.run_id, item.benchmark, item.fuzz_target, item.fuzzer))
    ]


def read_measurement(db_path: Path, key: CompositeMeasurementKey) -> CompositeMeasurement | None:
    '''Read one descriptor row by its measurement key.'''
    for measurement in read_measurements(db_path, key.source_id):
        if measurement.key == key:
            return measurement
    return None


def _record_to_measurement(record: db_metadata.MetadataRecord, db_path: Path, source_id: str) -> CompositeMeasurement:
    metadata = MetadataTriplet.from_json(record.metadata)
    if not metadata.environment_digest:
        metadata = MetadataTriplet(
            environment=metadata.environment,
            config=metadata.config,
            source=metadata.source,
            environment_digest=record.environment_digest,
            config_digest=record.config_digest,
            source_digest=record.source_digest,
        )
    key = CompositeMeasurementKey(
        source_id=source_id,
        run_id=record.run_id,
        fuzzer=record.fuzzer,
        benchmark=record.benchmark,
        fuzz_target=record.fuzz_target,
    )
    return CompositeMeasurement(
        key=key,
        source_path=Path(db_path).resolve().parent,
        db_path=Path(db_path).resolve(),
        metadata=metadata,
        runtime_seconds=record.runtime_seconds,
        repetitions=record.repetitions,
        created_at=record.created_at,
    )


def _metadata_table_error(exc: sqlite3.OperationalError) -> str:
    message = str(exc).lower()
    if 'no such table' in message and 'metadata' in message:
        return 'No composite metadata table found; re-run the measurement with a Fuzzmeter version that records composite descriptors.'
    if 'no such column' in message:
        return 'Incompatible metadata table created by an older Fuzzmeter version; re-run the measurement.'
    return f'Cannot read composite metadata: {exc}'
