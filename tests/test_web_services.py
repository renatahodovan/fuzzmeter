# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for web service helpers.'''

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fuzzmeter.composite import CompositeMeasurement, CompositeMeasurementKey, CompositeViewStore, MetadataTriplet
from fuzzmeter.composite.registry import selection_from_key
from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.web.services import composite_service
from fuzzmeter.web.services.file_service import (
    require_run_dir,
    require_run_file,
    resolve_run_dir,
    resolve_run_file,
)
from fuzzmeter.web.services.report_service import export_static_report, load_report_payload
from fuzzmeter.web.services.runs_service import delete_runs, list_runs, parse_config


class WebFileServiceTest(unittest.TestCase):
    def test_run_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(ValueError):
                resolve_run_dir(Path(tmp_dir), '../outside')

    def test_file_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'run').mkdir()

            with self.assertRaises(ValueError):
                resolve_run_file(root, 'run', '../secret')

    def test_directory_request_resolves_to_index_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            index = root / 'run' / 'report' / 'index.html'
            index.parent.mkdir(parents=True)
            index.write_text('index', encoding='utf-8')

            self.assertEqual(index.resolve(), resolve_run_file(root, 'run', 'report'))
            self.assertEqual(index.resolve(), require_run_file(root, 'run', 'report'))

    def test_missing_run_and_file_raise_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'run').mkdir()

            with self.assertRaises(FileNotFoundError):
                require_run_dir(root, 'missing')
            with self.assertRaises(FileNotFoundError):
                require_run_file(root, 'run', 'missing.html')


class WebRunsServiceTest(unittest.TestCase):
    def test_missing_runs_root_lists_no_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.assertEqual([], list_runs(Path(tmp_dir) / 'missing'))

    def test_parse_config_extracts_web_summary_fields(self) -> None:
        config = parse_config(
            '''
            fuzzers:
              - libfuzzer
              - {name: afl, parent: ignored}
              - {parent: honggfuzz}
            targets: [alpha, 2]
            run:
              time_seconds: 30
              repetitions: 4
              parallel_jobs: 2
              snapshot:
                every_seconds: 5
            '''
        )

        self.assertEqual(['libfuzzer', 'afl', 'honggfuzz'], config.fuzzers)
        self.assertEqual(['alpha', '2'], config.targets)
        self.assertEqual(30, config.policy.time_seconds)
        self.assertEqual(4, config.policy.repetitions)
        self.assertEqual(2, config.policy.parallel_jobs)
        self.assertEqual(5, config.policy.snapshot_every_seconds)

    def test_invalid_or_non_mapping_config_is_empty(self) -> None:
        self.assertEqual([], parse_config('[not: valid').fuzzers)
        self.assertEqual([], parse_config('- just-a-list').fuzzers)

    def test_list_runs_sorts_by_candidate_mtimes_created_ts_and_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            first = root / 'first'
            second = root / 'second'
            third = root / 'third'
            for run_dir in (first, second, third):
                run_dir.mkdir()
            _touch(first, 10)
            _touch(second, 10)
            _touch(third, 10)
            _touch(first / 'ignored.bin', 100)
            _touch(first, 10)
            _touch(second / 'report' / 'data.json', 50)
            _touch(second, 10)
            _build_run_db(first, run_id='first', created_ts=90)
            _touch(first / 'fuzzmeter.db', 20)
            _touch(first, 10)
            _build_run_db(third, run_id='third', created_ts=80)
            _touch(third / 'fuzzmeter.db', 20)
            _touch(third, 10)

            entries = list_runs(root)

        self.assertEqual(['second', 'first', 'third'], [entry.run_id for entry in entries])
        self.assertEqual(50, entries[0].updated_ts)

    def test_db_summary_inferred_run_id_and_config_override_filesystem_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / 'folder-name'
            run_dir.mkdir()
            (run_dir / 'config.yaml').write_text('fuzzers: [filesystem]\n', encoding='utf-8')
            _build_run_db(
                run_dir,
                run_id='db-run',
                created_ts=70,
                config_src='''
                fuzzers: [database]
                targets: [db-target]
                run:
                  time_seconds: 11
                ''',
                with_trial_data=True,
            )

            entry = list_runs(Path(tmp_dir))[0]

        self.assertEqual('db-run', entry.run_id)
        self.assertEqual(['database'], entry.summary.config.fuzzers)
        self.assertEqual(['db-target'], entry.summary.config.targets)
        self.assertEqual(11, entry.summary.config.policy.time_seconds)
        self.assertEqual(2, entry.summary.trials)
        self.assertEqual(1, entry.summary.snapshots)
        self.assertEqual(1, entry.summary.bugs)
        self.assertEqual(1, entry.summary.benchmark_count)
        self.assertEqual(2, entry.summary.target_count)
        self.assertEqual(1, entry.summary.fuzzer_count)
        self.assertEqual({'done': 1, 'running': 1}, entry.summary.status_counts)

    def test_db_error_stays_on_run_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / 'broken'
            run_dir.mkdir()
            (run_dir / 'fuzzmeter.db').write_text('not sqlite', encoding='utf-8')

            entry = list_runs(Path(tmp_dir))[0]

        self.assertEqual('broken', entry.run_id)
        self.assertIsNotNone(entry.error)

    def test_delete_runs_reports_deleted_missing_and_invalid_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'run').mkdir()

            result = delete_runs(root, ['run', 'missing', '../outside'])

        self.assertFalse(result['ok'])
        self.assertEqual(['run'], result['deleted'])
        self.assertEqual(['missing'], result['missing'])
        self.assertEqual([{'run_id': '../outside', 'error': 'invalid run path'}], result['failed'])


