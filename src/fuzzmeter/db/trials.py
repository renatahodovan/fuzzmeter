# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Store and update trial rows in the run database.'''

from __future__ import annotations

from dataclasses import dataclass

from .base import DB


@dataclass(frozen=True)
class TrialRecord:
    '''Describe one trial row to create or refresh.'''

    run_id: str
    fuzzer: str
    benchmark: str
    fuzz_target: str
    rep: int
    time_seconds: int
    status: str
    fuzzer_image: str
    build_config_json: str | None
    runtime_config_json: str | None
    start_ts: int


def ensure_trial_row(db: DB, record: TrialRecord) -> int:
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
            str(record.run_id),
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
            str(record.run_id),
            str(record.fuzzer),
            str(record.benchmark),
            str(record.fuzz_target),
            int(record.rep),
        ),
    )
    if tid is None:
        raise RuntimeError('Failed to create trial row')
    db.exec('UPDATE trials SET started_ts=? WHERE trial_id=?', (int(record.start_ts), int(tid)))
    return int(tid)


def set_trial_status(db: DB, *, trial_id: int, status: str, ended_ts: int | None = None) -> None:
    '''Update the status and optional end timestamp of one trial.'''
    if ended_ts is None:
        db.exec('UPDATE trials SET status=? WHERE trial_id=?', (str(status), int(trial_id)))
    else:
        db.exec('UPDATE trials SET status=?, ended_ts=? WHERE trial_id=?', (str(status), int(ended_ts), int(trial_id)))
