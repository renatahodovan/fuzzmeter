# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import argparse
import datetime
import json
import logging

from pathlib import Path
from typing import Any

from .analyzers.bug_analysis import BugAnalysis
from .analyzers.coverage_analysis import CoverageAnalysis
from .analyzers.summary_analysis import SummaryAnalysis
from .analyzers.trial_analysis import TrialAnalysis
from .coverage_sets import covered_element_keys_from_compact_sets
from .data.coverage_data import CoverageData
from .data.run_data import RunData
from .keys import COV_METRICS, FINAL_DIST_KEYS, SNAPSHOT_COVERAGE_FIELDS, TRIAL_METADATA_FIELDS
from .metrics import (
    cliffs_delta,
    mann_whitney_u_pvalue,
    maximum,
    mean,
    median,
    minimum,
    pct,
    rankdata_desc,
    safe_int,
    vargha_delaney_a12,
)
from .plugin_sections import attach_extra_sections

LOG = logging.getLogger(__name__)
CURVE_MAX_POINTS = 240


def dt(ts: int | None) -> str | None:
    '''Format a unix timestamp for the report payload.'''

    if ts is None:
        return None
    try:
        return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    except Exception:
        return None


def format_duration(seconds: int | None) -> str | None:
    '''Format an elapsed duration for the report payload.'''

    if seconds is None:
        return None
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f'{days}d')
    if hours:
        parts.append(f'{hours}h')
    if minutes:
        parts.append(f'{minutes}m')
    if secs or not parts:
        parts.append(f'{secs}s')
    return ' '.join(parts)


def _parse_json_text(value: Any) -> dict | None:
    if not value:
        return None
    try:
        parsed = json.loads(str(value))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