class WebReportServiceTest(unittest.TestCase):
    def test_live_payload_uses_run_file_url_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_dir = root / 'run'
            run_dir.mkdir()

            with patch(
                'fuzzmeter.web.services.report_service.build_payload',
                return_value={'ok': True},
            ) as build_payload:
                self.assertEqual({'ok': True}, load_report_payload(root, 'run'))

        build_payload.assert_called_once_with(run_dir.resolve(), run_id='run', file_url_prefix='/file/run/')

    def test_static_report_exports_to_run_report_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_dir = root / 'run'
            run_dir.mkdir()
            report_dir = run_dir / 'report'

            with patch('fuzzmeter.web.services.report_service.write_report', return_value=report_dir) as write_report:
                self.assertEqual(report_dir, export_static_report(root, 'run'))

        write_report.assert_called_once_with(run_dir.resolve(), out_dir=run_dir.resolve() / 'report')


class WebCompositeServiceTest(unittest.TestCase):
    def test_composite_source_id_path_traversal_is_rejected(self) -> None:
        '''Composite selections cannot escape the configured runs root.'''
        with self.assertRaises(ValueError):
            composite_service.create_view(
                CompositeViewStore(),
                {
                    'measurements': [
                        {
                            'source_id': '../outside',
                            'run_id': 'run',
                            'fuzzer': 'fz',
                            'benchmark': 'bench',
                            'fuzz_target': 'target',
                        }
                    ]
                },
            )

    def test_view_report_data_skips_compatibility_for_all_fresh_views(self) -> None:
        first = _composite_measurement('run-a', environment={'host': {'kernel': '6.8'}})
        second = _composite_measurement('run-b', environment={'host': {'kernel': '6.9'}})
        registry = _CompositeRegistryStub([first, second])
        store = CompositeViewStore()
        view = store.create([
            selection_from_key(first.key, origin='fresh'),
            selection_from_key(second.key, origin='fresh', display_fuzzer='fz #2'),
        ])
        payload = {
            'meta': {},
            'sources': [
                _source_payload(first, fuzzer='fz', origin='fresh'),
                _source_payload(second, fuzzer='fz #2', origin='fresh'),
            ],
            'targets': [{
                'benchmark': 'bench',
                'fuzz_target': 'target',
                'fuzzers': [
                    {'fuzzer': 'fz', 'origin': 'fresh', 'source_id': 'run-a', 'source_run_id': 'run'},
                    {'fuzzer': 'fz #2', 'origin': 'fresh', 'source_id': 'run-b', 'source_run_id': 'run'},
                ],
            }],
        }

        with patch('fuzzmeter.web.services.composite_service.build_composite_payload', return_value=payload):
            result = composite_service.view_report_data(Path('/runs'), registry, store, view.view_id)

        self.assertNotIn('compatibility', result['sources'][0])
        self.assertNotIn('compatibility', result['targets'][0]['fuzzers'][0])

    def test_view_report_data_attaches_source_compatibility_to_fuzzer_rows(self) -> None:
        first = _composite_measurement('run-a', environment={'host': {'kernel': '6.8'}})
        second = _composite_measurement('run-b', environment={'host': {'kernel': '6.9'}})
        registry = _CompositeRegistryStub([first, second])
        store = CompositeViewStore()
        view = store.create([
            selection_from_key(first.key, origin='fresh'),
            selection_from_key(second.key, origin='historical', display_fuzzer='fz #2'),
        ])
        payload = {
            'meta': {},
            'sources': [
                _source_payload(first, fuzzer='fz'),
                _source_payload(second, fuzzer='fz #2'),
            ],
            'targets': [
                {
                    'benchmark': 'bench',
                    'fuzz_target': 'target',
                    'fuzzers': [
                        {
                            'fuzzer': 'fz',
                            'origin': 'fresh',
                            'selection_id': first.key.as_id(),
                            'source_id': 'run-a',
                            'source_run_id': 'run',
                            'source_fuzzer': 'fz',
                        },
                        {
                            'fuzzer': 'fz #2',
                            'origin': 'historical',
                            'selection_id': second.key.as_id(),
                            'source_id': 'run-b',
                            'source_run_id': 'run',
                            'source_fuzzer': 'fz',
                            'source_detail': {'source_id': 'run-b', 'repetitions': 3},
                        },
                    ],
                }
            ],
        }

        with patch('fuzzmeter.web.services.composite_service.build_composite_payload', return_value=payload):
            result = composite_service.view_report_data(Path('/runs'), registry, store, view.view_id)

        fuzzer = result['targets'][0]['fuzzers'][1]
        self.assertNotIn('compatibility', result['sources'][0])
        self.assertNotIn('compatibility', result['targets'][0]['fuzzers'][0])
        self.assertEqual('risky', fuzzer['compatibility']['level'])
        self.assertEqual('run-a', fuzzer['compatibility']['reference']['source_id'])
        self.assertEqual('run-b', fuzzer['source_detail']['source_id'])
        self.assertEqual(3, fuzzer['source_detail']['repetitions'])

    def test_view_report_data_warns_about_shorter_historical_policy(self) -> None:
        first = _composite_measurement(
            'run-a',
            environment={'host': {'kernel': '6.8'}},
            runtime_seconds=7200,
            repetitions=5,
        )
        second = _composite_measurement(
            'run-b',
            environment={'host': {'kernel': '6.8'}},
            runtime_seconds=3600,
            repetitions=3,
        )
        registry = _CompositeRegistryStub([first, second])
        store = CompositeViewStore()
        view = store.create([
            selection_from_key(first.key, origin='fresh'),
            selection_from_key(second.key, origin='historical', display_fuzzer='fz #2'),
        ])
        payload = {
            'meta': {},
            'sources': [
                _source_payload(first, fuzzer='fz'),
                _source_payload(second, fuzzer='fz #2'),
            ],
            'targets': [
                {
                    'benchmark': 'bench',
                    'fuzz_target': 'target',
                    'fuzzers': [
                        {'fuzzer': 'fz', 'origin': 'fresh', 'selection_id': first.key.as_id()},
                        {'fuzzer': 'fz #2', 'origin': 'historical', 'selection_id': second.key.as_id()},
                    ],
                }
            ],
        }

        with patch('fuzzmeter.web.services.composite_service.build_composite_payload', return_value=payload):
            result = composite_service.view_report_data(Path('/runs'), registry, store, view.view_id)

        compatibility = result['targets'][0]['fuzzers'][1]['compatibility']
        self.assertEqual('risky', compatibility['level'])
        self.assertEqual(['repetitions', 'runtime_seconds'], [row['path'] for row in compatibility['diffs']])


