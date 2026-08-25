# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Unit tests for live trial container runtime monitoring.'''

from __future__ import annotations

import subprocess
import tempfile
import time
import unittest

from dataclasses import dataclass
from pathlib import Path

from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.trial.models import TrialConfig, TrialImages
from fuzzmeter.trial.runtime import TrialContainer
from tests.support.trials import make_trial_config


class _StoppedDocker:
    def is_running(self, container_name: str) -> bool:
        return False

    def logs(self, container_name: str, tail: int = 200) -> str:
        return 'log tail'

    def wait(self, container_name: str, timeout_s: int | None = None) -> int:
        return 17


class _StartingDocker:
    def __init__(self) -> None:
        self.spec = None

    @property
    def run_user(self) -> str:
        return 'runner'

    def out_volume(self, container_path: str) -> str:
        return f'out:{container_path}'

    def start(self, spec) -> str:
        self.spec = spec
        return 'container-id'

    def is_running(self, container_name: str) -> bool:
        return True


class _StubbornLogProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self.wait_calls = 0

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None) -> int:
        self.wait_calls += 1
        if self.wait_calls == 1:
            raise subprocess.TimeoutExpired('docker logs', timeout)
        return 0


@dataclass(frozen=True)
class _DockerRuntimeStub:
    fuzzer_dirs: dict[str, Path]
    out_root: Path

    def map_out_path(self, host_path: Path, *, container_root: str = '/tmp/fuzzmeter/out') -> str:
        return str(Path(container_root) / Path(host_path).relative_to(self.out_root))


def _trial_config(root: Path) -> TrialConfig:
    return make_trial_config(
        fuzzer='aflplusplus',
        fuzzer_impl='aflplusplus',
        benchmark='sqlite3',
        fuzz_target='sqlite',
        fuzz_target_bin=root / 'targets' / 'sqlite',
        fuzz_target_input_mode='file',
        fuzz_target_timeout=1.0,
        rep_idx=0,
        trial_key='aflplusplus__sqlite3-sqlite__rep0',
        output_paths=OutputPaths(
            corpus_root=Path('default/queue'),
            crashes_root=Path('default/crashes'),
        ),
        trial_timeout=3600,
        snapshot_preprocess=None,
        images=TrialImages(fuzzer_name='aflplusplus', target_key='sqlite3-sqlite'),
    )


class TrialRuntimeTest(unittest.TestCase):
    '''Verify trial container monitoring behavior.'''

    def test_trial_container_uses_run_scoped_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_root = Path(tmp_dir) / 'out'
            run_dir = out_root / '2026-05-19_133200'
            input_seed_root = run_dir / 'seed_corpora' / '_empty' / 'aflplusplus__sqlite3-sqlite__rep0' / 'corpus'
            target_bin = run_dir / 'targets' / 'sqlite'
            input_seed_root.mkdir(parents=True)
            target_bin.parent.mkdir(parents=True)
            target_bin.write_text('', encoding='utf-8')

            container = TrialContainer(
                docker_runtime=_DockerRuntimeStub(
                    fuzzer_dirs={'aflplusplus': run_dir / 'aflplusplus'}, out_root=out_root
                ),
                container_name='fm_01234567-89ab-cdef-0123-456789abcdef_7_aflplusplus__sqlite3-sqlite__rep0',
                config=_trial_config(run_dir),
                run_dir=run_dir,
                input_corpus_dir=input_seed_root,
                fuzzer_log=run_dir / 'trials' / 'aflplusplus__sqlite3-sqlite__rep0' / 'logs' / 'fuzzer.log',
                start_ts=1,
            )

            self.assertEqual(
                Path('/tmp/fuzzmeter/out/2026-05-19_133200/trials/aflplusplus__sqlite3-sqlite__rep0'),
                container.trial_mount_dir,
            )
            self.assertEqual(
                Path('/tmp/fuzzmeter/out/2026-05-19_133200/targets/sqlite'),
                container._mounted_path(target_bin),
            )

    def test_monitor_until_deadline_fails_when_container_exits_early(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            log_path = root / 'fuzzer.log'
            log_path.touch()
            target_bin = root / 'target'
            target_bin.write_text('', encoding='utf-8')
            runtime = TrialContainer(
                docker_runtime=_DockerRuntimeStub(fuzzer_dirs={'aflplusplus': root / 'aflplusplus'}, out_root=root),
                container_name='container',
                config=_trial_config(root),
                run_dir=root,
                input_corpus_dir=root,
                fuzzer_log=log_path,
                start_ts=int(time.time()) - 10,
            )
            runtime.docker = _StoppedDocker()

            with self.assertRaisesRegex(RuntimeError, 'exit_code=17'):
                runtime.monitor_until_deadline()

            self.assertIn('container exited before the configured deadline', log_path.read_text(encoding='utf-8'))
            self.assertIn('log tail', log_path.read_text(encoding='utf-8'))

    def test_start_passes_target_timeout_to_fuzzer_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            log_path = root / 'fuzzer.log'
            target_bin = root / 'target'
            target_bin.write_text('', encoding='utf-8')
            runtime = TrialContainer(
                docker_runtime=_DockerRuntimeStub(fuzzer_dirs={'aflplusplus': root / 'aflplusplus'}, out_root=root),
                container_name='container',
                config=_trial_config(root),
                run_dir=root,
                input_corpus_dir=root,
                fuzzer_log=log_path,
                start_ts=1,
            )
            docker = _StartingDocker()
            runtime.docker = docker

            runtime.start()
            TrialContainer._unregister_active_container('container')

        self.assertIsNotNone(docker.spec)
        self.assertEqual('file', docker.spec.env['FM_INPUT_MODE'])
        self.assertEqual('1.0', docker.spec.env['FM_FUZZ_TARGET_TIMEOUT'])

    def test_start_registers_container_before_docker_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            target_bin = root / 'target'
            target_bin.write_text('', encoding='utf-8')
            runtime = TrialContainer(
                docker_runtime=_DockerRuntimeStub(fuzzer_dirs={'aflplusplus': root / 'aflplusplus'}, out_root=root),
                container_name='ordered-container',
                config=_trial_config(root),
                run_dir=root,
                input_corpus_dir=root,
                fuzzer_log=root / 'fuzzer.log',
                start_ts=1,
            )
            docker = _StartingDocker()

            def assert_registered(_spec) -> str:
                self.assertIn('ordered-container', TrialContainer._active_container_names)
                return 'container-id'

            docker.start = assert_registered
            runtime.docker = docker
            runtime.start()
            TrialContainer._unregister_active_container('ordered-container')

    def test_stop_log_stream_escalates_to_kill_and_reaps(self) -> None:
        log_proc = _StubbornLogProcess()
        TrialContainer._stop_log_stream(log_proc, 'container')

        self.assertTrue(log_proc.terminated)
        self.assertTrue(log_proc.killed)
        self.assertEqual(2, log_proc.wait_calls)


if __name__ == '__main__':
    unittest.main()
