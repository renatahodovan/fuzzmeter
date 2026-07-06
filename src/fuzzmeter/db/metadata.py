# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Persist reusable measurement metadata records in run databases.'''

from __future__ import annotations

import json

from dataclasses import dataclass
from typing import Any

from .base import DB


@dataclass(frozen=True)
class MetadataRecord:
    '''Describe one reusable measurement metadata row.'''

    run_id: str
    fuzzer: str
    benchmark: str
    fuzz_target: str
    schema_version: int
    repetitions: int
    runtime_seconds: int
    metadata: dict[str, Any]
    created_at: int | None = None


def upsert_metadata(db: DB, record: MetadataRecord) -> None:
    '''Insert or replace one metadata record.'''
    db.exec(
        '''
        INSERT OR REPLACE INTO metadata(
          run_id, fuzzer, benchmark, fuzz_target, schema_version,
          repetitions, runtime_seconds, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            record.run_id,
            record.fuzzer,
            record.benchmark,
            record.fuzz_target,
            int(record.schema_version),
            int(record.repetitions),
            int(record.runtime_seconds),
            json.dumps(record.metadata, sort_keys=True),
            record.created_at,
        ),
    )


def list_metadata(db: DB) -> list[MetadataRecord]:
    '''Return all reusable metadata records from a run database.'''
    return [_row_to_record(row) for row in db.q('SELECT * FROM metadata')]


def get_metadata(
    db: DB,
    *,
    run_id: str,
    fuzzer: str,
    benchmark: str,
    fuzz_target: str,
) -> MetadataRecord | None:
    '''Return one metadata record by its logical key.'''
    row = db.q1(
        '''
        SELECT * FROM metadata
        WHERE run_id = ? AND fuzzer = ? AND benchmark = ? AND fuzz_target = ?
        ''',
        (run_id, fuzzer, benchmark, fuzz_target),
    )
    return _row_to_record(row) if row is not None else None


def _row_to_record(row: dict[str, Any]) -> MetadataRecord:
    return MetadataRecord(
        run_id=str(row['run_id']),
        fuzzer=str(row['fuzzer']),
        benchmark=str(row['benchmark']),
        fuzz_target=str(row['fuzz_target']),
        schema_version=int(row['schema_version']),
        repetitions=int(row['repetitions']),
        runtime_seconds=int(row['runtime_seconds']),
        metadata=json.loads(str(row['metadata_json'])),
        created_at=row['created_at'],
    )
