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

from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.trial.models import TrialConfig, TrialImages
from fuzzmeter.trial.replay import prepare_replay_trial
from tests.support.trials import make_trial_config


@dataclass(frozen=True)
class _DockerRuntimeStub:
    fuzzer_dirs: dict[str, Path]


def _trial_config(root: Path, *, replay_dir: Path) -> TrialConfig:
    return make_trial_config(
        fuzzer='aflplusplus_replay',
        fuzzer_impl='aflplusplus',
        benchmark='jerryscript',
        fuzz_target='jerry',
        fuzz_target_bin=root / 'target.bin',
        fuzz_target_input_mode='stdin',
        fuzz_target_timeout=1.0,
        rep_idx=0,
        trial_key='aflplusplus_replay__jerryscript-jerry__rep0',
        output_paths=OutputPaths(
            corpus_root=Path('default/queue'),
            crashes_root=Path('default/crashes'),
            hangs_root=Path('default/hangs'),
        ),
        trial_timeout=7_200,
        snapshot_preprocess=None,
        images=TrialImages(fuzzer_name='aflplusplus', target_key='jerryscript-jerry'),
        replay_dir=replay_dir,
    )


class ReplayTrialRunnerTest(unittest.TestCase):
    '''Verify that replay preparation preserves the original output layout.'''

    def test_prepare_links_original_fuzz_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run-1', 1, 'config'))
            db.close()

            replay_dir = root / 'source'
            queue_root = replay_dir / 'default' / 'queue'
            crashes_root = replay_dir / 'default' / 'crashes'
            queue_root.mkdir(parents=True)
            crashes_root.mkdir(parents=True)
            (queue_root / 'id:000001').write_text('first', encoding='utf-8')
            (queue_root / 'id:000002').write_text('last', encoding='utf-8')
            os.utime(queue_root / 'id:000001', ns=(1_000_000_000_000, 1_000_000_000_000))
            os.utime(queue_root / 'id:000002', ns=(1_900_000_000_000, 1_900_000_000_000))

            target_bin = root / 'target.bin'
            target_bin.write_text('bin', encoding='utf-8')
            cfg = _trial_config(root, replay_dir=replay_dir)

            prepared = prepare_replay_trial(
                db_path=db_path,
                docker_runtime=_DockerRuntimeStub(fuzzer_dirs={'aflplusplus': root / 'aflplusplus'}),
                run_dir=root / 'out',
                run_id='run-1',
                cfg=cfg,
            )

            replay_start_ns = replay_dir.stat().st_mtime_ns
            self.assertTrue(prepared.layout.fuzz_dir.is_symlink())
            self.assertEqual(prepared.layout.fuzz_dir.resolve(), replay_dir.resolve())
            self.assertEqual(prepared.start_ts, replay_start_ns // 1_000_000_000)
            self.assertEqual(prepared.end_ts, max(replay_start_ns, (queue_root / 'id:000002').stat().st_mtime_ns) // 1_000_000_000)
            self.assertTrue((prepared.layout.corpus_dir / 'id:000001').is_file())

    def test_prepare_writes_general_replay_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'state.db'
            db = DB.open(db_path)
            ensure_schema(db)
            db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run-1', 1, 'config'))
            db.close()

            replay_dir = root / 'source'
            queue_root = replay_dir / 'default' / 'queue'
            crashes_root = replay_dir / 'default' / 'crashes'
            queue_root.mkdir(parents=True)
            crashes_root.mkdir(parents=True)

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

            target_bin = root / 'target.bin'
            target_bin.write_text('bin', encoding='utf-8')
            cfg = _trial_config(root, replay_dir=replay_dir)

            prepared = prepare_replay_trial(
                db_path=db_path,
                docker_runtime=_DockerRuntimeStub(fuzzer_dirs={'aflplusplus': root / 'aflplusplus'}),
                run_dir=root / 'out',
                run_id='run-1',
                cfg=cfg,
            )

            replay_start_ns = replay_dir.stat().st_mtime_ns
            timeline = json.loads((prepared.layout.trial_dir / 'replay_timeline.json').read_text(encoding='utf-8'))
            self.assertEqual(timeline['start_ts'], prepared.start_ts)
            self.assertEqual(timeline['end_ts'], prepared.end_ts)
            self.assertEqual(
                timeline['file_times_ns']['default/queue/id:000001'],
                max(replay_start_ns, first_queue_file.stat().st_mtime_ns),
            )
            self.assertEqual(
                timeline['file_times_ns']['default/queue/id:000002'],
                max(replay_start_ns, mid_queue_file.stat().st_mtime_ns),
            )
            self.assertEqual(
                timeline['file_times_ns']['default/queue/id:000003'],
                max(replay_start_ns, last_queue_file.stat().st_mtime_ns),
            )
            self.assertEqual(
                timeline['file_times_ns']['default/crashes/id:000004'],
                max(replay_start_ns, crash_file.stat().st_mtime_ns),
            )


if __name__ == '__main__':
    unittest.main()
