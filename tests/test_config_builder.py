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

from pathlib import Path

from fuzzmeter.config import load_campaign_config
from fuzzmeter.paths import ExternalRoots


class ConfigBuilderTest(unittest.TestCase):
    """Verify campaign config expansion rules."""

    def test_repository_curl_target_config_loads(self) -> None:
        """Verify that the repository curl target config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            """
fuzzers:
  - libfuzzer
targets:
  - curl:curl_fuzzer
""",
        )

        self.assertEqual(
            [("curl", "curl_fuzzer", "in_process")],
            [(case.benchmark, case.fuzz_target, case.input_mode) for case in config.cases],
        )

    def test_repository_openssl_target_config_loads(self) -> None:
        """Verify that the repository OpenSSL target config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            """
fuzzers:
  - libfuzzer
targets:
  - openssl:x509
""",
        )

        self.assertEqual(
            [("openssl", "x509", "in_process")],
            [(case.benchmark, case.fuzz_target, case.input_mode) for case in config.cases],
        )

    def test_repository_libxml2_target_config_loads(self) -> None:
        """Verify that the repository libxml2 target config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            """
fuzzers:
  - libfuzzer
targets:
  - libxml2:reader
""",
        )

        self.assertEqual(
            [("libxml2", "reader", "in_process")],
            [(case.benchmark, case.fuzz_target, case.input_mode) for case in config.cases],
        )

    def test_repository_re2_target_config_loads(self) -> None:
        """Verify that the repository RE2 target config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            """
fuzzers:
  - libfuzzer
targets:
  - re2:re2_fuzzer
""",
        )

        self.assertEqual(
            [("re2", "re2_fuzzer", "in_process")],
            [(case.benchmark, case.fuzz_target, case.input_mode) for case in config.cases],
        )

    def test_repository_zlib_target_config_loads(self) -> None:
        """Verify that the repository zlib target config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            """
fuzzers:
  - libfuzzer
targets:
  - zlib:zlib_uncompress_fuzzer
""",
        )

        self.assertEqual(
            [("zlib", "zlib_uncompress_fuzzer", "in_process")],
            [(case.benchmark, case.fuzz_target, case.input_mode) for case in config.cases],
        )

    def test_repository_quickjs_target_config_loads(self) -> None:
        """Verify that the repository QuickJS target config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            """
fuzzers:
  - libfuzzer
targets:
  - quickjs:fuzz_eval
""",
        )

        self.assertEqual(
            [('quickjs', 'fuzz_eval', 'in_process')],
            [(case.benchmark, case.fuzz_target, case.input_mode) for case in config.cases],
        )

    def test_repository_jsc_target_config_loads(self) -> None:
        """Verify that the repository JSC target config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            """
fuzzers:
  - blackbox
targets:
  - jsc:jsc
""",
        )

        self.assertEqual(
            [('jsc', 'jsc', 'file')], [(case.benchmark, case.fuzz_target, case.input_mode) for case in config.cases]
        )

    def test_repository_v8_target_config_loads(self) -> None:
        """Verify that the repository V8 target config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            """
fuzzers:
  - blackbox
targets:
  - v8:d8
""",
        )

        self.assertEqual(
            [('v8', 'd8', 'file')], [(case.benchmark, case.fuzz_target, case.input_mode) for case in config.cases]
        )

    def test_repository_spidermonkey_target_config_loads(self) -> None:
        """Verify that the repository SpiderMonkey target config loads as-is."""
        repo_root = Path(__file__).resolve().parents[1]

        config = _load_campaign_config(
            repo_root,
            """
fuzzers:
  - blackbox
targets:
  - spidermonkey:js
""",
        )

        self.assertEqual(
            [('spidermonkey', 'js', 'file')],
            [(case.benchmark, case.fuzz_target, case.input_mode) for case in config.cases],
        )

    def test_allowed_benchmarks_limits_fuzzer_targets(self) -> None:
        """Verify that fuzzer-level benchmark allowlists filter campaign cases."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'limited', 'allowed_benchmarks:\n  - jerryscript:jerry\n')
            _write_fuzzer(root, 'plain', '')
            _write_target(root, 'jerryscript', 'jerry')
            _write_target(root, 'sqlite3', 'ossfuzz')

            config = _load_campaign_config(
                root,
                """
