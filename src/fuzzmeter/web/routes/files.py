# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Serve files that belong to discovered run directories.'''

from __future__ import annotations

from flask import Blueprint, abort, send_from_directory

from ..services.file_service import require_run_file
from ._common import run_dirs

bp = Blueprint('files', __name__)


@bp.get('/file/<run_id>/<path:relpath>')
def serve_run_file(run_id: str, relpath: str):
    '''Serve one existing file from a run directory.'''

    try:
        full = require_run_file(run_dirs(), run_id, relpath)
    except ValueError as exc:
        abort(400, description=str(exc))
    except FileNotFoundError:
        abort(404)

    return send_from_directory(str(full.parent), full.name)
