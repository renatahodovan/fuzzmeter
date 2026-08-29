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

from ...db.snapshot import AggSnapshotRow
from ...repro.coverage_sets import read_covered_keys


class CoverageData:
    '''Resolve and cache coverage files used by report generation.'''

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir).resolve()
        self._coverage_set_cache: dict[tuple[str, str], set[str] | None] = {}

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

    def coverage_sets_for_agg_snapshot(self, snapshot: AggSnapshotRow) -> Path | None:
        '''Return the compact coverage set artifact recorded by a campaign coverage row.'''

        return self._coverage_sets(snapshot.coverage_sets_json_rel, snapshot.coverage.coverage_html_dir)

    def coverage_sets_for_trial(self, trial: dict[str, Any]) -> Path | None:
        '''Return the compact coverage set artifact recorded by a report trial row.'''

        return self._coverage_sets(trial.get('coverage_sets_json_rel'), trial.get('coverage_html_rel'))

    def _coverage_sets(self, coverage_sets_json_rel: Any, coverage_html_rel: Any) -> Path | None:
        if coverage_sets_json_rel:
            path = self.run_dir / str(coverage_sets_json_rel)
            if path.exists():
                return path
        return self.coverage_sets_from_coverage_html_rel(coverage_html_rel)

    def covered_elements(self, coverage_path: Path, metric: str) -> set[str] | None:
        '''Return cached covered element keys for one compact coverage set metric.'''

        key = (str(coverage_path), metric)
        if key not in self._coverage_set_cache:
            self._coverage_set_cache[key] = read_covered_keys(coverage_path, metric)
        return self._coverage_set_cache[key]

    def coverage_sets_by_fuzzer(
        self,
        *,
        agg_snapshots: dict[tuple[str, str, str], AggSnapshotRow],
        fuzzers: list[str],
        benchmark: str,
        fuzz_target: str,
        metric: str,
    ) -> dict[str, set[str]]:
        '''Return per-fuzzer covered element sets for one target and metric.'''

        out: dict[str, set[str]] = {}
        for fuzzer in fuzzers:
            snapshot = agg_snapshots.get((str(fuzzer), str(benchmark), str(fuzz_target)))
            coverage_path = None if snapshot is None else self.coverage_sets_for_agg_snapshot(snapshot)
            if coverage_path is not None:
                values = self.covered_elements(coverage_path, metric)
                if values is not None:
                    out[fuzzer] = values
        return out

    def trial_coverage_sets_by_fuzzer(
        self,
        *,
        trials: list[dict[str, Any]],
        fuzzers: list[str],
        benchmark: str,
        fuzz_target: str,
        metric: str,
    ) -> dict[str, list[set[str] | None]]:
        '''Return per-trial covered element sets for one target and metric.'''

        out = {str(fuzzer): [] for fuzzer in fuzzers}
        for trial in trials:
            fuzzer = str(trial.get('fuzzer') or '')
            if (
                fuzzer not in out
                or trial.get('benchmark') != benchmark
                or trial.get('fuzz_target') != fuzz_target
            ):
                continue
            coverage_path = self.coverage_sets_for_trial(trial)
            out[fuzzer].append(
                self.covered_elements(coverage_path, metric)
                if coverage_path is not None
                else None
            )
        return {fuzzer: sets for fuzzer, sets in out.items() if sets}
