# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Serve the run list page and run deletion API endpoints.'''

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from ..services.runs_service import RunEntry, delete_run, delete_runs, list_runs

bp = Blueprint('runs', __name__)


def _runs_root() -> Path:
    provider = current_app.config['RUNS_ROOT_PROVIDER']
    return Path(provider()).resolve()


@bp.get('/')
def index():
    '''Render the run list page shell.'''

    return render_template('runs.html')


@bp.get('/api/runs')
def api_runs():
    '''Return discovered runs for the run list page.'''

    return jsonify({'runs': [_serialize_run_entry(run) for run in list_runs(_runs_root())]})


@bp.delete('/api/run/<run_id>')
def api_delete_run(run_id: str):
    '''Delete one run directory.'''

    try:
        delete_run(_runs_root(), run_id)
    except FileNotFoundError:
        abort(404)
    except ValueError as exc:
        abort(400, description=str(exc))
    return jsonify({'ok': True})


@bp.post('/api/runs/delete')
def api_delete_runs():
    '''Delete multiple run directories.'''

    payload = _json_object_payload()
    run_ids = payload.get('run_ids') or []
    if not isinstance(run_ids, list):
        abort(400, description='run_ids must be a list')
    return jsonify(delete_runs(_runs_root(), run_ids))


def _json_object_payload() -> dict[str, Any]:
    if not request.data:
        return {}
    try:
        payload = json.loads(request.get_data(as_text=True))
    except json.JSONDecodeError as exc:
        abort(400, description=str(exc))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        abort(400, description='JSON body must be an object')
    return payload


def _serialize_run_entry(run: RunEntry) -> dict[str, Any]:
    payload = asdict(run)
    payload['path'] = str(run.path)
    return payload
