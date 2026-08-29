# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Persist deduplicated bugs and their per-snapshot hit counts.'''

from __future__ import annotations

import json

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .base import DB


@dataclass(frozen=True)
class BugRecord:
    '''Describe one deduplicated bug row to persist.'''

    run_id: str
    fuzzer: str
    benchmark: str
    fuzz_target: str
    bug_key: str
    issue_type: str | None
    top_func: str | None
    frames: list[str]
    output: str | None
    first_seen_ts: int
    first_seen_snapshot_id: int


@dataclass(frozen=True)
class BugRow(BugRecord):
    """Describe one stored bug row, with the identity the database gave it."""

    bug_id: int

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> 'BugRow':
        """Build a bug row from its database columns."""
        return cls(
            run_id=str(row['run_id']),
            fuzzer=str(row['fuzzer']),
            benchmark=str(row['benchmark']),
            fuzz_target=str(row['fuzz_target']),
            bug_key=str(row['bug_key']),
            issue_type=row['issue_type'],
            top_func=row['top_func'],
            frames=_parse_frames(row['frames_json']),
            output=_normalize_text(row['output']),
            first_seen_ts=int(row['first_seen_ts']),
            first_seen_snapshot_id=int(row['first_seen_snapshot_id']),
            bug_id=int(row['bug_id']),
        )


def _normalize_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _parse_frames(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(frame) for frame in value if str(frame).strip()]
    try:
        parsed = json.loads(str(value or '[]'))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(frame) for frame in parsed if str(frame).strip()]


def get_bug_id(
    db: DB,
    *,
    run_id: str,
    fuzzer: str,
    benchmark: str,
    fuzz_target: str,
    bug_key: str,
) -> int | None:
    '''Return the database id of a known bug, if any.'''

    row = db.q1(
        '''
        SELECT bug_id
          FROM bugs
         WHERE run_id=? AND fuzzer=? AND benchmark=? AND fuzz_target=? AND bug_key=?
        ''',
        (run_id, fuzzer, benchmark, fuzz_target, bug_key),
    )
    return int(row['bug_id']) if row else None


def ensure_bug(db: DB, record: BugRecord) -> int:
    '''Insert one bug row when missing and return its database id.'''

    db.exec(
        '''
        INSERT OR IGNORE INTO bugs(
          run_id,fuzzer,benchmark,fuzz_target,bug_key,
          issue_type,top_func,frames_json,output,
          first_seen_ts,first_seen_snapshot_id
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ''',
        (
            record.run_id,
            record.fuzzer,
            record.benchmark,
            record.fuzz_target,
            record.bug_key,
            record.issue_type,
            record.top_func,
            json.dumps(record.frames[:8]),
            record.output,
            record.first_seen_ts,
            record.first_seen_snapshot_id,
        ),
    )
    bid = get_bug_id(
        db,
        run_id=record.run_id,
        fuzzer=record.fuzzer,
        benchmark=record.benchmark,
        fuzz_target=record.fuzz_target,
        bug_key=record.bug_key,
    )
    if bid is None:
        raise RuntimeError('Failed to ensure bug row')
    return bid


def upsert_bug_hits(db: DB, *, bug_id: int, snapshot_id: int, hits: int) -> None:
    '''Store the hit count of one bug for one snapshot.'''

    db.exec(
        'INSERT OR REPLACE INTO bug_hits(bug_id, snapshot_id, hits) VALUES(?,?,?)',
        (bug_id, snapshot_id, hits),
    )
