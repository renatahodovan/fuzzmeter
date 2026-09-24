'''Build run databases used across the unittest suite.'''

from __future__ import annotations

import shutil

from pathlib import Path
from typing import Any

from fuzzmeter.db import DB, ensure_schema, open_db
from fuzzmeter.db import metadata as db_metadata
from fuzzmeter.db import runs as db_runs
from fuzzmeter.db.resource_telemetry import TelemetrySample
from fuzzmeter.db.snapshot import AggSnapshotRow, SnapshotRow
from fuzzmeter.db.trials import TrialRow
from fuzzmeter.reporting.analyzers.trial_analysis import TrialReport
from fuzzmeter.reporting.data.run_data import RunDataSnapshot


def empty_run_db(db_path: Path) -> None:
    '''Create an empty run database with the current schema.'''
    with DB.open(db_path) as db:
        ensure_schema(db)


def seeded_run_db(db_path: Path) -> None:
    '''Create the run, trial, and snapshots required by bug persistence tests.'''
    db = DB.open(db_path)
    try:
        ensure_schema(db)
        db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run', 1, 'config'))
        db.exec(
            '''
            INSERT INTO trials(
              trial_id, run_id, fuzzer, benchmark, fuzz_target, rep, status, started_ts
            )
            VALUES(?,?,?,?,?,?,?,?)
            ''',
            (1, 'run', 'fuzzer', 'bench', 'target', 0, 'running', 1),
        )
        for snapshot_id in (7, 9):
            db.exec(
                '''
                INSERT INTO snapshots(snapshot_id, trial_id, idx, ts, corpus_files)
                VALUES(?,?,?,?,?)
                ''',
                (snapshot_id, 1, snapshot_id, snapshot_id, 0),
            )
    finally:
        db.close()


def measurement_run_db(
    run_dir: Path,
    *,
    source_id: str,
    run_id: str | None = None,
    fuzzer: str = 'libfuzzer',
    benchmark: str = 'zlib',
    fuzz_target: str = 'compress',
    environment: dict | None = None,
) -> None:
    '''Create a run database containing one discoverable measurement.'''
    run_dir.mkdir(parents=True, exist_ok=True)
    resolved_run_id = source_id if run_id is None else run_id
    resolved_environment = {'host': {'system': 'test'}} if environment is None else environment
    with open_db(run_dir / 'fuzzmeter.db') as db:
        ensure_schema(db)
        db_runs.upsert_run(db, run_id=resolved_run_id, created_ts=100, config_src='config')
        db_metadata.upsert_metadata(
            db,
            db_metadata.MetadataRecord(
                run_id=resolved_run_id,
                fuzzer=fuzzer,
                benchmark=benchmark,
                fuzz_target=fuzz_target,
                repetitions=1,
                runtime_seconds=60,
                environment_digest='env',
                config_digest='cfg',
                source_digest='src',
                metadata={
                    'environment': resolved_environment,
                    'config': {'benchmark': benchmark, 'fuzz_target': fuzz_target},
                    'source': {},
                    'digests': {'environment': 'env', 'config': 'cfg', 'source': 'src'},
                },
                created_at=100,
            ),
        )


def run_listing_db(
    run_dir: Path,
    *,
    run_id: str,
    created_ts: int,
    config_src: str = 'fuzzers: [fz]\n',
    label: str | None = None,
    with_trial_data: bool = False,
) -> None:
    '''Create a run database used by web run-listing service tests.'''
    db = DB.open(run_dir / 'fuzzmeter.db')
    try:
        ensure_schema(db)
        db.exec(
            'INSERT INTO runs(run_id, created_ts, config_src, label) VALUES(?,?,?,?)',
            (run_id, created_ts, config_src, label),
        )
        if with_trial_data:
            db.exec(
                '''
                INSERT INTO trials(run_id, fuzzer, benchmark, fuzz_target, rep, status, started_ts)
                VALUES(?,?,?,?,?,?,?)
                ''',
                (run_id, 'fz', 'bench', 'target-a', 0, 'done', created_ts),
            )
            db.exec(
                '''
                INSERT INTO trials(run_id, fuzzer, benchmark, fuzz_target, rep, status, started_ts)
                VALUES(?,?,?,?,?,?,?)
                ''',
                (run_id, 'fz', 'bench', 'target-b', 0, 'running', created_ts),
            )
            trial_id = int(db.scalar('SELECT trial_id FROM trials WHERE fuzz_target=?', ('target-a',)))
            db.exec(
                '''
                INSERT INTO snapshots(snapshot_id, trial_id, idx, ts)
                VALUES(?,?,?,?)
                ''',
                (10, trial_id, 1, 100),
            )
            db.exec(
                '''
                INSERT INTO bugs(
                  run_id, fuzzer, benchmark, fuzz_target, bug_key, first_seen_ts, first_seen_snapshot_id
                )
                VALUES(?,?,?,?,?,?,?)
                ''',
                (run_id, 'fz', 'bench', 'target-a', 'bug', 100, 10),
            )
        db.commit()
    finally:
        db.close()


