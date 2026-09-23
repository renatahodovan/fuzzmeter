# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for crash reproduction bug persistence.'''

from __future__ import annotations

import json
import signal
import tempfile
import threading
import unittest

from pathlib import Path
from unittest.mock import Mock, patch

from fuzzmeter.db import DB
from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.repro.bugs import reproduce_crash_batch, save_crash_hits
from fuzzmeter.repro.ingest import DetectedFile
from fuzzmeter.snapshot.crashes import process_snapshot_crashes
from fuzzmeter.snapshot.trial_snapshot import TrialCrashSnapshot
from fuzzmeter.trial.models import TrialInstance, TrialLayout
from tests.support.dbs import seeded_run_db
from tests.support.trials import make_trial_config


class ReproBugPersistenceTest(unittest.TestCase):
    '''Verify persisted bug metadata and hit-count behavior.'''

    def test_worker_outcomes_only_classify_reproduced_crashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            trial = _trial_instance(root)
            crash_dir = root / 'snapshot' / 'crashes'
            crash_dir.mkdir(parents=True)
            crash = crash_dir / 'input'
            crash.write_bytes(b'test')
            batch_root = crash_dir.parent / '.crash_repro_batches' / '000000'
            batch_root.mkdir(parents=True)
            docker = Mock()
            docker.container_path.side_effect = str
            asan = 'ERROR: AddressSanitizer: heap-buffer-overflow'
            cases = [
                (0, False, '', None),
                (1, False, 'invalid arguments', None),
                (124, True, '', None),
                (124, True, asan, None),
                (-signal.SIGKILL, False, '', None),
                (-signal.SIGSEGV, False, '', 'crash|'),
                (-signal.SIGABRT, False, '', 'crash|'),
                (-7, False, '', 'crash|'),  # Linux SIGBUS, even on a macOS host.
                (-10, False, '', None),  # Linux SIGUSR1, not macOS SIGBUS.
                (1, False, asan, 'heap-buffer-overflow|'),
                (0, False, 'runtime error: signed integer overflow', 'signed integer overflow|'),
            ]
            for returncode, timed_out, stderr, expected_key in cases:
                with self.subTest(returncode=returncode, timed_out=timed_out, stderr=stderr):
                    (batch_root / 'results.json').write_text(json.dumps([{
                        'returncode': returncode, 'timeout': timed_out,
                        'stdout': '', 'stderr': stderr,
                    }]), encoding='utf-8')
                    with patch('fuzzmeter.repro.bugs.DockerClient', return_value=docker):
                        results = reproduce_crash_batch(
                            docker_runtime=Mock(), trial=trial,
                            snapshot_crashes_dir=crash_dir,
                            crash_tests=[DetectedFile('input', crash, 10_000_000_000)],
                            batch_index=0, tick_idx=1,
                        )
                    self.assertEqual([] if expected_key is None else [expected_key],
                                     [key for key, _, _ in results])
                    self.assertTrue(docker.run.call_args.kwargs['check'])
            self.assertEqual(
                'runtime error: signed integer overflow',
                (
                    crash_dir.parent
                    / '.artifacts'
                    / 'crash-repro'
                    / 'input'
                    / 'output.log'
                ).read_text(encoding='utf-8'),
            )

    def test_duplicate_bug_key_uses_earliest_reproduction_metadata_and_counts_hits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'run.db'
            seeded_run_db(db_path)
            trial = _trial_instance(root)
            reproduced = [
                ('bug-key', {
                    'issue_type': 'late-issue', 'top_func': 'late_func',
                    'frames': ['late_func'], 'output': 'late output',
                }, 30),
                ('bug-key', {
                    'issue_type': 'early-issue', 'top_func': 'early_func',
                    'frames': ['early_func'], 'output': 'early output',
                }, 10),
            ]
            save_crash_hits(db_path=db_path, run_id='run', trial=trial,
                            snapshot_id=7, reproduced=reproduced)
            bug, hits = _bug_and_hits(db_path)

        self.assertEqual('early-issue', bug['issue_type'])
        self.assertEqual('early_func', bug['top_func'])
        self.assertEqual(['early_func'], json.loads(bug['frames_json']))
        self.assertEqual('early output', bug['output'])
        self.assertEqual(10, bug['first_seen_ts'])
        self.assertEqual(7, bug['first_seen_snapshot_id'])
        self.assertEqual(2, hits[7])

    def test_snapshot_batches_are_combined_without_double_counting_on_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'run.db'
            seeded_run_db(db_path)
            trial = _trial_instance(root)
            snapshots = [
                TrialCrashSnapshot(
                    trial=trial, snapshot_id=snapshot_id,
                    snapshot_dir=root / str(snapshot_id), tick_idx=1,
                    crash_files=[DetectedFile(str(index), root / str(index), 0)
                                 for index in range(count)],
                )
                for snapshot_id, count in ((7, 65), (9, 1))
            ]
            later_batch_finished = threading.Event()

            def reproduce(**kwargs):
                first_snapshot = kwargs['snapshot_crashes_dir'].parent.name == '7'
                if first_snapshot and kwargs['batch_index'] == 0:
                    self.assertTrue(later_batch_finished.wait(timeout=5))
                else:
                    later_batch_finished.set()
                first_seen = 10 if kwargs['batch_index'] == 1 else 30
                return [('bug-key', {
                    'issue_type': 'crash', 'top_func': 'func', 'frames': ['func'],
                    'output': str(first_seen),
                }, first_seen)] * len(kwargs['crash_tests'])

            with patch('fuzzmeter.snapshot.crashes.repro_bugs.reproduce_crash_batch',
                       side_effect=reproduce) as worker:
                for _ in range(2):
                    later_batch_finished.clear()
                    process_snapshot_crashes(
                        db_path=db_path, run_id='run', tick_idx=1,
                        jobs=2, snapshots=snapshots, docker_runtime=Mock(),
                    )
                    bug, hits = _bug_and_hits(db_path)
                    self.assertEqual({7: 65, 9: 1}, hits)
                    self.assertEqual(10, bug['first_seen_ts'])
                    self.assertEqual('10', bug['output'])
                self.assertEqual(6, worker.call_count)


def _bug_and_hits(db_path: Path) -> tuple[dict, dict[int, int]]:
    db = DB.open(db_path)
    try:
        bugs = db.q('SELECT * FROM bugs')
        hits = db.q('SELECT snapshot_id, hits FROM bug_hits')
    finally:
        db.close()
    return bugs[0], {int(row['snapshot_id']): int(row['hits']) for row in hits}


def _trial_instance(root: Path) -> TrialInstance:
    config = make_trial_config(
        fuzzer='fuzzer',
        fuzzer_impl='fuzzer',
        benchmark='bench',
        fuzz_target='target',
        fuzz_target_bin=root / 'target',
        fuzz_target_input_mode='file',
        fuzz_target_timeout=1.0,
        rep_idx=0,
        trial_key='fuzzer__bench-target__rep0',
        output_paths=OutputPaths(
            corpus_root=Path('queue'),
            crashes_root=Path('crashes'),
        ),
        trial_timeout=60,
        snapshot_preprocess=None,
    )
    layout = TrialLayout.from_config(trial_dir=root / 'trial', cfg=config)
    return TrialInstance(
        db_id=1,
        config=config,
        layout=layout,
        container_name='container',
        fuzzer_dirs={'fuzzer': root / 'fuzzer'},
        start_ts=0,
    )


if __name__ == '__main__':
    unittest.main()
