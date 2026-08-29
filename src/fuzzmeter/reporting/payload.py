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

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..db.fields import TRIAL_METADATA_FIELDS
from ..db.trials import TrialRow
from .analyzers import coverage_curves, target_matrices, trial_analysis
from .analyzers.bug_analysis import BugAnalysis
from .analyzers.custom_metrics import attach_custom_metric_sections, has_custom_metric_sections
from .data.coverage_data import CoverageData
from .data.run_data import RunData
from .keys import COV_METRICS
from .metrics import dt, safe_int
from .plugin_sections import attach_extra_sections
from .provenance import attach_measurement_provenance

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


@dataclass(frozen=True)
class _RunTimeWindow:
    '''Hold the wall-clock window of a run and the runtime of its longest trial.'''

    started_ts: int | None
    last_activity_ts: int | None
    elapsed_seconds: int | None
    wall_elapsed_seconds: int | None


def _run_time_window(
    *,
    created_ts: int | None,
    trial_rows: list[TrialRow],
    snapshot_rows: list[dict[str, Any]],
    trial_elapsed_seconds: list[int],
) -> _RunTimeWindow:
    '''Derive the wall-clock window of a run from its trials and snapshots.

    A trial that is still running has no ``ended_ts``, so for live reports the timestamp
    of its latest snapshot is the only evidence of activity; the end of the window is
    therefore taken over both sources. ``trial_elapsed_seconds`` are the runtimes already
    measured for the collected trials, which apply the same rule per trial.
    '''

    started_candidates = [row.started_ts for row in trial_rows]
    activity_candidates = [
        *(row.ended_ts for row in trial_rows if row.ended_ts is not None),
        *(ts for ts in (safe_int(row.get('ts')) for row in snapshot_rows) if ts is not None),
    ]
    started_ts = min(started_candidates, default=created_ts)
    last_activity_ts = max(activity_candidates, default=started_ts)
    wall_elapsed_seconds = (
        None
        if started_ts is None or last_activity_ts is None
        else last_activity_ts - started_ts
    )
    return _RunTimeWindow(
        started_ts=started_ts,
        last_activity_ts=last_activity_ts,
        elapsed_seconds=max(trial_elapsed_seconds, default=wall_elapsed_seconds),
        wall_elapsed_seconds=wall_elapsed_seconds,
    )