def reporting_run_db(run_dir: Path) -> None:
    '''Create the deterministic database used by report payload tests.'''
    reporting_path = run_dir / 'fuzzer_resources' / 'run' / 'fz' / 'fz' / 'run' / 'reporting.py'
    reporting_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        Path(__file__).resolve().parents[2] / 'fuzzers' / 'afl' / 'run' / 'reporting.py',
        reporting_path,
    )
    db = DB.open(run_dir / 'fuzzmeter.db')
    try:
        ensure_schema(db)
        db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run', 1, 'config'))
        db.exec(
            '''
            INSERT INTO trials(
              run_id, fuzzer, benchmark, fuzz_target, rep, time_seconds, jobs,
              status, started_ts, ended_ts, fuzzer_image, build_config_json, runtime_config_json
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                'run', 'fz', 'bench', 'target', 0, 60, 1, 'done', 100, 160,
                'image', '{"opt":"O2"}', '{"jobs":1}',
            ),
        )
        trial_id = int(db.scalar('SELECT trial_id FROM trials'))
        _insert_snapshot(
            db,
            snapshot_id=10,
            trial_id=trial_id,
            idx=1,
            ts=130,
            corpus_files=2,
            execs_done=100,
            stats_json=(
                '{"custom_metrics":{"counts":{"havoc":2},"id":"afl-mutator-counts",'
                '"kind":"counter_map"},'
                '"execs_per_sec":"3.5"}'
            ),
            crashes=1,
            hangs=0,
            lines=(5, 10),
            branches=(3, 6),
            functions=(1, 2),
            regions=(4, 8),
        )
        _insert_snapshot(
            db,
            snapshot_id=11,
            trial_id=trial_id,
            idx=2,
            ts=170,
            corpus_files=3,
            execs_done=180,
            stats_json=(
                '{"custom_metrics":{"counts":{"havoc":1,"splice":3},"id":"afl-mutator-counts",'
                '"kind":"counter_map"},'
                '"execs_per_sec":"4.5"}'
            ),
            crashes=2,
            hangs=1,
            lines=(6, 10),
            branches=(4, 6),
            functions=(1, 2),
            regions=(5, 8),
        )
        db.exec(
            '''
            INSERT INTO resource_telemetry(
              trial_id, idx, ts, container_name, cpu_percent, memory_usage_bytes,
              memory_limit_bytes, memory_percent, corpus_disk_usage_bytes
            )
            VALUES(?,?,?,?,?,?,?,?,?)
            ''',
            (
                trial_id, 2, 170, 'c', 12.5, 2 * 1024 * 1024,
                8 * 1024 * 1024, 25.0, 3 * 1024 * 1024,
            ),
        )
        db.exec(
            '''
            INSERT INTO metadata(
              run_id, fuzzer, benchmark, fuzz_target, repetitions, runtime_seconds,
              environment_digest, config_digest, source_digest, metadata_json, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                'run', 'fz', 'bench', 'target', 1, 60, 'env-digest',
                'cfg-digest', 'src-digest',
                '{"config":{"benchmark":"bench","fuzz_target":"target"},'
                '"environment":{"host":{"machine":"x86_64"}}}',
                1,
            ),
        )
        db.commit()
    finally:
        db.close()


def _insert_snapshot(
    db: DB,
    *,
    snapshot_id: int,
    trial_id: int,
    idx: int,
    ts: int,
    corpus_files: int,
    execs_done: int,
    stats_json: str,
    crashes: int,
    hangs: int,
    lines: tuple[int, int],
    branches: tuple[int, int],
    functions: tuple[int, int],
    regions: tuple[int, int],
) -> None:
    db.exec(
        '''
        INSERT INTO snapshots(
          snapshot_id, trial_id, idx, ts, corpus_files, execs_done, stats_json,
          crashes, hangs, cov_lines_covered, cov_lines_total,
          cov_branches_covered, cov_branches_total, cov_functions_covered,
          cov_functions_total, cov_regions_covered, cov_regions_total, coverage_html_dir
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''',
        (
            snapshot_id, trial_id, idx, ts, corpus_files, execs_done, stats_json,
            crashes, hangs, lines[0], lines[1], branches[0], branches[1],
            functions[0], functions[1], regions[0], regions[1],
            'coverage/fz/index.html',
        ),
    )


