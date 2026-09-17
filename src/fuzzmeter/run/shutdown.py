'''Coordinate signal-driven and normal container cleanup for one run.'''

from __future__ import annotations

import logging
import os
import signal
import threading

from types import TracebackType

from ..docker import DockerRuntime
from ..trial.runtime import TrialContainer

LOG = logging.getLogger(__name__)


class RunShutdown:
    '''Install process signal handlers and expose the shared stop event.'''

    def __init__(self, docker_runtime: DockerRuntime) -> None:
        self.docker_runtime = docker_runtime
        self.stop_event = threading.Event()
        self._signal_count = 0
        self._previous_handlers: dict[signal.Signals, object] = {}

    def __enter__(self) -> 'RunShutdown':
        if threading.current_thread() is threading.main_thread():
            for handled_signal in (signal.SIGINT, signal.SIGTERM):
                self._previous_handlers[handled_signal] = signal.getsignal(handled_signal)
                signal.signal(handled_signal, self._handle_signal)
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        try:
            cleanup_containers(self.docker_runtime)
        finally:
            for handled_signal, previous_handler in self._previous_handlers.items():
                signal.signal(handled_signal, previous_handler)

    def _handle_signal(self, signum: int, _frame: object) -> None:
        self._signal_count += 1
        self.stop_event.set()
        if self._signal_count > 1:
            # The container sweep runs unbounded Docker commands so that cleanup
            # always completes. A repeated signal is the user demanding an
            # immediate exit, and it is the escape hatch when the daemon is
            # wedged, so it must not start another sweep and wait again.
            LOG.warning('Signal %s received again, exiting without another sweep', signum)
            os._exit(128 + signum)
        swept = cleanup_containers(self.docker_runtime)
        LOG.warning('Signal %s container sweep found %d container(s)', signum, swept)
        if signum == signal.SIGTERM:
            raise SystemExit(128 + signum)
        raise KeyboardInterrupt


def cleanup_containers(docker_runtime: DockerRuntime | None) -> int:
    '''Stop registered trials and sweep every container labelled for this run.'''
    swept = TrialContainer.force_stop_all_active(docker_runtime)
    LOG.info('Container cleanup sweep found %d container(s)', swept)
    return swept
