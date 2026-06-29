# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Test full reporting payload preservation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import unittest

from fuzzmeter.db import DB, ensure_schema
from fuzzmeter.reporting import build_payload, write_report

PAYLOAD_HASH = '043c5f6e6398d2db7df0d6510f3bc3872e38331a2b4b88d83f6b76cb45ca2707'
REPO_ROOT = Path(__file__).resolve().parents[1]
_BUNDLE_SMOKE_SCRIPT = r"""
import fs from 'node:fs';
import vm from 'node:vm';

const bundle = fs.readFileSync(process.argv[1], 'utf8');

class FakeElement {
  constructor(tagName = 'div') {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.childElementCount = 0;
    this.className = '';
    this.dataset = {};
    this.hidden = false;
    this.parentElement = null;
    this.style = {};
    this.textContent = '';
    this.classList = {
      add: () => {},
      remove: () => {},
      toggle: () => {},
    };
  }
  addEventListener() {}
  appendChild(child) {
    child.parentElement = this;
    this.children.push(child);
    this.childElementCount = this.children.length;
    return child;
  }
  closest() { return null; }
  contains() { return false; }
  getBoundingClientRect() { return { height: 1, left: 0, top: 0, width: 1 }; }
  getContext() { return null; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  scrollTo() {}
  setAttribute(name, value) { this[name] = value; }
}

const elements = new Map();
const document = {
  documentElement: new FakeElement('html'),
  addEventListener: () => {},
  createElement: (tagName) => new FakeElement(tagName),
  createTextNode: (text) => ({ textContent: String(text) }),
  getElementById: (id) => {
    if (!elements.has(id)) elements.set(id, new FakeElement());
    return elements.get(id);
  },
  querySelector: () => new FakeElement(),
  querySelectorAll: () => [],
};

const window = {
  FM_STATIC_DATA: {
    meta: { run_id: 'run', generated_at: 'generated' },
    overview: {},
    summary: { rankings: [] },
    targets: [],
  },
  addEventListener: () => {},
  matchMedia: () => ({ matches: false }),
  setTimeout: () => {},
};

const sandbox = {
  Blob,
  Element: FakeElement,
  HTMLTemplateElement: class {},
  TextEncoder,
  URL: { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} },
  console,
  document,
  getComputedStyle: () => ({ getPropertyValue: () => '', fontWeight: '400', textAlign: 'left' }),
  localStorage: { getItem: () => null, setItem: () => {} },
  setTimeout: () => {},
  window,
};
sandbox.globalThis = sandbox;

vm.runInNewContext(bundle, sandbox, { filename: process.argv[1] });
"""


class ReportingPayloadTest(unittest.TestCase):
    """Verify full report payload stability for a deterministic run fixture."""

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
            self.assertIn(
                '<script src="report.js"></script>',
                (report_dir / 'report.html').read_text(encoding='utf-8'),
            )

    def test_write_report_static_bundle_parses_and_smoke_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _build_run_fixture(run_dir)

            report_dir = write_report(run_dir, out_dir=run_dir / 'report')
            bundle_path = report_dir / 'report.js'

            subprocess.run(['node', '--check', str(bundle_path)], check=True)
            subprocess.run(
                ['node', '--no-warnings', '--input-type=module', '-e', _BUNDLE_SMOKE_SCRIPT, str(bundle_path)],
                check=True,
            )

    def test_report_module_bundle_uses_supported_module_syntax(self) -> None:
        module_dir = REPO_ROOT / 'src' / 'fuzzmeter' / 'web' / 'static' / 'report'
        unsupported_patterns = ('export default', 'import.meta')
        for path in sorted(module_dir.glob('*.js')):
            text = path.read_text(encoding='utf-8')
            for pattern in unsupported_patterns:
                self.assertNotIn(pattern, text, path.name)
            lines = text.splitlines()
            for index, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('import '):
                    statement = stripped
                    cursor = index
                    while not statement.endswith(';') and cursor + 1 < len(lines):
                        cursor += 1
                        statement = f'{statement} {lines[cursor].strip()}'
                    self.assertTrue(statement.endswith(';'), f'Unsupported import form in {path.name}: {line}')
                if stripped.startswith('export '):
                    self.assertFalse(stripped.startswith('export default'), path.name)


def _build_run_fixture(run_dir: Path) -> None:
    db = DB.open(run_dir / 'fuzzmeter.db')
    try:
        ensure_schema(db)
        db.exec('INSERT INTO runs(run_id, created_ts, config_src) VALUES(?,?,?)', ('run', 1, 'config'))
        db.exec(
            """
            INSERT INTO trials(
              run_id, fuzzer, benchmark, fuzz_target, rep, time_seconds, jobs,
              status, started_ts, ended_ts, fuzzer_image, build_config_json, runtime_config_json
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
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
            """
            INSERT INTO resource_telemetry(
              trial_id, idx, ts, container_name, cpu_percent, memory_usage_bytes,
              memory_limit_bytes, memory_percent, corpus_disk_usage_bytes
            )
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
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
        """
        INSERT INTO snapshots(
          snapshot_id, trial_id, idx, ts, corpus_files, execs_done, stats_json,
          crashes, hangs, cov_lines_covered, cov_lines_total,
          cov_branches_covered, cov_branches_total, cov_functions_covered,
          cov_functions_total, cov_regions_covered, cov_regions_total, coverage_html_dir
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
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