class ReportBuilder:
    '''Build the report JSON payload from a fuzzmeter run database.'''

    def __init__(self, run_dir: Path, *, run_id: str | None = None, url_prefix: str | None = None):
        self.run_dir = Path(run_dir).resolve()
        self.db_path = self.run_dir / 'fuzzmeter.db'
        if not self.db_path.exists():
            raise FileNotFoundError(f'Missing DB: {self.db_path}')
        self.url_prefix = url_prefix
        self._run_data = RunData(self.db_path)
        loaded = self._run_data.load(run_dir_name=self.run_dir.name, run_id=run_id)
        self.run_id = loaded.run_id
        self._overview_raw = loaded.overview_raw
        self._trial_rows = loaded.trial_rows
        self._latest_snapshots = loaded.latest_snapshots
        self._latest_agg_snapshots = loaded.latest_agg_snapshots
        self._snapshot_rows = loaded.snapshot_rows
        self._resource_telemetry_rows = loaded.resource_telemetry_rows
        self._bug_hits_by_snapshot = loaded.bug_hits_by_snapshot
        self._unique_bug_delta_by_snapshot = loaded.unique_bug_delta_by_snapshot
        self._bug_stats_by_trial = loaded.bug_stats_by_trial
        self._bugs = loaded.bugs
        self._bug_hits_by_bug = loaded.bug_hits_by_bug
        self._bug_trials_by_bug = loaded.bug_trials_by_bug
        self._coverage_data = CoverageData(self.run_dir)
        self._trial_analysis = TrialAnalysis(
            snapshot_coverage_fields=SNAPSHOT_COVERAGE_FIELDS,
            trial_version_fields=TRIAL_METADATA_FIELDS,
            safe_int=safe_int,
            pct=pct,
            dt=dt,
            parse_json_text=_parse_json_text,
        )
        self._bug_analysis = BugAnalysis(safe_int=safe_int, dt=dt)
        self._coverage_analysis = CoverageAnalysis(
            cov_metrics=COV_METRICS,
            final_output_dist_keys=FINAL_DIST_KEYS,
            curve_max_points=CURVE_MAX_POINTS,
            safe_int=safe_int,
            mean=mean,
            median=median,
            minimum=minimum,
            maximum=maximum,
            mann_whitney_u_pvalue=mann_whitney_u_pvalue,
            vargha_delaney_a12=vargha_delaney_a12,
            dt=dt,
        )
        self._summary_analysis = SummaryAnalysis(
            cov_metrics=COV_METRICS,
            mean=mean,
            rankdata_desc=rankdata_desc,
            mann_whitney_u_pvalue=mann_whitney_u_pvalue,
            cliffs_delta=cliffs_delta,
        )
        self._repo_root = Path(__file__).resolve().parents[3]
        self._coverage_set_cache: dict[tuple[str, str], set[str]] = {}

    def build(self) -> dict[str, Any]:
        '''Build the complete report payload.'''

        LOG.info('Collect overview')
        overview = self.collect_overview()
        LOG.info('Collect trials')
        trials = self.collect_trials()
        LOG.info('Collect timeseries')
        timeseries = self.collect_timeseries(trials)
        LOG.info('Collect bugs')
        bugs = self.collect_bugs()
        LOG.info('Collect target view')
        targets = self.collect_target_view(trials, timeseries, bugs)
        LOG.info('Enrich target summary metrics')
        targets = self._summary_analysis.enrich_targets(targets)
        LOG.info('Collect uniqueness matrices')
        targets = self.create_matrices(targets, trials)

        LOG.info('Collect summary scores')
        summary = self._summary_analysis.collect_summary_scores(targets)

        LOG.info('Collect extra sections')
        attach_extra_sections(
            repo_root=self._repo_root,
            run_dir=self.run_dir,
            run_id=self.run_id,
            targets=targets,
            trials=trials,
            timeseries=timeseries,
            bugs=bugs,
        )

        fuzzers = sorted({trial['fuzzer'] for trial in trials if trial.get('fuzzer')})
        benchmarks = sorted({target['benchmark'] for target in targets if target.get('benchmark')})
        target_keys = [target['key'] for target in targets]
        return {
            'meta': {
                'generated_at': dt(int(datetime.datetime.now(datetime.timezone.utc).timestamp())),
                'run_dir': str(self.run_dir),
                'run_id': self.run_id,
                'schema_version': 9,
                'mode': 'dynamic' if self.url_prefix else 'static',
            },
            'overview': overview,
            'filters': {'fuzzers': fuzzers, 'benchmarks': benchmarks, 'targets': target_keys},
            'summary': summary,
            'targets': targets,
            'trials': trials,
            'timeseries': timeseries,
            'bugs': bugs,
        }

    def collect_overview(self) -> dict[str, Any]:
        '''Collect run-level overview metadata.'''

        overview = dict(self._overview_raw)
        created = safe_int(overview.get('created_ts'))
        overview['created_ts'] = created
        overview['created_at'] = dt(created)
        trial_start_values = [safe_int(row.get('started_ts')) for row in self._trial_rows]
        trial_end_values = [safe_int(row.get('ended_ts')) for row in self._trial_rows]
        snapshot_values = [safe_int(row.get('ts')) for row in self._snapshot_rows]
        start_candidates = [value for value in trial_start_values if value is not None]
        end_candidates = [value for value in [*trial_end_values, *snapshot_values] if value is not None]
        started_ts = min(start_candidates) if start_candidates else created
        last_activity_ts = max(end_candidates) if end_candidates else started_ts
        wall_elapsed_seconds = None
        if started_ts is not None and last_activity_ts is not None:
            wall_elapsed_seconds = last_activity_ts - started_ts
        elapsed_candidates: list[int] = []
        for row in self._trial_rows:
            trial_start = safe_int(row.get('started_ts'))
            trial_end = safe_int(row.get('ended_ts'))
            time_seconds = safe_int(row.get('time_seconds'))
            if trial_start is not None and trial_end is not None and trial_end >= trial_start:
                elapsed = int(trial_end - trial_start)
                if time_seconds is not None and time_seconds > 0:
                    elapsed = min(elapsed, int(time_seconds))
                elapsed_candidates.append(elapsed)
            elif time_seconds is not None and time_seconds > 0:
                elapsed_candidates.append(int(time_seconds))
        elapsed_seconds = max(elapsed_candidates) if elapsed_candidates else wall_elapsed_seconds
        overview['started_ts'] = started_ts
        overview['started_at'] = dt(started_ts)
        overview['last_activity_ts'] = last_activity_ts
        overview['last_activity_at'] = dt(last_activity_ts)
        overview['elapsed_seconds'] = elapsed_seconds
        overview['elapsed_human'] = format_duration(elapsed_seconds)
        overview['wall_elapsed_seconds'] = wall_elapsed_seconds
        overview['wall_elapsed_human'] = format_duration(wall_elapsed_seconds)
        return overview

    @staticmethod
    def _trial_elapsed_seconds(trial: dict[str, Any]) -> int | None:
        started_ts = safe_int(trial.get('started_ts'))
        coverage = trial.get('coverage') or {}
        ended_ts = (
            safe_int(coverage.get('last_snapshot_ts'))
            or safe_int(trial.get('ended_ts'))
            or started_ts
        )
        if started_ts is None or ended_ts is None or ended_ts < started_ts:
            return None
        elapsed_seconds = int(ended_ts - started_ts)
        time_seconds = safe_int(trial.get('time_seconds'))
        if time_seconds is not None and time_seconds > 0:
            elapsed_seconds = min(elapsed_seconds, int(time_seconds))
        return elapsed_seconds

    def _rel_to_url(self, relpath: str | None) -> str | None:
        if not relpath:
            return None
        rel = str(relpath).replace('\\', '/')
        if self.url_prefix:
            return self.url_prefix.rstrip('/') + '/' + rel.lstrip('/')
        return '../' + rel

    def _coverage_sets_from_coverage_html_rel(self, coverage_html_rel: str | None) -> Path | None:
        return self._coverage_data.coverage_sets_from_coverage_html_rel(coverage_html_rel)

    def _agg_snapshot_for_fuzzer(self, fuzzer: str, benchmark: str, fuzz_target: str) -> dict[str, Any]:
        return self._latest_agg_snapshots.get((str(fuzzer), str(benchmark), str(fuzz_target)), {})

    def _aggregated_snapshot_coverage_for_fuzzer(self, fuzzer: str, benchmark: str, fuzz_target: str) -> dict[str, Any]:
        agg_snapshot = self._agg_snapshot_for_fuzzer(fuzzer, benchmark, fuzz_target)
        if not agg_snapshot:
            return {}
        return self._trial_analysis.coverage_summary_from_snapshot(agg_snapshot)

    def _covered_elements_for_path(self, coverage_path: Path, metric: str) -> set[str]:
        key = (str(coverage_path), metric)
        if key not in self._coverage_set_cache:
            self._coverage_set_cache[key] = covered_element_keys_from_compact_sets(coverage_path, metric)
        return self._coverage_set_cache[key]

    def _coverage_sets_for_fuzzer(
        self,
        benchmark: str,
        fuzz_target: str,
        fuzzer: str,
    ) -> Path | None:
        agg_snapshot = self._agg_snapshot_for_fuzzer(fuzzer, benchmark, fuzz_target)
        rel_path = agg_snapshot.get('coverage_sets_json_rel')
        if rel_path:
            path = self.run_dir / str(rel_path)
            if path.exists():
                return path
        return self._coverage_sets_from_coverage_html_rel(agg_snapshot.get('coverage_html_dir'))

    def collect_trials(self) -> list[dict[str, Any]]:
        '''Collect per-trial report rows.'''

        return self._trial_analysis.collect_trials(
            trial_rows=self._trial_rows,
            latest_snapshots=self._latest_snapshots,
            snapshot_rows=self._snapshot_rows,
            bug_stats_by_trial=self._bug_stats_by_trial,
            rel_to_url=self._rel_to_url,
        )

    def collect_timeseries(self, trials: list[dict[str, Any]]) -> dict[str, Any]:
        '''Collect per-trial snapshot time series.'''

        return self._trial_analysis.collect_timeseries(
            trials=trials,
            snapshot_rows=self._snapshot_rows,
            resource_telemetry_rows=self._resource_telemetry_rows,
            bug_hits_by_snapshot=self._bug_hits_by_snapshot,
            unique_bug_delta_by_snapshot=self._unique_bug_delta_by_snapshot,
        )

    def collect_bugs(self) -> list[dict[str, Any]]:
        '''Collect crash and bug rows.'''

        return self._bug_analysis.collect_bugs(
            bugs=self._bugs,
            bug_hits_by_bug=self._bug_hits_by_bug,
            bug_trials_by_bug=self._bug_trials_by_bug,
        )

    def collect_target_view(
        self,
        trials: list[dict[str, Any]],
        timeseries: dict[str, Any],
        bugs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        '''Collect target-level fuzzer comparison data.'''

        targets = self._coverage_analysis.collect_target_view(
            run_dir=self.run_dir,
            trials=trials,
            timeseries=timeseries,
            bugs=bugs,
            trial_version_fields=TRIAL_METADATA_FIELDS,
            trial_elapsed_seconds=self._trial_elapsed_seconds,
            coverage_sets_for_fuzzer=self._coverage_sets_for_fuzzer,
            aggregated_snapshot_coverage_for_fuzzer=self._aggregated_snapshot_coverage_for_fuzzer,
            covered_elements_for_path=self._covered_elements_for_path,
        )
        for target in targets:
            benchmark = str(target.get('benchmark') or '')
            fuzz_target = str(target.get('fuzz_target') or '')
            for fuzzer in target.get('fuzzers') or []:
                agg_snapshot = self._agg_snapshot_for_fuzzer(str(fuzzer.get('fuzzer') or ''), benchmark, fuzz_target)
                fuzzer['coverage_report'] = self._rel_to_url(agg_snapshot.get('coverage_html_dir'))
        return targets

    def create_matrices(self, targets, trials):
        empty_metric_group = {'by_metric': {}, 'has_data': False, 'available_metrics': []}
        empty_matrix = {'fuzzers': [], 'matrix': [], 'max_value': 0, 'has_data': False}
        empty_bug_table = {'fuzzers': [], 'rows': [], 'has_data': False}
        for target in targets:
            benchmark = target.get('benchmark')
            fuzz_target = target.get('fuzz_target')
            fuzzer_count = len({
                str(fuzzer.get('fuzzer') or '')
                for fuzzer in target.get('fuzzers') or []
                if fuzzer.get('fuzzer')
            })
            if benchmark and fuzz_target and fuzzer_count > 1:
                target['unique_matrix'] = self.compute_unique_matrix(trials, benchmark, fuzz_target)
                target['relcov_matrix'], target['relcov_score_by_fuzzer'] = self.compute_relcov_matrix(
                    trials,
                    benchmark,
                    fuzz_target,
                )
                target['branch_mwu_matrix'], target['branch_a12_matrix'] = self.compute_branch_stat_matrices(
                    trials,
                    benchmark,
                    fuzz_target,
                )
                self._coverage_analysis.attach_exclusive_coverage_stats(target=target)
                target['unique_bug_table'] = self._bug_analysis.compute_unique_bug_table(target)
                target['unique_bug_matrix'] = self._bug_analysis.compute_unique_bug_matrix(target)
                target['relbug_matrix'], target['relbug_score_by_fuzzer'] = self._bug_analysis.compute_rel_bug_matrix(
                    target,
                )
                self._bug_analysis.attach_exclusive_bug_stats(target)
            else:
                target['unique_matrix'] = empty_metric_group
                target['relcov_matrix'] = empty_metric_group
                target['branch_mwu_matrix'] = empty_metric_group
                target['branch_a12_matrix'] = empty_metric_group
                target['relcov_score_by_fuzzer'] = {}
                target['unique_bug_table'] = empty_bug_table
                target['unique_bug_matrix'] = empty_matrix
                target['relbug_matrix'] = empty_matrix
                target['relbug_score_by_fuzzer'] = {}
        return targets

    def compute_unique_matrix(self, trials: list[dict[str, Any]], benchmark: str, fuzz_target: str) -> dict[str, Any]:
        '''Compute per-fuzzer unique coverage matrices for a target.'''

        return self._coverage_analysis.compute_unique_matrix(
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            coverage_sets_for_fuzzer=self._coverage_sets_for_fuzzer,
            covered_elements_for_path=self._covered_elements_for_path,
        )

    def compute_relcov_matrix(self, trials: list[dict[str, Any]], benchmark: str, fuzz_target: str) -> tuple[dict[str, Any], dict[str, float]]:
        '''Compute per-fuzzer relative coverage containment matrix and scores.'''

        return self._coverage_analysis.compute_relcov_matrix(
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            coverage_sets_for_fuzzer=self._coverage_sets_for_fuzzer,
            covered_elements_for_path=self._covered_elements_for_path,
        )

    def compute_branch_stat_matrices(self, trials: list[dict[str, Any]], benchmark: str, fuzz_target: str) -> tuple[dict[str, Any], dict[str, Any]]:
        '''Compute pairwise branch-coverage significance and effect-size matrices.'''

        return self._coverage_analysis.compute_branch_stat_matrices(
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
        )


def build_payload(run_dir: Path, *, run_id: str | None = None, url_prefix: str | None = None) -> dict[str, Any]:
    '''Build the JSON payload consumed by the web report.'''

    from .api import build_payload as api_build_payload

    return api_build_payload(run_dir, run_id=run_id, url_prefix=url_prefix)


def generate_report(run_dir: Path, *, out_dir: Path | None = None, template_dir: Path | None = None) -> Path:
    '''Generate a static report directory for a fuzzmeter run.'''

    from .api import generate_report as api_generate_report

    return api_generate_report(run_dir, out_dir=out_dir, template_dir=template_dir)


def main() -> int:
    '''Run the report generator command line interface.'''

    parser = argparse.ArgumentParser(description='Generate static fuzzmeter HTML report')
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--out', dest='out_dir', type=Path, default=None)
    parser.add_argument('--templates', dest='template_dir', type=Path, default=None)
    args = parser.parse_args()
    report_dir = generate_report(args.run_dir, out_dir=args.out_dir, template_dir=args.template_dir)
    LOG.info('Report written to %s', report_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