def trial_row(**overrides: Any) -> TrialRow:
    '''Build a stored trial row with the columns a test cares about.'''

    return TrialRow.from_row({
        'trial_id': 1, 'fuzzer': 'fz', 'benchmark': 'bench', 'fuzz_target': 'target',
        'rep': 0, 'time_seconds': 0, 'jobs': None, 'status': 'done',
        'started_ts': 0, 'ended_ts': None, 'fuzzer_image': 'image',
        'build_config_json': None, 'runtime_config_json': None,
        **overrides,
    })


def run_data_snapshot(**overrides: Any) -> RunDataSnapshot:
    '''Build a loaded run snapshot with only the rows a test cares about.'''

    return RunDataSnapshot(**{
        'run_id': 'run',
        'overview_raw': {},
        'trial_rows': [],
        'latest_snapshots': {},
        'latest_agg_snapshots': {},
        'seed_baselines': {},
        'metadata_rows': [],
        'snapshot_rows': [],
        'resource_telemetry_rows': [],
        'bug_hits_by_snapshot': {},
        'unique_bug_delta_by_snapshot': {},
        'bug_stats_by_trial': {},
        'bugs': [],
        'bug_hits_by_bug': {},
        'bug_trials_by_bug': {},
        **overrides,
    })


def snapshot_row(**overrides: Any) -> SnapshotRow:
    '''Build a stored snapshot row with the columns a test cares about.'''

    return SnapshotRow.from_row({
        'snapshot_id': 1, 'trial_id': 1, 'idx': 1, 'ts': 0, 'corpus_files': 0,
        'execs_done': None, 'crashes': 0, 'hangs': 0, 'stats_json': None,
        'coverage_html_dir': None, 'coverage_sets_json_rel': None,
        'cov_lines_covered': None, 'cov_lines_total': None,
        'cov_branches_covered': None, 'cov_branches_total': None,
        'cov_regions_covered': None, 'cov_regions_total': None,
        'cov_functions_covered': None, 'cov_functions_total': None,
        **overrides,
    })


def agg_snapshot_row(**overrides: Any) -> AggSnapshotRow:
    '''Build a stored campaign coverage row with the columns a test cares about.'''

    return AggSnapshotRow.from_row({
        'run_id': 'run', 'fuzzer': 'fz', 'benchmark': 'bench', 'fuzz_target': 'target',
        'idx': 1, 'ts': 0, 'coverage_html_dir': None, 'coverage_sets_json_rel': None,
        'measurement_provenance_json': None,
        'cov_lines_covered': None, 'cov_lines_total': None,
        'cov_branches_covered': None, 'cov_branches_total': None,
        'cov_regions_covered': None, 'cov_regions_total': None,
        'cov_functions_covered': None, 'cov_functions_total': None,
        **overrides,
    })


def telemetry_sample(**overrides: Any) -> TelemetrySample:
    '''Build a stored resource telemetry sample with the columns a test cares about.'''

    return TelemetrySample.from_row({
        'trial_id': 1, 'idx': 1, 'ts': 0, 'container_name': 'c',
        'cpu_percent': None, 'memory_usage_bytes': None, 'memory_limit_bytes': None,
        'memory_percent': None, 'corpus_disk_usage_bytes': None,
        **overrides,
    })


def trial_report(**overrides: Any) -> TrialReport:
    '''Build the report view of a trial with the fields a test cares about.'''

    fields: dict[str, Any] = {
        'trial_id': 1, 'fuzzer': 'fz', 'benchmark': 'bench', 'fuzz_target': 'target',
        'rep': 0, 'time_seconds': 0, 'status': 'done', 'fuzzer_image': 'image',
        'build_config': None, 'runtime_config': None,
        'started_ts': 0, 'ended_ts': None, 'elapsed_seconds': None,
        'bug_hits_total': 0, 'unique_bugs_total': 0,
        'corpus_files_total': None, 'execs_done': None, 'crashes': None, 'hangs': None,
        'coverage_html': None, 'coverage_html_rel': None, 'coverage_sets_json_rel': None,
    }
    for metric in ('branches', 'lines', 'functions', 'regions'):
        fields[f'{metric}_cov'] = None
        fields[f'{metric}_total'] = None
        fields[f'{metric}_pct'] = None
    return TrialReport(**{**fields, **overrides})
