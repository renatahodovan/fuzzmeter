# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Store per-tick resource telemetry rows.'''

from __future__ import annotations

import json

from typing import Any

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
    corpus_disk_usage_human: str | None,
    stats: dict[str, Any] | None,
) -> None:
    '''Insert or replace one resource telemetry sample.'''

    stats_json = None
    if isinstance(stats, dict) and stats:
        stats_json = json.dumps(stats, sort_keys=True, separators=(',', ':'), default=str)
    db.exec(
        '''
        INSERT OR REPLACE INTO resource_telemetry(
          trial_id, idx, ts, container_name,
          cpu_percent, memory_usage_bytes, memory_limit_bytes, memory_percent,
          corpus_disk_usage_bytes, corpus_disk_usage_human, stats_json
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
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
            corpus_disk_usage_human,
            stats_json,
        ),
    )
