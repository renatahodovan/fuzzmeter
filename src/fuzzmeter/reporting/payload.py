# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Assemble the full fuzzmeter web report payload.'''

from __future__ import annotations

import datetime
import json
import logging

from pathlib import Path
from typing import Any

from ..db.fields import TRIAL_METADATA_FIELDS
from .analyzers import coverage_curves, coverage_matrices
from .analyzers.bug_analysis import BugAnalysis
from .analyzers.custom_metrics import attach_custom_metric_sections, has_custom_metric_sections
from .analyzers.trial_analysis import TrialAnalysis
from .data.coverage_data import CoverageData
from .data.run_data import RunData
from .keys import (
    BRANCH_A12_MATRIX_KEY,
    BRANCH_MWU_MATRIX_KEY,
    COV_METRICS,
    RELBUG_MATRIX_KEY,
    RELBUG_SCORE_BY_FUZZER_KEY,
    RELCOV_MATRIX_KEY,
    RELCOV_SCORE_BY_FUZZER_KEY,
    SNAPSHOT_COVERAGE_FIELDS,
    UNIQUE_BUG_MATRIX_KEY,
    UNIQUE_BUG_TABLE_KEY,
    UNIQUE_MATRIX_KEY,
)
from .metrics import dt, safe_int
from .plugin_sections import attach_extra_sections
from .provenance import attach_measurement_provenance
from .set_comparison import TrialSetIndex, empty_trial_set_comparison, trial_set_index

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


