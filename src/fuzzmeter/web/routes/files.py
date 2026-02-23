# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.
 
from __future__ import annotations

from flask import Blueprint, abort, current_app, send_from_directory

from ..services.file_service import FileService

bp = Blueprint("files", __name__)


@bp.get("/file/<run_id>/<path:relpath>")
def serve_run_file(run_id: str, relpath: str):
    try:
        provider = current_app.config["RUNS_ROOT_PROVIDER"]
        full = FileService.resolve_run_file(provider(), run_id, relpath)
    except ValueError as exc:
        abort(400, description=str(exc))

    if not full.is_file():
        abort(404)

    return send_from_directory(str(full.parent), full.name)
