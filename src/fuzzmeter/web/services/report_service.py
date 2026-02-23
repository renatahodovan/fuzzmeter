# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from pathlib import Path
from typing import Any

from .file_service import FileService
from ...reporting.api import build_payload, generate_report


class WebReportService:

    @staticmethod
    def load_payload(runs_root: Path, run_id: str) -> dict[str, Any]:
        run_dir = FileService.resolve_run_dir(runs_root, run_id)
        if not run_dir.is_dir():
            raise FileNotFoundError(str(run_dir))
        return build_payload(run_dir, run_id=run_id, url_prefix=f"/file/{run_id}/")

    @staticmethod
    def export_report(runs_root: Path, run_id: str) -> Path:
        run_dir = FileService.resolve_run_dir(runs_root, run_id)
        if not run_dir.is_dir():
            raise FileNotFoundError(str(run_dir))
        out_dir = run_dir / "report"
        return generate_report(run_dir, out_dir=out_dir, template_dir=None)
