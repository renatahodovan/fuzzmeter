# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Regression tests for campaign configuration loading."""

from __future__ import annotations

import tempfile
import unittest

from dataclasses import fields
from pathlib import Path

from fuzzmeter.config import CampaignCase, load_campaign_config


class ConfigBuilderTest(unittest.TestCase):
    """Verify campaign config expansion rules."""

    def test_campaign_case_stores_normalized_objects(self) -> None:
        """Verify that a case owns normalized fuzzer and target objects."""
        field_names = {field.name for field in fields(CampaignCase)}

        self.assertEqual({'fuzzer', 'fuzz_target', 'build_config', 'run_config', 'replay_trials'}, field_names)

    def test_repository_curl_fuzz_target_config_loads(self) -> None:
        """Verify that the repository curl benchmark config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            '''
fuzzers:
  - libfuzzer
fuzz_targets:
  - curl:curl_fuzzer
''',
        )

        self.assertEqual(
            [('curl', 'curl_fuzzer', 'in_process')],
            [(case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target, case.fuzz_target.input_mode) for case in config.cases],
        )

    def test_repository_openssl_fuzz_target_config_loads(self) -> None:
        """Verify that the repository OpenSSL benchmark config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            '''
fuzzers:
  - libfuzzer
fuzz_targets:
  - openssl:x509
''',
        )

        self.assertEqual(
            [('openssl', 'x509', 'in_process')],
            [(case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target, case.fuzz_target.input_mode) for case in config.cases],
        )

    def test_repository_libxml2_fuzz_target_config_loads(self) -> None:
        """Verify that the repository libxml2 benchmark config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            '''
fuzzers:
  - libfuzzer
fuzz_targets:
  - libxml2:reader
''',
        )

        self.assertEqual(
            [('libxml2', 'reader', 'in_process')],
            [(case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target, case.fuzz_target.input_mode) for case in config.cases],
        )

    def test_repository_re2_fuzz_target_config_loads(self) -> None:
        """Verify that the repository RE2 benchmark config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            '''
fuzzers:
  - libfuzzer
fuzz_targets:
  - re2:re2_fuzzer
''',
        )

        self.assertEqual(
            [('re2', 're2_fuzzer', 'in_process')],
            [(case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target, case.fuzz_target.input_mode) for case in config.cases],
        )

    def test_repository_zlib_fuzz_target_config_loads(self) -> None:
        """Verify that the repository zlib benchmark config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            '''
fuzzers:
  - libfuzzer
fuzz_targets:
  - zlib:zlib_uncompress_fuzzer
''',
        )

        self.assertEqual(
            [('zlib', 'zlib_uncompress_fuzzer', 'in_process')],
            [(case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target, case.fuzz_target.input_mode) for case in config.cases],
        )

    def test_repository_harfbuzz_fuzz_target_config_loads(self) -> None:
        """Verify that the repository HarfBuzz benchmark config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            '''
fuzzers:
  - libfuzzer
fuzz_targets:
  - harfbuzz:hb-shape-fuzzer
''',
        )

        self.assertEqual(
            [('harfbuzz', 'hb-shape-fuzzer', 'in_process')],
            [(case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target, case.fuzz_target.input_mode) for case in config.cases],
        )

    def test_repository_freetype2_fuzz_target_config_loads(self) -> None:
        """Verify that the repository FreeType2 benchmark config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            '''
fuzzers:
  - libfuzzer
fuzz_targets:
  - freetype2:ftfuzzer
''',
        )

        self.assertEqual(
            [('freetype2', 'ftfuzzer', 'in_process')],
            [(case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target, case.fuzz_target.input_mode) for case in config.cases],
        )

    def test_repository_quickjs_fuzz_target_config_loads(self) -> None:
        """Verify that the repository QuickJS benchmark config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            '''
fuzzers:
  - libfuzzer
fuzz_targets:
  - quickjs:fuzz_eval
''',
        )

        self.assertEqual(
            [('quickjs', 'fuzz_eval', 'in_process')],
            [(case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target, case.fuzz_target.input_mode) for case in config.cases],
        )

    def test_repository_jsc_fuzz_target_config_loads(self) -> None:
        """Verify that the repository JSC benchmark config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            '''
fuzzers:
  - blackbox
fuzz_targets:
  - jsc:jsc
''',
        )

        self.assertEqual(
            [('jsc', 'jsc', 'file')], [(case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target, case.fuzz_target.input_mode) for case in config.cases]
        )

    def test_repository_v8_fuzz_target_config_loads(self) -> None:
        """Verify that the repository V8 benchmark config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            '''
fuzzers:
  - blackbox
fuzz_targets:
  - v8:d8
''',
        )

        self.assertEqual(
            [('v8', 'd8', 'file')], [(case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target, case.fuzz_target.input_mode) for case in config.cases]
        )

    def test_repository_spidermonkey_fuzz_target_config_loads(self) -> None:
        """Verify that the repository SpiderMonkey benchmark config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            '''
fuzzers:
  - blackbox
fuzz_targets:
  - spidermonkey:js
''',
        )

        self.assertEqual(
            [('spidermonkey', 'js', 'file')],
            [(case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target, case.fuzz_target.input_mode) for case in config.cases],
        )

    def test_allowed_benchmarks_limits_fuzzer_targets(self) -> None:
        """Verify that fuzzer-level benchmark allowlists filter campaign cases."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'limited', 'allowed_fuzz_targets:\n  - jerryscript:jerry\n')
            _write_fuzzer(root, 'plain', '')
            _write_benchmark(root, 'jerryscript', 'jerry')
            _write_benchmark(root, 'sqlite3', 'ossfuzz')

            config = _load_campaign_config(
                root,
                '''
fuzzers:
  - limited
  - plain
fuzz_targets:
  - jerryscript:jerry
  - sqlite3:ossfuzz
''',
            )

        self.assertEqual(
            [
                ('limited', 'jerryscript', 'jerry'),
                ('plain', 'jerryscript', 'jerry'),
                ('plain', 'sqlite3', 'ossfuzz'),
            ],
            [(case.fuzzer.name, case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target) for case in config.cases],
        )

    def test_campaign_config_keeps_only_required_fuzzer_dirs(self) -> None:
        """Verify that campaign configuration excludes unused fuzzer directories."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'base', 'source_dependencies:\n  - support\n')
            _write_fuzzer(root, 'selected', 'parent: base\nreporting_parent: reporter\n')
            _write_fuzzer(root, 'support', '')
            _write_fuzzer(root, 'blackbox', '')
            _write_fuzzer(root, 'reporter', '')
            _write_fuzzer(root, 'unused', '')
            run_dir = root / 'fuzzers' / 'base' / 'run'
            run_dir.mkdir()
            run_dir.joinpath('run.yaml').write_text('source_dependencies:\n  - blackbox\n', encoding='utf-8')
            _write_benchmark(root, 'jerryscript', 'jerry')

            config = _load_campaign_config(
                root,
                '''
fuzzers:
  - selected
fuzz_targets:
  - jerryscript:jerry
''',
            )

        self.assertEqual({'base', 'blackbox', 'reporter', 'selected', 'support'}, set(config.fuzzer_dirs))

    def test_source_dependencies_must_be_a_list(self) -> None:
        """Verify malformed source dependency configuration fails at load time."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', 'source_dependencies: support\n')
            _write_benchmark(root, 'jerryscript', 'jerry')

            with self.assertRaisesRegex(ValueError, 'source_dependencies must be defined as a list'):
                _load_campaign_config(
                    root,
                    '''
fuzzers:
  - plain
fuzz_targets:
  - jerryscript:jerry
''',
                )

    def test_source_dependencies_must_be_configured(self) -> None:
        """Verify missing source dependencies fail before artifact building."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', 'source_dependencies:\n  - support\n')
            _write_benchmark(root, 'jerryscript', 'jerry')

            with self.assertRaisesRegex(ValueError, "Fuzzer 'support' is not configured"):
                _load_campaign_config(
                    root,
                    '''
fuzzers:
  - plain
fuzz_targets:
  - jerryscript:jerry
''',
                )

    def test_cyclic_fuzzer_dependencies_are_rejected(self) -> None:
        """Verify incomplete fuzzer entries identify dependency cycles."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'first', 'parent: second\n')
            _write_fuzzer(root, 'second', 'source_dependencies:\n  - first\n')
            _write_benchmark(root, 'jerryscript', 'jerry')

            with self.assertRaisesRegex(ValueError, "Cyclic fuzzer dependency detected at 'first'"):
                _load_campaign_config(
                    root,
                    '''
fuzzers:
  - first
fuzz_targets:
  - jerryscript:jerry
''',
                )

    def test_allowed_benchmarks_are_inherited_from_parent_fuzzer(self) -> None:
        """Verify that derived fuzzer entries keep parent benchmark allowlists."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'limited_base', 'allowed_fuzz_targets:\n  - jerryscript:jerry\n')
            _write_benchmark(root, 'jerryscript', 'jerry')
            _write_benchmark(root, 'sqlite3', 'ossfuzz')

            config = _load_campaign_config(
                root,
                '''
fuzzers:
  - id: limited_child
    parent: limited_base
fuzz_targets:
  - jerryscript:jerry
  - sqlite3:ossfuzz
''',
            )

        self.assertEqual(
            [('limited_child', 'limited_base', 'jerryscript', 'jerry')],
            [(case.fuzzer.id, case.fuzzer.name, case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target) for case in config.cases],
        )
        self.assertEqual('limited_base', config.cases[0].fuzzer.parent.name)
        self.assertEqual({'jerryscript'}, {case.fuzz_target.benchmark.name for case in config.cases})

    def test_fuzzer_with_parent_keeps_its_own_implementation(self) -> None:
        """Verify a selected fuzzer remains the implementation despite having a parent."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'base', '')
            _write_fuzzer(root, 'derived', 'parent: base\n')
            _write_benchmark(root, 'jerryscript', 'jerry')

            config = _load_campaign_config(
                root,
                '''
fuzzers:
  - derived
fuzz_targets:
  - jerryscript:jerry
''',
            )

        self.assertEqual(
            [('derived', 'derived', ('derived', 'base'))],
            [(case.fuzzer.id, case.fuzzer.name, tuple(item.name for item in [case.fuzzer, *case.fuzzer.parents])) for case in config.cases],
        )

    def test_replay_trials_are_scoped_to_the_fuzzer_and_fuzz_target_pair(self) -> None:
        """Verify that replay trials follow the fuzz target spec and are not a fuzzer property."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ignored, jerry, sqlite = root / 'ignored', root / 'jerry', root / 'sqlite'
            for path in (ignored, jerry, sqlite):
                path.mkdir()
            _write_fuzzer(root, 'base', f'replay_trials:\n  jerryscript:jerry:\n    - {ignored}\n')
            _write_benchmark(root, 'jerryscript', 'jerry')
            _write_benchmark(root, 'sqlite3', 'ossfuzz')

            config = _load_campaign_config(
                root,
                f'''
fuzzers:
  - id: replayed
    parent: base
    replay_trials:
      jerryscript:jerry:
        - {jerry}
      sqlite3:ossfuzz:
        - {sqlite}
fuzz_targets:
  - jerryscript:jerry
  - sqlite3:ossfuzz
''',
            )

        self.assertEqual(
            [('jerryscript:jerry', (jerry,)), ('sqlite3:ossfuzz', (sqlite,))],
            [(case.fuzz_target.spec, case.replay_trials) for case in config.cases],
        )

    def test_replay_trials_reject_unselected_fuzz_targets(self) -> None:
        """Verify that replay trials must name a fuzz target the campaign runs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_benchmark(root, 'jerryscript', 'jerry')

            with self.assertRaisesRegex(ValueError, 'unselected fuzz targets'):
                _load_campaign_config(
                    root,
                    f'''
fuzzers:
  - id: replayed
    parent: plain
    replay_trials:
      sqlite3:ossfuzz:
        - {root}
fuzz_targets:
  - jerryscript:jerry
''',
                )

    def test_replay_trials_must_cover_every_case_with_one_directory_per_repetition(self) -> None:
        """Verify that a run is either fully replayed with repetitions directories, or fully live."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_benchmark(root, 'jerryscript', 'jerry')
            _write_benchmark(root, 'sqlite3', 'ossfuzz')
            campaign = f'''
fuzzers:
  - id: replayed
    parent: plain
    replay_trials:
      jerryscript:jerry:
        - {root}
{{extra}}
run:
  repetitions: {{repetitions}}
fuzz_targets:
  - jerryscript:jerry
  - sqlite3:ossfuzz
'''

            # A live sqlite3 case cannot be mixed with a replayed jerryscript case.
            with self.assertRaisesRegex(ValueError, 'for every campaign case, or for none'):
                _load_campaign_config(root, campaign.format(extra='', repetitions=1))

            # Every case is replayed, but one directory does not match repetitions: 2.
            with self.assertRaisesRegex(ValueError, r'exactly run.repetitions \(2\)'):
                _load_campaign_config(
                    root,
                    campaign.format(extra=f'      sqlite3:ossfuzz:\n        - {root}', repetitions=2),
                )

            config = _load_campaign_config(
                root,
                campaign.format(extra=f'      sqlite3:ossfuzz:\n        - {root}', repetitions=1),
            )

        self.assertEqual([(root,), (root,)], [case.replay_trials for case in config.cases])

    def test_target_timeout_is_stored_on_campaign_case(self) -> None:
        """Verify that target-level timeouts are stored on the campaign case."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_benchmark(root, 'jerryscript', 'jerry', timeout_s=10)

            config = _load_campaign_config(
                root,
                '''
fuzzers:
  - plain
fuzz_targets:
  - jerryscript:jerry
''',
            )

        self.assertEqual(10.0, config.cases[0].fuzz_target.target_timeout_s)
        self.assertEqual({}, config.cases[0].run_config)

    def test_missing_target_timeout_defaults_to_one_second(self) -> None:
        """Verify that missing target timeouts default to one second."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_benchmark(root, 'jerryscript', 'jerry')

            config = _load_campaign_config(
                root,
                '''
fuzzers:
  - plain
fuzz_targets:
  - jerryscript:jerry
''',
            )

        self.assertEqual(1.0, config.cases[0].fuzz_target.target_timeout_s)
        self.assertEqual({}, config.cases[0].run_config)

    def test_runtime_target_timeout_is_preserved_without_changing_target_timeout(self) -> None:
        """Verify that fuzzer runtime config does not replace the benchmark target timeout."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_benchmark(root, 'jerryscript', 'jerry', timeout_s=10)

            config = _load_campaign_config(
                root,
                '''
fuzzers:
  - id: plain
    runtime:
      target:
        timeout_s: 3
fuzz_targets:
  - jerryscript:jerry
''',
            )

        self.assertEqual(10.0, config.cases[0].fuzz_target.target_timeout_s)
        self.assertEqual({'target': {'timeout_s': 3}}, config.cases[0].run_config)

    def test_snapshot_export_interval_defaults_to_one(self) -> None:
        """Verify that snapshot exports run on every tick by default."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_benchmark(root, 'jerryscript', 'jerry')

            config = _load_campaign_config(
                root,
                '''
run:
  time_seconds: 14400
  snapshot:
    every_seconds: 300
fuzzers:
  - plain
fuzz_targets:
  - jerryscript:jerry
''',
            )

        self.assertEqual(1, config.settings.snapshot_export_every_ticks)

    def test_snapshot_export_interval_can_be_configured(self) -> None:
        """Verify that configs can override the LLVM export cadence."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_benchmark(root, 'jerryscript', 'jerry')

            config = _load_campaign_config(
                root,
                '''
run:
  time_seconds: 14400
  snapshot:
    every_seconds: 300
    export_every_ticks: 7
fuzzers:
  - plain
fuzz_targets:
  - jerryscript:jerry
''',
            )

        self.assertEqual(7, config.settings.snapshot_export_every_ticks)

    def test_multi_target_benchmark_loads_requested_target(self) -> None:
        """Verify that multi-target benchmark configs resolve the requested target key."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_multi_benchmark(
                root,
                'jerryscript',
                {
                    'jerry': {
                        'input_mode': 'in_process',
                        'timeout_s': 7,
                    },
                    'jerry_file': {
                        'input_mode': 'file',
                        'timeout_s': 3,
                    },
                },
            )

            config = _load_campaign_config(
                root,
                '''
fuzzers:
  - plain
fuzz_targets:
  - jerryscript:jerry_file
''',
            )

        self.assertEqual(
            [('jerryscript', 'jerry_file', 'file', 3.0)],
            [
                (case.fuzz_target.benchmark.name, case.fuzz_target.fuzz_target, case.fuzz_target.input_mode, case.fuzz_target.target_timeout_s)
                for case in config.cases
            ],
        )

    def test_multi_target_benchmark_fuzzer_overrides_are_target_specific(self) -> None:
        """Verify that multi-target benchmark fuzzer overrides come from the selected target entry."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_multi_benchmark(
                root,
                'jerryscript',
                {
                    'jerry': {
                        'input_mode': 'in_process',
                        'fuzzers': {'plain': {'build': {'env': {'MODE': 'proc'}}}},
                    },
                    'jerry_file': {
                        'input_mode': 'file',
                        'fuzzers': {'plain': {'build': {'env': {'MODE': 'file'}}}},
                    },
                },
            )

            config = _load_campaign_config(
                root,
                '''
fuzzers:
  - plain
fuzz_targets:
  - jerryscript:jerry_file
''',
            )

        self.assertEqual({'env': {'MODE': 'file'}}, config.cases[0].build_config)

    def test_multi_target_benchmark_rejects_missing_requested_target(self) -> None:
        """Verify that missing multi-target entries produce a clear error."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_multi_benchmark(root, 'jerryscript', {'jerry': {'input_mode': 'in_process'}})

            with self.assertRaisesRegex(ValueError, r"fuzz_targets\['missing'\] must be a mapping"):
                _load_campaign_config(
                    root,
                    '''
fuzzers:
  - plain
fuzz_targets:
  - jerryscript:missing
''',
                )

    def test_benchmark_config_rejects_legacy_single_target_schema(self) -> None:
        """Verify that benchmark configs reject the root-level fuzz_target field."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            benchmark_dir = root / 'benchmarks' / 'jerryscript'
            benchmark_dir.mkdir(parents=True)
            benchmark_dir.joinpath('benchmark.yaml').write_text(
                '''
benchmark: jerryscript
fuzz_target: legacy
input_mode: in_process
'''.lstrip(),
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'fuzz_targets must be a non-empty mapping'):
                _load_campaign_config(
                    root,
                    '''
fuzzers:
  - plain
fuzz_targets:
  - jerryscript:jerry
''',
                )

    def test_benchmark_config_rejects_empty_multi_target_mapping(self) -> None:
        """Verify that benchmark configs reject empty fuzz_targets mappings."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            benchmark_dir = root / 'benchmarks' / 'jerryscript'
            benchmark_dir.mkdir(parents=True)
            benchmark_dir.joinpath('benchmark.yaml').write_text(
                'benchmark: jerryscript\nfuzz_targets: {}\n',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'non-empty mapping'):
                _load_campaign_config(
                    root,
                    '''
fuzzers:
  - plain
fuzz_targets:
  - jerryscript:jerry
''',
                )


def _write_fuzzer(root: Path, name: str, text: str) -> None:
    fuzzer_dir = root / 'fuzzers' / name / 'build'
    fuzzer_dir.mkdir(parents=True)
    fuzzer_dir.joinpath('build.yaml').write_text(text, encoding='utf-8')


def _load_campaign_config(root: Path, text: str):
    return load_campaign_config(
        fuzzer_dirs={path.name: path for path in (root / 'fuzzers').iterdir() if path.is_dir()},
        benchmark_dirs={path.name: path for path in (root / 'benchmarks').iterdir() if path.is_dir()},
        text=text,
    )


def _write_benchmark(root: Path, benchmark: str, fuzz_target: str, *, timeout_s: int | None = None) -> None:
    benchmark_dir = root / 'benchmarks' / benchmark
    benchmark_dir.mkdir(parents=True)
    timeout_line = f'    timeout_s: {timeout_s}\n' if timeout_s is not None else ''
    benchmark_dir.joinpath('benchmark.yaml').write_text(
        f'benchmark: {benchmark}\nfuzz_targets:\n  {fuzz_target}:\n    input_mode: file\n{timeout_line}',
        encoding='utf-8',
    )


def _write_multi_benchmark(
    root: Path, benchmark: str, fuzz_targets: dict[str, dict[str, object]]
) -> None:
    benchmark_dir = root / 'benchmarks' / benchmark
    benchmark_dir.mkdir(parents=True)
    lines = [f'benchmark: {benchmark}', 'fuzz_targets:']
    for fuzz_target, config in fuzz_targets.items():
        lines.append(f'  {fuzz_target}:')
        for key, value in config.items():
            _append_yaml_value(lines, 4, key, value)
    benchmark_dir.joinpath('benchmark.yaml').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _append_yaml_value(lines: list[str], indent: int, key: str, value: object) -> None:
    prefix = ' ' * indent
    if isinstance(value, dict):
        lines.append(f'{prefix}{key}:')
        for nested_key, nested_value in value.items():
            _append_yaml_value(lines, indent + 2, str(nested_key), nested_value)
        return
    if isinstance(value, list):
        lines.append(f'{prefix}{key}:')
        for item in value:
            lines.append(f'{" " * (indent + 2)}- {item}')
        return
    lines.append(f'{prefix}{key}: {value}')


if __name__ == '__main__':
    unittest.main()
