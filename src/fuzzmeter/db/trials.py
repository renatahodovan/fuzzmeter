# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Store and update trial rows in the run database.'''

from __future__ import annotations

from .base import DB


def ensure_trial_row(
    db: DB,
    *,
    run_id: str,
    fuzzer: str,
    benchmark: str,
    fuzz_target: str,
    rep: int,
    time_seconds: int,
    jobs: int,
    status: str,
    fuzzer_image: str,
    build_config_json: str | None,
    runtime_config_json: str | None,
    started_ts: int,
) -> int:
    '''Create or find one trial row and return its database id.'''
    db.exec(
        '''
        INSERT OR IGNORE INTO trials(
            run_id,fuzzer,benchmark,fuzz_target,rep,
            time_seconds,jobs,status,fuzzer_image,build_config_json,runtime_config_json
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ''',
        (
            str(run_id),
            str(fuzzer),
            str(benchmark),
            str(fuzz_target),
            int(rep),
            int(time_seconds),
            int(jobs),
            str(status),
            str(fuzzer_image),
            build_config_json,
            runtime_config_json,
        ),
    )
    tid = db.scalar(
        'SELECT trial_id FROM trials WHERE run_id=? AND fuzzer=? AND benchmark=? AND fuzz_target=? AND rep=?',
        (str(run_id), str(fuzzer), str(benchmark), str(fuzz_target), int(rep)),
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
