# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Serve dynamic report pages and report payload endpoints.'''

from __future__ import annotations

import logging
import time

from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, render_template

from ..services.report_service import WebReportService

LOG = logging.getLogger(__name__)
bp = Blueprint('reports', __name__)


def _runs_root() -> Path:
    provider = current_app.config['RUNS_ROOT_PROVIDER']
    return Path(provider()).resolve()


@bp.get('/run/<run_id>')
def run_page(run_id: str):
    return render_template('report.html', run_id=run_id)


@bp.get('/api/run/<run_id>/data')
def api_run_data(run_id: str):
    try:
        ts = time.time()
        payload = WebReportService.load_payload(_runs_root(), run_id)
        LOG.info('Report payload for %s ready in %.2f seconds', run_id, time.time() - ts)
        return jsonify(payload)
    except FileNotFoundError as exc:
        LOG.exception('Report payload not found for %s', run_id)
        abort(404, description=str(exc))
    except Exception as exc:
        LOG.exception('Failed to load report payload for %s', run_id)
        abort(500, description=str(exc))


@bp.post('/api/run/<run_id>/generate')
def api_generate_run(run_id: str):
    try:
        out = WebReportService.export_report(_runs_root(), run_id)
    except FileNotFoundError:
        abort(404)
    except ValueError as exc:
        abort(400, description=str(exc))
    return jsonify({'ok': True, 'report_dir': str(out)})
