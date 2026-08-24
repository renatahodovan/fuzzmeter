# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Serve the run list page and run deletion API endpoints.'''

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from flask import Blueprint, abort, jsonify, redirect, render_template, url_for

from ..services.runs_service import RunEntry, delete_run, delete_runs, list_runs
from ._common import json_object_payload, run_dirs

bp = Blueprint('runs', __name__)


@bp.get('/')
def index():
    '''Render the run list page shell.'''

    configured_run_dirs = run_dirs()
    if len(configured_run_dirs) == 1:
        return redirect(url_for('reports.run_page', run_id=configured_run_dirs[0].name))
    return render_template('runs.html')


@bp.get('/api/runs')
def api_runs():
    '''Return discovered runs for the run list page.'''

    return jsonify({'runs': [_serialize_run_entry(run) for run in list_runs(run_dirs())]})


@bp.delete('/api/run/<run_id>')
def api_delete_run(run_id: str):
    '''Delete one run directory.'''

    try:
        delete_run(run_dirs(), run_id)
    except FileNotFoundError:
        abort(404)
    except ValueError as exc:
        abort(400, description=str(exc))
    return jsonify({'ok': True})


@bp.post('/api/runs/delete')
def api_delete_runs():
    '''Delete multiple run directories.'''

    payload = json_object_payload()
    run_ids = payload.get('run_ids') or []
    if not isinstance(run_ids, list):
        abort(400, description='run_ids must be a list')
    return jsonify(delete_runs(run_dirs(), run_ids))


def _serialize_run_entry(run: RunEntry) -> dict[str, Any]:
    payload = asdict(run)
    payload['path'] = str(run.path)
    return payload
