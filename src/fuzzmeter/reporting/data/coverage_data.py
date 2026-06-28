# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Resolve and read coverage artifacts used by report generation.'''

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...repro.coverage_sets import read_covered_keys


class CoverageData:
    '''Resolve and cache coverage files used by report generation.'''

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir).resolve()
        self._coverage_set_cache: dict[tuple[str, str], set[str]] = {}

    def coverage_sets_from_coverage_html_rel(self, coverage_html_rel: str | None) -> Path | None:
        '''Return the compact coverage set artifact next to a recorded coverage HTML path.'''

        if not coverage_html_rel:
            return None
        try:
            raw_path = (self.run_dir / coverage_html_rel).resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        coverage_dir = raw_path.parent.parent if raw_path.name == 'index.html' else raw_path.parent
        candidate = coverage_dir / 'coverage-sets.json'
        if candidate.exists():
            return candidate
        return None

    def coverage_sets_for_snapshot(self, snapshot: dict[str, Any]) -> Path | None:
        '''Return the compact coverage set artifact recorded by a snapshot row.'''

        rel_path = snapshot.get('coverage_sets_json_rel')
        if rel_path:
            path = self.run_dir / str(rel_path)
            if path.exists():
                return path
        return self.coverage_sets_from_coverage_html_rel(snapshot.get('coverage_html_dir'))

    def covered_elements(self, coverage_path: Path, metric: str) -> set[str]:
        '''Return cached covered element keys for one compact coverage set metric.'''

        key = (str(coverage_path), metric)
        if key not in self._coverage_set_cache:
            self._coverage_set_cache[key] = read_covered_keys(coverage_path, metric)
        return self._coverage_set_cache[key]

    def covered_counts(self, coverage_path: Path | None, metrics: tuple[str, ...]) -> dict[str, int | None]:
        '''Return covered element counts for each requested metric.'''

        if coverage_path is None or not coverage_path.exists():
            return {f'{metric}_covered': None for metric in metrics}
        return {
            f'{metric}_covered': len(self.covered_elements(coverage_path, metric))
            for metric in metrics
        }

    def coverage_sets_by_fuzzer(
        self,
        *,
        agg_snapshots: dict[tuple[str, str, str], dict[str, Any]],
        fuzzers: list[str],
        benchmark: str,
        fuzz_target: str,
        metric: str,
    ) -> dict[str, set[str]]:
        '''Return per-fuzzer covered element sets for one target and metric.'''

        out: dict[str, set[str]] = {}
        for fuzzer in fuzzers:
            snapshot = agg_snapshots.get((str(fuzzer), str(benchmark), str(fuzz_target)), {})
            coverage_path = self.coverage_sets_for_snapshot(snapshot)
            if coverage_path is not None:
                out[fuzzer] = self.covered_elements(coverage_path, metric)
        return out
