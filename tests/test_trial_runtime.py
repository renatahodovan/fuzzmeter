# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Unit tests for live trial container runtime monitoring.'''

from __future__ import annotations

import tempfile
import time
import unittest

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace


class _StoppedDocker:
    def is_running(self, container_name: str) -> bool:
        return False

    def logs(self, container_name: str, tail: int = 200) -> str:
        return 'log tail'

    def wait(self, container_name: str, timeout_s: int | None = None) -> int:
        return 17


@dataclass(frozen=True)
class _Workspace:
    input_seed_root: Path
    paths: object
    seed_root: Path | None = None


class TrialRuntimeTest(unittest.TestCase):
    '''Verify trial container monitoring behavior.'''

    def test_build_context_uses_run_scoped_container_name(self) -> None:
        from fuzzmeter.trial.runtime import TrialContainerRuntime

        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / 'run'
            trial_dir = run_dir / 'trials' / 'aflplusplus__sqlite3-sqlite__rep0'
            input_seed_root = run_dir / 'seed_corpora' / '_empty' / 'aflplusplus__sqlite3-sqlite__rep0' / 'corpus'
            target_bin = run_dir / 'targets' / 'sqlite'
            input_seed_root.mkdir(parents=True)
            target_bin.parent.mkdir(parents=True)
            target_bin.write_text('', encoding='utf-8')

            runtime = TrialContainerRuntime(
                run_id='20260519-133200',
                docker_runtime=None,
                fuzzer_image='runner',
                target_bin_host_path=target_bin,
            )
            ctx = runtime.build_context(
                run_dir=run_dir,
                workspace=_Workspace(
                    input_seed_root=input_seed_root,
                    paths=SimpleNamespace(
                        trial_dir=trial_dir,
                        fuzzer_log=trial_dir / 'logs' / 'fuzzer.log',
                        live_out_root=trial_dir / 'work',
                    ),
                ),
                cfg=SimpleNamespace(
                    trial_key='aflplusplus__sqlite3-sqlite__rep0',
                    paths=SimpleNamespace(
                        live_out_root=Path('work'),
                        fuzzer_log=Path('logs/fuzzer.log'),
                    ),
                ),
                jobs=1,
                trial_row_id=7,
                started_ts=1,
            )

            self.assertEqual(ctx.container_name, 'fm_20260519-133200_7_aflplusplus__sqlite3-sqlite__rep0')

    def test_monitor_until_deadline_fails_when_container_exits_early(self) -> None:
        from fuzzmeter.trial.runtime import TrialContainerRuntime

        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / 'fuzzer.log'
            log_path.touch()
            runtime = TrialContainerRuntime(
                run_id='run',
                docker_runtime=None,
                fuzzer_image='runner',
                target_bin_host_path=Path(tmp_dir) / 'target',
            )
            runtime.docker = _StoppedDocker()

            ctx = SimpleNamespace(
                cfg=SimpleNamespace(time_seconds=3600),
                container_name='container',
                log_path=log_path,
                started_ts=int(time.time()) - 10,
            )

            with self.assertRaisesRegex(RuntimeError, 'exit_code=17'):
                runtime.monitor_until_deadline(ctx)

            self.assertIn('container exited before the configured deadline', log_path.read_text(encoding='utf-8'))
            self.assertIn('log tail', log_path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
