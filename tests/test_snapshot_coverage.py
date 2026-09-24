# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for snapshot coverage orchestration.'''

from __future__ import annotations

import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import Mock, patch

from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.db import snapshot as db_snapshot
from fuzzmeter.fuzzers.models import OutputPaths
from fuzzmeter.repro.coverage_measure import CoverageBatch
from fuzzmeter.repro.coverage_state import apply_snapshot_summary
from fuzzmeter.snapshot.coverage import merge_trial_coverage_outputs, process_snapshot_coverage
from fuzzmeter.snapshot.trial_snapshot import TrialCoverageSnapshot
from fuzzmeter.trial.models import TrialInstance, TrialLayout
from tests.support.trials import make_trial_config


class SnapshotCoverageTest(unittest.TestCase):
    '''Verify snapshot coverage scheduling behavior.'''

    def test_trial_merge_includes_previous_cumulative_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            trial = _trial_instance(root)
            snapshot = TrialCoverageSnapshot(
                trial=trial,
                snapshot_id=1,
                snapshot_dir=root / 'snapshot',
                tick_idx=1,
            )
            batch = CoverageBatch(
                image='coverage-image',
                fuzz_target='target',
                input_mode='file',
                inputs=[root / 'input'],
                profdata_path=root / 'batch.profdata',
                diagnostics_dir=root / 'diagnostics',
                timeout_s=1.0,
            )

            with patch('fuzzmeter.snapshot.coverage.merge_coverage_outputs', return_value={}) as merge:
                merge_trial_coverage_outputs(
                    docker_runtime=Mock(),
                    run_dir=root / 'run',
                    snapshot=snapshot,
                    batches=[batch],
                    write_export=False,
                )

            state_dir = trial.layout.snapshots_dir / '.state' / 'coverage'

        self.assertEqual(
            [state_dir / 'merged.profdata', batch.profdata_path],
            merge.call_args.kwargs['profile_inputs'],
        )

    def test_empty_corpus_snapshots_do_not_execute_coverage_batches(self) -> None:
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

            with patch('fuzzmeter.snapshot.coverage.bootstrap_from_seed_baseline') as bootstrap, \
                 patch('fuzzmeter.snapshot.coverage.load_coverage_summary', return_value={}), \
                 patch('fuzzmeter.snapshot.coverage.apply_snapshot_summary'), \
                 patch('fuzzmeter.snapshot.coverage.execute_coverage_batches') as execute_batches:
                process_snapshot_coverage(
                    db=Mock(),
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

        self.assertEqual(0, execute_batches.call_count)
        self.assertEqual(
            trial.layout.snapshots_dir / '.state' / 'coverage',
            bootstrap.call_args.kwargs['state_dir'],
        )

    def test_trial_coverage_sets_path_is_stored_without_html_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            out_root = run_dir / 'coverage' / 'fz' / 'bench' / 'target' / 'trial'
            out_root.mkdir(parents=True)
            (out_root / 'coverage-sets.json').write_text('{}', encoding='utf-8')
            (out_root / 'measurement-provenance.json').write_text(
                json.dumps({
                    'schema_version': 2,
                    'coverage_sets': {'freshness': 'fresh', 'source_tick': 1},
                }),
                encoding='utf-8',
            )
            db = DB.open(run_dir / 'fuzzmeter.db')
            try:
                ensure_schema(db)
                db.exec('INSERT INTO runs(run_id) VALUES(?)', ('run',))
                db.exec(
                    '''
                    INSERT INTO trials(run_id, fuzzer, benchmark, fuzz_target, rep, started_ts)
                    VALUES(?,?,?,?,?,?)
                    ''',
                    ('run', 'fz', 'bench', 'target', 0, 1),
                )
                trial_id = int(db.scalar('SELECT trial_id FROM trials'))
                snapshot_id = db_snapshot.save_snapshot_data(
                    db,
                    db_snapshot.SnapshotRecord(
                        trial_db_id=trial_id,
                        tick_idx=1,
                        end_ts=10,
                        corpus_files=1,
                        execs_done=1,
                        stats=None,
                        crashes=0,
                        hangs=0,
                    ),
                )

                apply_snapshot_summary(
                    db=db,
                    run_dir=run_dir,
                    snapshot_id=snapshot_id,
                    out_root=out_root,
                    summary={
                        'cov_lines_covered': 1,
                        'cov_lines_total': 1,
                        'cov_branches_covered': 1,
                        'cov_branches_total': 2,
                    },
                )
                row = db.q1(
                    '''
                    SELECT coverage_html_dir, coverage_sets_json_rel,
                           measurement_provenance_json
                      FROM snapshots
                     WHERE snapshot_id=?
                    ''',
                    (snapshot_id,),
                )
            finally:
                db.close()

        self.assertIsNone(row['coverage_html_dir'])
        self.assertEqual(
            'coverage/fz/bench/target/trial/coverage-sets.json',
            row['coverage_sets_json_rel'],
        )
        provenance = json.loads(row['measurement_provenance_json'])
        self.assertEqual('fresh', provenance['coverage_sets']['freshness'])


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
