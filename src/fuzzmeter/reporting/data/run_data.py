# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...db.report_views import ReportingDB


@dataclass(frozen=True)
class RunDataSnapshot:
    '''Hold all database rows needed for report generation.'''

    run_id: str
    overview_raw: dict[str, Any]
    trial_rows: list[dict[str, Any]]
    latest_snapshots: dict[int, dict[str, Any]]
    latest_agg_snapshots: dict[tuple[str, str, str], dict[str, Any]]
    snapshot_rows: list[dict[str, Any]]
    resource_telemetry_rows: list[dict[str, Any]]
    bug_hits_by_snapshot: dict[int, int]
    unique_bug_delta_by_snapshot: dict[int, int]
    bug_stats_by_trial: dict[int, tuple[int, int]]
    bugs: list[dict[str, Any]]
    bug_hits_by_bug: dict[int, int]
    bug_trials_by_bug: dict[int, list[int]]


class RunData:
    '''Load report data from the run database.'''

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def open(self) -> ReportingDB:
        '''Open the reporting database view.'''

        return ReportingDB(self.db_path)

    def load(self, *, run_dir_name: str, run_id: str | None = None) -> RunDataSnapshot:
        '''Load all report rows for a run.'''

        with self.open() as db:
            resolved_run_id = run_id or db.infer_run_id(run_dir_name)
            overview_raw = db.run_overview(resolved_run_id)
            trial_rows = db.trial_rows(resolved_run_id)
            trial_ids = [int(row['trial_id']) for row in trial_rows]
            latest_snapshots = db.latest_snapshots_by_trial(trial_ids)
            latest_agg_snapshots = db.latest_agg_snapshots_by_fuzzer_target(resolved_run_id)
            snapshot_rows = db.snapshot_rows(trial_ids)
            resource_telemetry_rows = db.resource_telemetry_rows(trial_ids)
            bug_hits_by_snapshot = db.bug_hits_by_snapshot()
            unique_bug_delta_by_snapshot = db.unique_bug_delta_by_snapshot()
            bug_stats_by_trial = db.bug_stats_by_trial(resolved_run_id)
            bugs = db.bug_rows(resolved_run_id)
            bug_hits_by_bug = db.bug_hits_by_bug()
            bug_trials_by_bug = db.bug_trials_by_bug()
        return RunDataSnapshot(
            run_id=resolved_run_id,
            overview_raw=overview_raw,
            trial_rows=trial_rows,
            latest_snapshots=latest_snapshots,
            latest_agg_snapshots=latest_agg_snapshots,
            snapshot_rows=snapshot_rows,
            resource_telemetry_rows=resource_telemetry_rows,
            bug_hits_by_snapshot=bug_hits_by_snapshot,
            unique_bug_delta_by_snapshot=unique_bug_delta_by_snapshot,
            bug_stats_by_trial=bug_stats_by_trial,
            bugs=bugs,
            bug_hits_by_bug=bug_hits_by_bug,
            bug_trials_by_bug=bug_trials_by_bug,
        )