def _touch(path: Path, ts: int) -> None:
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(path.name, encoding='utf-8')
    else:
        path.mkdir(parents=True, exist_ok=True)
    os.utime(path, (ts, ts))


def _build_run_db(
    run_dir: Path,
    *,
    run_id: str,
    created_ts: int,
    config_src: str = 'fuzzers: [fz]\n',
    with_trial_data: bool = False,
) -> None:
    db = DB.open(run_dir / 'fuzzmeter.db')
    try:
        ensure_schema(db)
        db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', (run_id, created_ts, config_src))
        if with_trial_data:
            db.exec(
                '''
                INSERT INTO trials(run_id, fuzzer, benchmark, fuzz_target, rep, status)
                VALUES(?,?,?,?,?,?)
                ''',
                (run_id, 'fz', 'bench', 'target-a', 0, 'done'),
            )
            db.exec(
                '''
                INSERT INTO trials(run_id, fuzzer, benchmark, fuzz_target, rep, status)
                VALUES(?,?,?,?,?,?)
                ''',
                (run_id, 'fz', 'bench', 'target-b', 0, 'running'),
            )
            trial_id = int(db.scalar('SELECT trial_id FROM trials WHERE fuzz_target=?', ('target-a',)))
            db.exec(
                '''
                INSERT INTO snapshots(snapshot_id, trial_id, idx, ts)
                VALUES(?,?,?,?)
                ''',
                (10, trial_id, 1, 100),
            )
            db.exec(
                '''
                INSERT INTO bugs(
                  run_id, fuzzer, benchmark, fuzz_target, bug_key, first_seen_ts, first_seen_snapshot_id
                )
                VALUES(?,?,?,?,?,?,?)
                ''',
                (run_id, 'fz', 'bench', 'target-a', 'bug', 100, 10),
            )
        db.commit()
    finally:
        db.close()


