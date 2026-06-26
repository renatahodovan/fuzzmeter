#!/usr/bin/env python3
# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Replay crashing inputs inside the sanitizer container worker.'''

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
    input_mode = os.environ['FM_INPUT_MODE']
    timeout_s = float(os.environ['FM_TIMEOUT_S'])
    input_list_fn = os.environ['FM_CRASH_INPUT_LIST']
    output_json_fn = os.environ['FM_CRASH_OUTPUT_JSON']

    env = os.environ.copy()
    env['ASAN_OPTIONS'] = 'symbolize=1:abort_on_error=1:disable_coredump=1:detect_leaks=0:handle_abort=1'
    env['UBSAN_OPTIONS'] = 'print_stacktrace=1:halt_on_error=1'

    output_json = Path(output_json_fn)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    crash_inputs = [
        Path(line.strip())
        for line in Path(input_list_fn).read_text(encoding='utf-8', errors='replace').splitlines()
    ]

    results = [
        _run_one(
            asan_bin=Path(f'/out/{target_name}'),
            crash_input=crash_input,
            input_mode=input_mode,
            timeout_s=timeout_s,
            env=env,
        )
        for crash_input in crash_inputs
    ]

    output_json.write_text(json.dumps(results), encoding='utf-8')


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
        stdin_data = crash_input.read_text(encoding='utf-8', errors='replace')

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
