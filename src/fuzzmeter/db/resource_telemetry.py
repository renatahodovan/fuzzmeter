# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Store per-tick resource telemetry rows.'''

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .base import DB


@dataclass(frozen=True)
class TelemetrySample:
    '''Describe one resource telemetry sample for a trial tick.'''

    trial_id: int
    idx: int
    ts: int
    container_name: str
    cpu_percent: float | None
    memory_usage_bytes: int | None
    memory_limit_bytes: int | None
    memory_percent: float | None
    corpus_disk_usage_bytes: int | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> 'TelemetrySample':
        '''Build a telemetry sample from its database columns.'''
        return cls(
            trial_id=int(row['trial_id']),
            idx=int(row['idx']),
            ts=int(row['ts']),
            container_name=str(row['container_name']),
            cpu_percent=None if row['cpu_percent'] is None else float(row['cpu_percent']),
            memory_usage_bytes=None if row['memory_usage_bytes'] is None else int(row['memory_usage_bytes']),
            memory_limit_bytes=None if row['memory_limit_bytes'] is None else int(row['memory_limit_bytes']),
            memory_percent=None if row['memory_percent'] is None else float(row['memory_percent']),
            corpus_disk_usage_bytes=(
                None if row['corpus_disk_usage_bytes'] is None else int(row['corpus_disk_usage_bytes'])
            ),
        )


def upsert_resource_telemetry(db: DB, sample: TelemetrySample) -> None:
    '''Insert or replace one resource telemetry sample.'''
    db.exec(
        '''
        INSERT OR REPLACE INTO resource_telemetry(
          trial_id, idx, ts, container_name,
          cpu_percent, memory_usage_bytes, memory_limit_bytes, memory_percent,
          corpus_disk_usage_bytes
        )
        VALUES(?,?,?,?,?,?,?,?,?)
        ''',
        (
            sample.trial_id,
            sample.idx,
            sample.ts,
            sample.container_name,
            sample.cpu_percent,
            sample.memory_usage_bytes,
            sample.memory_limit_bytes,
            sample.memory_percent,
            sample.corpus_disk_usage_bytes,
        ),
    )
