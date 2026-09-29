# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Test reporting boundary and plugin helper behavior.'''

from __future__ import annotations

import shutil
import tempfile
import unittest

from pathlib import Path
from typing import get_args
from unittest.mock import patch

from fuzzers.afl.run.reporting import build_extra_sections as build_afl_sections
from fuzzers.aflplusplus.run.reporting import build_extra_sections as build_aflplusplus_sections
from fuzzmeter.config.models import RUN_CONFIG_FILE, read_run_config
from fuzzmeter.reporting.data.coverage_data import CoverageData
from fuzzmeter.reporting.plugin_api import (
    ChartSeries,
    ChartSpec,
    ChartType,
    DataPoint,
    ExtraSection,
    MatrixData,
    ReportingContext,
    TableColumn,
)
from fuzzmeter.reporting.plugin_sections import (
    _build_plugin_sections,
    _build_trial_snapshot_index,
    _snapshot_dirs_by_trial,
)
from fuzzmeter.reporting.plugins.loader import (
    FunctionReportingPlugin,
    NullReportingPlugin,
    ReportingPluginLoader,
)
from fuzzmeter.reporting.web_payload import (
    ALLOWED_CHART_TYPES,
    serialize_extra_sections,
    validate_extra_sections,
)
from tests.support.dbs import agg_snapshot_row, trial_report


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
                data.coverage_sets_for_agg_snapshot(
                    agg_snapshot_row(
                        coverage_sets_json_rel='coverage/explicit/coverage-sets.json',
                        coverage_html_dir='coverage/html-root/html/index.html',
                    )
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
                data.coverage_sets_for_agg_snapshot(
                    agg_snapshot_row(coverage_html_dir='coverage/fz/html/index.html')
                ),
            )

    def test_loads_trial_sets_from_explicit_paths_without_html_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            coverage_path = run_dir / 'coverage' / 'fz' / 'trial' / 'coverage-sets.json'
            coverage_path.parent.mkdir(parents=True)
            coverage_path.write_text('{}', encoding='utf-8')
            data = CoverageData(run_dir)

            with patch('fuzzmeter.reporting.data.coverage_data.read_covered_keys') as read_covered_keys:
                read_covered_keys.return_value = {'branch-a'}
                result = data.trial_coverage_sets_by_fuzzer(
                    fuzzers=['fz'],
                    trials_by_fuzzer={'fz': [
                        trial_report(coverage_sets_json_rel='coverage/fz/trial/coverage-sets.json')
                    ]},
                    metric='branches',
                )

            self.assertEqual({'fz': [{'branch-a'}]}, result)
            read_covered_keys.assert_called_once_with(coverage_path.resolve(), 'branches')

    def test_missing_trial_artifact_is_preserved_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            coverage_path = run_dir / 'coverage' / 'trial-0' / 'coverage-sets.json'
            coverage_path.parent.mkdir(parents=True)
            coverage_path.write_text('{"metrics":{"branches":[1]}}', encoding='utf-8')
            data = CoverageData(run_dir)

            with patch('fuzzmeter.reporting.data.coverage_data.read_covered_keys', return_value={'1'}):
                result = data.trial_coverage_sets_by_fuzzer(
                    fuzzers=['fz'],
                    trials_by_fuzzer={'fz': [
                        trial_report(coverage_sets_json_rel='coverage/trial-0/coverage-sets.json'),
                        trial_report(coverage_sets_json_rel='coverage/missing/coverage-sets.json'),
                    ]},
                    metric='branches',
                )

        self.assertEqual({'fz': [{'1'}, None]}, result)

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

    def test_runtime_constraints_come_from_public_literal_types(self) -> None:
        self.assertEqual(set(get_args(ChartType)), ALLOWED_CHART_TYPES)

    def test_rejects_non_list_plugin_output(self) -> None:
        self.assertEqual(([], ['plugin output is not a list']), validate_extra_sections({'not': 'a list'}))

    def test_rejects_invalid_sections_charts_and_matrices(self) -> None:
        valid = ExtraSection(
            id='valid',
            title='Valid',
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
                    'charts': [
                        {
                            'id': 'chart',
                            'type': 'table',
                            'title': 'Chart',
                            'subtitle': None,
                            'x_axis': None,
                            'y_axis': None,
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
            serialize_extra_sections([section]),
        )


class ReportingPluginLoaderTest(unittest.TestCase):
    '''Verify fuzzer reporting plugin discovery and adaptation.'''

    def test_aflplusplus_reexports_the_afl_reporting_plugin(self) -> None:
        self.assertIs(build_afl_sections, build_aflplusplus_sections)

    def test_aflplusplus_reexport_loads_through_the_run_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context_root = Path(tmp) / 'context'
            repository_root = Path(__file__).resolve().parents[1]
            for fuzzer in ('afl', 'aflplusplus'):
                source = repository_root / 'fuzzers' / fuzzer / 'run' / 'reporting.py'
                destination = context_root / fuzzer / 'run' / 'reporting.py'
                destination.parent.mkdir(parents=True)
                shutil.copy2(source, destination)

            plugin, matched = ReportingPluginLoader(
                {
                    'afl': context_root / 'afl',
                    'aflplusplus': context_root / 'aflplusplus',
                }
            ).load_first(['aflplusplus'])

        self.assertEqual('aflplusplus', matched)
        self.assertEqual([], plugin.build_extra_sections(_context()))

    def test_missing_plugin_returns_null_plugin(self) -> None:
        plugin, matched = ReportingPluginLoader({}).load_first(['missing'])

        self.assertIsInstance(plugin, NullReportingPlugin)
        self.assertIsNone(matched)

    def test_module_without_plugin_entrypoint_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fuzzers' / 'fz' / 'run' / 'reporting.py'
            path.parent.mkdir(parents=True)
            path.write_text('VALUE = 1\n', encoding='utf-8')

            plugin, matched = ReportingPluginLoader({'fz': Path(tmp) / 'fuzzers' / 'fz'}).load_first(['fz'])

        self.assertIsInstance(plugin, NullReportingPlugin)
        self.assertIsNone(matched)

    def test_function_plugin_is_adapted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fuzzers' / 'fz' / 'run' / 'reporting.py'
            path.parent.mkdir(parents=True)
            path.write_text('def build_extra_sections(ctx):\n    return []\n', encoding='utf-8')

            plugin, matched = ReportingPluginLoader({'fz': Path(tmp) / 'fuzzers' / 'fz'}).load_first(['fz'])

        self.assertIsInstance(plugin, FunctionReportingPlugin)
        self.assertEqual('fz', matched)

    def test_plugin_can_import_another_configured_fuzzer_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fuzzers_root = Path(tmp) / 'fuzzers'
            plugin_path = fuzzers_root / 'fz' / 'run' / 'reporting.py'
            helper_path = fuzzers_root / 'reporting_helper' / 'run' / 'fuzz.py'
            plugin_path.parent.mkdir(parents=True)
            helper_path.parent.mkdir(parents=True)
            helper_path.write_text('VALUE = "imported"\n', encoding='utf-8')
            plugin_path.write_text(
                'from fuzzers.reporting_helper.run.fuzz import VALUE\n'
                'def build_extra_sections(ctx):\n'
                '    return [] if VALUE == "imported" else None\n',
                encoding='utf-8',
            )

            plugin, matched = ReportingPluginLoader(
                {'fz': fuzzers_root / 'fz', 'reporting_helper': fuzzers_root / 'reporting_helper'}
            ).load_first(['fz'])

        self.assertEqual('fz', matched)
        self.assertEqual([], plugin.build_extra_sections(_context()))

    def test_cross_fuzzer_imports_switch_to_the_current_fuzzer_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roots = [Path(tmp) / name for name in ('first', 'second')]
            for root, value in zip(roots, ('first', 'second'), strict=True):
                plugin_path = root / 'plugin' / 'run' / 'reporting.py'
                helper_path = root / 'shared' / 'run' / 'fuzz.py'
                plugin_path.parent.mkdir(parents=True)
                helper_path.parent.mkdir(parents=True)
                helper_path.write_text(f'VALUE = {value!r}\n', encoding='utf-8')
                plugin_path.write_text(
                    'from fuzzers.shared.run.fuzz import VALUE\n'
                    'def build_extra_sections(ctx):\n'
                    '    return [VALUE]\n',
                    encoding='utf-8',
                )

            plugins = [
                ReportingPluginLoader({'plugin': root / 'plugin', 'shared': root / 'shared'})
                .load_first(['plugin'])[0]
                for root in roots
            ]

        self.assertEqual(['first'], plugins[0].build_extra_sections(_context()))
        self.assertEqual(['second'], plugins[1].build_extra_sections(_context()))

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

            plugin, matched = ReportingPluginLoader({'fz': Path(tmp) / 'fuzzers' / 'fz'}).load_first(['fz'])

        self.assertEqual('fz', matched)
        self.assertEqual([], plugin.build_extra_sections(_context()))

    def test_import_time_error_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fuzzers_root = Path(tmp) / 'fuzzers'
            broken_path = fuzzers_root / 'fz' / 'run' / 'reporting.py'
            fallback_path = fuzzers_root / 'base' / 'run' / 'reporting.py'
            broken_path.parent.mkdir(parents=True)
            fallback_path.parent.mkdir(parents=True)
            broken_path.write_text('raise RuntimeError("boom")\n', encoding='utf-8')
            fallback_path.write_text('def build_extra_sections(ctx):\n    return []\n', encoding='utf-8')
            loader = ReportingPluginLoader({'fz': fuzzers_root / 'fz', 'base': fuzzers_root / 'base'})

            with self.assertLogs('fuzzmeter.reporting.plugins.loader', level='ERROR'):
                plugin, matched = loader.load_first(['fz', 'base'])

        self.assertEqual('base', matched)
        self.assertEqual([], plugin.build_extra_sections(_context()))
        self.assertEqual([{'plugin': 'fz', 'error': 'boom'}], loader.load_errors)

    def test_invalid_candidate_names_do_not_escape_fuzzers_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            escaped = Path(tmp) / 'escape' / 'run' / 'reporting.py'
            escaped.parent.mkdir(parents=True)
            escaped.write_text('def build_extra_sections(ctx):\n    return []\n', encoding='utf-8')

            plugin, matched = ReportingPluginLoader({}).load_first(['../escape'])

        self.assertIsInstance(plugin, NullReportingPlugin)
        self.assertIsNone(matched)


class ReportingPluginSectionsTest(unittest.TestCase):
    '''Verify plugin section context, candidate, and debug helpers.'''

    def test_read_run_config_ignores_unreadable_or_foreign_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            self.assertEqual(({}, {}), read_run_config(run_dir))

            (run_dir / RUN_CONFIG_FILE).write_text('{not-json', encoding='utf-8')
            self.assertEqual(({}, {}), read_run_config(run_dir))

            (run_dir / RUN_CONFIG_FILE).write_text('{"version": 999, "fuzzers": {}}', encoding='utf-8')
            self.assertEqual(({}, {}), read_run_config(run_dir))

    def test_snapshot_dirs_use_fuzzer_base_and_candidate_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            snap_dir = run_dir / 'trials' / 'base__bench-target__rep2' / 'snapshots' / 'snap_000001'
            snap_dir.mkdir(parents=True)

            index = _build_trial_snapshot_index(run_dir)
            dirs = _snapshot_dirs_by_trial(
                [trial_report(trial_id=7, fuzzer='derived', rep=2)],
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
                return [ExtraSection(id='', title='Missing id')]

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

    def test_build_plugin_sections_drops_non_json_output(self) -> None:
        class NonJsonPlugin:
            def build_extra_sections(self, ctx):
                series = ChartSeries(id='s', label='S', points=[DataPoint(x=0, y=float('nan'))])
                chart = ChartSpec(id='c', title='C', type='line', series=[series])
                return [ExtraSection(id='nan', title='NaN', charts=[chart])]

            def build_debug_info(self, ctx):
                return {'paths': {'a'}}

        sections, debug = _build_plugin_sections(
            plugin=NonJsonPlugin(),
            matched_plugin_name='fz',
            plugin_candidates=['fz'],
            base_name=None,
            ctx=_context(),
        )

        self.assertEqual([], sections)
        self.assertRegex(debug['validation_warnings'][0], r'^section\[0\]: not JSON-serializable: ')
        self.assertNotIn('paths', debug)
        self.assertIn('debug_error', debug)

    def test_build_plugin_sections_drops_malformed_plugin_output(self) -> None:
        class NotAListPlugin:
            def build_extra_sections(self, ctx):
                return 1

        _, debug = _build_plugin_sections(
            plugin=NotAListPlugin(), matched_plugin_name='fz', plugin_candidates=['fz'], base_name=None, ctx=_context(),
        )
        self.assertEqual(['plugin output is not a list'], debug['validation_warnings'])

        chart = ChartSpec(id='c', title='C', type='line', series=[object()])
        sections, warnings = validate_extra_sections(
            [ExtraSection(id='s', title='S', charts=[chart])]
        )
        self.assertEqual([], sections)
        self.assertRegex(warnings[0], r'^section\[0\]: invalid plugin data: ')


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
