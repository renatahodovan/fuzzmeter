# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for crash reproduction bug persistence.'''

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fuzzmeter.db import DB
from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.repro.bugs import repro_crash_batch
from fuzzmeter.trial.models import TrialImages, TrialInstance, TrialLayout
from tests.support.dbs import seeded_run_db
from tests.support.trials import make_trial_config


class ReproBugPersistenceTest(unittest.TestCase):
    '''Verify persisted bug metadata and hit-count behavior.'''

    def test_duplicate_bug_key_uses_earliest_reproduction_metadata_and_counts_hits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'run.db'
            seeded_run_db(db_path)
            trial = _trial_instance(root)

            with patch(
                'fuzzmeter.repro.bugs._reproduce_crash_batch',
                return_value=[
                    (
                        'bug-key',
                        {
                            'issue_type': 'late-issue',
                            'top_func': 'late_func',
                            'frames': ['late_func'],
                            'output': 'late output',
                        },
                        30,
                    ),
                    (
                        'bug-key',
                        {
                            'issue_type': 'early-issue',
                            'top_func': 'early_func',
                            'frames': ['early_func'],
                            'output': 'early output',
                        },
                        10,
                    ),
                ],
            ):
                repro_crash_batch(
                    db_path=db_path,
                    docker_runtime=Mock(),
                    run_id='run',
                    trial=trial,
                    snapshot_id=7,
                    snapshot_crashes_dir=root / 'snapshots' / 'crashes',
                    crash_tests=[],
                    batch_index=0,
                    repro_logs_dir=root / 'logs',
                )

            bug, hits = _bug_and_hits(db_path)

        self.assertEqual('early-issue', bug['issue_type'])
        self.assertEqual('early_func', bug['top_func'])
        self.assertEqual(['early_func'], json.loads(bug['frames_json']))
        self.assertEqual('early output', bug['output'])
        self.assertEqual(10, bug['first_seen_ts'])
        self.assertEqual(7, bug['first_seen_snapshot_id'])
        self.assertEqual(2, hits[7])

    def test_repeated_bug_key_preserves_original_metadata_and_replaces_snapshot_hits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / 'run.db'
            seeded_run_db(db_path)
            trial = _trial_instance(root)

            with patch(
                'fuzzmeter.repro.bugs._reproduce_crash_batch',
                return_value=[
                    (
                        'bug-key',
                        {
                            'issue_type': 'original-issue',
                            'top_func': 'original_func',
                            'frames': ['original_func'],
                            'output': 'original output',
                        },
                        40,
                    )
                ],
            ):
                repro_crash_batch(
                    db_path=db_path,
                    docker_runtime=Mock(),
                    run_id='run',
                    trial=trial,
                    snapshot_id=9,
                    snapshot_crashes_dir=root / 'snapshots' / 'crashes',
                    crash_tests=[],
                    batch_index=0,
                    repro_logs_dir=root / 'logs',
                )

            with patch(
                'fuzzmeter.repro.bugs._reproduce_crash_batch',
                return_value=[
                    (
                        'bug-key',
                        {
                            'issue_type': 'new-issue',
                            'top_func': 'new_func',
                            'frames': ['new_func'],
                            'output': 'new output',
                        },
                        20,
                    ),
                    (
                        'bug-key',
                        {
                            'issue_type': 'new-issue',
                            'top_func': 'new_func',
                            'frames': ['new_func'],
                            'output': 'new output',
                        },
                        20,
                    ),
                ],
            ):
                repro_crash_batch(
                    db_path=db_path,
                    docker_runtime=Mock(),
                    run_id='run',
                    trial=trial,
                    snapshot_id=9,
                    snapshot_crashes_dir=root / 'snapshots' / 'crashes',
                    crash_tests=[],
                    batch_index=1,
                    repro_logs_dir=root / 'logs',
                )

            bug, hits = _bug_and_hits(db_path)

        self.assertEqual('original-issue', bug['issue_type'])
        self.assertEqual('original_func', bug['top_func'])
        self.assertEqual(['original_func'], json.loads(bug['frames_json']))
        self.assertEqual('original output', bug['output'])
        self.assertEqual(40, bug['first_seen_ts'])
        self.assertEqual(9, bug['first_seen_snapshot_id'])
        self.assertEqual(2, hits[9])


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
        images=TrialImages(fuzzer_name='fuzzer', target_key='bench-target'),
    )
    layout = TrialLayout.from_config(trial_dir=root / 'trial', cfg=config)
    return TrialInstance(
        db_id=1,
        config=config,
        layout=layout,
        container_name='container',
        fuzzers_root=root,
        start_ts=0,
    )


if __name__ == '__main__':
    unittest.main()
