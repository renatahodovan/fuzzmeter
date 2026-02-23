# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import json

from .base import DB


def get_bug_id(
    db: DB,
    *,
    run_id: str,
    fuzzer: str,
    benchmark: str,
    fuzz_target: str,
    bug_key: str,
) -> int | None:
    row = db.q1(
        """
        SELECT bug_id
          FROM bugs
         WHERE run_id=? AND fuzzer=? AND benchmark=? AND fuzz_target=? AND bug_key=?
        """,
        (str(run_id), str(fuzzer), str(benchmark), str(fuzz_target), str(bug_key)),
    )
    return int(row["bug_id"]) if row else None


def ensure_bug(
    db: DB,
    *,
    run_id: str,
    fuzzer: str,
    benchmark: str,
    fuzz_target: str,
    bug_key: str,
    issue_type: str | None,
    top_func: str | None,
    frames: list[str],
    output: str | None,
    first_seen_ts: int,
    first_seen_snapshot_id: int,
) -> int:
    db.exec(
        """
        INSERT OR IGNORE INTO bugs(
          run_id,fuzzer,benchmark,fuzz_target,bug_key,
          issue_type,top_func,frames_json,output,
          first_seen_ts,first_seen_snapshot_id
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            str(run_id),
            str(fuzzer),
            str(benchmark),
            str(fuzz_target),
            str(bug_key),
            issue_type,
            top_func,
            json.dumps(frames[:8]),
            output,
            int(first_seen_ts),
            int(first_seen_snapshot_id),
        ),
    )
    bid = get_bug_id(
        db,
        run_id=run_id,
        fuzzer=fuzzer,
        benchmark=benchmark,
        fuzz_target=fuzz_target,
        bug_key=bug_key,
    )
    if bid is None:
        raise RuntimeError('Failed to ensure bug row')
    return int(bid)


def upsert_bug_hits(db: DB, *, bug_id: int, snapshot_id: int, hits: int) -> None:
    db.exec(
        "INSERT OR REPLACE INTO bug_hits(bug_id, snapshot_id, hits) VALUES(?,?,?)",
        (int(bug_id), int(snapshot_id), int(hits)),
    )
