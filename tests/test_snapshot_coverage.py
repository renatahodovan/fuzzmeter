# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for snapshot coverage orchestration.'''

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.snapshot.coverage import process_snapshot_coverage
from fuzzmeter.snapshot.trial_snapshot import TrialCoverageSnapshot
from fuzzmeter.trial.models import TrialConfig, TrialImages, TrialInstance, TrialLayout


class SnapshotCoverageTest(unittest.TestCase):
    '''Verify snapshot coverage replay scheduling behavior.'''

    def test_empty_corpus_snapshots_do_not_replay_coverage_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            trial = _trial_instance(root)
            snapshot_dir = root / 'snapshot'
            (snapshot_dir / 'corpus').mkdir(parents=True)
            snapshot = TrialCoverageSnapshot(
                trial=trial,
                snapshot_id=1,
                snapshot_dir=snapshot_dir,
                tick_idx=1,
            )

            with patch('fuzzmeter.snapshot.coverage.bootstrap_from_seed_baseline'), \
                 patch('fuzzmeter.snapshot.coverage.load_coverage_summary', return_value={}), \
                 patch('fuzzmeter.snapshot.coverage.apply_snapshot_summary'), \
                 patch('fuzzmeter.snapshot.coverage.replay_coverage_batches') as replay_batches:
                process_snapshot_coverage(
                    db=Mock(),
                    db_path=root / 'state.db',
                    run_dir=root / 'run',
                    run_id='run',
                    tick_idx=1,
                    ts=10,
                    jobs=1,
                    snapshots=[snapshot],
                    campaign_trials=[trial],
                    docker_runtime=Mock(),
                    write_export=True,
                )

        self.assertEqual(0, replay_batches.call_count)


def _trial_instance(root: Path) -> TrialInstance:
    config = TrialConfig(
        fuzzer='fuzzer',
        fuzzer_base='fuzzer',
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
        images=TrialImages(fuzzer_name='fuzzer', target_id='bench-target'),
    )
    layout = TrialLayout.from_config(trial_dir=root / 'trial', cfg=config)
    return TrialInstance(
        db_id=1,
        config=config,
        layout=layout,
        container_name='container',
        repo_root=root,
        start_ts=0,
    )


if __name__ == '__main__':
    unittest.main()
