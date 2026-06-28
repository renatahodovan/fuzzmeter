# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Test reporting boundary and plugin helper behavior.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from fuzzmeter.reporting.data.coverage_data import CoverageData
from fuzzmeter.reporting.plugin_api import (
    ChartSeries,
    ChartSpec,
    DataPoint,
    ExtraSection,
    MatrixData,
    ReportingContext,
    TableColumn,
)
from fuzzmeter.reporting.plugin_sections import (
    _build_plugin_sections,
    _build_trial_snapshot_index,
    _expand_reporting_candidates,
    _snapshot_dirs_by_trial,
)
from fuzzmeter.reporting.plugins.loader import (
    FunctionReportingPlugin,
    NullReportingPlugin,
    ReportingPluginLoader,
)
from fuzzmeter.reporting.web_payload import serialize_extra_sections, validate_extra_sections


class CoverageDataTest(unittest.TestCase):
    '''Verify reporting coverage artifact resolution and caching.'''

    def test_resolves_explicit_coverage_sets_path_before_html_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            explicit_path = run_dir / 'coverage' / 'explicit' / 'coverage-sets.json'
            fallback_path = run_dir / 'coverage' / 'html-root' / 'coverage-sets.json'
            html_path = run_dir / 'coverage' / 'html-root' / 'html' / 'index.html'
            explicit_path.parent.mkdir(parents=True)
            fallback_path.parent.mkdir(parents=True)
            html_path.parent.mkdir(parents=True)
            explicit_path.write_text('{}', encoding='utf-8')
            fallback_path.write_text('{}', encoding='utf-8')

            data = CoverageData(run_dir)

            self.assertEqual(
                explicit_path.resolve(),
                data.coverage_sets_for_snapshot(
                    {
                        'coverage_sets_json_rel': 'coverage/explicit/coverage-sets.json',
                        'coverage_html_dir': 'coverage/html-root/html/index.html',
                    }
                ),
            )

    def test_resolves_coverage_sets_next_to_html_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            coverage_sets = run_dir / 'coverage' / 'fz' / 'coverage-sets.json'
            html_path = run_dir / 'coverage' / 'fz' / 'html' / 'index.html'
            html_path.parent.mkdir(parents=True)
            coverage_sets.write_text('{}', encoding='utf-8')

            data = CoverageData(run_dir)

            self.assertEqual(
                coverage_sets.resolve(),
                data.coverage_sets_for_snapshot({'coverage_html_dir': 'coverage/fz/html/index.html'}),
            )

    def test_returns_empty_counts_for_missing_coverage_sets(self) -> None:
        data = CoverageData(Path('/missing/run'))

        self.assertEqual(
            {'branches_covered': None, 'lines_covered': None},
            data.covered_counts(None, ('branches', 'lines')),
        )

    def test_caches_covered_elements_by_path_and_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coverage_path = Path(tmp) / 'coverage-sets.json'
            coverage_path.write_text('{}', encoding='utf-8')
            data = CoverageData(Path(tmp))

            with patch('fuzzmeter.reporting.data.coverage_data.read_covered_keys') as read_covered_keys:
                read_covered_keys.return_value = {'a', 'b'}

                self.assertEqual({'a', 'b'}, data.covered_elements(coverage_path, 'branches'))
                self.assertEqual({'a', 'b'}, data.covered_elements(coverage_path, 'branches'))

            read_covered_keys.assert_called_once_with(coverage_path, 'branches')


