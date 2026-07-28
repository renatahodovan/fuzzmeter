'''Unit tests for run-scoped signal and container cleanup coordination.'''

from __future__ import annotations

import signal
import unittest

from pathlib import Path
from unittest.mock import call, patch

from fuzzmeter.docker import DockerRuntime
from fuzzmeter.run.shutdown import RunShutdown


class RunShutdownTest(unittest.TestCase):
    '''Verify startup and signal-triggered sweeps without Docker side effects.'''

    def setUp(self) -> None:
        self.runtime = DockerRuntime(
            fuzzers_root=Path('/repo/fuzzers'),
            out_src='/out',
            run_user=None,
            run_id='run-1',
        )

    def test_context_sweeps_at_startup_and_restores_signal_handlers(self) -> None:
        with patch('fuzzmeter.run.shutdown.DockerClient.sweep_run', return_value=3) as sweep, \
             patch('fuzzmeter.run.shutdown.cleanup_containers', return_value=0) as cleanup, \
             patch('fuzzmeter.run.shutdown.signal.getsignal', return_value=signal.SIG_DFL), \
             patch('fuzzmeter.run.shutdown.signal.signal') as install:
            with RunShutdown(self.runtime) as shutdown:
                self.assertEqual(3, shutdown.startup_orphans)

        sweep.assert_called_once_with()
        cleanup.assert_called_once_with(self.runtime)
        self.assertEqual(
            [
                call(signal.SIGINT, shutdown._handle_signal),
                call(signal.SIGTERM, shutdown._handle_signal),
                call(signal.SIGINT, signal.SIG_DFL),
                call(signal.SIGTERM, signal.SIG_DFL),
            ],
            install.call_args_list,
        )

    def test_first_signal_sets_stop_event_and_sweeps(self) -> None:
        shutdown = RunShutdown(self.runtime)
        with patch('fuzzmeter.run.shutdown.cleanup_containers', return_value=2) as cleanup:
            with self.assertRaises(KeyboardInterrupt):
                shutdown._handle_signal(signal.SIGINT, None)

        self.assertTrue(shutdown.stop_event.is_set())
        cleanup.assert_called_once_with(self.runtime)

    def test_second_signal_exits_immediately_without_another_sweep(self) -> None:
        shutdown = RunShutdown(self.runtime)
        with (
            patch('fuzzmeter.run.shutdown.cleanup_containers', return_value=1) as cleanup,
            patch('fuzzmeter.run.shutdown.os._exit', side_effect=RuntimeError('forced exit')) as force_exit,
        ):
            with self.assertRaises(KeyboardInterrupt):
                shutdown._handle_signal(signal.SIGINT, None)
            with self.assertRaisesRegex(RuntimeError, 'forced exit'):
                shutdown._handle_signal(signal.SIGINT, None)

        # The sweep runs unbounded Docker commands, so a repeated signal must be
        # the escape hatch rather than starting a second sweep that also hangs.
        self.assertEqual(1, cleanup.call_count)
        force_exit.assert_called_once_with(130)


if __name__ == '__main__':
    unittest.main()
