# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from pathlib import Path
from typing import Any

from .generate import ReportBuilder


def build_payload(run_dir: Path, *, run_id: str | None = None, url_prefix: str | None = None) -> dict[str, Any]:
    '''Build the JSON payload consumed by the web report.'''

    builder = ReportBuilder(run_dir, run_id=run_id, url_prefix=url_prefix)
    return builder.build()
