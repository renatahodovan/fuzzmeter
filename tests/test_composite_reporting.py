# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for composite report payload assembly.'''

from __future__ import annotations

import json
import tempfile
import unittest

from pathlib import Path

from fuzzmeter.composite import (
    COMPOSITE_ORIGIN_FRESH,
    COMPOSITE_ORIGIN_HISTORICAL,
)
from fuzzmeter.composite.registry import selection_from_key
from fuzzmeter.db import DB
from fuzzmeter.reporting.composite import build_composite_payload
from fuzzmeter.reporting.metrics import mann_whitney_u_pvalue
from tests.support.composite import make_measurement
from tests.support.dbs import reporting_run_db


class CompositeReportingTest(unittest.TestCase):
    '''Verify selected measurements render as full report series.'''

    def test_composite_branch_statistics_use_per_trial_counts(self) -> None:
        '''Composite branch matrices use the final count from every selected trial.'''
        with tempfile.TemporaryDirectory() as tmp:
            payload = _composite_payload_with_trial_coverage(Path(tmp))

        matrix = payload['targets'][0]['branch_mwu_matrix']['by_metric']['branches']
        a12_matrix = payload['targets'][0]['branch_a12_matrix']['by_metric']['branches']
        self.assertTrue(matrix['has_data'])
        self.assertEqual([3, 3], matrix['sample_sizes'])
        self.assertAlmostEqual(
            mann_whitney_u_pvalue([1, 2, 3], [10, 11, 12]),
            matrix['matrix'][0][1],
        )
        self.assertEqual(0.0, a12_matrix['matrix'][0][1])
        self.assertEqual(1.0, a12_matrix['matrix'][1][0])

    def test_composite_relcov_uses_per_trial_sets(self) -> None:
        '''Composite RelCov labels and values both describe per-trial coverage sets.'''
        with tempfile.TemporaryDirectory() as tmp:
            payload = _composite_payload_with_trial_coverage(Path(tmp))

        matrix = payload['targets'][0]['relcov_matrix']['by_metric']['branches']
        self.assertEqual('per-trial median compact branches coverage sets', matrix['aggregation'])
        self.assertFalse(matrix['uses_aggregate_fallback'])
        self.assertEqual([], matrix['aggregate_fallback_fuzzers'])
        self.assertEqual(
            [[100.0 / 3.0, 25.0], [100.0, 100.0]],
            matrix['matrix'],
        )

    def test_build_composite_payload_merges_selected_series(self) -> None:
        '''Two selected run series appear together under one target.'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_a = root / 'run-a'
            run_b = root / 'run-b'
            run_a.mkdir()
            run_b.mkdir()
            reporting_run_db(run_a)
            reporting_run_db(run_b)

            first = make_measurement(
                source_id='run-a',
                source_path=run_a,
                environment={},
                source={},
                runtime_seconds=60,
                repetitions=1,
            )
            second = make_measurement(
                source_id='run-b',
                source_path=run_b,
                environment={},
                source={},
                runtime_seconds=60,
                repetitions=1,
            )
            payload = build_composite_payload(
                [
                    (selection_from_key(first.key, origin=COMPOSITE_ORIGIN_FRESH), first),
                    (selection_from_key(second.key, origin=COMPOSITE_ORIGIN_HISTORICAL), second),
                ]
            )

        self.assertEqual(1, len(payload['targets']))
        self.assertEqual(['fz', 'fz #2'], [entry['fuzzer'] for entry in payload['targets'][0]['fuzzers']])
        self.assertEqual('run-b', payload['targets'][0]['fuzzers'][1]['source_detail']['source_id'])
        self.assertIn('metadata', payload['targets'][0]['fuzzers'][1])
        self.assertEqual(['fresh', 'historical'], [source['origin'] for source in payload['sources']])
        self.assertNotIn('source', payload['sources'][0])
        self.assertEqual(first.key.as_id(), payload['sources'][0]['selection_id'])
        self.assertEqual(['run-a:1', 'run-b:1'], [trial['trial_id'] for trial in payload['trials']])
        self.assertTrue(payload['targets'][0]['relbug_matrix']['has_data'] is False)

    def test_missing_source_fuzzer_is_reported_as_skipped_source(self) -> None:
        '''Descriptors whose report data is incomplete stay visible as skipped sources.'''
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / 'run-a'
            run_dir.mkdir()
            reporting_run_db(run_dir)
            measurement = make_measurement(
                source_id='run-a',
                source_path=run_dir,
                environment={},
                source={},
                runtime_seconds=60,
                repetitions=1,
            )
            missing_fuzzer = make_measurement(
                source_id='run-a',
                fuzzer='missing',
                source_path=run_dir,
                environment={},
                source={},
                runtime_seconds=60,
                repetitions=1,
            )

            payload = build_composite_payload(
                [
                    (selection_from_key(measurement.key, origin=COMPOSITE_ORIGIN_FRESH), measurement),
                    (selection_from_key(missing_fuzzer.key, origin=COMPOSITE_ORIGIN_HISTORICAL), missing_fuzzer),
                ]
            )

        skipped = payload['sources'][1]
        self.assertEqual('skipped', skipped['status'])
        self.assertIn('Fuzzer data not found', skipped['error'])
        self.assertEqual('missing', skipped['source_fuzzer'])


def _composite_payload_with_trial_coverage(root: Path) -> dict:
    '''Build a two-source composite with three distinguishable trials per source.'''
    measurements = []
    trial_sets_by_source = {
        'run-a': [{1}, {2}, {3}],
        'run-b': [{1, 2, 3, 4}, {1, 2, 3, 4}, {1, 2, 3, 4}],
    }
    branch_counts_by_source = {
        'run-a': [1, 2, 3],
        'run-b': [10, 11, 12],
    }
    for source_id in ('run-a', 'run-b'):
        run_dir = root / source_id
        run_dir.mkdir()
        reporting_run_db(run_dir)
        db = DB.open(run_dir / 'fuzzmeter.db')
        try:
            first_trial_id = int(db.scalar('SELECT trial_id FROM trials'))
            trial_ids = [first_trial_id]
            for rep in (1, 2):
                db.exec(
                    '''
                    INSERT INTO trials(
                      run_id, fuzzer, benchmark, fuzz_target, rep, time_seconds,
                      jobs, status, started_ts, ended_ts
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                    ''',
                    ('run', 'fz', 'bench', 'target', rep, 60, 1, 'done', 100, 160),
                )
                trial_ids.append(int(db.scalar('SELECT trial_id FROM trials WHERE rep=?', (rep,))))

            for rep, (trial_id, branch_count, covered_set) in enumerate(zip(
                trial_ids,
                branch_counts_by_source[source_id],
                trial_sets_by_source[source_id],
                strict=True,
            )):
                coverage_html_rel = f'coverage/trial-{rep}/html/index.html'
                if rep == 0:
                    db.exec(
                        '''
                        UPDATE snapshots
                           SET cov_branches_covered=?, cov_branches_total=?,
                               coverage_html_dir=?
                         WHERE trial_id=? AND idx=2
                        ''',
                        (branch_count, 20, coverage_html_rel, trial_id),
                    )
                else:
                    db.exec(
                        '''
                        INSERT INTO snapshots(
                          trial_id, idx, ts, cov_branches_covered,
                          cov_branches_total, coverage_html_dir
                        )
                        VALUES(?,?,?,?,?,?)
                        ''',
                        (trial_id, 2, 160, branch_count, 20, coverage_html_rel),
                    )
                coverage_sets = run_dir / f'coverage/trial-{rep}/coverage-sets.json'
                coverage_sets.parent.mkdir(parents=True, exist_ok=True)
                coverage_sets.write_text(
                    json.dumps({
                        'metrics': {
                            'lines': [],
                            'branches': sorted(covered_set),
                            'functions': [],
                            'regions': [],
                        },
                    }),
                    encoding='utf-8',
                )

            aggregate_html_rel = 'coverage/aggregate/html/index.html'
            db.exec(
                '''
                INSERT INTO agg_snapshots(
                  run_id, fuzzer, benchmark, fuzz_target, idx, ts,
                  coverage_html_dir, cov_branches_covered, cov_branches_total
                )
                VALUES(?,?,?,?,?,?,?,?,?)
                ''',
                (
                    'run', 'fz', 'bench', 'target', 2, 160, aggregate_html_rel,
                    len(set().union(*trial_sets_by_source[source_id])), 20,
                ),
            )
            db.commit()
        finally:
            db.close()

        aggregate_sets = run_dir / 'coverage/aggregate/coverage-sets.json'
        aggregate_sets.parent.mkdir(parents=True, exist_ok=True)
        aggregate_sets.write_text(
            json.dumps({
                'metrics': {
                    'lines': [],
                    'branches': sorted(set().union(*trial_sets_by_source[source_id])),
                    'functions': [],
                    'regions': [],
                },
            }),
            encoding='utf-8',
        )
        measurements.append(make_measurement(
            source_id=source_id,
            source_path=run_dir,
            environment={},
            source={},
            runtime_seconds=60,
            repetitions=3,
        ))

    return build_composite_payload([
        (
            selection_from_key(measurement.key, origin=COMPOSITE_ORIGIN_FRESH),
            measurement,
        )
        for measurement in measurements
    ])


if __name__ == '__main__':
    unittest.main()
