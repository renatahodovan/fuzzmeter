# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for Flask web route boundaries.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

try:
    from flask import Flask

    from fuzzmeter.composite import CompositeRegistry, CompositeViewStore
    from fuzzmeter.web.app import configure_run_dirs
    from fuzzmeter.web.routes import composite_bp, files_bp, reports_bp, runs_bp
    from tests.support.dbs import measurement_run_db
except ModuleNotFoundError as exc:
    FLASK_IMPORT_ERROR = exc
else:
    FLASK_IMPORT_ERROR = None


@unittest.skipIf(FLASK_IMPORT_ERROR is not None, 'Flask is not installed in this environment')
class WebRoutesTest(unittest.TestCase):
    def test_api_runs_serializes_service_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_dir = root / 'run'
            run_dir.mkdir()
            app = _app(run_dir)

            response = app.test_client().get('/api/runs')

        self.assertEqual(200, response.status_code)
        self.assertEqual('run', response.json['runs'][0]['run_id'])
        self.assertEqual('run', response.json['runs'][0]['directory_name'])
        self.assertEqual(str((root / 'run').resolve()), response.json['runs'][0]['path'])
        self.assertEqual({}, response.json['runs'][0]['summary']['status_counts'])

    def test_single_delete_traversal_returns_bad_request(self) -> None:
        response = _app().test_client().delete('/api/run/%2E%2E')

        self.assertEqual(400, response.status_code)

    def test_bulk_delete_reports_invalid_missing_and_deleted_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_dir = root / 'run'
            run_dir.mkdir()
            response = _app(run_dir).test_client().post('/api/runs/delete', json={'run_ids': ['run', 'missing', '..']})

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                'ok': False,
                'deleted': ['run'],
                'missing': ['missing'],
                'failed': [{'run_id': '..', 'error': 'invalid run path'}],
            },
            response.json,
        )

    def test_bulk_delete_rejects_malformed_json(self) -> None:
        response = _app().test_client().post(
            '/api/runs/delete',
            data='{',
            content_type='application/json',
        )

        self.assertEqual(400, response.status_code)

    def test_bulk_delete_rejects_non_list_run_ids(self) -> None:
        response = _app().test_client().post('/api/runs/delete', json={'run_ids': 'run'})

        self.assertEqual(400, response.status_code)

    def test_file_route_serves_directory_index_and_reports_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_dir = root / 'run'
            index = run_dir / 'report' / 'index.html'
            index.parent.mkdir(parents=True)
            index.write_text('static report', encoding='utf-8')
            client = _app(run_dir).test_client()

            ok_response = client.get('/file/run/report')
            missing_response = client.get('/file/run/missing.html')

        self.assertEqual(200, ok_response.status_code)
        self.assertEqual(b'static report', ok_response.data)
        self.assertEqual(404, missing_response.status_code)

    def test_report_data_missing_run_returns_not_found(self) -> None:
        response = _app().test_client().get('/api/run/missing/data')

        self.assertEqual(404, response.status_code)

    def test_report_data_failure_hides_exception_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            secret_path = str(Path(tmp_dir) / 'secret.db')
            with patch(
                'fuzzmeter.web.routes.reports.load_report_payload',
                side_effect=RuntimeError(secret_path),
            ):
                response = _app().test_client().get('/api/run/run/data')

        self.assertEqual(500, response.status_code)
        self.assertIn(b'Failed to load report data.', response.data)
        self.assertNotIn(secret_path.encode(), response.data)

    def test_composite_view_create_and_get(self) -> None:
        client = _app().test_client()

        created = client.post(
            '/api/composite/views',
            json={
                'measurements': [
                    {
                        'source_id': 'source',
                        'run_id': 'run',
                        'fuzzer': 'fz',
                        'benchmark': 'bench',
                        'fuzz_target': 'target',
                    }
                ]
            },
        )
        loaded = client.get(f'/api/composite/views/{created.json["view_id"]}')

        self.assertEqual(200, created.status_code)
        self.assertEqual(200, loaded.status_code)
        self.assertEqual('source', loaded.json['selections'][0]['key']['source_id'])
        self.assertEqual('missing', loaded.json['sources'][0]['status'])

    def test_composite_measurements_endpoint_has_nested_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            measurement_run_db(
                root / 'run-a',
                source_id='run-a',
                fuzzer='fz',
                benchmark='bench',
                fuzz_target='target',
                environment={},
            )
            response = _app(root / 'run-a').test_client().get('/api/composite/measurements')

        self.assertEqual(200, response.status_code)
        measurement = response.json['measurements'][0]
        self.assertEqual('run-a', measurement['key']['source_id'])
        self.assertEqual('bench', measurement['key']['benchmark'])

    def test_composite_measurements_rebinds_stale_registry_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_dir = root / 'run-a'
            measurement_run_db(
                run_dir,
                source_id='run-a',
                fuzzer='fz',
                benchmark='bench',
                fuzz_target='target',
                environment={},
            )
            app = _app()
            app.config['RUN_DIRS_PROVIDER'] = lambda: (run_dir,)

            response = app.test_client().post('/api/composite/sources/refresh')

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, len(response.json['measurements']))

    def test_single_run_index_redirects_and_duplicate_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_dir = root / 'run-a'
            run_dir.mkdir(parents=True)
            (run_dir / 'fuzzmeter.db').write_text('', encoding='utf-8')
            duplicate = root / 'other' / 'run-a'
            duplicate.mkdir(parents=True)
            (duplicate / 'fuzzmeter.db').write_text('', encoding='utf-8')

            response = _app(run_dir).test_client().get('/')
            with self.assertRaisesRegex(ValueError, 'Duplicate run directory name: run-a'):
                configure_run_dirs([run_dir, duplicate])

        self.assertEqual(302, response.status_code)
        self.assertTrue(response.location.endswith('/run/run-a'))

    def test_composite_expired_view_returns_not_found(self) -> None:
        response = _app().test_client().get('/api/composite/views/missing')

        self.assertEqual(404, response.status_code)


def _app(*run_dirs: Path) -> Flask:
    app = Flask(__name__)
    app.config['RUN_DIRS_PROVIDER'] = lambda: run_dirs
    app.config['COMPOSITE_REGISTRY'] = CompositeRegistry(run_dirs)
    app.config['COMPOSITE_VIEW_STORE'] = CompositeViewStore()
    app.register_blueprint(runs_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(composite_bp)
    app.register_blueprint(files_bp)
    return app


if __name__ == '__main__':
    unittest.main()