class WebPayloadTest(unittest.TestCase):
    '''Verify plugin payload validation and serialization.'''

    def test_rejects_non_list_plugin_output(self) -> None:
        self.assertEqual(([], ['plugin output is not a list']), validate_extra_sections({'not': 'a list'}))

    def test_rejects_invalid_sections_charts_and_matrices(self) -> None:
        valid = ExtraSection(
            id='valid',
            title='Valid',
            scope='target',
            placement='after:coverage',
            charts=[
                ChartSpec(
                    id='valid-chart',
                    title='Valid chart',
                    type='matrix',
                    matrix=MatrixData(fuzzers=['a'], matrix=[[0]], max_value=0),
                )
            ],
        )
        invalid = ExtraSection(
            id='invalid',
            title='Invalid',
            scope='target',
            placement='after:coverage',
            charts=[
                ChartSpec(
                    id='bad-matrix',
                    title='Bad matrix',
                    type='matrix',
                    matrix=MatrixData(fuzzers=['a', 'b'], matrix=[[1]], max_value=1),
                )
            ],
        )

        sections, warnings = validate_extra_sections([valid, invalid, object()])

        self.assertEqual([valid], sections)
        self.assertEqual(
            [
                'section[1]: chart[0]: matrix row count does not match labels',
                'section[2]: not an ExtraSection',
            ],
            warnings,
        )

    def test_serializes_valid_extra_section_payload(self) -> None:
        section = ExtraSection(
            id='section',
            title='Section',
            scope='fuzzer',
            placement='after:target',
            charts=[
                ChartSpec(
                    id='chart',
                    title='Chart',
                    type='table',
                    filter_mode='static',
                    series=[
                        ChartSeries(
                            id='series',
                            label='Series',
                            points=[DataPoint(x=1, y=2, lo=0, hi=3, meta={'k': 'v'})],
                            values=[1.5],
                            color_hint='#fff',
                        )
                    ],
                    columns=[TableColumn(key='name', label='Name')],
                    rows=[{'name': 'row'}],
                )
            ],
        )

        self.assertEqual(
            [
                {
                    'id': 'section',
                    'title': 'Section',
                    'scope': 'fuzzer',
                    'placement': 'after:target',
                    'owner_fuzzer': 'fz',
                    'charts': [
                        {
                            'id': 'chart',
                            'type': 'table',
                            'title': 'Chart',
                            'subtitle': None,
                            'x_axis': None,
                            'y_axis': None,
                            'metric_key': None,
                            'filter_mode': 'static',
                            'series': [
                                {
                                    'id': 'series',
                                    'label': 'Series',
                                    'points': [{'x': 1, 'y': 2, 'lo': 0, 'hi': 3, 'meta': {'k': 'v'}}],
                                    'values': [1.5],
                                    'color_hint': '#fff',
                                }
                            ],
                            'matrix': None,
                            'columns': [{'key': 'name', 'label': 'Name', 'kind': 'text'}],
                            'rows': [{'name': 'row'}],
                        }
                    ],
                }
            ],
            serialize_extra_sections([section], default_owner_fuzzer='fz'),
        )


class ReportingPluginLoaderTest(unittest.TestCase):
    '''Verify fuzzer reporting plugin discovery and adaptation.'''

    def test_missing_plugin_returns_null_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin, matched = ReportingPluginLoader(Path(tmp)).load_first(['missing'])

        self.assertIsInstance(plugin, NullReportingPlugin)
        self.assertIsNone(matched)

    def test_module_without_plugin_entrypoint_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fuzzers' / 'fz' / 'run' / 'reporting.py'
            path.parent.mkdir(parents=True)
            path.write_text('VALUE = 1\n', encoding='utf-8')

            plugin, matched = ReportingPluginLoader(Path(tmp)).load_first(['fz'])

        self.assertIsInstance(plugin, NullReportingPlugin)
        self.assertIsNone(matched)

    def test_function_plugin_is_adapted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fuzzers' / 'fz' / 'run' / 'reporting.py'
            path.parent.mkdir(parents=True)
            path.write_text('def build_extra_sections(ctx):\n    return []\n', encoding='utf-8')

            plugin, matched = ReportingPluginLoader(Path(tmp)).load_first(['fz'])

        self.assertIsInstance(plugin, FunctionReportingPlugin)
        self.assertEqual('fz', matched)

    def test_getter_plugin_is_loaded_before_function_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fuzzers' / 'fz' / 'run' / 'reporting.py'
            path.parent.mkdir(parents=True)
            path.write_text(
                'class Plugin:\n'
                '    def build_extra_sections(self, ctx):\n'
                '        return []\n'
                'def get_reporting_plugin():\n'
                '    return Plugin()\n'
                'def build_extra_sections(ctx):\n'
                '    raise AssertionError("wrong entrypoint")\n',
                encoding='utf-8',
            )

            plugin, matched = ReportingPluginLoader(Path(tmp)).load_first(['fz'])

        self.assertEqual('fz', matched)
        self.assertEqual([], plugin.build_extra_sections(_context()))

    def test_import_time_error_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fuzzers' / 'fz' / 'run' / 'reporting.py'
            path.parent.mkdir(parents=True)
            path.write_text('raise RuntimeError("boom")\n', encoding='utf-8')

            with self.assertRaisesRegex(RuntimeError, 'boom'):
                ReportingPluginLoader(Path(tmp)).load_first(['fz'])

    def test_invalid_candidate_names_do_not_escape_fuzzers_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            escaped = Path(tmp) / 'escape' / 'run' / 'reporting.py'
            escaped.parent.mkdir(parents=True)
            escaped.write_text('def build_extra_sections(ctx):\n    return []\n', encoding='utf-8')

            plugin, matched = ReportingPluginLoader(Path(tmp)).load_first(['../escape'])

        self.assertIsInstance(plugin, NullReportingPlugin)
        self.assertIsNone(matched)