fuzzers:
  - limited
  - plain
targets:
  - jerryscript:jerry
  - sqlite3:ossfuzz
""",
            )

        self.assertEqual(
            [
                ('limited', 'jerryscript', 'jerry'),
                ('plain', 'jerryscript', 'jerry'),
                ('plain', 'sqlite3', 'ossfuzz'),
            ],
            [(case.fuzzer_name, case.benchmark, case.fuzz_target) for case in config.cases],
        )

    def test_allowed_benchmarks_are_inherited_from_parent_fuzzer(self) -> None:
        """Verify that derived fuzzer entries keep parent benchmark allowlists."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'limited_base', 'allowed_benchmarks:\n  - jerryscript:jerry\n')
            _write_target(root, 'jerryscript', 'jerry')
            _write_target(root, 'sqlite3', 'ossfuzz')

            config = _load_campaign_config(
                root,
                """
fuzzers:
  - fuzzer: limited_child
    parent: limited_base
targets:
  - jerryscript:jerry
  - sqlite3:ossfuzz
""",
            )

        self.assertEqual(
            [('limited_child', 'jerryscript', 'jerry')],
            [(case.fuzzer_name, case.benchmark, case.fuzz_target) for case in config.cases],
        )

    def test_target_timeout_is_stored_on_campaign_case(self) -> None:
        """Verify that target-level timeouts are stored on the campaign case."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_target(root, 'jerryscript', 'jerry', timeout_s=10)

            config = _load_campaign_config(
                root,
                """
fuzzers:
  - plain
targets:
  - jerryscript:jerry
""",
            )

        self.assertEqual(10.0, config.cases[0].target_timeout_s)
        self.assertEqual({}, config.cases[0].runtime_config)

    def test_runtime_target_timeout_overrides_target_default(self) -> None:
        """Verify that config/fuzzer runtime config can override target defaults."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_target(root, 'jerryscript', 'jerry', timeout_s=10)

            config = _load_campaign_config(
                root,
                """
fuzzers:
  - fuzzer: plain
    runtime:
      target:
        timeout_s: 3
targets:
  - jerryscript:jerry
""",
            )

        self.assertEqual({'target': {'timeout_s': 3}}, config.cases[0].runtime_config)

    def test_snapshot_export_interval_defaults_to_one(self) -> None:
        """Verify that snapshot exports run on every tick by default."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_target(root, 'jerryscript', 'jerry')

            config = _load_campaign_config(
                root,
                """
run:
  time_seconds: 14400
  snapshot:
    every_seconds: 300
fuzzers:
  - plain
targets:
  - jerryscript:jerry
""",
            )

        self.assertEqual(1, config.settings.snapshot_export_every_ticks)

    def test_snapshot_export_interval_can_be_configured(self) -> None:
        """Verify that configs can override the LLVM export cadence."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_target(root, 'jerryscript', 'jerry')

            config = _load_campaign_config(
                root,
                """
run:
  time_seconds: 14400
  snapshot:
    every_seconds: 300
    export_every_ticks: 7
fuzzers:
  - plain
targets:
  - jerryscript:jerry
""",
            )

        self.assertEqual(7, config.settings.snapshot_export_every_ticks)

    def test_multi_target_benchmark_loads_requested_target(self) -> None:
        """Verify that multi-target benchmark configs resolve the requested target key."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_multi_target(
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
                """
fuzzers:
  - plain
targets:
  - jerryscript:jerry_file
