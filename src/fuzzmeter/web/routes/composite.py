# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Serve temporary composite report view APIs.'''

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from flask import Blueprint, abort, current_app, jsonify, request

from ...composite import CompositeRegistry
from ..services import composite_service

bp = Blueprint('composite', __name__)


def _runs_root() -> Path:
    provider = current_app.config['RUNS_ROOT_PROVIDER']
    return Path(provider()).resolve()


def _registry():
    runs_root = _runs_root()
    registry = current_app.config['COMPOSITE_REGISTRY']
    if Path(registry.runs_root).resolve() != runs_root:
        registry = CompositeRegistry(runs_root)
        current_app.config['COMPOSITE_REGISTRY'] = registry
    return registry


def _store():
    return current_app.config['COMPOSITE_VIEW_STORE']


@bp.errorhandler(KeyError)
def api_composite_missing_view(_exc):
    '''Return a stable expired-view response for missing temporary views.'''
    return jsonify({'status': 'expired', 'error': 'Composite view expired; recreate the comparison.'}), 404


@bp.get('/api/composite/measurements')
def api_composite_measurements():
    '''Return discoverable composite measurement descriptors.'''
    return jsonify(composite_service.list_measurements(_registry()))


@bp.post('/api/composite/sources/refresh')
def api_composite_refresh_sources():
    '''Refresh the descriptor registry.'''
    return jsonify(composite_service.refresh_sources(_registry()))


@bp.post('/api/composite/views')
def api_composite_create_view():
    '''Create a temporary composite view.'''
    try:
        return jsonify(composite_service.create_view(_store(), _json_object_payload()))
    except ValueError as exc:
        abort(400, description=str(exc))


@bp.post('/api/composite/views/from-run/<run_id>')
def api_composite_create_view_from_run(run_id: str):
    '''Create a temporary composite view from an active run.'''
    try:
        return jsonify(composite_service.create_view_from_run(_runs_root(), _store(), run_id))
    except FileNotFoundError:
        abort(404)
    except ValueError as exc:
        abort(400, description=str(exc))


@bp.post('/api/composite/views/<view_id>/measurements')
def api_composite_add_measurements(view_id: str):
    '''Add selected measurements to a temporary composite view.'''
    try:
        return jsonify(composite_service.add_measurements(_store(), view_id, _json_object_payload()))
    except ValueError as exc:
        abort(400, description=str(exc))


@bp.delete('/api/composite/views/<view_id>/measurements/<selection_id>')
def api_composite_remove_measurement(view_id: str, selection_id: str):
    '''Remove one selected measurement from a temporary composite view.'''
    return jsonify(composite_service.remove_measurement(_store(), view_id, selection_id))


@bp.get('/api/composite/views/<view_id>')
def api_composite_view(view_id: str):
    '''Return one temporary composite view summary.'''
    try:
        return jsonify(composite_service.view_summary(_runs_root(), _registry(), _store(), view_id))
    except FileNotFoundError as exc:
        abort(404, description=str(exc))


@bp.get('/api/composite/views/<view_id>/data')
def api_composite_view_data(view_id: str):
    '''Return report payload data for one temporary composite view.'''
    try:
        return jsonify(composite_service.view_report_data(_runs_root(), _registry(), _store(), view_id))
    except FileNotFoundError as exc:
        abort(404, description=str(exc))


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
