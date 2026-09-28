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
import subprocess
import sys
import tempfile
import unittest

from pathlib import Path
from typing import Any

from fuzzmeter.db import DB
from fuzzmeter.db import bug as db_bug
from fuzzmeter.db.report_views import ReportingDB
from fuzzmeter.reporting import build_payload, write_report
from fuzzmeter.reporting.provenance import attach_measurement_provenance
from fuzzmeter.web.services.report_service import load_report_payload
from tests.support.dbs import agg_snapshot_row, reporting_run_db

PAYLOAD_HASH = '4e11b172cb08886b379c3b3b68efcb70ce6c8b22dc2224e73711609587b306f5'
REPO_ROOT = Path(__file__).resolve().parents[1]
_BUNDLE_SMOKE_SCRIPT = r'''
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
'''


class ReportingPayloadTest(unittest.TestCase):
    """Verify full report payload stability for a deterministic run fixture."""

    def test_payload_import_does_not_load_execution_pipelines(self) -> None:
        subprocess.run(
            [
                sys.executable,
                '-c',
                'import sys\n'
                'import fuzzmeter.reporting.payload\n'
                'blocked = ("fuzzmeter.docker", "fuzzmeter.artifacts.seeds", '
                '"fuzzmeter.repro", "fuzzmeter.composite")\n'
                'loaded = [name for name in sys.modules '
                'if any(name == prefix or name.startswith(prefix + ".") for prefix in blocked)]\n'
                'assert not loaded, loaded\n',
            ],
            check=True,
        )

    def test_payload_carries_only_the_sections_the_report_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            reporting_run_db(run_dir)

            payload = build_payload(run_dir, run_id='run')

        self.assertEqual(['meta', 'overview', 'targets', 'measurement_provenance'], list(payload))

    def test_build_payload_matches_stable_snapshot_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            reporting_run_db(run_dir)

            payload = build_payload(run_dir, run_id='run')

        fuzzer = payload['targets'][0]['fuzzers'][0]
        self.assertEqual('bench', fuzzer['metadata']['config']['benchmark'])
        self.assertEqual(1, len(fuzzer['extra_sections']))
        chart = fuzzer['extra_sections'][0]['charts'][0]
        self.assertEqual(
            {'bucket_size_seconds': 60, 'time_points': 1, 'series_count': 2},
            {
                key: fuzzer['extra_section_debug'][0][key]
                for key in ('bucket_size_seconds', 'time_points', 'series_count')
            },
        )
        self.assertEqual(
            {
                'havoc': [(60, 50.0)],
                'splice': [(60, 50.0)],
            },
            {
                series['id']: [(point['x'], point['y']) for point in series['points']]
                for series in chart['series']
            },
        )
        normalized = _normalize_payload(payload)
        self.assertEqual(PAYLOAD_HASH, _payload_hash(normalized))

    def test_broken_reporting_plugin_does_not_prevent_payload_building(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / 'run'
            run_dir.mkdir()
            reporting_run_db(run_dir)
            with DB.open(run_dir / 'fuzzmeter.db') as db:
                db.exec("UPDATE snapshots SET stats_json = '{}' ")
                db.commit()
            fuzzer_dir = run_dir / 'fuzzer_resources' / 'run' / 'fz' / 'fz'
            reporting_path = fuzzer_dir / 'run' / 'reporting.py'
            reporting_path.parent.mkdir(parents=True, exist_ok=True)
            reporting_path.write_text('raise RuntimeError("broken plugin")\n', encoding='utf-8')

            payload = build_payload(run_dir, run_id='run')

        fuzzer = payload['targets'][0]['fuzzers'][0]
        self.assertEqual([], fuzzer['extra_sections'])
        self.assertEqual('load_error', fuzzer['extra_section_debug'][0]['status'])
        self.assertEqual('broken plugin', fuzzer['extra_section_debug'][0]['error'])

    def test_unique_bug_discoveries_are_counted_independently_per_trial(self) -> None:
        '''A shared bug contributes once to each repetition, in tick order.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            reporting_run_db(run_dir)
            db_path = run_dir / 'fuzzmeter.db'
            with DB.open(db_path) as db:
                db.exec(
                    '''INSERT INTO trials(
                        trial_id, run_id, fuzzer, benchmark, fuzz_target, rep,
                        time_seconds, status, started_ts, ended_ts
                    ) VALUES(2, 'run', 'fz', 'bench', 'target', 1, 60, 'done', 200, 260)''',
                )
                # Snapshot IDs need not have the same order as logical ticks.
                for snapshot_id, idx, ts in ((30, 2, 260), (40, 1, 230)):
                    db.exec(
                        'INSERT INTO snapshots(snapshot_id, trial_id, idx, ts) VALUES(?,2,?,?)',
                        (snapshot_id, idx, ts),
                    )
                for bug_key, first_snapshot, first_ts, hits in (
                    ('shared', 10, 120, {10: 2, 11: 1, 40: 4, 30: 2}),
                    ('later', 30, 250, {40: 0, 30: 1}),
                ):
                    bug_id = db_bug.ensure_bug(db, db_bug.BugRecord(
                        run_id='run', fuzzer='fz', benchmark='bench', fuzz_target='target',
                        bug_key=bug_key, issue_type='crash', top_func='func',
                        frames=['func'], output='crash', first_seen_ts=first_ts,
                        first_seen_snapshot_id=first_snapshot,
                    ))
                    for snapshot_id, count in hits.items():
                        db_bug.upsert_bug_hits(db, bug_id=bug_id, snapshot_id=snapshot_id, hits=count)
                db.commit()
            with ReportingDB(db_path) as db:
                self.assertEqual({10: 1, 40: 1, 30: 1}, db.unique_bug_delta_by_snapshot())
            payload = build_payload(run_dir)

        fuzzer = payload['targets'][0]['fuzzers'][0]
        self.assertEqual([1, 2], [trial['unique_bugs_total'] for trial in fuzzer['trials']])
        self.assertEqual([1.0, 2.0], fuzzer['distribution']['unique_bugs_total'])
        self.assertEqual(1.5, fuzzer['final']['unique_bugs_total_mean'])
        self.assertEqual([1.0, 1.5], [point['unique_bugs_total_mean'] for point in fuzzer['curve']])

    def test_curve_points_carry_the_resource_series_the_report_plots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            reporting_run_db(run_dir)

            payload = build_payload(run_dir, run_id='run')

        curve = payload['targets'][0]['fuzzers'][0]['curve']
        plotted = [point for point in curve if 'resource_memory_mib_median' in point]
        self.assertTrue(plotted, 'report.js detects and plots the _median resource series')
        self.assertIn('resource_corpus_disk_mib_median', plotted[0])

    def test_mixed_provenance_adds_visible_comparison_warning(self) -> None:
        targets = [{
            'benchmark': 'bench',
            'fuzz_target': 'target',
            'fuzzers': [{'fuzzer': 'a'}, {'fuzzer': 'b'}],
        }]
        base = {
            'schema_version': 2,
            'requested_counter_update_mode': 'atomic',
            'branch_definition_version': 5,
            'branch_counting_definition': 'per-instantiation',
            'measurement': {'mode': 'stateless'},
            'coverage_build': {'clang_version': '18'},
            'llvm_cov': {'report_flags': ['-instr-profile=x']},
            'coverage_sets': {'freshness': 'fresh'},
        }
        snapshots = {
            ('a', 'bench', 'target'): agg_snapshot_row(measurement_provenance_json=json.dumps(base)),
            ('b', 'bench', 'target'): agg_snapshot_row(
                fuzzer='b',
                measurement_provenance_json=json.dumps({
                    **base,
                    'measurement': {'mode': 'batched-stateful'},
                }),
            ),
        }

        run_provenance = attach_measurement_provenance(
            targets=targets,
            agg_snapshots=snapshots,
        )

        self.assertIn('different or unavailable provenance', targets[0]['provenance_warning'])
        self.assertEqual('mixed_or_unavailable', run_provenance['consistency'])
        self.assertIn('mixed or unavailable provenance', run_provenance['warning'])
        self.assertTrue(run_provenance['threats_table'])

    def test_provenance_ignores_the_values_that_differ_per_fuzzer_by_construction(self) -> None:
        '''Profile paths and replay restart counts are not comparability deviations.'''

        targets = [{
            'benchmark': 'bench',
            'fuzz_target': 'target',
            'fuzzers': [{'fuzzer': 'a'}, {'fuzzer': 'b'}],
        }]
        base = {
            'schema_version': 2,
            'requested_counter_update_mode': 'atomic',
            'branch_definition_version': 5,
            'branch_counting_definition': 'per-instantiation',
            'measurement': {'mode': 'stateless', 'ordering': 'path-sorted'},
            'coverage_build': {'clang_version': '18'},
            'coverage_sets': {'freshness': 'fresh', 'source_tick': 1},
            'llvm_cov': {'report_flags': [], 'export_flags': ['-skip-expansions']},
        }
        snapshots = {
            ('a', 'bench', 'target'): agg_snapshot_row(measurement_provenance_json=json.dumps({
                **base,
                'measurement': {**base['measurement'], 'artificial_restarts': 1, 'batch_size': 168},
                'llvm_cov': {**base['llvm_cov'], 'report_flags': ['-instr-profile=/run/a/merged.profdata']},
            })),
            ('b', 'bench', 'target'): agg_snapshot_row(fuzzer='b', measurement_provenance_json=json.dumps({
                **base,
                'measurement': {**base['measurement'], 'artificial_restarts': 4, 'batch_size': 256},
                'llvm_cov': {**base['llvm_cov'], 'report_flags': ['-instr-profile=/run/b/merged.profdata']},
            })),
        }

        run_provenance = attach_measurement_provenance(
            targets=targets,
            agg_snapshots=snapshots,
        )

        self.assertEqual('consistent', run_provenance['consistency'])
        self.assertIsNone(run_provenance['warning'])
        self.assertNotIn('provenance_warning', targets[0])
        self.assertNotIn('provenance_badges', targets[0])
        statuses = {row['field']: row['status'] for row in run_provenance['threats_table']}
        self.assertEqual('consistent', statuses['llvm-cov report flags'])
        self.assertEqual('consistent', statuses['measurement mode'])

    def test_write_report_writes_static_payload_and_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            reporting_run_db(run_dir)

            report_dir = write_report(run_dir, out_dir=run_dir / 'report')

            self.assertEqual((run_dir / 'report').resolve(), report_dir)
            self.assertTrue((report_dir / 'data.json').is_file())
            self.assertTrue((report_dir / 'report.css').is_file())
            self.assertTrue((report_dir / 'report.js').is_file())
            self.assertTrue((report_dir / 'report').is_dir())
            self.assertTrue((report_dir / 'report' / 'favicon.png').is_file())
            self.assertTrue((report_dir / 'report' / 'favicon.svg').is_file())
            self.assertIn(
                'window.FM_STATIC_DATA = ',
                (report_dir / 'report.html').read_text(encoding='utf-8'),
            )
            self.assertIn(
                '<link rel="icon" type="image/png" href="report/favicon.png" />',
                (report_dir / 'report.html').read_text(encoding='utf-8'),
            )
            self.assertIn(
                '<link rel="icon" type="image/svg+xml" sizes="any" href="report/favicon.svg" />',
                (report_dir / 'report.html').read_text(encoding='utf-8'),
            )
            self.assertIn(
                '<script src="report.js"></script>',
                (report_dir / 'report.html').read_text(encoding='utf-8'),
            )
            self.assertIn(
                'id="comparisonModeAny"',
                (report_dir / 'report.html').read_text(encoding='utf-8'),
            )
            self.assertIn(
                'id="measurementProvenancePanel"',
                (report_dir / 'report.html').read_text(encoding='utf-8'),
            )
            self.assertIn(
                'provenance_warning',
                (report_dir / 'report.js').read_text(encoding='utf-8'),
            )
            self.assertIn(
                'id="comparisonModeAll"',
                (report_dir / 'report.html').read_text(encoding='utf-8'),
            )

    def test_static_and_live_reports_use_the_same_fuzzer_plugin_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / 'run'
            run_dir.mkdir()
            reporting_run_db(run_dir)

            live_payload = load_report_payload([run_dir], 'run')
            report_dir = write_report(run_dir, out_dir=run_dir / 'report')
            static_payload = json.loads((report_dir / 'data.json').read_text(encoding='utf-8'))

        live_sections = live_payload['targets'][0]['fuzzers'][0]['extra_sections']
        static_sections = static_payload['targets'][0]['fuzzers'][0]['extra_sections']
        self.assertEqual(live_sections, static_sections)
        self.assertEqual('mutator-usefulness-ratio', live_sections[0]['charts'][0]['id'])

    def test_write_report_static_bundle_parses_and_smoke_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            reporting_run_db(run_dir)

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
