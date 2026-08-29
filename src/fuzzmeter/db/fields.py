# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Define shared database row field groups used by readers.'''

from __future__ import annotations

import json

from typing import Any

TRIAL_METADATA_FIELDS = (
    'fuzzer_image',
    'build_config_json',
    'runtime_config_json',
)


def json_object(value: Any) -> dict[str, Any] | None:
    """Return a stored JSON column as the object it holds, or None when it holds no object."""
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None
