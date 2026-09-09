# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Render a fixed-position progress dashboard for snapshot processing.'''

from __future__ import annotations

import logging
import sys
import threading

from tqdm import tqdm


class _TqdmLoggingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            tqdm.write(self.format(record), file=sys.stderr)
        except Exception:
            self.handleError(record)


class SnapshotProgress:
    '''Keep a fixed set of progress bars at the bottom of the terminal.'''

    def __init__(
        self,
        *,
        total_seconds: int,
        enabled: bool,
        total_trials: int = 0,
        trial_workers: int = 0,
    ) -> None:
        self._enabled = (
            enabled
            and sys.stderr is not None
            and not getattr(sys.stderr, 'closed', True)
            and getattr(sys.stderr, 'isatty', lambda: False)()
        )
        self._lock = threading.Lock()
        self._replaced_handlers: list[tuple[logging.Logger, logging.Handler, logging.Handler]] = []
        self._campaign_bar = None
        self._run_bar = None
        self._scheduler_bar = None
        self._coverage_bar = None
        self._crashes_bar = None

        if not self._enabled:
            return

        self._install_logging_handlers()
        show_campaign = total_trials > trial_workers > 0
        run_position = 1 if show_campaign else 0
        if show_campaign:
            self._campaign_bar = tqdm(
                total=total_trials,
                desc='Trials',
                unit='trial',
                position=0,
                leave=True,
                dynamic_ncols=True,
                colour='blue',
            )
        self._run_bar = tqdm(
            total=max(total_seconds, 1),
            desc='Run',
            unit='s',
            position=run_position,
            leave=True,
            dynamic_ncols=True,
            colour='cyan',
        )
        self._scheduler_bar = tqdm(
            total=1,
            desc='Scheduler',
            unit='tick',
            position=run_position + 1,
            leave=True,
            dynamic_ncols=True,
            colour='yellow',
        )
        self._coverage_bar = tqdm(
            total=1,
            desc='Coverage',
            unit='job',
            position=run_position + 2,
            leave=True,
            dynamic_ncols=True,
            colour='green',
        )
        self._crashes_bar = tqdm(
            total=1,
            desc='Crashes',
            unit='job',
            position=run_position + 3,
            leave=True,
            dynamic_ncols=True,
            colour='red',
        )
        self.idle_coverage()
        self.idle_crashes()
        self.update_scheduler(scheduled_ticks=0, processed_ticks=0, lag_seconds=None)

    def close(self) -> None:
        '''Close progress bars and restore regular logging handlers.'''
        if not self._enabled:
            return
        with self._lock:
            for bar in (self._crashes_bar, self._coverage_bar, self._scheduler_bar, self._run_bar, self._campaign_bar):
                if bar is not None:
                    bar.close()
            self._run_bar = None
            self._scheduler_bar = None
            self._coverage_bar = None
            self._crashes_bar = None
            self._campaign_bar = None
            self._restore_logging_handlers()

    def update_campaign(self, *, completed: int, active: int, queued: int, remaining_seconds: int) -> None:
        '''Refresh the multi-wave trial progress bar.'''
        if self._campaign_bar is None:
            return
        with self._lock:
            self._campaign_bar.n = min(max(completed, 0), self._campaign_bar.total)
            minutes = max(0, remaining_seconds) // 60
            self._campaign_bar.set_postfix(
                running=active,
                queued=queued,
                eta=f'{minutes // 60}h {minutes % 60}m',
                refresh=False,
            )
            self._campaign_bar.refresh()

    def update_run(
        self,
        *,
        elapsed_seconds: int,
        total_seconds: int,
        tick_idx: int,
        active_trials: int,
        wave_idx: int = 1,
        wave_count: int = 1,
    ) -> None:
        '''Refresh the current trial-wave progress bar.'''
        if self._run_bar is None:
            return
        with self._lock:
            description = 'Run' if wave_count == 1 else f'Run [{wave_idx}/{wave_count}]'
            if self._run_bar.desc != description:
                self._run_bar.reset(total=max(total_seconds, 1))
                self._run_bar.set_description_str(description)
            self._run_bar.total = max(total_seconds, 1)
            target = max(0, min(elapsed_seconds, self._run_bar.total))
            delta = target - int(self._run_bar.n)
            if delta > 0:
                self._run_bar.update(delta)
            self._run_bar.set_postfix(tick=tick_idx, active=active_trials, refresh=False)
            self._run_bar.refresh()

    def update_scheduler(self, *, scheduled_ticks: int, processed_ticks: int, lag_seconds: int | None) -> None:
        '''Refresh the snapshot scheduler backlog progress bar.'''
        if self._scheduler_bar is None:
            return
        with self._lock:
            backlog = max(0, scheduled_ticks - processed_ticks)
            self._scheduler_bar.total = max(scheduled_ticks, 1)
            self._scheduler_bar.n = min(processed_ticks, self._scheduler_bar.total)
            postfix = {'scheduled': scheduled_ticks, 'backlog': backlog}
            if lag_seconds is not None:
                postfix['lag_s'] = lag_seconds
            self._scheduler_bar.set_postfix(postfix, refresh=False)
            self._scheduler_bar.refresh()

    def start_coverage(self, *, tick_idx: int, total: int, phase: str) -> None:
        '''Prepare the fixed coverage bar for a new task phase.'''
        self._start_task(self._coverage_bar, desc=f'Coverage [{tick_idx}:{phase}]', total=total)

    def step_coverage(self) -> None:
        '''Advance the fixed coverage bar by one unit.'''
        self._step_task(self._coverage_bar)

    def idle_coverage(self) -> None:
        '''Show that no coverage task is currently running.'''
        self._idle_task(self._coverage_bar, desc='Coverage')

    def start_crashes(self, *, tick_idx: int, total: int) -> None:
        '''Prepare the fixed crash reproduction bar for a new tick.'''
        self._start_task(self._crashes_bar, desc=f'Crashes [{tick_idx}]', total=total)

    def step_crashes(self) -> None:
        '''Advance the fixed crash reproduction bar by one unit.'''
        self._step_task(self._crashes_bar)

    def idle_crashes(self) -> None:
        '''Show that no crash reproduction task is currently running.'''
        self._idle_task(self._crashes_bar, desc='Crashes')

    def _start_task(self, bar, *, desc: str, total: int) -> None:
        if bar is None:
            return
        with self._lock:
            bar.reset(total=max(total, 1))
            bar.set_description_str(desc)
            bar.set_postfix_str('idle' if total <= 0 else '', refresh=False)
            if total <= 0:
                bar.n = 0
            bar.refresh()

    def _step_task(self, bar) -> None:
        if bar is None:
            return
        with self._lock:
            if bar.n < bar.total:
                bar.update(1)
            bar.set_postfix_str('', refresh=False)
            bar.refresh()

    def _idle_task(self, bar, *, desc: str) -> None:
        if bar is None:
            return
        with self._lock:
            bar.reset(total=1)
            bar.n = 0
            bar.set_description_str(desc)
            bar.set_postfix_str('idle', refresh=False)
            bar.refresh()

    def _install_logging_handlers(self) -> None:
        root = logging.getLogger()
        for handler in list(root.handlers):
            if not isinstance(handler, logging.StreamHandler):
                continue
            stream = getattr(handler, 'stream', None)
            if stream not in {sys.stderr, sys.stdout}:
                continue
            tqdm_handler = _TqdmLoggingHandler()
            tqdm_handler.setLevel(handler.level)
            tqdm_handler.setFormatter(handler.formatter)
            root.removeHandler(handler)
            root.addHandler(tqdm_handler)
            self._replaced_handlers.append((root, handler, tqdm_handler))

    def _restore_logging_handlers(self) -> None:
        for logger, original_handler, tqdm_handler in reversed(self._replaced_handlers):
            logger.removeHandler(tqdm_handler)
            logger.addHandler(original_handler)
        self._replaced_handlers.clear()
