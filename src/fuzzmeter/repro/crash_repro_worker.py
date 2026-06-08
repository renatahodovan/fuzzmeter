#!/usr/bin/env python3
# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import json
import logging
import os
import subprocess

from pathlib import Path

level = getattr(logging, os.environ.get('FM_LOG_LEVEL', 'WARNING'))
logging.basicConfig(
    level=level,
    format='%(asctime)s - %(levelname)-7s - %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
LOG = logging.getLogger(__name__)


def main() -> None:
    '''Run crash inputs against the sanitizer binary and write JSON results.'''
    target_name = os.environ['FM_TARGET_NAME']
    crash_input_list_env = os.environ.get('FM_CRASH_INPUT_LIST', '')
    output_json_env = os.environ.get('FM_CRASH_OUTPUT_JSON', '')
    timeout_s = float(os.environ.get('FM_TIMEOUT_S', '10.0'))
    input_mode = os.environ.get('FM_INPUT_MODE', '')

    asan_bin = Path(f'/out/{target_name}')
    if not asan_bin.exists():
        LOG.error('ASAN binary not found: %s', asan_bin)
        raise SystemExit(2)

    env = os.environ.copy()
    env.setdefault('ASAN_OPTIONS', 'symbolize=1:abort_on_error=1:disable_coredump=1:detect_leaks=0:handle_abort=1')
    env.setdefault('UBSAN_OPTIONS', 'print_stacktrace=1:halt_on_error=1')

    if not crash_input_list_env or not output_json_env:
        LOG.error('FM_CRASH_INPUT_LIST and FM_CRASH_OUTPUT_JSON are required')
        raise SystemExit(2)

    output_json = Path(output_json_env)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    crash_inputs = [
        Path(line.strip())
        for line in Path(crash_input_list_env).read_text(encoding='utf-8', errors='replace').splitlines()
    ]

    results = [
        _run_one(
            asan_bin=asan_bin,
            crash_input=crash_input,
            input_mode=input_mode,
            timeout_s=timeout_s,
            env=env,
        )
        for crash_input in crash_inputs
    ]

    output_json.write_text(json.dumps(results), encoding='utf-8')

    raise SystemExit(0)


def _run_one(
    *,
    asan_bin: Path,
    crash_input: Path,
    input_mode: str,
    timeout_s: float,
    env: dict[str, str],
) -> dict:
    if input_mode in ('in_process', 'file'):
        cmd = [str(asan_bin), str(crash_input)]
        stdin_data = None
    else:
        cmd = [str(asan_bin)]
        stdin_data = Path(crash_input).read_text(encoding='utf-8', errors='replace')

    LOG.debug('Running crash repro command: %s', ' '.join(str(item) for item in cmd))
    try:
        result = subprocess.run(
            cmd,
            input=stdin_data,
            text=True,
            encoding='utf-8',
            errors='replace',
            capture_output=True,
            timeout=timeout_s,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            'returncode': 124,
            'stdout': exc.stdout.decode('utf-8', errors='replace') if exc.stdout else '',
            'stderr': exc.stderr.decode('utf-8', errors='replace') if exc.stderr else '',
            'timeout': True,
        }

    return {
        'returncode': int(result.returncode),
        'stdout': result.stdout or '',
        'stderr': result.stderr or '',
        'timeout': False,
    }


if __name__ == '__main__':
    main()
