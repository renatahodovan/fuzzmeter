# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Store per-tick resource telemetry rows.'''

from __future__ import annotations

from .base import DB


def upsert_resource_telemetry(
    db: DB,
    *,
    trial_row_id: int,
    idx: int,
    ts: int,
    container_name: str,
    cpu_percent: float | None,
    memory_usage_bytes: int | None,
    memory_limit_bytes: int | None,
    memory_percent: float | None,
    corpus_disk_usage_bytes: int | None,
) -> None:
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
            int(trial_row_id),
            int(idx),
            int(ts),
            str(container_name),
            cpu_percent,
            memory_usage_bytes,
            memory_limit_bytes,
            memory_percent,
            corpus_disk_usage_bytes,
        ),
    )
