# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for replay trial workspace preparation.'''

from __future__ import annotations

import json
import os
import tempfile
import unittest

from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.trial.models import TrialConfig, TrialPathConfig
from fuzzmeter.trial.replay import ReplayTrialRunner


@dataclass(frozen=True)
class _DockerRuntimeStub:
    repo_root: Path


class ReplayTrialRunnerTest(unittest.TestCase):
    '''Verify that replay preparation preserves the original output layout.'''

    def test_prepare_links_original_live_out_and_uses_corpus_dir_creation_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            db.close()

            target_bin = root / 'target.bin'
            target_bin.write_text('bin', encoding='utf-8')

            source_trial_root = root / 'source' / '20251219-195423_r001'
            queue_root = source_trial_root / 'default' / 'queue'
            crashes_root = source_trial_root / 'default' / 'crashes'
            queue_root.mkdir(parents=True)
            crashes_root.mkdir(parents=True)
            (source_trial_root / 'default' / 'fuzzer_stats').write_text('', encoding='utf-8')

            first_queue_file = queue_root / 'id:000001'
            last_queue_file = queue_root / 'id:000002'
            first_queue_file.write_text('first', encoding='utf-8')
            last_queue_file.write_text('last', encoding='utf-8')
            os.utime(first_queue_file, ns=(1_000_000_000_000, 1_000_000_000_000))
            os.utime(last_queue_file, ns=(1_900_000_000_000, 1_900_000_000_000))

            cfg = TrialConfig(
                fuzzer='aflplusplus_replay',
                fuzzer_base='aflplusplus',
                benchmark='jerryscript',
                fuzz_target='jerry',
                input_mode='stdin',
                rep=0,
                trial_key='aflplusplus_replay__jerryscript-jerry__rep0',
                paths=TrialPathConfig(
                    live_out_root=Path('work'),
                    snapshots_root=Path('snapshots'),
                    logs_root=Path('logs'),
                    fuzzer_log=Path('logs/fuzzer.log'),
                    output_paths=OutputPaths(
                        corpus_root=Path('default/queue'),
                        crashes_root=Path('default/crashes'),
                        hangs_root=Path('default/hangs'),
                    ),
                ),
                time_seconds=7_200,
                snapshot_every_seconds=900,
                snapshot_preprocess_script=None,
                runner_image='runner',
                coverage_image='coverage',
                asan_image='asan',
                replay_trial_path=source_trial_root / 'default',
            )
            replay_path = (source_trial_root / 'default').resolve()

            def _creationish_ns(path: Path) -> int:
                if path.resolve() == replay_path:
                    return 1_500_000_000_000
                if path.resolve() == queue_root.resolve():
                    return 1_800_000_000_000
                return path.stat().st_ctime_ns

            with patch.object(ReplayTrialRunner, '_creationish_ns', side_effect=_creationish_ns):
                prepared = ReplayTrialRunner(
                    repo_root=root,
                    docker_runtime=_DockerRuntimeStub(repo_root=root),
                    db_path=db_path,
                    run_id='run-1',
                    fuzzer_image='runner',
                    target_bin_host_path=target_bin,
                ).prepare(
                    run_dir=root / 'out',
                    cfg=cfg,
                    jobs=2,
                )

            live_out_root = prepared.active_trial.live_out
            self.assertTrue(live_out_root.is_symlink())
            self.assertEqual(live_out_root.resolve(), source_trial_root.resolve())
            self.assertEqual(prepared.replay_start_ts, 1_500)
            self.assertEqual(prepared.replay_end_ts, 1_900)
            self.assertTrue((prepared.active_trial.corpus_root / 'id:000001').is_file())
            self.assertTrue((prepared.active_trial.trial_root / 'work' / 'default' / 'fuzzer_stats').is_file())

    def test_prepare_writes_general_replay_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            db.close()

            target_bin = root / 'target.bin'
            target_bin.write_text('bin', encoding='utf-8')

            source_trial_root = root / 'source' / '20251219-195423_r001'
            queue_root = source_trial_root / 'default' / 'queue'
            crashes_root = source_trial_root / 'default' / 'crashes'
            queue_root.mkdir(parents=True)
            crashes_root.mkdir(parents=True)
            (source_trial_root / 'default' / 'fuzzer_stats').write_text('', encoding='utf-8')

            first_queue_file = queue_root / 'id:000001'
            mid_queue_file = queue_root / 'id:000002'
            last_queue_file = queue_root / 'id:000003'
            crash_file = crashes_root / 'id:000004'
            first_queue_file.write_text('first', encoding='utf-8')
            mid_queue_file.write_text('mid', encoding='utf-8')
            last_queue_file.write_text('last', encoding='utf-8')
            crash_file.write_text('crash', encoding='utf-8')
            os.utime(first_queue_file, ns=(1_000_000_000_000, 1_000_000_000_000))
            os.utime(mid_queue_file, ns=(1_050_000_000_000, 1_050_000_000_000))
            os.utime(last_queue_file, ns=(1_900_000_000_000, 1_900_000_000_000))
            os.utime(crash_file, ns=(1_500_000_000_000, 1_500_000_000_000))

            cfg = TrialConfig(
                fuzzer='aflplusplus_replay',
                fuzzer_base='aflplusplus',
                benchmark='jerryscript',
                fuzz_target='jerry',
                input_mode='stdin',
                rep=0,
                trial_key='aflplusplus_replay__jerryscript-jerry__rep0',
                paths=TrialPathConfig(
                    live_out_root=Path('work'),
                    snapshots_root=Path('snapshots'),
                    logs_root=Path('logs'),
                    fuzzer_log=Path('logs/fuzzer.log'),
                    output_paths=OutputPaths(
                        corpus_root=Path('default/queue'),
                        crashes_root=Path('default/crashes'),
                        hangs_root=Path('default/hangs'),
                    ),
                ),
                time_seconds=7_200,
                snapshot_every_seconds=900,
                snapshot_preprocess_script=None,
                runner_image='runner',
                coverage_image='coverage',
                asan_image='asan',
                replay_trial_path=source_trial_root / 'default',
            )
            replay_path = (source_trial_root / 'default').resolve()

            def _creationish_ns(path: Path) -> int:
                if path.resolve() == replay_path:
                    return 1_300_000_000_000
                if path.resolve() == queue_root.resolve():
                    return 1_700_000_000_000
                return path.stat().st_ctime_ns

            with patch.object(ReplayTrialRunner, '_creationish_ns', side_effect=_creationish_ns):
                prepared = ReplayTrialRunner(
                    repo_root=root,
                    docker_runtime=_DockerRuntimeStub(repo_root=root),
                    db_path=db_path,
                    run_id='run-1',
                    fuzzer_image='runner',
                    target_bin_host_path=target_bin,
                ).prepare(
                    run_dir=root / 'out',
                    cfg=cfg,
                    jobs=2,
                )

            self.assertEqual(prepared.replay_start_ts, 1_300)
            self.assertEqual(prepared.replay_end_ts, 1_900)
            timeline = json.loads((prepared.active_trial.trial_root / 'replay_timeline.json').read_text(encoding='utf-8'))
            self.assertEqual(timeline['replay_start_ts'], 1_300)
            self.assertEqual(timeline['replay_end_ts'], 1_900)
            self.assertEqual(
                timeline['file_times_ns']['default/queue/id:000001'],
                1_300_000_000_000,
            )
            self.assertEqual(
                timeline['file_times_ns']['default/queue/id:000002'],
                1_300_000_000_000,
            )
            self.assertEqual(
                timeline['file_times_ns']['default/queue/id:000003'],
                1_900_000_000_000,
            )
            self.assertEqual(
                timeline['file_times_ns']['default/crashes/id:000004'],
                1_500_000_000_000,
            )

    def test_linux_birthtime_ns_parses_stat_output(self) -> None:
        with patch(
            'fuzzmeter.trial.replay.subprocess.run',
            return_value=CompletedProcess(
                args=['stat', '-c', '%w', '/tmp/example'],
                returncode=0,
                stdout='2025-12-05 18:03:19.123456789 +0000\n',
                stderr='',
            ),
        ):
            self.assertEqual(
                ReplayTrialRunner._linux_birthtime_ns(Path('/tmp/example')),
                1_764_957_799_123_456_789,
            )


if __name__ == '__main__':
    unittest.main()
