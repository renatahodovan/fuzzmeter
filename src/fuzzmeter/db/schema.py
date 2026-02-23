# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Define the SQLite schema used by fuzzmeter runs.'''

from __future__ import annotations

from .base import DB


_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS runs(
      run_id TEXT PRIMARY KEY,
      created_ts INTEGER,
      suite_yaml TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trials(
      trial_id INTEGER PRIMARY KEY AUTOINCREMENT,

      run_id TEXT NOT NULL,
      fuzzer TEXT NOT NULL,
      benchmark TEXT NOT NULL,
      fuzz_target TEXT NOT NULL,
      rep INTEGER NOT NULL,

      time_seconds INTEGER,
      jobs INTEGER,
      status TEXT,

      fuzzer_image TEXT,
      build_config_json TEXT,
      runtime_config_json TEXT,

      started_ts INTEGER,
      ended_ts INTEGER
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_trials_run_target
      ON trials(run_id, benchmark, fuzz_target)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_trials_run_f_b_t_rep
      ON trials(run_id, fuzzer, benchmark, fuzz_target, rep)
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshot_ticks(
      run_id TEXT NOT NULL,
      idx INTEGER NOT NULL,
      ts INTEGER NOT NULL,
      PRIMARY KEY(run_id, idx)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots(
      snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
      trial_id INTEGER NOT NULL,
      idx INTEGER NOT NULL,
      ts INTEGER NOT NULL,

      corpus_files INTEGER NOT NULL DEFAULT 0,
      execs_done INTEGER,
      stats_json TEXT,
      crashes INTEGER NOT NULL DEFAULT 0,
      hangs INTEGER NOT NULL DEFAULT 0,

      coverage_html_dir TEXT,

      cov_lines_covered INTEGER,
      cov_lines_total INTEGER,
      cov_branches_covered INTEGER,
      cov_branches_total INTEGER,
      cov_regions_covered INTEGER,
      cov_regions_total INTEGER,
      cov_functions_covered INTEGER,
      cov_functions_total INTEGER,

      UNIQUE(trial_id, idx)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_snapshots_trial_idx
      ON snapshots(trial_id, idx)
    """,
    """
    CREATE TABLE IF NOT EXISTS agg_snapshots(
      agg_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id TEXT NOT NULL,
      fuzzer TEXT NOT NULL,
      benchmark TEXT NOT NULL,
      fuzz_target TEXT NOT NULL,
      idx INTEGER NOT NULL,
      ts INTEGER NOT NULL,
      coverage_html_dir TEXT,
      coverage_sets_json_rel TEXT,

      cov_lines_covered INTEGER,
      cov_lines_total INTEGER,
      cov_branches_covered INTEGER,
      cov_branches_total INTEGER,
      cov_regions_covered INTEGER,
      cov_regions_total INTEGER,
      cov_functions_covered INTEGER,
      cov_functions_total INTEGER,

      UNIQUE(run_id, fuzzer, benchmark, fuzz_target, idx)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agg_snapshots_run_fuzzer_target
      ON agg_snapshots(run_id, fuzzer, benchmark, fuzz_target, idx)
    """,
    """
    CREATE TABLE IF NOT EXISTS bugs(
      bug_id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id TEXT NOT NULL,
      fuzzer TEXT NOT NULL,
      benchmark TEXT NOT NULL,
      fuzz_target TEXT NOT NULL,
      bug_key TEXT NOT NULL,
      issue_type TEXT,
      top_func TEXT,
      frames_json TEXT,
      output TEXT,
      first_seen_ts INTEGER NOT NULL,
      first_seen_snapshot_id INTEGER NOT NULL,
      UNIQUE(run_id, fuzzer, benchmark, fuzz_target, bug_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bug_hits(
      bug_id INTEGER NOT NULL,
      snapshot_id INTEGER NOT NULL,
      hits INTEGER NOT NULL,
      PRIMARY KEY(bug_id, snapshot_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_telemetry(
      trial_id INTEGER NOT NULL,
      idx INTEGER NOT NULL,
      ts INTEGER NOT NULL,
      container_name TEXT NOT NULL,
      cpu_percent REAL,
      memory_usage_bytes INTEGER,
      memory_limit_bytes INTEGER,
      memory_percent REAL,
      corpus_disk_usage_bytes INTEGER,
      corpus_disk_usage_human TEXT,
      stats_json TEXT,
      PRIMARY KEY(trial_id, idx)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resource_telemetry_trial_idx
      ON resource_telemetry(trial_id, idx)
    """,
]


def ensure_schema(db: DB) -> None:
    '''Create the current run database schema.'''
    for stmt in _SCHEMA:
        db.exec(stmt)
    db.commit()
