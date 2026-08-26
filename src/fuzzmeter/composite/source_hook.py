# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Run and sanitize user-defined composite source metadata hooks.'''

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE_HOOK_TIMEOUT = 10
SOURCE_HOOK_SCOPES = ('benchmark_source', 'fuzzer_version')
SECRET_KEY_PARTS = ('secret', 'token', 'password', 'passwd', 'credential', 'apikey', 'api_key')
HOME_PATH_PATTERNS = (
    re.compile(r'(?P<root>/(?:Users|home)/)(?P<name>[^/\s:;,"\']+)'),
    re.compile(r'(?i)(?P<root>[a-z]:[\\/]+Users[\\/]+)(?P<name>[^\\/:\s;,"\']+)'),
)


@dataclass(frozen=True)
class SourceHookResult:
    '''Hold one source metadata hook outcome.'''

    status: str
    data: dict[str, Any] | None = None
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        '''Return a JSON-compatible representation.'''
        return {'status': self.status, 'data': self.data, 'error': self.error}


def run_source_hook(path: Path, context: dict[str, Any], scope: str) -> SourceHookResult:
    '''Execute a source info hook for one metadata scope.'''
    if scope not in SOURCE_HOOK_SCOPES:
        raise ValueError(f'Unsupported source hook scope: {scope!r}.')
    hook_path = Path(path)
    if not hook_path.is_file():
        return SourceHookResult(status='missing')

    env = dict(os.environ)
    src_root = str(Path(__file__).resolve().parents[2])
    env['PYTHONPATH'] = f'{src_root}{os.pathsep}{env.get("PYTHONPATH", "")}'.rstrip(os.pathsep)
    payload = {'scope': scope, **context}
    try:
        result = subprocess.run(
            [sys.executable, str(hook_path)],
            input=json.dumps(payload, sort_keys=True),
            capture_output=True,
            text=True,
            check=False,
            timeout=SOURCE_HOOK_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return SourceHookResult(status='timeout', error='Source hook timed out.')
    except OSError as exc:
        return SourceHookResult(status='error', error=redact_source_info(str(exc)))

    if result.returncode != 0:
        return SourceHookResult(status='error', error=redact_source_info(result.stderr.strip()))
    try:
        data = json.loads(result.stdout or '{}')
    except json.JSONDecodeError as exc:
        return SourceHookResult(status='error', error=redact_source_info(str(exc)))
    if not isinstance(data, dict):
        return SourceHookResult(status='error', error='Source hook must write a JSON object.')
    return SourceHookResult(status='ok', data=redact_source_info(data))


def source_hook_context(case: Any) -> dict[str, Any]:
    '''Build the safe context passed to a source metadata hook.'''
    return {
        'fuzzer_id': case.fuzzer_id,
        'fuzzer_name': case.fuzzer_name,
        'fuzzer_chain': list(case.fuzzer_chain),
        'benchmark': case.benchmark,
        'fuzz_target': case.fuzz_target,
        'input_mode': case.input_mode,
        'target_timeout_s': case.target_timeout_s,
        'build_config': redact_source_info(case.build_config),
        'runtime_config': redact_source_info(case.runtime_config),
    }


def redact_source_info(value: Any) -> Any:
    '''Return source metadata with common secrets and private paths redacted.'''
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            key_text = str(key)
            if any(part in key_text.lower() for part in SECRET_KEY_PARTS):
                out[key_text] = '<redacted>'
            else:
                out[key_text] = redact_source_info(child)
        return out
    if isinstance(value, list):
        return [redact_source_info(child) for child in value]
    if isinstance(value, tuple):
        return [redact_source_info(child) for child in value]
    if isinstance(value, str):
        return _redact_path(value)
    return value


def _redact_path(value: str) -> str:
    text = str(value)
    for pattern in HOME_PATH_PATTERNS:
        text = pattern.sub('<private>', text)
    return text
