# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import json

from pathlib import Path
from typing import Any, Callable, Sequence

from ..metrics import trapezoid_auc
from ..set_comparison import pairwise_matrix, unique_matrix


class CoverageAnalysis:
    '''Build coverage, performance, and target comparison report data.'''

    def __init__(
        self,
        *,
        cov_metrics: tuple[str, ...],
        final_output_dist_keys: tuple[str, ...],
        curve_max_points: int,
        safe_int: Callable[[Any], int | None],
        mean: Callable[[Any], float | None],
        median: Callable[[Any], float | None],
        minimum: Callable[[Any], float | None],
        maximum: Callable[[Any], float | None],
        mann_whitney_u_pvalue: Callable[[list[float], list[float]], float | None],
        vargha_delaney_a12: Callable[[list[float], list[float]], float | None],
        dt: Callable[[int | None], str | None],
    ) -> None:
        self._cov_metrics = cov_metrics
        self._final_output_dist_keys = final_output_dist_keys
        self._curve_max_points = curve_max_points
        self._safe_int = safe_int
        self._mean = mean
        self._median = median
        self._minimum = minimum
        self._maximum = maximum
        self._mann_whitney_u_pvalue = mann_whitney_u_pvalue
        self._vargha_delaney_a12 = vargha_delaney_a12
        self._dt = dt

    def _covered_counts_from_sets(
        self,
        *,
        coverage_path: Path | None,
        covered_elements_for_path: Callable[[Path, str], set[str]],
    ) -> dict[str, int | None]:
        '''Collect aggregated covered element counts from compact coverage sets.'''

        if coverage_path is None or not coverage_path.exists():
            return {f'{metric}_covered': None for metric in self._cov_metrics}
        return {
            f'{metric}_covered': len(covered_elements_for_path(coverage_path, metric))
            for metric in self._cov_metrics
        }

    def _build_aggregate_summary(
        self,
        *,
        finals: dict[str, list[float]],
        bugs: list[dict[str, Any]],
        aggregated_coverage: dict[str, int | None],
    ) -> dict[str, float | None]:
        '''Build aggregate metrics across all trials of one fuzzer-target entry.'''

        execs_done = sum(finals.get('execs_done') or []) or None
        elapsed_seconds = sum(finals.get('elapsed_seconds') or []) or None
        execs_per_sec = None
        if execs_done is not None and elapsed_seconds not in (None, 0):
            execs_per_sec = float(execs_done) / float(elapsed_seconds)
        aggregate = {
            'execs_done': execs_done,
            'elapsed_seconds': elapsed_seconds,
            'execs_per_sec': execs_per_sec,
            'corpus_files_total': sum(finals.get('corpus_files_total') or []) or None,
            'unique_bugs_total': float(len({str(bug.get('bug_key')) for bug in bugs if bug.get('bug_key')})) or None,
            'bug_hits_total': sum(finals.get('bug_hits_total') or []) or None,
        }
        aggregate.update(aggregated_coverage)
        return aggregate

    def _add_mean_median(self, out: dict[str, float | None], key: str, values: list[float]) -> None:
        '''Add mean and median fields for a metric distribution.'''

        out[f'{key}_mean'] = self._mean(values)
        out[f'{key}_median'] = self._median(values)

    def _build_final_summary(
        self,
        *,
        finals: dict[str, list[float]],
        trial_rows: list[dict[str, Any]],
        bugs: list[dict[str, Any]],
    ) -> dict[str, float | None]:
        '''Build final per-trial metric summaries for one fuzzer-target entry.'''

        final_summary: dict[str, float | None] = {}
        for metric in self._cov_metrics:
            for suffix in ('cov', 'total', 'pct'):
                self._add_mean_median(final_summary, f'{metric}_{suffix}', finals.get(f'{metric}_{suffix}') or [])
        for key in (
            'regions_pct_auc',
            'regions_pct_auc_norm',
            'branches_cov_auc',
            'branches_cov_auc_norm',
            'branches_pct_auc',
            'branches_pct_auc_norm',
            'convergence_pct',
        ):
            values = [float(row[key]) for row in trial_rows if isinstance(row.get(key), (int, float))]
            self._add_mean_median(final_summary, key, values)
        for key in (
            'execs_per_sec',
            'execs_done',
            'elapsed_seconds',
            'corpus_files_total',
            'unique_bugs_total',
            'bug_hits_total',
            'crashes_total',
            'resource_cpu_percent',
            'resource_memory_mib',
            'resource_memory_percent',
            'resource_corpus_disk_mib',
        ):
            self._add_mean_median(final_summary, key, finals.get(key) or [])
        bug_keys = {str(bug.get('bug_key')) for bug in bugs if bug.get('bug_key')}
        final_summary['accumulated_bug_count'] = float(len(bug_keys))
        return final_summary

    @staticmethod
    def _convergence_pct(auc: float | None, max_coverage: float | None, duration_s: int | None) -> float | None:
        '''Return normalized coverage convergence percentage.'''

        if auc is None or max_coverage is None or duration_s is None:
            return None
        if max_coverage <= 0 or duration_s <= 0:
            return None
        return 100.0 * float(auc) / (float(max_coverage) * float(duration_s))

    def downsample_curve(self, curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
        '''Return a curve with at most the configured number of points.'''

        if len(curve) <= self._curve_max_points:
            return curve
        if self._curve_max_points < 3:
            return [curve[0], curve[-1]]
        selected = [curve[0]]
        interior = curve[1:-1]
        buckets = self._curve_max_points - 2
        for bucket_idx in range(buckets):
            start = int(bucket_idx * len(interior) / buckets)
            end = int((bucket_idx + 1) * len(interior) / buckets)
            if start >= len(interior):
                break
            chunk = interior[start:max(start + 1, end)]
            selected.append(chunk[len(chunk) // 2])
        selected.append(curve[-1])
        deduped: list[dict[str, Any]] = []
        seen_idx: set[int] = set()
        for point in selected:
            idx = self._safe_int(point.get("idx"))
            if idx is not None and idx in seen_idx:
                continue
            if idx is not None:
                seen_idx.add(idx)
            deduped.append(point)
        return deduped

    def aggregate_finals(
        self,
        reps: list[dict[str, Any]],
        points_by_trial: dict[int, list[dict[str, Any]]],
        *,
        trial_elapsed_seconds: Callable[[dict[str, Any]], int | None],
    ) -> dict[str, list[float]]:
        '''Collect final metric distributions for a fuzzer entry.'''

        finals: dict[str, list[float]] = {key: [] for key in self._final_output_dist_keys}
        for trial in reps:
            coverage = trial.get("coverage") or {}
            for metric in self._cov_metrics:
                cov_value = coverage.get(f"{metric}_covered")
                total_value = coverage.get(f"{metric}_total")
                pct_value = coverage.get(f"{metric}_pct")
                if cov_value is not None:
                    finals[f"{metric}_cov"].append(float(cov_value))
                if total_value is not None:
                    finals[f"{metric}_total"].append(float(total_value))
                if pct_value is not None:
                    finals[f"{metric}_pct"].append(float(pct_value))
            trial_points = points_by_trial.get(int(trial["trial_id"]), [])
            if not trial_points:
                continue
            last_point = trial_points[-1]
            for key in (
                "corpus_files_total",
                "execs_done",
                "unique_bugs_total",
                "bug_hits_total",
                "crashes_total",
                "resource_cpu_percent",
                "resource_memory_mib",
                "resource_memory_percent",
                "resource_corpus_disk_mib",
            ):
                value = last_point.get(key)
                if value is not None:
                    finals[key].append(float(value))
            elapsed_seconds = trial_elapsed_seconds(trial)
            if elapsed_seconds is not None:
                finals.setdefault("elapsed_seconds", []).append(float(elapsed_seconds))
                execs_done = self._safe_int(last_point.get("execs_done"))
                if execs_done is not None and elapsed_seconds > 0:
                    finals["execs_per_sec"].append(float(execs_done) / float(elapsed_seconds))
        return finals

    def build_curve(self, reps: list[dict[str, Any]], points_by_trial: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        '''Build an aggregate fuzzer curve across repetitions.'''

        trial_series: list[tuple[int, dict[float, dict[str, Any]]]] = []
        all_elapsed: set[float] = set()
        for trial in reps:
            points = sorted(
                points_by_trial.get(int(trial["trial_id"]), []),
                key=lambda point: (
                    float(point.get("elapsed_s"))
                    if isinstance(point.get("elapsed_s"), (int, float))
                    else float(point.get("ordinal") or point.get("idx") or 0)
                ),
            )
            point_map: dict[float, dict[str, Any]] = {}
            for point in points:
                elapsed_s = point.get("elapsed_s")
                if not isinstance(elapsed_s, (int, float)):
                    continue
                elapsed_key = max(0.0, float(elapsed_s))
                point_map[elapsed_key] = point
                all_elapsed.add(elapsed_key)
            trial_series.append((int(trial["trial_id"]), point_map))

        last_seen_per_trial: dict[int, dict[str, Any]] = {}
        curve: list[dict[str, Any]] = []
        for idx, elapsed_key in enumerate(sorted(all_elapsed), start=1):
            curve_item: dict[str, Any] = {"idx": idx, "elapsed_s": elapsed_key}
            ts_values: list[float] = []
            values: dict[str, list[float]] = {key: [] for key in self._final_output_dist_keys}

            for trial_id, point_map in trial_series:
                state = last_seen_per_trial.setdefault(trial_id, {})
                point = point_map.get(elapsed_key)
                if point is not None:
                    ts = self._safe_int(point.get("ts"))
                    if ts is not None:
                        ts_values.append(float(ts))
                    for key in self._final_output_dist_keys:
                        value = point.get(key)
                        if value is not None:
                            state[key] = value
                if not state:
                    continue
                for key in self._final_output_dist_keys:
                    if key in state:
                        values[key].append(float(state[key]))

            if ts_values:
                ts_median = self._median(ts_values)
                curve_item["ts_median"] = ts_median
                if ts_median is not None:
                    curve_item["t"] = self._dt(int(ts_median))

            for key, clean in values.items():
                if not clean:
                    continue
                curve_item[f"{key}_mean"] = self._mean(clean)
                curve_item[f"{key}_median"] = self._median(clean)
                curve_item[f"{key}_min"] = self._minimum(clean)
                curve_item[f"{key}_max"] = self._maximum(clean)

            curve.append(curve_item)
        return curve

    def _trial_auc(
        self,
        trial_points: list[dict[str, Any]],
        *,
        y_key: str,
        duration_s: int | None,
    ) -> tuple[float | None, float | None]:
        points: list[tuple[float, float]] = []
        for point in trial_points:
            x = point.get("elapsed_s")
            y = point.get(y_key)
            if x is None or y is None:
                continue
            points.append((float(x), float(y)))
        auc = trapezoid_auc(points, duration_s=float(duration_s) if duration_s is not None else None)
        if auc is None:
            return None, None
        if duration_s is None or duration_s <= 0:
            return auc, None
        return auc, float(auc) / float(duration_s)

    def build_trial_rows(
        self,
        *,
        reps: list[dict[str, Any]],
        points_by_trial: dict[int, list[dict[str, Any]]],
        trial_elapsed_seconds: Callable[[dict[str, Any]], int | None],
    ) -> list[dict[str, Any]]:
        '''Build per-trial metric rows for a fuzzer entry.'''

        rows: list[dict[str, Any]] = []
        for trial in sorted(reps, key=lambda row: (str(row.get("fuzzer") or ""), int(row.get("rep") or 0), int(row.get("trial_id") or 0))):
            trial_id = int(trial["trial_id"])
            coverage = trial.get("coverage") or {}
            points = sorted(points_by_trial.get(trial_id, []), key=lambda point: int(point.get("idx") or 0))
            last_point = points[-1] if points else {}
            elapsed_seconds = trial_elapsed_seconds(trial)
            execs_done = self._safe_int(last_point.get("execs_done"))
            execs_per_sec = None
            if execs_done is not None and elapsed_seconds is not None and elapsed_seconds > 0:
                execs_per_sec = float(execs_done) / float(elapsed_seconds)

            regions_cov_auc, regions_cov_auc_norm = self._trial_auc(points, y_key="regions_cov", duration_s=elapsed_seconds)
            branches_cov_auc, branches_cov_auc_norm = self._trial_auc(points, y_key="branches_cov", duration_s=elapsed_seconds)
            regions_pct_auc, regions_pct_auc_norm = self._trial_auc(points, y_key="regions_pct", duration_s=elapsed_seconds)
            branches_pct_auc, branches_pct_auc_norm = self._trial_auc(points, y_key="branches_pct", duration_s=elapsed_seconds)
            convergence_pct = self._convergence_pct(
                branches_cov_auc,
                self._safe_int(coverage.get("branches_covered")),
                elapsed_seconds,
            )

            rows.append(
                {
                    "trial_id": trial_id,
                    "fuzzer": trial.get("fuzzer"),
                    "benchmark": trial.get("benchmark"),
                    "fuzz_target": trial.get("fuzz_target"),
                    "rep": self._safe_int(trial.get("rep")),
                    "started_ts": self._safe_int(trial.get("started_ts")),
                    "ended_ts": self._safe_int(trial.get("ended_ts")),
                    "time_seconds": self._safe_int(trial.get("time_seconds")),
                    "status": trial.get("status"),
                    "elapsed_seconds": elapsed_seconds,
                    "execs_done": execs_done,
                    "execs_per_sec": execs_per_sec,
                    "regions_cov": coverage.get("regions_covered"),
                    "regions_pct": coverage.get("regions_pct"),
                    "branches_cov": coverage.get("branches_covered"),
                    "branches_pct": coverage.get("branches_pct"),
                    "regions_cov_auc": regions_cov_auc,
                    "regions_cov_auc_norm": regions_cov_auc_norm,
                    "branches_cov_auc": branches_cov_auc,
                    "branches_cov_auc_norm": branches_cov_auc_norm,
                    "regions_pct_auc": regions_pct_auc,
                    "regions_pct_auc_norm": regions_pct_auc_norm,
                    "branches_pct_auc": branches_pct_auc,
                    "branches_pct_auc_norm": branches_pct_auc_norm,
                    "convergence_pct": convergence_pct,
                    "corpus_files_total": self._safe_int(last_point.get("corpus_files_total")),
                    "unique_bugs_total": self._safe_int(last_point.get("unique_bugs_total")),
                    "bug_hits_total": self._safe_int(last_point.get("bug_hits_total")),
                    "crashes_total": self._safe_int(last_point.get("crashes_total")),
                }
            )
        return rows

    @staticmethod
    def seed_baseline_for(run_dir: Path, *, fuzzer: str, benchmark: str, fuzz_target: str) -> dict[str, Any] | None:
        '''Load seed baseline coverage for one fuzzer-target pair.'''

        summary_path = run_dir / "coverage_seed" / fuzzer / benchmark / fuzz_target / "summary.json"
        if not summary_path.is_file():
            return None
        try:
            return json.loads(summary_path.read_text(encoding="utf-8", errors="replace") or "{}")
        except Exception:
            return None

    def build_fuzzer_entry(
        self,
        *,
        run_dir: Path,
        fuzzer: str,
        reps: list[dict[str, Any]],
        bugs: list[dict[str, Any]],
        versions: dict[str, Any],
        points_by_trial: dict[int, list[dict[str, Any]]],
        trial_elapsed_seconds: Callable[[dict[str, Any]], int | None],
        coverage_sets_for_fuzzer: Callable[[str, str, str], Path | None],
        aggregated_snapshot_coverage_for_fuzzer: Callable[[str, str, str], dict[str, Any]],
        covered_elements_for_path: Callable[[Path, str], set[str]],
    ) -> dict[str, Any]:
        '''Build one fuzzer entry inside a target report.'''

        finals = self.aggregate_finals(reps, points_by_trial, trial_elapsed_seconds=trial_elapsed_seconds)
        curve = self.downsample_curve(self.build_curve(reps, points_by_trial))
        trial_rows = self.build_trial_rows(
            reps=reps,
            points_by_trial=points_by_trial,
            trial_elapsed_seconds=trial_elapsed_seconds,
        )
        benchmark = reps[0]['benchmark'] if reps else ''
        fuzz_target = reps[0]['fuzz_target'] if reps else ''
        agg_snapshot_coverage = aggregated_snapshot_coverage_for_fuzzer(fuzzer, benchmark, fuzz_target)
        aggregated_coverage_path = coverage_sets_for_fuzzer(benchmark, fuzz_target, fuzzer)
        aggregated_coverage = self._covered_counts_from_sets(
            coverage_path=aggregated_coverage_path,
            covered_elements_for_path=covered_elements_for_path,
        )
        for metric in self._cov_metrics:
            summary_covered = self._safe_int(agg_snapshot_coverage.get(f'{metric}_covered'))
            if summary_covered is None:
                continue
            summary_count = int(summary_covered)
            current_count = aggregated_coverage.get(f'{metric}_covered')
            if current_count is None or metric == 'branches' or summary_count > int(current_count):
                aggregated_coverage[f'{metric}_covered'] = summary_count
        final_summary = self._build_final_summary(finals=finals, trial_rows=trial_rows, bugs=bugs)
        aggregate_summary = self._build_aggregate_summary(
            finals=finals,
            bugs=bugs,
            aggregated_coverage=aggregated_coverage,
        )
        return {
            'fuzzer': fuzzer,
            'final': final_summary,
            'aggregate': aggregate_summary,
            'distribution': finals,
            'curve': curve,
            'trials': trial_rows,
            'seed_baseline': self.seed_baseline_for(
                run_dir,
                fuzzer=fuzzer,
                benchmark=benchmark,
                fuzz_target=fuzz_target,
            ),
            'bugs': sorted(bugs, key=lambda bug: (-(int(bug.get('hits_total') or 0)), str(bug.get('bug_key') or ''))),
            'versions': versions,
            'extra_sections': [],
            'extra_section_debug': [],
        }

    def collect_target_view(
        self,
        *,
        run_dir: Path,
        trials: list[dict[str, Any]],
        timeseries: dict[str, Any],
        bugs: list[dict[str, Any]],
        trial_version_fields: Sequence[str],
        trial_elapsed_seconds: Callable[[dict[str, Any]], int | None],
        coverage_sets_for_fuzzer: Callable[[str, str, str], Path | None],
        aggregated_snapshot_coverage_for_fuzzer: Callable[[str, str, str], dict[str, Any]],
        covered_elements_for_path: Callable[[Path, str], set[str]],
    ) -> list[dict[str, Any]]:
        '''Collect all target report entries from trials, time series, and bugs.'''

        points_by_trial = {
            int(entry["trial_id"]): list(entry.get("points") or [])
            for entry in (timeseries.get("per_trial") or {}).values()
        }
        grouped: dict[tuple[str, str], dict[str, Any]] = {}

        def merge_version_config(dst: dict[str, Any], key: str, value: Any) -> None:
            if value is None:
                return
            if not isinstance(value, dict):
                dst[key] = value
                return
            current = dst.get(key)
            if not isinstance(current, dict):
                dst[key] = dict(value)
                return
            merged = dict(current)
            merged.update(value)
            dst[key] = merged

        for trial in trials:
            benchmark = trial.get("benchmark")
            fuzz_target = trial.get("fuzz_target")
            fuzzer = trial.get("fuzzer")
            if not (benchmark and fuzz_target and fuzzer):
                continue
            target_group = grouped.setdefault((benchmark, fuzz_target), {"benchmark": benchmark, "fuzz_target": fuzz_target, "fuzzers": {}})
            fuzzer_group = target_group["fuzzers"].setdefault(fuzzer, {"reps": [], "bugs": [], "versions": {}})
            fuzzer_group["reps"].append(trial)
            for key in trial_version_fields:
                if trial.get(key):
                    fuzzer_group["versions"][key] = trial.get(key)
            merge_version_config(fuzzer_group["versions"], "build_config", trial.get("build_config"))
            merge_version_config(fuzzer_group["versions"], "runtime_config", trial.get("runtime_config"))

        for bug in bugs:
            key = (bug.get("benchmark"), bug.get("fuzz_target"))
            fuzzer = bug.get("fuzzer")
            if key not in grouped or not fuzzer:
                continue
            grouped[key]["fuzzers"].setdefault(fuzzer, {"reps": [], "bugs": [], "versions": {}})["bugs"].append(bug)

        targets: list[dict[str, Any]] = []
        for (benchmark, fuzz_target), target_group in sorted(grouped.items()):
            target = {
                "benchmark": benchmark,
                "fuzz_target": fuzz_target,
                "key": f"{benchmark}:{fuzz_target}",
                "fuzzers": [],
                "extra_sections": [],
                "extra_section_debug": [],
            }
            for fuzzer, group in sorted(target_group["fuzzers"].items()):
                target["fuzzers"].append(
                    self.build_fuzzer_entry(
                        run_dir=run_dir,
                        fuzzer=fuzzer,
                        reps=group["reps"],
                        bugs=group["bugs"],
                        versions=group["versions"],
                        points_by_trial=points_by_trial,
                        trial_elapsed_seconds=trial_elapsed_seconds,
                        coverage_sets_for_fuzzer=coverage_sets_for_fuzzer,
                        aggregated_snapshot_coverage_for_fuzzer=aggregated_snapshot_coverage_for_fuzzer,
                        covered_elements_for_path=covered_elements_for_path,
                    )
                )
            targets.append(target)
        return targets

    def compute_unique_matrix(
        self,
        *,
        trials: list[dict[str, Any]],
        benchmark: str,
        fuzz_target: str,
        coverage_sets_for_fuzzer: Callable[[str, str, str], Path | None],
        covered_elements_for_path: Callable[[Path, str], set[str]],
    ) -> dict[str, Any]:
        '''Compute all unique coverage matrices for one target.'''

        by_metric = {
            metric: self._compute_unique_matrix_for_metric(
                trials=trials,
                benchmark=benchmark,
                fuzz_target=fuzz_target,
                metric=metric,
                coverage_sets_for_fuzzer=coverage_sets_for_fuzzer,
                covered_elements_for_path=covered_elements_for_path,
            )
            for metric in self._cov_metrics
        }
        return {
            "by_metric": by_metric,
            "has_data": any(entry.get("has_data") for entry in by_metric.values()),
            "available_metrics": [metric for metric, entry in by_metric.items() if entry.get("has_data")],
        }

    def _compute_unique_matrix_for_metric(
        self,
        *,
        trials: list[dict[str, Any]],
        benchmark: str,
        fuzz_target: str,
        metric: str,
        coverage_sets_for_fuzzer: Callable[[str, str, str], Path | None],
        covered_elements_for_path: Callable[[Path, str], set[str]],
    ) -> dict[str, Any]:
        '''Compute pairwise unique union coverage matrix for one coverage metric.'''

        fuzzers = sorted(
            {
                str(trial.get("fuzzer"))
                for trial in trials
                if trial.get("benchmark") == benchmark and trial.get("fuzz_target") == fuzz_target and trial.get("fuzzer")
            }
        )
        coverage_sets = self._coverage_sets_for_metric(
            fuzzers=fuzzers,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            metric=metric,
            coverage_sets_for_fuzzer=coverage_sets_for_fuzzer,
            covered_elements_for_path=covered_elements_for_path,
        )
        result = unique_matrix(
            fuzzers,
            coverage_sets,
            note='Compact coverage sets missing for one or more fuzzers; the matrix may be partial.' if len(coverage_sets) != len(fuzzers) else None,
        )
        return {
            **result,
            'metric': metric,
            'aggregation': 'per-fuzzer aggregate compact coverage sets',
        }

    def compute_branch_stat_matrices(
        self,
        *,
        trials: list[dict[str, Any]],
        benchmark: str,
        fuzz_target: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        '''Compute pairwise branch-coverage Mann-Whitney and A12 matrices.'''

        fuzzers = sorted(
            {
                str(trial.get('fuzzer'))
                for trial in trials
                if trial.get('benchmark') == benchmark and trial.get('fuzz_target') == fuzz_target and trial.get('fuzzer')
            }
        )
        distributions, missing_any = self._branch_coverage_distributions(
            trials=trials,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            fuzzers=fuzzers,
        )
        note = 'Final branch coverage missing for one or more trials; pairwise branch statistics may be partial.' if missing_any else None
        p_value_matrix = pairwise_matrix(
            fuzzers,
            distributions,
            compare=self._mann_whitney_u_pvalue,
            max_value=1.0,
            missing_value=1.0,
            note=note,
        )
        a12_matrix = pairwise_matrix(
            fuzzers,
            distributions,
            compare=self._vargha_delaney_a12,
            max_value=1.0,
            missing_value=0.5,
            note=note,
        )
        p_value_matrix.update(
            {
                'format': 'float',
                'aggregation': 'per-trial final branch coverage',
                'metric': 'branches',
                'statistic': 'mann_whitney_u_pvalue',
            }
        )
        a12_matrix.update(
            {
                'format': 'float',
                'aggregation': 'per-trial final branch coverage',
                'metric': 'branches',
                'statistic': 'vargha_delaney_a12',
            }
        )
        return (
            self._single_metric_matrix_group(p_value_matrix),
            self._single_metric_matrix_group(a12_matrix),
        )

    def attach_exclusive_coverage_stats(
        self,
        *,
        target: dict[str, Any],
        metric: str = 'branches',
    ) -> dict[str, Any]:
        '''Attach per-fuzzer exclusive coverage totals to a target.'''

        entries = target.get('fuzzers') or []
        unique_matrix = ((target.get('unique_matrix') or {}).get('by_metric') or {}).get(metric) or {}
        fuzzers = [str(fuzzer) for fuzzer in unique_matrix.get('fuzzers') or []]
        unique_counts = unique_matrix.get('unique_counts') or []
        note = unique_matrix.get('note')

        for entry in entries:
            fuzzer = str(entry.get('fuzzer') or '')
            idx = fuzzers.index(fuzzer) if fuzzer in fuzzers else -1
            total = unique_counts[idx] if idx >= 0 and idx < len(unique_counts) else None
            entry['exclusive_coverage'] = {
                'metric': metric,
                'total': int(total) if isinstance(total, (int, float)) else None,
                'min': None,
                'max': None,
                'median': None,
                'note': note,
            }
        return target

    def compute_relcov_matrix(
        self,
        *,
        trials: list[dict[str, Any]],
        benchmark: str,
        fuzz_target: str,
        coverage_sets_for_fuzzer: Callable[[str, str, str], Path | None],
        covered_elements_for_path: Callable[[Path, str], set[str]],
    ) -> tuple[dict[str, Any], dict[str, float]]:
        '''Compute pairwise relative coverage containment and novelty-weighted branch scores.'''

        fuzzers = sorted(
            {
                str(trial.get('fuzzer'))
                for trial in trials
                if trial.get('benchmark') == benchmark and trial.get('fuzz_target') == fuzz_target and trial.get('fuzzer')
            }
        )
        by_metric = {
            metric: self._compute_relcov_matrix_for_metric(
                fuzzers=fuzzers,
                benchmark=benchmark,
                fuzz_target=fuzz_target,
                metric=metric,
                coverage_sets_for_fuzzer=coverage_sets_for_fuzzer,
                covered_elements_for_path=covered_elements_for_path,
            )
            for metric in self._cov_metrics
        }
        branch_sets = self._coverage_sets_for_metric(
            fuzzers=fuzzers,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            metric='branches',
            coverage_sets_for_fuzzer=coverage_sets_for_fuzzer,
            covered_elements_for_path=covered_elements_for_path,
        )
        score_by_fuzzer = self._relcov_scores(fuzzers=fuzzers, coverage_sets=branch_sets)
        return (
            {
                'by_metric': by_metric,
                'has_data': any(entry.get('has_data') for entry in by_metric.values()),
                'available_metrics': [metric for metric, entry in by_metric.items() if entry.get('has_data')],
            },
            score_by_fuzzer,
        )

    def _compute_relcov_matrix_for_metric(
        self,
        *,
        fuzzers: list[str],
        benchmark: str,
        fuzz_target: str,
        metric: str,
        coverage_sets_for_fuzzer: Callable[[str, str, str], Path | None],
        covered_elements_for_path: Callable[[Path, str], set[str]],
    ) -> dict[str, Any]:
        coverage_sets = self._coverage_sets_for_metric(
            fuzzers=fuzzers,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            metric=metric,
            coverage_sets_for_fuzzer=coverage_sets_for_fuzzer,
            covered_elements_for_path=covered_elements_for_path,
        )
        missing_any = len(coverage_sets) != len(fuzzers)
        matrix: list[list[float]] = []
        max_value = 0.0
        for row_fuzzer in fuzzers:
            row_union = coverage_sets.get(row_fuzzer, set())
            row_vals = []
            for col_fuzzer in fuzzers:
                col_union = coverage_sets.get(col_fuzzer, set())
                denominator = len(col_union)
                value = 100.0 * len(row_union & col_union) / denominator if denominator > 0 else 0.0
                row_vals.append(value)
                max_value = max(max_value, value)
            matrix.append(row_vals)

        has_data = any(bool(values) for values in coverage_sets.values())
        return {
            'fuzzers': fuzzers,
            'matrix': matrix,
            'covered_counts': [len(coverage_sets.get(fuzzer, set())) for fuzzer in fuzzers],
            'has_data': has_data,
            'note': 'Compact coverage sets missing for one or more fuzzers; relative coverage may be partial.' if missing_any else None,
            'max_value': max_value,
            'format': 'pct',
            'aggregation': f'per-fuzzer aggregate compact {metric} coverage sets',
        }

    def _coverage_sets_for_metric(
        self,
        *,
        fuzzers: list[str],
        benchmark: str,
        fuzz_target: str,
        metric: str,
        coverage_sets_for_fuzzer: Callable[[str, str, str], Path | None],
        covered_elements_for_path: Callable[[Path, str], set[str]],
    ) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for fuzzer in fuzzers:
            coverage_path = coverage_sets_for_fuzzer(benchmark, fuzz_target, fuzzer)
            if coverage_path is not None:
                out[fuzzer] = covered_elements_for_path(coverage_path, metric)
        return out

    @staticmethod
    def _single_metric_matrix_group(matrix: dict[str, Any]) -> dict[str, Any]:
        return {
            'by_metric': {'branches': matrix},
            'has_data': bool(matrix.get('has_data')),
            'available_metrics': ['branches'] if matrix.get('has_data') else [],
        }

    def _branch_coverage_distributions(
        self,
        *,
        trials: list[dict[str, Any]],
        benchmark: str,
        fuzz_target: str,
        fuzzers: list[str],
    ) -> tuple[dict[str, list[float]], bool]:
        distributions = {fuzzer: [] for fuzzer in fuzzers}
        missing_any = False
        for trial in trials:
            if trial.get('benchmark') != benchmark or trial.get('fuzz_target') != fuzz_target:
                continue
            fuzzer = str(trial.get('fuzzer') or '')
            if fuzzer not in distributions:
                continue
            value = self._safe_int((trial.get('coverage') or {}).get('branches_covered'))
            if value is None:
                missing_any = True
                continue
            distributions[fuzzer].append(float(value))
        return distributions, missing_any

    @staticmethod
    def _relcov_scores(*, fuzzers: list[str], coverage_sets: dict[str, set[str]]) -> dict[str, float]:
        fuzzer_count = len(fuzzers)
        covered_by_fuzzers_count: dict[str, int] = {}
        for edge in set().union(*(coverage_sets.get(fuzzer, set()) for fuzzer in fuzzers)):
            covered_by_fuzzers_count[edge] = sum(1 for fuzzer in fuzzers if edge in coverage_sets.get(fuzzer, set()))
        return {
            fuzzer: sum(float(fuzzer_count - covered_by_fuzzers_count.get(edge, 0)) for edge in coverage_sets.get(fuzzer, set()))
            for fuzzer in fuzzers
        }
