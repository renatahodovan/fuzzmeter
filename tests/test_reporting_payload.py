# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Test full reporting payload preservation.'''

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest

from pathlib import Path
from typing import Any

from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.reporting import build_payload, write_report

PAYLOAD_HASH = '043c5f6e6398d2db7df0d6510f3bc3872e38331a2b4b88d83f6b76cb45ca2707'


class ReportingPayloadTest(unittest.TestCase):
    '''Verify full report payload stability for a deterministic run fixture.'''

    def test_build_payload_matches_stable_snapshot_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _build_run_fixture(run_dir)

            payload = build_payload(run_dir, run_id='run')

        normalized = _normalize_payload(payload)
        self.assertEqual(PAYLOAD_HASH, _payload_hash(normalized))

    def test_write_report_writes_static_payload_and_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _build_run_fixture(run_dir)

            report_dir = write_report(run_dir, out_dir=run_dir / 'report')

            self.assertEqual((run_dir / 'report').resolve(), report_dir)
            self.assertTrue((report_dir / 'data.json').is_file())
            self.assertTrue((report_dir / 'report.css').is_file())
            self.assertTrue((report_dir / 'report.js').is_file())
            self.assertTrue((report_dir / 'report').is_dir())
            self.assertIn(
                'window.FM_STATIC_DATA = ',
                (report_dir / 'report.html').read_text(encoding='utf-8'),
            )


def _build_run_fixture(run_dir: Path) -> None:
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
                'run',
                'fz',
                'bench',
                'target',
                0,
                60,
                1,
                'done',
                100,
                160,
                'image',
                '{"opt":"O2"}',
                '{"jobs":1}',
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
            stats_json='{"execs_per_sec": "3.5"}',
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
            stats_json='{"execs_per_sec": "4.5"}',
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
                trial_id,
                2,
                170,
                'c',
                12.5,
                2 * 1024 * 1024,
                8 * 1024 * 1024,
                25.0,
                3 * 1024 * 1024,
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
            snapshot_id,
            trial_id,
            idx,
            ts,
            corpus_files,
            execs_done,
            stats_json,
            crashes,
            hangs,
            lines[0],
            lines[1],
            branches[0],
            branches[1],
            functions[0],
            functions[1],
            regions[0],
            regions[1],
            'coverage/fz/index.html',
        ),
    )


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized['meta'] = dict(payload['meta'])
    normalized['meta']['generated_at'] = '<generated>'
    return normalized


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


if __name__ == '__main__':
    unittest.main()
