# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Provide request and application helpers shared by web routes."""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from flask import abort, current_app, request


def run_dirs() -> tuple[Path, ...]:
    """Return the configured direct run directories as absolute paths."""
    provider = current_app.config['RUN_DIRS_PROVIDER']
    return tuple(Path(path).resolve() for path in provider())


def json_object_payload() -> dict[str, Any]:
    """Decode the request body as a JSON object."""
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
