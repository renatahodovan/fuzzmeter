#!/usr/bin/env python3
# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import logging
import os
import subprocess
import sys
import json

from pathlib import Path

TRACE = 5
logging.addLevelName(TRACE, 'TRACE')
level = getattr(logging, os.environ.get('FM_LOG_LEVEL', 'WARNING'))
logging.basicConfig(
    level=level,
    format='%(asctime)s - %(levelname)-7s - %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
LOG = logging.getLogger(__name__)


def main() -> None:
    '''Run one crash input against the sanitizer binary.'''
    target_name = os.environ['FM_TARGET_NAME']
    crash_input_env = os.environ.get('FM_CRASH_INPUT', '')
    crash_input_list_env = os.environ.get('FM_CRASH_INPUT_LIST', '')
    output_jsonl_env = os.environ.get('FM_CRASH_OUTPUT_JSONL', '')
    timeout_s = float(os.environ.get('FM_TIMEOUT_S', '10.0'))
    input_mode = os.environ.get('FM_INPUT_MODE', '')

    asan_bin = Path(f'/out/{target_name}')
    if not asan_bin.exists():
        LOG.error('ASAN binary not found: %s', asan_bin)
        raise SystemExit(2)

    env = os.environ.copy()
    env.setdefault('ASAN_OPTIONS', 'symbolize=1:abort_on_error=1:disable_coredump=1:detect_leaks=0:handle_abort=1')
    env.setdefault('UBSAN_OPTIONS', 'print_stacktrace=1:halt_on_error=1')

    if crash_input_list_env:
        if not output_jsonl_env:
            LOG.error('FM_CRASH_OUTPUT_JSONL is required with FM_CRASH_INPUT_LIST')
            raise SystemExit(2)
        output_jsonl = Path(output_jsonl_env)
        output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        crash_inputs = _read_input_list(Path(crash_input_list_env))
        with output_jsonl.open('w', encoding='utf-8') as handle:
            for index, crash_input in enumerate(crash_inputs):
                payload = _run_one(
                    asan_bin=asan_bin,
                    crash_input=crash_input,
                    input_mode=input_mode,
                    timeout_s=timeout_s,
                    env=env,
                )
                payload['index'] = index
                payload['input'] = str(crash_input)
                handle.write(json.dumps(payload))
                handle.write('\n')
        raise SystemExit(0)

    crash_input = Path(crash_input_env)
    if not crash_input.exists():
        LOG.error('Crash input not found: %s', crash_input)
        raise SystemExit(2)

    payload = _run_one(
        asan_bin=asan_bin,
        crash_input=crash_input,
        input_mode=input_mode,
        timeout_s=timeout_s,
        env=env,
    )
    _write_child_output(stdout=payload.get('stdout') or '', stderr=payload.get('stderr') or '')
    raise SystemExit(0)


def _run_one(
    *,
    asan_bin: Path,
    crash_input: Path,
    input_mode: str,
    timeout_s: float,
    env: dict[str, str],
) -> dict:
    cmd, stdin_data = _target_command(asan_bin=asan_bin, input_mode=input_mode, input_path=crash_input)
    LOG.debug('Running crash repro command: %s', ' '.join(str(item) for item in cmd))
    try:
        result = subprocess.run(
            cmd,
            input=stdin_data,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            'returncode': 124,
            'stdout': _decode_output(exc.stdout or ''),
            'stderr': _decode_output(exc.stderr or ''),
            'timeout': True,
        }

    return {
        'returncode': int(result.returncode),
        'stdout': result.stdout or '',
        'stderr': result.stderr or '',
        'timeout': False,
    }


def _read_input_list(path: Path) -> list[Path]:
    if not path.is_file():
        return []
    return [
        Path(line.strip())
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines()
        if line.strip()
    ]


def _target_command(*, asan_bin: Path, input_mode: str, input_path: str) -> tuple[list[str], str | None]:
    if input_mode in ('in_process', 'file'):
        return [str(asan_bin), str(input_path)], None
    return [str(asan_bin)], Path(input_path).read_text(encoding='utf-8', errors='replace')


def _write_child_output(*, stdout: str | bytes, stderr: str | bytes) -> None:
    stdout = _decode_output(stdout)
    stderr = _decode_output(stderr)
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)


def _decode_output(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return value


if __name__ == '__main__':
    main()
