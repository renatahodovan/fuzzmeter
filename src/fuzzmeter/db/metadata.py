# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Persist composite measurement descriptors in run databases.'''

from __future__ import annotations

import json

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .base import DB
from .fields import json_object

CURRENT_METADATA_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MetadataRecord:
    '''Describe one composite measurement descriptor row.'''

    run_id: str
    fuzzer: str
    benchmark: str
    fuzz_target: str
    repetitions: int
    runtime_seconds: int
    environment_digest: str | None
    config_digest: str | None
    source_digest: str | None
    metadata: dict[str, Any]
    metadata_schema_version: int = CURRENT_METADATA_SCHEMA_VERSION
    created_at: int | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> 'MetadataRecord':
        '''Build a metadata record from its database columns.'''
        return cls(
            run_id=str(row['run_id']),
            fuzzer=str(row['fuzzer']),
            benchmark=str(row['benchmark']),
            fuzz_target=str(row['fuzz_target']),
            repetitions=int(row['repetitions']),
            runtime_seconds=int(row['runtime_seconds']),
            environment_digest=row['environment_digest'],
            config_digest=row['config_digest'],
            source_digest=row['source_digest'],
            metadata=json_object(row['metadata_json']) or {},
            metadata_schema_version=int(row['metadata_schema_version']),
            created_at=None if row['created_at'] is None else int(row['created_at']),
        )


def upsert_metadata(db: DB, record: MetadataRecord) -> None:
    '''Insert or replace one metadata record.'''
    db.exec(
        '''
        INSERT OR REPLACE INTO metadata(
          run_id, fuzzer, benchmark, fuzz_target, metadata_schema_version,
          repetitions, runtime_seconds, environment_digest, config_digest,
          source_digest, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            record.run_id,
            record.fuzzer,
            record.benchmark,
            record.fuzz_target,
            int(record.metadata_schema_version),
            int(record.repetitions),
            int(record.runtime_seconds),
            record.environment_digest,
            record.config_digest,
            record.source_digest,
            json.dumps(record.metadata, sort_keys=True),
            record.created_at,
        ),
    )


def list_metadata(db: DB) -> list[MetadataRecord]:
    '''Return all reusable metadata records from a run database.'''
    return [_row_to_record(row) for row in db.q('SELECT * FROM metadata')]


def _row_to_record(row: dict[str, Any]) -> MetadataRecord:
    metadata_schema_version = int(row['metadata_schema_version'])
    if metadata_schema_version != CURRENT_METADATA_SCHEMA_VERSION:
        raise ValueError(f'Unsupported composite metadata schema version: {metadata_schema_version}.')
    return MetadataRecord(
        run_id=str(row['run_id']),
        fuzzer=str(row['fuzzer']),
        benchmark=str(row['benchmark']),
        fuzz_target=str(row['fuzz_target']),
        metadata_schema_version=metadata_schema_version,
        repetitions=int(row['repetitions']),
        runtime_seconds=int(row['runtime_seconds']),
        environment_digest=row['environment_digest'],
        config_digest=row['config_digest'],
        source_digest=row['source_digest'],
        metadata=json.loads(str(row['metadata_json'])),
        created_at=row['created_at'],
    )