class _PayloadBuilder:
    '''Build the report JSON payload from a fuzzmeter run database.'''

    def __init__(
        self,
        run_dir: Path,
        *,
        run_id: str | None = None,
        file_url_prefix: str | None = None,
        fuzzers_root: Path | None = None,
    ):
        self.run_dir = Path(run_dir).resolve()
        self.db_path = self.run_dir / 'fuzzmeter.db'
        if not self.db_path.exists():
            raise FileNotFoundError(f'Missing DB: {self.db_path}')
        self.file_url_prefix = file_url_prefix
        self._run_data = RunData(self.db_path)
        loaded = self._run_data.load(run_dir_name=self.run_dir.name, run_id=run_id)
        self.run_id = loaded.run_id
        self._overview_raw = loaded.overview_raw
        self._trial_rows = loaded.trial_rows
        self._latest_snapshots = loaded.latest_snapshots
        self._latest_agg_snapshots = loaded.latest_agg_snapshots
        self._seed_baselines = loaded.seed_baselines
        self._metadata_rows = loaded.metadata_rows
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
        self._fuzzers_root = Path(fuzzers_root).expanduser().resolve() if fuzzers_root is not None else None

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
        LOG.info('Collect persisted custom metrics')
        attach_custom_metric_sections(targets, timeseries)
        LOG.info('Collect uniqueness matrices')
        targets = self.create_matrices(targets, trials)
        measurement_provenance = attach_measurement_provenance(
            targets=targets,
            agg_snapshots=self._latest_agg_snapshots,
        )

        if self._fuzzers_root is not None and not has_custom_metric_sections(targets):
            LOG.info('Collect extra sections')
            attach_extra_sections(
                fuzzers_root=self._fuzzers_root,
                run_dir=self.run_dir,
                run_id=self.run_id,
                targets=targets,
                trials=trials,
                timeseries=timeseries,
                bugs=bugs,
            )

        return {
            'meta': {
                'generated_at': dt(int(datetime.datetime.now(datetime.timezone.utc).timestamp())),
                'run_id': self.run_id,
            },
            'overview': overview,
            'targets': targets,
            'trials': trials,
            'timeseries': timeseries,
            'bugs': bugs,
            'measurement_provenance': measurement_provenance,
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
        if self.file_url_prefix:
            return self.file_url_prefix.rstrip('/') + '/' + rel.lstrip('/')
        return '../' + rel

    def _agg_snapshot_for_fuzzer(self, fuzzer: str, benchmark: str, fuzz_target: str) -> dict[str, Any]:
        return self._latest_agg_snapshots.get((str(fuzzer), str(benchmark), str(fuzz_target)), {})

    def _aggregated_coverage_for_fuzzer(self, fuzzer: str, benchmark: str, fuzz_target: str) -> dict[str, int | None]:
        agg_snapshot = self._agg_snapshot_for_fuzzer(fuzzer, benchmark, fuzz_target)
        return {
            f'{metric}_covered': safe_int(agg_snapshot.get(f'cov_{metric}_covered'))
            for metric in COV_METRICS
        }

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
            seed_baseline_by_fuzzer[key] = self._seed_baselines.get(key)
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

    def _trial_coverage_sets_by_metric(
        self,
        trials: list[dict[str, Any]],
        fuzzers: list[str],
        benchmark: str,
        fuzz_target: str,
    ) -> dict[str, dict[str, list[set[str] | None]]]:
        return {
            metric: self._coverage_data.trial_coverage_sets_by_fuzzer(
                trials=trials,
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
        targets = coverage_curves.collect_target_view(
            cov_metrics=COV_METRICS,
            curve_max_points=CURVE_MAX_POINTS,
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
        self._attach_metadata(targets)
        return targets

    def _attach_metadata(self, targets: list[dict[str, Any]]) -> None:
        metadata_by_key = self._metadata_by_key()
        if not metadata_by_key:
            return
        for target in targets:
            benchmark = str(target.get('benchmark') or '')
            fuzz_target = str(target.get('fuzz_target') or '')
            for fuzzer in target.get('fuzzers') or []:
                key = (str(fuzzer.get('fuzzer') or ''), benchmark, fuzz_target)
                metadata = metadata_by_key.get(key)
                if metadata:
                    fuzzer['metadata'] = metadata

    def _metadata_by_key(self) -> dict[tuple[str, str, str], dict[str, Any]]:
        out: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in self._metadata_rows:
            try:
                metadata = json.loads(str(row.get('metadata_json') or '{}'))
            except json.JSONDecodeError:
                continue
            if not isinstance(metadata, dict):
                continue
            digests = metadata.get('digests') if isinstance(metadata.get('digests'), dict) else {}
            digests = {
                **digests,
                'environment': digests.get('environment') or row.get('environment_digest'),
                'config': digests.get('config') or row.get('config_digest'),
                'source': digests.get('source') or row.get('source_digest'),
            }
            metadata['digests'] = {key: value for key, value in digests.items() if value is not None}
            out[
                (
                    str(row.get('fuzzer') or ''),
                    str(row.get('benchmark') or ''),
                    str(row.get('fuzz_target') or ''),
                )
            ] = metadata
        return out

    def create_matrices(self, targets, trials):
        '''Attach pairwise coverage and bug comparison matrices to each target.'''

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
                trial_coverage_sets_by_metric = self._trial_coverage_sets_by_metric(
                    trials,
                    fuzzers,
                    benchmark,
                    fuzz_target,
                )
                trial_coverage_sets_by_metric, aggregate_fallback_fuzzers_by_metric = (
                    self._with_aggregate_trial_fallback(
                        trial_coverage_sets_by_metric,
                        coverage_sets_by_metric,
                        fuzzers,
                    )
                )
                trial_set_indexes_by_metric = {
                    metric: trial_set_index(fuzzers, trial_coverage_sets_by_metric.get(metric, {}))
                    for metric in COV_METRICS
                }
                target[UNIQUE_MATRIX_KEY] = self.compute_unique_matrix(
                    trials=trials,
                    benchmark=benchmark,
                    fuzz_target=fuzz_target,
                    trial_coverage_sets_by_metric=trial_coverage_sets_by_metric,
                    aggregate_fallback_fuzzers_by_metric=aggregate_fallback_fuzzers_by_metric,
                    trial_set_indexes_by_metric=trial_set_indexes_by_metric,
                )
                target[RELCOV_MATRIX_KEY], target[RELCOV_SCORE_BY_FUZZER_KEY] = self.compute_relcov_matrix(
                    trials=trials,
                    benchmark=benchmark,
                    fuzz_target=fuzz_target,
                    trial_coverage_sets_by_metric=trial_coverage_sets_by_metric,
                    aggregate_fallback_fuzzers_by_metric=aggregate_fallback_fuzzers_by_metric,
                    trial_set_indexes_by_metric=trial_set_indexes_by_metric,
                )
                target[BRANCH_MWU_MATRIX_KEY], target[BRANCH_A12_MATRIX_KEY] = self.compute_branch_stat_matrices(
                    trials,
                    benchmark,
                    fuzz_target,
                )
                coverage_matrices.attach_exclusive_coverage_stats(
                    target=target,
                    trial_coverage_sets_by_metric=trial_coverage_sets_by_metric,
                    aggregate_fallback_fuzzers_by_metric=aggregate_fallback_fuzzers_by_metric,
                )
                target[UNIQUE_BUG_TABLE_KEY] = self._bug_analysis.compute_unique_bug_table(target)
                target[UNIQUE_BUG_MATRIX_KEY] = self._bug_analysis.compute_unique_bug_matrix(target)
                target[RELBUG_MATRIX_KEY], target[RELBUG_SCORE_BY_FUZZER_KEY] = (
                    self._bug_analysis.compute_rel_bug_matrix(target)
                )
                self._bug_analysis.attach_exclusive_bug_stats(target)
            else:
                target[UNIQUE_MATRIX_KEY] = empty_metric_group
                target[RELCOV_MATRIX_KEY] = empty_metric_group
                target[BRANCH_MWU_MATRIX_KEY] = empty_metric_group
                target[BRANCH_A12_MATRIX_KEY] = empty_metric_group
                target[RELCOV_SCORE_BY_FUZZER_KEY] = {}
                target[UNIQUE_BUG_TABLE_KEY] = empty_bug_table
                target[UNIQUE_BUG_MATRIX_KEY] = empty_trial_set_comparison()
                target[RELBUG_MATRIX_KEY] = empty_matrix
                target[RELBUG_SCORE_BY_FUZZER_KEY] = {}
        return targets

    @staticmethod
    def _with_aggregate_trial_fallback(
        trial_coverage_sets_by_metric: dict[str, dict[str, list[set[str] | None]]],
        coverage_sets_by_metric: dict[str, dict[str, set[str]]],
        fuzzers: list[str],
    ) -> tuple[dict[str, dict[str, list[set[str] | None]]], dict[str, set[str]]]:
        '''Use final aggregate coverage sets when trial compact sets are unavailable.'''

        out: dict[str, dict[str, list[set[str] | None]]] = {}
        fallback_fuzzers_by_metric: dict[str, set[str]] = {}
        for metric in COV_METRICS:
            trial_sets = trial_coverage_sets_by_metric.get(metric, {})
            aggregate_sets = coverage_sets_by_metric.get(metric, {})
            merged = {
                fuzzer: [set(value) if value is not None else None for value in values]
                for fuzzer, values in trial_sets.items()
            }
            for fuzzer in fuzzers:
                if any(value is not None for value in merged.get(fuzzer, [])):
                    continue
                aggregate_set = aggregate_sets.get(fuzzer)
                if aggregate_set is not None:
                    merged[fuzzer] = [set(aggregate_set)]
                    fallback_fuzzers_by_metric.setdefault(metric, set()).add(fuzzer)
            out[metric] = merged
        return out, fallback_fuzzers_by_metric

    def compute_unique_matrix(
        self,
        *,
        trials: list[dict[str, Any]],
        benchmark: str,
        fuzz_target: str,
        trial_coverage_sets_by_metric: dict[str, dict[str, list[set[str] | None]]],
        aggregate_fallback_fuzzers_by_metric: dict[str, set[str]] | None = None,
        trial_set_indexes_by_metric: dict[str, TrialSetIndex] | None = None,
    ) -> dict[str, Any]:
        '''Compute per-fuzzer unique coverage matrices for a target.'''

        return coverage_matrices.compute_unique_matrix(
            cov_metrics=COV_METRICS,
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            trial_coverage_sets_by_metric=trial_coverage_sets_by_metric,
            aggregate_fallback_fuzzers_by_metric=aggregate_fallback_fuzzers_by_metric,
            trial_set_indexes_by_metric=trial_set_indexes_by_metric,
        )

    def compute_relcov_matrix(
        self,
        *,
        trials: list[dict[str, Any]],
        benchmark: str,
        fuzz_target: str,
        trial_coverage_sets_by_metric: dict[str, dict[str, list[set[str] | None]]],
        aggregate_fallback_fuzzers_by_metric: dict[str, set[str]] | None = None,
        trial_set_indexes_by_metric: dict[str, TrialSetIndex] | None = None,
    ) -> tuple[dict[str, Any], dict[str, float]]:
        '''Compute per-fuzzer relative coverage containment matrix and scores.'''

        return coverage_matrices.compute_relcov_matrix(
            cov_metrics=COV_METRICS,
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            trial_coverage_sets_by_metric=trial_coverage_sets_by_metric,
            aggregate_fallback_fuzzers_by_metric=aggregate_fallback_fuzzers_by_metric,
            trial_set_indexes_by_metric=trial_set_indexes_by_metric,
        )

    def compute_branch_stat_matrices(
        self,
        trials: list[dict[str, Any]],
        benchmark: str,
        fuzz_target: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        '''Compute pairwise branch-coverage significance and effect-size matrices.'''

        return coverage_matrices.compute_branch_stat_matrices(
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
        )


def build_payload(
    run_dir: Path,
    *,
    run_id: str | None = None,
    file_url_prefix: str | None = None,
    fuzzers_root: Path | None = None,
) -> dict[str, Any]:
    '''Build the JSON payload consumed by the web report.'''

    return _PayloadBuilder(
        run_dir,
        run_id=run_id,
        file_url_prefix=file_url_prefix,
        fuzzers_root=fuzzers_root,
    ).build()
