# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Persist deduplicated bugs and their per-snapshot hit counts.'''

from __future__ import annotations

import json

from dataclasses import dataclass

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
        (str(run_id), str(fuzzer), str(benchmark), str(fuzz_target), str(bug_key)),
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
            str(record.run_id),
            str(record.fuzzer),
            str(record.benchmark),
            str(record.fuzz_target),
            str(record.bug_key),
            record.issue_type,
            record.top_func,
            json.dumps(record.frames[:8]),
            record.output,
            int(record.first_seen_ts),
            int(record.first_seen_snapshot_id),
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
    return int(bid)


def upsert_bug_hits(db: DB, *, bug_id: int, snapshot_id: int, hits: int) -> None:
    '''Store the hit count of one bug for one snapshot.'''

    db.exec(
        'INSERT OR REPLACE INTO bug_hits(bug_id, snapshot_id, hits) VALUES(?,?,?)',
        (int(bug_id), int(snapshot_id), int(hits)),
    )