""",
            )

        self.assertEqual(
            [('jerryscript', 'jerry_file', 'file', 3.0)],
            [(case.benchmark, case.fuzz_target, case.input_mode, case.target_timeout_s) for case in config.cases],
        )

    def test_multi_target_benchmark_fuzzer_overrides_are_target_specific(self) -> None:
        """Verify that multi-target benchmark fuzzer overrides come from the selected target entry."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_multi_target(
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
                """
fuzzers:
  - plain
targets:
  - jerryscript:jerry_file
""",
            )

        self.assertEqual({'env': {'MODE': 'file'}}, config.cases[0].build_config)

    def test_multi_target_benchmark_rejects_root_level_fuzzers(self) -> None:
        """Verify that multi-target benchmark configs do not accept root-level fuzzer overrides."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            target_dir = root / 'targets' / 'jerryscript'
            target_dir.mkdir(parents=True)
            target_dir.joinpath('benchmark.yaml').write_text(
                """
project: jerryscript
fuzzers:
  plain:
    build:
      env:
        MODE: bad
fuzz_targets:
  jerry:
    input_mode: in_process
""".lstrip(),
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'root-level fuzzers'):
                _load_campaign_config(
                    root,
                    """
fuzzers:
  - plain
targets:
  - jerryscript:jerry
""",
                )

    def test_multi_target_benchmark_rejects_missing_requested_target(self) -> None:
        """Verify that missing multi-target entries produce a clear error."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            _write_multi_target(root, 'jerryscript', {'jerry': {'input_mode': 'in_process'}})

            with self.assertRaisesRegex(ValueError, "requested fuzz target 'missing'"):
                _load_campaign_config(
                    root,
                    """
fuzzers:
  - plain
targets:
  - jerryscript:missing
""",
                )

    def test_benchmark_config_rejects_mixed_legacy_and_multi_target_forms(self) -> None:
        """Verify that benchmark configs cannot define both legacy and multi-target schemas."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            target_dir = root / 'targets' / 'jerryscript'
            target_dir.mkdir(parents=True)
            target_dir.joinpath('benchmark.yaml').write_text(
                """
project: jerryscript
fuzz_target: legacy
fuzz_targets:
  jerry:
    input_mode: in_process
""".lstrip(),
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'exactly one of fuzz_target or fuzz_targets'):
                _load_campaign_config(
                    root,
                    """
fuzzers:
  - plain
targets:
  - jerryscript:jerry
""",
                )

    def test_benchmark_config_rejects_empty_multi_target_mapping(self) -> None:
        """Verify that benchmark configs reject empty fuzz_targets mappings."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fuzzer(root, 'plain', '')
            target_dir = root / 'targets' / 'jerryscript'
            target_dir.mkdir(parents=True)
            target_dir.joinpath('benchmark.yaml').write_text(
                'project: jerryscript\nfuzz_targets: {}\n',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'non-empty mapping'):
                _load_campaign_config(
                    root,
                    """
fuzzers:
  - plain
targets:
  - jerryscript:jerry
""",
                )


def _write_fuzzer(root: Path, name: str, text: str) -> None:
    fuzzer_dir = root / 'fuzzers' / name / 'build'
    fuzzer_dir.mkdir(parents=True)
    fuzzer_dir.joinpath('build.yaml').write_text(text, encoding='utf-8')


def _load_campaign_config(root: Path, text: str):
    return load_campaign_config(ExternalRoots.from_checkout(root), text)


def _write_target(root: Path, project: str, fuzz_target: str, *, timeout_s: int | None = None) -> None:
    target_dir = root / 'targets' / project
    target_dir.mkdir(parents=True)
    timeout_line = f'timeout_s: {timeout_s}\n' if timeout_s is not None else ''
    target_dir.joinpath('benchmark.yaml').write_text(
        f'project: {project}\nfuzz_target: {fuzz_target}\ninput_mode: file\n{timeout_line}',
        encoding='utf-8',
    )


def _write_multi_target(root: Path, project: str, targets: dict[str, dict[str, object]]) -> None:
    target_dir = root / 'targets' / project
    target_dir.mkdir(parents=True)
    lines = [f'project: {project}', 'fuzz_targets:']
    for fuzz_target, config in targets.items():
        lines.append(f'  {fuzz_target}:')
        for key, value in config.items():
            _append_yaml_value(lines, 4, key, value)
    target_dir.joinpath('benchmark.yaml').write_text('\n'.join(lines) + '\n', encoding='utf-8')


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
