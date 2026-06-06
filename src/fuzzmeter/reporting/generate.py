# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Assemble and export the full fuzzmeter web report payload.'''

from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .analyzers.bug_analysis import BugAnalysis
from .analyzers.coverage_analysis import CoverageAnalysis
from .analyzers.summary_analysis import SummaryAnalysis
from .analyzers.trial_analysis import TrialAnalysis
from .data.coverage_data import CoverageData
from .data.run_data import RunData
from .keys import COV_METRICS, FINAL_DIST_KEYS, SNAPSHOT_COVERAGE_FIELDS, TRIAL_METADATA_FIELDS
from .metrics import dt, safe_int
from .plugin_sections import attach_extra_sections

LOG = logging.getLogger(__name__)
CURVE_MAX_POINTS = 240


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
        )
        self._bug_analysis = BugAnalysis()
        self._coverage_analysis = CoverageAnalysis(
            cov_metrics=COV_METRICS,
            final_output_dist_keys=FINAL_DIST_KEYS,
            curve_max_points=CURVE_MAX_POINTS,
        )
        self._summary_analysis = SummaryAnalysis(cov_metrics=COV_METRICS)
        self._repo_root = Path(__file__).resolve().parents[3]

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

    def _rel_to_url(self, relpath: str | None) -> str | None:
        if not relpath:
            return None
        rel = str(relpath).replace('\\', '/')
        if self.url_prefix:
            return self.url_prefix.rstrip('/') + '/' + rel.lstrip('/')
        return '../' + rel

    def _agg_snapshot_for_fuzzer(self, fuzzer: str, benchmark: str, fuzz_target: str) -> dict[str, Any]:
        return self._latest_agg_snapshots.get((str(fuzzer), str(benchmark), str(fuzz_target)), {})

    def _aggregated_coverage_for_fuzzer(self, fuzzer: str, benchmark: str, fuzz_target: str) -> dict[str, int | None]:
        agg_snapshot = self._agg_snapshot_for_fuzzer(fuzzer, benchmark, fuzz_target)
        coverage_path = self._coverage_data.coverage_sets_for_snapshot(agg_snapshot)
        aggregated_coverage = self._coverage_data.covered_counts(coverage_path, COV_METRICS)
        agg_snapshot_coverage = (
            self._trial_analysis.coverage_summary_from_snapshot(agg_snapshot)
            if agg_snapshot
            else {}
        )
        for metric in COV_METRICS:
            summary_covered = safe_int(agg_snapshot_coverage.get(f'{metric}_covered'))
            if summary_covered is None:
                continue
            summary_count = int(summary_covered)
            current_count = aggregated_coverage.get(f'{metric}_covered')
            if current_count is None or metric == 'branches' or summary_count > int(current_count):
                aggregated_coverage[f'{metric}_covered'] = summary_count
        return aggregated_coverage

    @staticmethod
    def _coverage_keys_from_trials(trials: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
        return sorted({
            (str(trial.get('fuzzer')), str(trial.get('benchmark')), str(trial.get('fuzz_target')))
            for trial in trials
            if trial.get('fuzzer') and trial.get('benchmark') and trial.get('fuzz_target')
        })

    def _target_coverage_inputs(
        self,
        trials: list[dict[str, Any]],
    ) -> tuple[
        dict[tuple[str, str, str], dict[str, int | None]],
        dict[tuple[str, str, str], dict[str, Any] | None],
    ]:
        aggregated_coverage_by_fuzzer: dict[tuple[str, str, str], dict[str, int | None]] = {}
        seed_baseline_by_fuzzer: dict[tuple[str, str, str], dict[str, Any] | None] = {}
        for fuzzer, benchmark, fuzz_target in self._coverage_keys_from_trials(trials):
            key = (fuzzer, benchmark, fuzz_target)
            aggregated_coverage_by_fuzzer[key] = self._aggregated_coverage_for_fuzzer(fuzzer, benchmark, fuzz_target)
            seed_baseline_by_fuzzer[key] = self._coverage_data.seed_baseline_for(
                fuzzer=fuzzer,
                benchmark=benchmark,
                fuzz_target=fuzz_target,
            )
        return aggregated_coverage_by_fuzzer, seed_baseline_by_fuzzer

    def _coverage_sets_by_metric(
        self,
        fuzzers: list[str],
        benchmark: str,
        fuzz_target: str,
    ) -> dict[str, dict[str, set[str]]]:
        return {
            metric: self._coverage_data.coverage_sets_by_fuzzer(
                agg_snapshots=self._latest_agg_snapshots,
                fuzzers=fuzzers,
                benchmark=benchmark,
                fuzz_target=fuzz_target,
                metric=metric,
            )
            for metric in COV_METRICS
        }

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

        aggregated_coverage_by_fuzzer, seed_baseline_by_fuzzer = self._target_coverage_inputs(trials)
        targets = self._coverage_analysis.collect_target_view(
            trials=trials,
            timeseries=timeseries,
            bugs=bugs,
            trial_version_fields=TRIAL_METADATA_FIELDS,
            aggregated_coverage_by_fuzzer=aggregated_coverage_by_fuzzer,
            seed_baseline_by_fuzzer=seed_baseline_by_fuzzer,
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
            fuzzers = sorted({
                str(fuzzer.get('fuzzer') or '')
                for fuzzer in target.get('fuzzers') or []
                if fuzzer.get('fuzzer')
            })
            if benchmark and fuzz_target and len(fuzzers) > 1:
                coverage_sets_by_metric = self._coverage_sets_by_metric(fuzzers, benchmark, fuzz_target)
                target['unique_matrix'] = self.compute_unique_matrix(
                    trials, benchmark, fuzz_target, coverage_sets_by_metric
                )
                target['relcov_matrix'], target['relcov_score_by_fuzzer'] = self.compute_relcov_matrix(
                    trials, benchmark, fuzz_target, coverage_sets_by_metric
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

    def compute_unique_matrix(
        self,
        trials: list[dict[str, Any]],
        benchmark: str,
        fuzz_target: str,
        coverage_sets_by_metric: dict[str, dict[str, set[str]]],
    ) -> dict[str, Any]:
        '''Compute per-fuzzer unique coverage matrices for a target.'''

        return self._coverage_analysis.compute_unique_matrix(
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            coverage_sets_by_metric=coverage_sets_by_metric,
        )

    def compute_relcov_matrix(
        self,
        trials: list[dict[str, Any]],
        benchmark: str,
        fuzz_target: str,
        coverage_sets_by_metric: dict[str, dict[str, set[str]]],
    ) -> tuple[dict[str, Any], dict[str, float]]:
        '''Compute per-fuzzer relative coverage containment matrix and scores.'''

        return self._coverage_analysis.compute_relcov_matrix(
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            coverage_sets_by_metric=coverage_sets_by_metric,
        )

    def compute_branch_stat_matrices(
        self,
        trials: list[dict[str, Any]],
        benchmark: str,
        fuzz_target: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        '''Compute pairwise branch-coverage significance and effect-size matrices.'''

        return self._coverage_analysis.compute_branch_stat_matrices(
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
        )


def generate_report(run_dir: Path, *, out_dir: Path | None = None, template_dir: Path | None = None) -> Path:
    '''Generate a static report directory for a fuzzmeter run.'''

    run_dir = Path(run_dir).resolve()
    report_dir = (out_dir or (run_dir / 'report')).resolve()
    payload = ReportBuilder(run_dir).build()
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / 'data.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    _write_assets(report_dir, template_dir, payload)
    return report_dir


def _write_assets(report_dir: Path, template_dir: Path | None, payload: dict[str, Any]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    candidates = _asset_roots(template_dir)
    for name in ('report.css',):
        source = _find_asset(candidates, name)
        if source is None:
            raise FileNotFoundError('Could not locate report assets (report.html/report.css/report.js)')
        shutil.copy2(source, report_dir / name)

    report_html = _find_asset(candidates, 'report.html')
    if report_html is None:
        raise FileNotFoundError('Could not locate report assets (report.html/report.css/report.js)')
    env = Environment(loader=FileSystemLoader(str(report_html.parent)))
    rendered_html = env.get_template(report_html.name).render(run_id=None)
    rendered_html = rendered_html.replace(
        '<script type="module" src="report.js"></script>',
        '<script src="report.js"></script>',
    )
    static_payload_script = (
        '<script>\n'
        f'window.FM_STATIC_DATA = {json.dumps(payload, ensure_ascii=False)};\n'
        '</script>\n'
    )
    (report_dir / 'report.html').write_text(
        rendered_html.replace('</body>', f'{static_payload_script}</body>'),
        encoding='utf-8',
    )

    module_dir = _find_report_module_dir(candidates)
    if module_dir is None:
        raise FileNotFoundError('Could not locate report module assets (static/report)')
    out_module_dir = report_dir / 'report'
    if out_module_dir.exists():
        shutil.rmtree(out_module_dir)
    shutil.copytree(module_dir, out_module_dir)
    (report_dir / 'report.js').write_text(_bundle_report_modules(module_dir), encoding='utf-8')


def _asset_roots(template_dir: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if template_dir:
        candidate = template_dir.resolve()
        if not candidate.is_dir():
            raise FileNotFoundError(f'--templates is not a directory: {candidate}')
        candidates.append(candidate)
    pkg_root = Path(__file__).resolve().parents[1]
    candidates.extend([pkg_root / 'web', pkg_root / 'reporting'])
    return candidates


def _find_asset(candidates: list[Path], name: str) -> Path | None:
    for base in candidates:
        for rel in (Path('templates') / name, Path('static') / name, Path(name)):
            candidate = base / rel
            if candidate.is_file():
                return candidate
    return None


def _find_report_module_dir(candidates: list[Path]) -> Path | None:
    for base in candidates:
        candidate = base / 'static' / 'report'
        if candidate.is_dir():
            return candidate
    return None


def _bundle_report_modules(module_dir: Path) -> str:
    order = ['report-utils.js', 'charts.js', 'extras.js', 'filters.js', 'page.js', 'app.js']
    parts = [
        '/* Auto-generated static bundle for file:// report viewing. */',
        '',
    ]
    for name in order:
        source = module_dir / name
        if not source.is_file():
            raise FileNotFoundError(f'Could not locate report module: {source}')
        text = source.read_text(encoding='utf-8')
        text = re.sub(r"^\s*import\s+[\s\S]*?;\s*$", '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*export\s+', '', text, flags=re.MULTILINE)
        parts.append(text.strip())
        parts.append('')
    return '\n'.join(parts)



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
