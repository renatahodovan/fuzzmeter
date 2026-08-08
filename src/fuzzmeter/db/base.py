# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Provide a small SQLite wrapper with retry support for worker contention.'''

from __future__ import annotations

import sqlite3
import time

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence


def _row_factory(cur: sqlite3.Cursor, row: tuple) -> dict:
    cols = [d[0] for d in cur.description]
    return {cols[i]: row[i] for i in range(len(cols))}


def _is_locked_error(e: Exception) -> bool:
    # sqlite3.OperationalError: database is locked
    msg = str(e).lower()
    return 'database is locked' in msg or 'database table is locked' in msg


def open_readonly_connection(path: Path) -> sqlite3.Connection:
    '''Open a read-only SQLite connection for reporting and web views.'''

    path = Path(path)
    uri = f'file:{path.as_posix()}?mode=ro'
    # Immutable mode avoids sidecars for finished runs, but would hide live WAL rows.
    if not Path(f'{path}-wal').exists():
        uri += '&immutable=1'
    con = sqlite3.connect(uri, uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=3000')
    con.execute('PRAGMA temp_store=MEMORY')
    return con


@dataclass
class DB:
    '''Wrap a SQLite connection with retrying query helpers.'''

    con: sqlite3.Connection

    # default: allow short bursts of contention from parallel workers
    DEFAULT_BUSY_TIMEOUT_MS: int = 30_000
    DEFAULT_RETRY_TOTAL_S: float = 30.0

    @staticmethod
    def open(path: Path, *, busy_timeout_ms: int | None = None) -> 'DB':
        '''Open a SQLite database configured for concurrent fuzzmeter workers.'''

        # Use autocommit mode so concurrent workers hold the SQLite write lock
        # only for the duration of individual statements instead of an entire
        # snapshot collection/replay phase.
        con = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        con.row_factory = _row_factory

        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA synchronous=NORMAL')

        # IMPORTANT: allow waiting on locks instead of failing immediately
        if busy_timeout_ms is None:
            busy_timeout_ms = DB.DEFAULT_BUSY_TIMEOUT_MS
        con.execute(f'PRAGMA busy_timeout={int(busy_timeout_ms)}')

        return DB(con=con)

    def __enter__(self) -> 'DB':
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        '''Close the underlying SQLite connection.'''

        try:
            self.con.close()
        except Exception:
            pass

    # --- internal retry wrapper ---

    def _retry(self, fn, *, total_s: float | None = None):
        if total_s is None:
            total_s = DB.DEFAULT_RETRY_TOTAL_S
        deadline = time.monotonic() + float(total_s)

        sleep_s = 0.01
        while True:
            try:
                return fn()
            except sqlite3.OperationalError as e:
                if not _is_locked_error(e):
                    raise
                if time.monotonic() >= deadline:
                    raise
                time.sleep(sleep_s)
                # exponential backoff, capped
                sleep_s = min(sleep_s * 1.7, 0.25)

    # --- helpers ---

    def exec(self, sql: str, params: Sequence[Any] = ()) -> None:
        '''Execute one statement without returning rows.'''

        def _do():
            self.con.execute(sql, params)
        self._retry(_do)

    def q(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        '''Execute one query and return all rows.'''

        # Reads usually don't need retry, but safe in WAL contention
        def _do():
            cur = self.con.execute(sql, params)
            return list(cur.fetchall())
        return self._retry(_do)

    def q1(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        '''Execute one query and return the first row if present.'''

        def _do():
            cur = self.con.execute(sql, params)
            row = cur.fetchone()
            return row if row is not None else None
        return self._retry(_do)

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        '''Execute one query and return the first column of the first row.'''

        r = self.q1(sql, params)
        if r is None:
            return None
        return next(iter(r.values()))

    def commit(self) -> None:
        '''Commit the current transaction state.'''

        self._retry(self.con.commit)

    def rollback(self) -> None:
        '''Rollback the current transaction state when possible.'''

        try:
            self.con.rollback()
        except Exception:
            pass


@contextmanager
def open_db(path: Path, *, busy_timeout_ms: int | None = None) -> Iterator[DB]:
    '''Open a database connection, commit successful work, and always close it.'''
    db = DB.open(path, busy_timeout_ms=busy_timeout_ms)
    try:
        yield db
        db.commit()
    finally:
        db.close()