class ReportingPluginSectionsTest(unittest.TestCase):
    '''Verify plugin section context, candidate, and debug helpers.'''

    def test_expand_reporting_candidates_follows_parent_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            child_build = repo_root / 'fuzzers' / 'child' / 'build' / 'build.yaml'
            parent_run = repo_root / 'fuzzers' / 'parent' / 'run' / 'run.yaml'
            child_build.parent.mkdir(parents=True)
            parent_run.parent.mkdir(parents=True)
            child_build.write_text('reporting_parent: parent\n', encoding='utf-8')
            parent_run.write_text('parent: grand\n', encoding='utf-8')

            self.assertEqual(
                ['child', 'parent', 'grand'],
                _expand_reporting_candidates(repo_root, ['child', 'parent']),
            )

    def test_snapshot_dirs_use_fuzzer_base_and_candidate_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            snap_dir = run_dir / 'trials' / 'base__bench-target__rep2' / 'snapshots' / 'snap_000001'
            snap_dir.mkdir(parents=True)

            index = _build_trial_snapshot_index(run_dir)
            dirs = _snapshot_dirs_by_trial(
                [{'trial_id': 7, 'fuzzer': 'derived', 'benchmark': 'bench', 'fuzz_target': 'target', 'rep': 2}],
                index,
                ['derived', 'base'],
                'base',
            )

            self.assertEqual({7: [snap_dir.resolve()]}, dirs)

    def test_build_plugin_sections_reports_plugin_errors_and_debug(self) -> None:
        class BrokenPlugin:
            def build_extra_sections(self, ctx):
                raise RuntimeError('broken')

            def build_debug_info(self, ctx):
                return {'source': 'debug'}

        with patch('fuzzmeter.reporting.plugin_sections.LOG.exception'):
            sections, debug = _build_plugin_sections(
                plugin=BrokenPlugin(),
                matched_plugin_name='fz',
                plugin_candidates=['fz'],
                base_name=None,
                ctx=_context(),
            )

        self.assertEqual([], sections)
        self.assertEqual('error', debug['status'])
        self.assertEqual('broken', debug['error'])
        self.assertEqual('debug', debug['source'])
        self.assertEqual('plugin_returned_no_sections', debug['reason'])

    def test_build_plugin_sections_reports_validation_warnings(self) -> None:
        class InvalidPlugin:
            def build_extra_sections(self, ctx):
                return [ExtraSection(id='', title='Missing id', scope='target', placement='after:coverage')]

        sections, debug = _build_plugin_sections(
            plugin=InvalidPlugin(),
            matched_plugin_name='fz',
            plugin_candidates=['fz'],
            base_name='base',
            ctx=_context(),
        )

        self.assertEqual([], sections)
        self.assertEqual('ok', debug['status'])
        self.assertEqual(['section[0]: missing section id'], debug['validation_warnings'])
        self.assertEqual('plugin_returned_no_sections', debug['reason'])


def _context() -> ReportingContext:
    return ReportingContext(
        run_id='run',
        run_dir=Path('/tmp/run'),
        benchmark='bench',
        fuzz_target='target',
        fuzzer='fz',
        trials=[],
        timeseries_by_trial={},
        bugs=[],
        snapshot_dirs_by_trial={},
    )


if __name__ == '__main__':
    unittest.main()