class _CompositeRegistryStub:
    def __init__(self, measurements: list[CompositeMeasurement]):
        self.measurements = {measurement.key: measurement for measurement in measurements}

    def get(self, key: CompositeMeasurementKey) -> CompositeMeasurement | None:
        return self.measurements.get(key)


def _composite_measurement(
    source_id: str,
    *,
    environment: dict,
    runtime_seconds: int = 3600,
    repetitions: int = 3,
) -> CompositeMeasurement:
    key = CompositeMeasurementKey(
        source_id=source_id,
        run_id='run',
        fuzzer='fz',
        benchmark='bench',
        fuzz_target='target',
    )
    return CompositeMeasurement(
        key=key,
        source_path=Path('/runs') / source_id,
        db_path=Path('/runs') / source_id / 'fuzzmeter.db',
        metadata=MetadataTriplet(
            environment=environment,
            config={'benchmark': 'bench', 'fuzz_target': 'target'},
            source={
                'target_source': {'status': 'ok', 'data': {'revision': 'target'}},
                'fuzzer_version': {'status': 'ok', 'data': {'revision': 'fuzzer'}},
            },
        ),
        runtime_seconds=runtime_seconds,
        repetitions=repetitions,
    )


def _source_payload(measurement: CompositeMeasurement, *, fuzzer: str, origin: str | None = None) -> dict:
    return {
        'selection_id': measurement.key.as_id(),
        'origin': origin or ('fresh' if measurement.key.source_id == 'run-a' else 'historical'),
        'source_id': measurement.key.source_id,
        'run_id': measurement.key.run_id,
        'fuzzer': fuzzer,
        'source_fuzzer': measurement.key.fuzzer,
        'benchmark': measurement.key.benchmark,
        'fuzz_target': measurement.key.fuzz_target,
        'runtime_seconds': measurement.runtime_seconds,
        'repetitions': measurement.repetitions,
    }


if __name__ == '__main__':
    unittest.main()
