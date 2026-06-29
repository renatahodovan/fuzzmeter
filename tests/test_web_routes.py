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

try:
    from flask import Flask

    from fuzzmeter.web.routes import files_bp, reports_bp, runs_bp
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


def _app(runs_root: Path) -> Flask:
    app = Flask(__name__)
    app.config['RUNS_ROOT_PROVIDER'] = lambda: runs_root
    app.register_blueprint(runs_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(files_bp)
    return app


if __name__ == '__main__':
    unittest.main()
