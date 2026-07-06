# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for composite source hook helpers.'''

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import Any
import unittest

from fuzzmeter.composite.source_hook import redact_source_info, run_source_hook, source_hook_context


@dataclass(frozen=True)
class _Case:
    fuzzer_name: str = 'libfuzzer'
    fuzzer_chain: tuple[str, ...] = ('libfuzzer',)
    benchmark: str = 'zlib'
    fuzz_target: str = 'compress'
    input_mode: str = 'file'
    target_timeout_s: float = 1.0
    build_config: dict[str, Any] = field(default_factory=lambda: {'token': 'secret', 'safe': 'ok'})
    runtime_config: dict[str, Any] = field(default_factory=dict)


class CompositeSourceHookTest(unittest.TestCase):
    '''Verify source hook redaction and missing-hook behavior.'''

    def test_redacts_common_secret_keys_and_private_paths(self) -> None:
        '''Sensitive source hook values are not persisted verbatim.'''
        redacted = redact_source_info(
            {
                'api_key': 'abc',
                'nested': {'password': 'pw'},
                'path': '/Users/alice/project/src',
                'windows_path': r'C:\Users\bob\project\src',
            }
        )

        self.assertEqual('<redacted>', redacted['api_key'])
        self.assertEqual('<redacted>', redacted['nested']['password'])
        self.assertEqual('<private>/project/src', redacted['path'])
        self.assertEqual(r'<private>\project\src', redacted['windows_path'])

    def test_missing_hook_returns_missing_status(self) -> None:
        '''Absent source hooks are represented explicitly.'''
        result = run_source_hook(Path('/no/such/source-info.py'), {}, 'target_source')

        self.assertEqual('missing', result.status)
        self.assertIsNone(result.data)

    def test_context_uses_redacted_configs(self) -> None:
        '''Hook context exposes safe campaign case metadata.'''
        ctx = source_hook_context(_Case())

        self.assertEqual('zlib', ctx['benchmark'])
        self.assertEqual('<redacted>', ctx['build_config']['token'])
        self.assertEqual('ok', ctx['build_config']['safe'])

    def test_error_stderr_redacts_private_paths(self) -> None:
        '''Hook error text is sanitized before it is stored in metadata.'''
        with tempfile.TemporaryDirectory() as tmp:
            hook = Path(tmp) / 'source-info.py'
            hook.write_text(
                'import sys\nsys.stderr.write("/Users/alice/project/source_info.py failed")\nsys.exit(2)\n',
                encoding='utf-8',
            )

            result = run_source_hook(hook, {}, 'target_source')

        self.assertEqual('error', result.status)
        self.assertEqual('<private>/project/source_info.py failed', result.error)


if __name__ == '__main__':
    unittest.main()
