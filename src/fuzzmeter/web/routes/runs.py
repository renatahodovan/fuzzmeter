# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from ..services.runs_service import RunsService

bp = Blueprint("runs", __name__)


def _runs_root() -> Path:
    provider = current_app.config["RUNS_ROOT_PROVIDER"]
    return Path(provider()).resolve()


@bp.get("/")
def index():
    return render_template("runs.html")


@bp.get("/api/runs")
def api_runs():
    return jsonify({"runs": RunsService.list_runs(_runs_root())})


@bp.delete("/api/run/<run_id>")
def api_delete_run(run_id: str):
    try:
        RunsService.delete_run(_runs_root(), run_id)
    except FileNotFoundError:
        abort(404)
    except ValueError as exc:
        abort(400, description=str(exc))
    return jsonify({"ok": True})


@bp.post("/api/runs/delete")
def api_delete_runs():
    payload = request.get_json(silent=True) or {}
    run_ids = payload.get("run_ids") or []
    if not isinstance(run_ids, list):
        abort(400, description="run_ids must be a list")
    return jsonify(RunsService.delete_runs(_runs_root(), run_ids))
