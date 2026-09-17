'''Unit tests for run-scoped signal and container cleanup coordination.'''

from __future__ import annotations

import signal
import unittest

from pathlib import Path
from unittest.mock import patch

from fuzzmeter.docker import DockerRuntime
from fuzzmeter.run.shutdown import RunShutdown


class RunShutdownTest(unittest.TestCase):
    '''Verify signal-triggered cleanup without Docker side effects.'''

    def setUp(self) -> None:
        self.runtime = DockerRuntime(
            fuzzer_dirs={'fuzzer': Path('/repo/fuzzers/fuzzer')},
            out_src='/out',
            run_user='1000:1000',
            run_id='run-1',
            memory=None,
            memory_swap=None,
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