class _PayloadBuilder:
    '''Build the report JSON payload from a fuzzmeter run database.'''

    def __init__(
        self,
        run_dir: Path,
        *,
        run_id: str | None = None,
        file_url_prefix: str | None = None,
        fuzzer_dirs: dict[str, Path] | None = None,
    ):
        self.run_dir = run_dir
        self.file_url_prefix = file_url_prefix
        self._data = RunData(run_dir / 'fuzzmeter.db').load(run_dir_name=run_dir.name, run_id=run_id)
        self.run_id = self._data.run_id
        self._coverage_data = CoverageData(run_dir)
        self._bug_analysis = BugAnalysis()
        self._fuzzer_dirs = fuzzer_dirs

    def build(self) -> dict[str, Any]:
        '''Build the complete report payload.'''

        LOG.info('Collect trials')
        trials = self.collect_trials()
        LOG.info('Collect overview')
        overview = self.collect_overview(trials)
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
            agg_snapshots=self._data.latest_agg_snapshots,
        )

        if self._fuzzer_dirs is not None and not has_custom_metric_sections(targets):
            LOG.info('Collect extra sections')
            attach_extra_sections(
                fuzzer_dirs=self._fuzzer_dirs,
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

    def collect_overview(self, trials: list[dict[str, Any]]) -> dict[str, Any]:
        '''Collect run-level overview metadata from the run rows and the collected trials.'''

        created_ts = self._data.overview_raw.get('created_ts')
        window = _run_time_window(
            created_ts=created_ts,
            trial_rows=self._data.trial_rows,
            snapshot_rows=self._data.snapshot_rows,
            trial_elapsed_seconds=[
                seconds
                for seconds in (safe_int(trial.get('elapsed_seconds')) for trial in trials)
                if seconds is not None
            ],
        )
        return {
            **self._data.overview_raw,
            'created_at': dt(created_ts),
            'started_ts': window.started_ts,
            'started_at': dt(window.started_ts),
            'last_activity_ts': window.last_activity_ts,
            'last_activity_at': dt(window.last_activity_ts),
            'elapsed_seconds': window.elapsed_seconds,
            'elapsed_human': format_duration(window.elapsed_seconds),
            'wall_elapsed_seconds': window.wall_elapsed_seconds,
            'wall_elapsed_human': format_duration(window.wall_elapsed_seconds),
        }

    def _rel_to_url(self, relpath: str | None) -> str | None:
        if not relpath:
            return None
        rel = str(relpath).replace('\\', '/')
        if self.file_url_prefix:
            return self.file_url_prefix.rstrip('/') + '/' + rel.lstrip('/')
        return '../' + rel

    def _agg_snapshot_for_fuzzer(self, fuzzer: str, benchmark: str, fuzz_target: str) -> dict[str, Any]:
        return self._data.latest_agg_snapshots.get((fuzzer, benchmark, fuzz_target), {})

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
            seed_baseline_by_fuzzer[key] = self._data.seed_baselines.get(key)
        return aggregated_coverage_by_fuzzer, seed_baseline_by_fuzzer

    def _coverage_sets_by_metric(
        self,
        fuzzers: list[str],
        benchmark: str,
        fuzz_target: str,
    ) -> dict[str, dict[str, set[str]]]:
        return {
            metric: self._coverage_data.coverage_sets_by_fuzzer(
                agg_snapshots=self._data.latest_agg_snapshots,
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

        return trial_analysis.collect_trials(
            trial_rows=self._data.trial_rows,
            latest_snapshots=self._data.latest_snapshots,
            bug_stats_by_trial=self._data.bug_stats_by_trial,
            rel_to_url=self._rel_to_url,
        )

    def collect_timeseries(self, trials: list[dict[str, Any]]) -> dict[str, Any]:
        '''Collect per-trial snapshot time series.'''

        return trial_analysis.collect_timeseries(
            trials=trials,
            snapshot_rows=self._data.snapshot_rows,
            resource_telemetry_rows=self._data.resource_telemetry_rows,
            bug_hits_by_snapshot=self._data.bug_hits_by_snapshot,
            unique_bug_delta_by_snapshot=self._data.unique_bug_delta_by_snapshot,
        )

    def collect_bugs(self) -> list[dict[str, Any]]:
        '''Collect crash and bug rows.'''

        return self._bug_analysis.collect_bugs(
            bugs=self._data.bugs,
            bug_hits_by_bug=self._data.bug_hits_by_bug,
            bug_trials_by_bug=self._data.bug_trials_by_bug,
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
        for row in self._data.metadata_rows:
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

    def create_matrices(
        self,
        targets: list[dict[str, Any]],
        trials: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        '''Attach pairwise coverage and bug comparison matrices to each target.'''

        for target in targets:
            benchmark = target.get('benchmark')
            fuzz_target = target.get('fuzz_target')
            fuzzers = sorted({
                str(fuzzer.get('fuzzer') or '')
                for fuzzer in target.get('fuzzers') or []
                if fuzzer.get('fuzzer')
            })
            if not (benchmark and fuzz_target and len(fuzzers) > 1):
                target_matrices.attach_empty_target_matrices(target)
                continue

            target_matrices.attach_target_matrices(
                target=target,
                trials=trials,
                fuzzers=fuzzers,
                benchmark=benchmark,
                fuzz_target=fuzz_target,
                coverage_sets_by_metric=self._coverage_sets_by_metric(fuzzers, benchmark, fuzz_target),
                trial_coverage_sets_by_metric=self._trial_coverage_sets_by_metric(
                    trials,
                    fuzzers,
                    benchmark,
                    fuzz_target,
                ),
            )
        return targets


def build_payload(
    run_dir: Path,
    *,
    run_id: str | None = None,
    file_url_prefix: str | None = None,
    fuzzer_dirs: dict[str, Path] | None = None,
) -> dict[str, Any]:
    '''Build the JSON payload consumed by the web report.

    The caller must pass a resolved run directory that contains ``fuzzmeter.db``.
    '''

    return _PayloadBuilder(
        run_dir,
        run_id=run_id,
        file_url_prefix=file_url_prefix,
        fuzzer_dirs=fuzzer_dirs,
    ).build()
