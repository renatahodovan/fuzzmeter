# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Store and update trial rows in the run database.'''

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .base import DB


@dataclass(frozen=True)
class TrialRecord:
    """Describe one trial row to create or refresh."""

    fuzzer: str
    benchmark: str
    fuzz_target: str
    rep: int
    time_seconds: int
    status: str
    fuzzer_image: str
    build_config_json: str | None
    runtime_config_json: str | None


@dataclass(frozen=True)
class TrialRow(TrialRecord):
    """Describe one stored trial row, with the state it gained once it existed."""

    trial_id: int
    jobs: int | None
    started_ts: int | None
    ended_ts: int | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> 'TrialRow':
        """Build a trial row from its database columns."""
        return cls(
            fuzzer=str(row['fuzzer']),
            benchmark=str(row['benchmark']),
            fuzz_target=str(row['fuzz_target']),
            rep=int(row['rep']),
            time_seconds=int(row['time_seconds']),
            status=str(row['status']),
            fuzzer_image=str(row['fuzzer_image'] or ''),
            build_config_json=row['build_config_json'],
            runtime_config_json=row['runtime_config_json'],
            trial_id=int(row['trial_id']),
            jobs=None if row['jobs'] is None else int(row['jobs']),
            started_ts=None if row['started_ts'] is None else int(row['started_ts']),
            ended_ts=None if row['ended_ts'] is None else int(row['ended_ts']),
        )


def ensure_trial_row(db: DB, *, run_id: str, record: TrialRecord, started_ts: int) -> int:
    '''Create or find one trial row and return its database id.'''
    db.exec(
        '''
        INSERT OR IGNORE INTO trials(
            run_id,fuzzer,benchmark,fuzz_target,rep,
            time_seconds,status,fuzzer_image,build_config_json,runtime_config_json
        )
        VALUES(?,?,?,?,?,?,?,?,?,?)
        ''',
        (
            str(run_id),
            str(record.fuzzer),
            str(record.benchmark),
            str(record.fuzz_target),
            int(record.rep),
            int(record.time_seconds),
            str(record.status),
            str(record.fuzzer_image),
            record.build_config_json,
            record.runtime_config_json,
        ),
    )
    tid = db.scalar(
        'SELECT trial_id FROM trials WHERE run_id=? AND fuzzer=? AND benchmark=? AND fuzz_target=? AND rep=?',
        (
            str(run_id),
            str(record.fuzzer),
            str(record.benchmark),
            str(record.fuzz_target),
            int(record.rep),
        ),
    )
    if tid is None:
        raise RuntimeError('Failed to create trial row')
    db.exec('UPDATE trials SET started_ts=? WHERE trial_id=?', (int(started_ts), int(tid)))
    return int(tid)


def set_trial_status(db: DB, *, trial_id: int, status: str, ended_ts: int | None = None) -> None:
    '''Update the status and optional end timestamp of one trial.'''
    if ended_ts is None:
        db.exec('UPDATE trials SET status=? WHERE trial_id=?', (str(status), int(trial_id)))
    else:
        db.exec('UPDATE trials SET status=?, ended_ts=? WHERE trial_id=?', (str(status), int(ended_ts), int(trial_id)))
