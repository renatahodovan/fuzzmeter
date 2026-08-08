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
    from fuzzmeter.web.app import resolve_runs_root
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
            (root / 'run').mkdir()
            app = _app(root)

            response = app.test_client().get('/api/runs')

        self.assertEqual(200, response.status_code)
        self.assertEqual('run', response.json['runs'][0]['run_id'])
        self.assertEqual(str((root / 'run').resolve()), response.json['runs'][0]['path'])
        self.assertEqual({}, response.json['runs'][0]['summary']['status_counts'])

    def test_single_delete_traversal_returns_bad_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            response = _app(Path(tmp_dir)).test_client().delete('/api/run/%2E%2E')

        self.assertEqual(400, response.status_code)

    def test_bulk_delete_reports_invalid_missing_and_deleted_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'run').mkdir()
            response = _app(root).test_client().post('/api/runs/delete', json={'run_ids': ['run', 'missing', '..']})

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
        with tempfile.TemporaryDirectory() as tmp_dir:
            response = _app(Path(tmp_dir)).test_client().post(
                '/api/runs/delete',
                data='{',
                content_type='application/json',
            )

        self.assertEqual(400, response.status_code)

    def test_bulk_delete_rejects_non_list_run_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            response = _app(Path(tmp_dir)).test_client().post('/api/runs/delete', json={'run_ids': 'run'})

        self.assertEqual(400, response.status_code)

    def test_file_route_serves_directory_index_and_reports_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            index = root / 'run' / 'report' / 'index.html'
            index.parent.mkdir(parents=True)
            index.write_text('static report', encoding='utf-8')
            client = _app(root).test_client()

            ok_response = client.get('/file/run/report')
            missing_response = client.get('/file/run/missing.html')

        self.assertEqual(200, ok_response.status_code)
        self.assertEqual(b'static report', ok_response.data)
        self.assertEqual(404, missing_response.status_code)

    def test_report_data_missing_run_returns_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            response = _app(Path(tmp_dir)).test_client().get('/api/run/missing/data')

        self.assertEqual(404, response.status_code)

    def test_report_data_failure_hides_exception_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            secret_path = str(Path(tmp_dir) / 'secret.db')
            with patch(
                'fuzzmeter.web.routes.reports.load_report_payload',
                side_effect=RuntimeError(secret_path),
            ):
                response = _app(Path(tmp_dir)).test_client().get('/api/run/run/data')

        self.assertEqual(500, response.status_code)
        self.assertIn(b'Failed to load report data.', response.data)
        self.assertNotIn(secret_path.encode(), response.data)

    def test_composite_view_create_and_get(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = _app(Path(tmp_dir)).test_client()

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
            response = _app(root).test_client().get('/api/composite/measurements')

        self.assertEqual(200, response.status_code)
        measurement = response.json['measurements'][0]
        self.assertEqual('run-a', measurement['key']['source_id'])
        self.assertEqual('bench', measurement['key']['benchmark'])
        self.assertEqual(str(root.resolve()), response.json['runs_root'])

    def test_composite_measurements_rebinds_stale_registry_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            stale_root = root / 'stale'
            runs_root = root / 'runs'
            stale_root.mkdir()
            measurement_run_db(
                runs_root / 'run-a',
                source_id='run-a',
                fuzzer='fz',
                benchmark='bench',
                fuzz_target='target',
                environment={},
            )
            app = _app(stale_root)
            app.config['RUNS_ROOT_PROVIDER'] = lambda: runs_root

            response = app.test_client().post('/api/composite/sources/refresh')

        self.assertEqual(200, response.status_code)
        self.assertEqual(str(runs_root.resolve()), response.json['runs_root'])
        self.assertEqual(1, len(response.json['measurements']))

    def test_resolve_runs_root_accepts_output_runs_and_single_run_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            runs_root = root / 'runs'
            run_dir = runs_root / 'run-a'
            run_dir.mkdir(parents=True)
            (run_dir / 'fuzzmeter.db').write_text('', encoding='utf-8')

            self.assertEqual(runs_root.resolve(), resolve_runs_root(root))
            self.assertEqual(runs_root.resolve(), resolve_runs_root(runs_root))
            self.assertEqual(runs_root.resolve(), resolve_runs_root(run_dir))

    def test_composite_expired_view_returns_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            response = _app(Path(tmp_dir)).test_client().get('/api/composite/views/missing')

        self.assertEqual(404, response.status_code)


def _app(runs_root: Path) -> Flask:
    app = Flask(__name__)
    app.config['RUNS_ROOT_PROVIDER'] = lambda: runs_root
    app.config['COMPOSITE_REGISTRY'] = CompositeRegistry(runs_root)
    app.config['COMPOSITE_VIEW_STORE'] = CompositeViewStore()
    app.register_blueprint(runs_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(composite_bp)
    app.register_blueprint(files_bp)
    return app


if __name__ == '__main__':
    unittest.main()
