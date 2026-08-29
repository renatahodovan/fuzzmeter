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
            cpu_percent=_optional_float(row['cpu_percent']),
            memory_usage_bytes=_optional_int(row['memory_usage_bytes']),
            memory_limit_bytes=_optional_int(row['memory_limit_bytes']),
            memory_percent=_optional_float(row['memory_percent']),
            corpus_disk_usage_bytes=_optional_int(row['corpus_disk_usage_bytes']),
        )


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


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
            int(sample.trial_id),
            int(sample.idx),
            int(sample.ts),
            str(sample.container_name),
            sample.cpu_percent,
            sample.memory_usage_bytes,
            sample.memory_limit_bytes,
            sample.memory_percent,
            sample.corpus_disk_usage_bytes,
        ),
    )
