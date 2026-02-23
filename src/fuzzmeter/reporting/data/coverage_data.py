# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import json

from pathlib import Path


class CoverageData:
    '''Resolve and cache coverage files used by report generation.'''

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir).resolve()

    def coverage_sets_from_coverage_html_rel(self, coverage_html_rel: str | None) -> Path | None:
        '''Return the compact coverage set artifact next to a recorded coverage HTML path.'''

        if not coverage_html_rel:
            return None
        try:
            raw_path = (self.run_dir / coverage_html_rel).resolve()
        except Exception:
            return None
        coverage_dir = raw_path.parent.parent if raw_path.name == 'index.html' else raw_path.parent
        candidate = coverage_dir / 'coverage-sets.json'
        if candidate.exists():
            return candidate
        return None
