'''Build run databases used across the unittest suite.'''

from __future__ import annotations

from pathlib import Path

from fuzzmeter.db import DB, ensure_schema, open_db
from fuzzmeter.db import metadata as db_metadata
from fuzzmeter.db import runs as db_runs


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
              trial_id, run_id, fuzzer, benchmark, fuzz_target, rep, status
            )
            VALUES(?,?,?,?,?,?,?)
            ''',
            (1, 'run', 'fuzzer', 'bench', 'target', 0, 'running'),
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
    with_trial_data: bool = False,
) -> None:
    '''Create a run database used by web run-listing service tests.'''
    db = DB.open(run_dir / 'fuzzmeter.db')
    try:
        ensure_schema(db)
        db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', (run_id, created_ts, config_src))
        if with_trial_data:
            db.exec(
                '''
                INSERT INTO trials(run_id, fuzzer, benchmark, fuzz_target, rep, status)
                VALUES(?,?,?,?,?,?)
                ''',
                (run_id, 'fz', 'bench', 'target-a', 0, 'done'),
            )
            db.exec(
                '''
                INSERT INTO trials(run_id, fuzzer, benchmark, fuzz_target, rep, status)
                VALUES(?,?,?,?,?,?)
                ''',
                (run_id, 'fz', 'bench', 'target-b', 0, 'running'),
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
                '{"custom_metrics":[{"counts":{"havoc":2},"id":"afl-mutator-counts",'
                '"kind":"counter_map","schema_version":1}],"custom_metrics_schema_version":1,'
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
                '{"custom_metrics":[{"counts":{"havoc":3,"splice":1},"id":"afl-mutator-counts",'
                '"kind":"counter_map","schema_version":1}],"custom_metrics_schema_version":1,'
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
