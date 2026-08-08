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

from flask import Blueprint, abort, jsonify, render_template, request

from ..services.report_service import export_static_report, load_report_payload
from ._common import runs_root

LOG = logging.getLogger(__name__)
bp = Blueprint('reports', __name__)


@bp.get('/run/<run_id>')
def run_page(run_id: str):
    '''Render the live report shell for a run id without validating it yet.'''

    return render_template('report.html', run_id=run_id, view_id=request.args.get('view') or None)


@bp.get('/compare/<view_id>')
def compare_page(view_id: str):
    '''Render the report shell for a temporary composite view.'''

    return render_template('report.html', run_id=None, view_id=view_id)


@bp.get('/api/run/<run_id>/data')
def api_run_data(run_id: str):
    '''Return live report data for an existing run.'''

    try:
        ts = time.time()
        payload = load_report_payload(runs_root(), run_id)
        LOG.info('Report payload for %s ready in %.2f seconds', run_id, time.time() - ts)
        return jsonify(payload)
    except FileNotFoundError as exc:
        LOG.exception('Report payload not found for %s', run_id)
        abort(404, description=str(exc))
    except Exception:
        LOG.exception('Failed to load report payload for %s', run_id)
        abort(500, description='Failed to load report data.')


@bp.post('/api/run/<run_id>/generate')
def api_generate_run(run_id: str):
    '''Generate a static report for an existing run.'''

    try:
        out = export_static_report(runs_root(), run_id)
    except FileNotFoundError:
        abort(404)
    except ValueError as exc:
        abort(400, description=str(exc))
    return jsonify({'ok': True, 'report_dir': str(out)})
