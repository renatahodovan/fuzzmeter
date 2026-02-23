# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from .base import DB


def upsert_run(db: DB, *, run_id: str, created_ts: int, suite_yaml: str) -> None:
    db.exec(
        "INSERT OR REPLACE INTO runs(run_id, created_ts, suite_yaml) VALUES(?,?,?)",
        (str(run_id), int(created_ts), str(suite_yaml)),
    )
    
