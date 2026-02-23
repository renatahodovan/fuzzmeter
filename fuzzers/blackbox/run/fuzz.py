# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Shared blackbox test generation and target execution support.'''

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import time

from pathlib import Path
from typing import Any

from fuzzers import utils

level = getattr(logging, os.environ.get('FM_LOG_LEVEL', 'DEBUG'))
logging.basicConfig(level=level, 
                    format='%(asctime)s - %(levelname)-7s - %(name)s - %(message)s',
                    datefmt="%Y-%m-%d %H:%M:%S")
LOG = logging.getLogger(__name__)


class BlackBoxFuzzer:
    '''Generate tests in batches and execute the target on each generated input.'''

    def __init__(
        self,
        *,
        generator_command: list[str],
        input_corpus: str,
        input_mode: str,
        output_corpus: str,
        target_command: list[str],
        batch_size: int,
        generator_timeout_s: float | None = None,
        target_timeout_s: float | None = None,
    ) -> None:
        '''Initialize a blackbox fuzzing loop.'''
        self.batch_size = batch_size
        self.batch_index = 0
        self.crashes = 0
        self.executed = 0
        self.generator_command = generator_command
        self.generator_timeout_s = generator_timeout_s
        self.hangs = 0
        self.input_corpus = Path(input_corpus)
        self.input_mode = input_mode
        self.output_root = Path(output_corpus)
        self.start_time = time.monotonic()
        self.target_command = target_command
        self.target_timeout_s = target_timeout_s

        self.corpus_dir = self.output_root / 'corpus'
        self.crashes_dir = self.output_root / 'crashes'
        self.hangs_dir = self.output_root / 'hangs'
        self.state_dir = self.output_root / 'state'
        self.batches_dir = self.state_dir / 'batches'
        for directory in (self.corpus_dir, self.crashes_dir, self.hangs_dir, self.batches_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.next_corpus_id = _next_prefixed_id(self.corpus_dir, 'id:')

    def run(self) -> None:
        '''Run the generator-target cycle until the process is stopped.'''
        while True:
            LOG.debug('#%d batch generate...', self.batch_index)
            batch_dir = self._create_batch_dir()
            self._run_generator(batch_dir)
            generated_files = _generated_files(batch_dir)
            if not generated_files:
                raise RuntimeError(f'Generator produced no test cases in {batch_dir}')
            for generated_path in generated_files:
                corpus_path = self._copy_to_corpus(generated_path)
                self._run_target(corpus_path)
                self._write_stats()
            LOG.debug('All generated test of #%d iteration is executed.', self.batch_index)

    def get_stats(self) -> dict[str, Any]:
        '''Return the latest in-memory execution statistics.'''
        elapsed_s = max(time.monotonic() - self.start_time, 0.001)
        return {
            'crashes': self.crashes,
            'execs_done': float(self.executed),
            'execs_per_sec': self.executed / elapsed_s,
            'hangs': self.hangs,
        }

    def _create_batch_dir(self) -> Path:
        batch_dir = self.batches_dir / f'batch_{self.batch_index:06d}'
        self.batch_index += 1
        if batch_dir.exists():
            shutil.rmtree(batch_dir)
        batch_dir.mkdir(parents=True)
        return batch_dir

    def _run_generator(self, batch_dir: Path) -> None:
        command = _format_command(
            self.generator_command,
            batch_dir=batch_dir,
            batch_size=self.batch_size,
            corpus_dir=self.corpus_dir,
            crashes_dir=self.crashes_dir,
            hangs_dir=self.hangs_dir,
            input_dir=self.input_corpus,
            output_dir=self.corpus_dir,
        )
        LOG.info('Running generator command: %s', ' '.join(command))
        subprocess.run(command, check=True, timeout=self.generator_timeout_s)

    def _copy_to_corpus(self, generated_path: Path) -> Path:
        corpus_path = self._next_corpus_path()
        shutil.copy2(generated_path, corpus_path)
        return corpus_path

    def _next_corpus_path(self) -> Path:
        while True:
            corpus_path = self.corpus_dir / f'id:{self.next_corpus_id:06d}'
            self.next_corpus_id += 1
            if not corpus_path.exists():
                return corpus_path

    def _run_target(self, input_path: Path) -> None:
        command = _target_command(self.target_command, input_path=input_path, input_mode=self.input_mode)
        LOG.debug('Running target command: %s', ' '.join(command))
        try:
            result = subprocess.run(
                command,
                input=_stdin_data(input_path, self.input_mode),
                timeout=self.target_timeout_s,
            )
        except subprocess.TimeoutExpired:
            self.hangs += 1
            hang_path = _copy_without_overwrite(input_path, self.hangs_dir / input_path.name)
            self.executed += 1
            LOG.warning('Target timed out on %s, saved to %s', input_path, hang_path)
            return

        if result.returncode:
            self.crashes += 1
            crash_path = _copy_without_overwrite(input_path, self.crashes_dir / input_path.name)
            LOG.warning(
                'Target exited with code %d on %s, saved to %s',
                result.returncode,
                input_path,
                crash_path,
            )
        self.executed += 1

    def _write_stats(self) -> None:
        stats = self.get_stats()
        stats['elapsed_s'] = time.monotonic() - self.start_time
        with (self.state_dir / 'stats.jsonl').open('a', encoding='utf-8') as stats_file:
            stats_file.write(json.dumps(stats, sort_keys=True) + '\n')


def fuzz_blackbox(
    *,
    input_corpus: str,
    output_corpus: str,
    target_binary: str,
    input_mode: str,
    generator_command: list[str] | None = None,
    target_args: list[str] | None = None,
) -> None:
    '''Run a configured blackbox generator against the selected target.'''
    utils.apply_configured_env(utils.get_runtime_env())
    generator_cfg = _config_section('generator')
    target_cfg = _config_section('target')

    fuzzer = BlackBoxFuzzer(
        generator_command=_configured_command(generator_cfg, generator_command),
        input_corpus=input_corpus,
        input_mode=input_mode,
        output_corpus=output_corpus,
        target_command=_configured_target_command(target_cfg, target_binary, target_args or []),
        batch_size=_configured_batch_size(generator_cfg),
        generator_timeout_s=_optional_float(generator_cfg.get('timeout_s')),
        target_timeout_s=_optional_float(target_cfg.get('timeout_s')),
    )
    fuzzer.run()


def get_output_paths(live_out: Path) -> dict[str, Any]:
    '''Return blackbox output directories for live trial collection.'''
    root = Path(live_out)
    return {
        'corpus_root': root / 'corpus',
        'crashes_root': root / 'crashes',
        'hangs_root': root / 'hangs',
    }


def get_stats(trial_root: Path) -> dict[str, Any]:
    '''Return the latest persisted blackbox statistics.'''
    return get_stats_until(trial_root)


def get_stats_until(trial_root: Path, *, cutoff_elapsed_s: int | None = None) -> dict[str, Any]:
    '''Return persisted blackbox statistics up to the selected elapsed time.'''
    latest: dict[str, Any] = {}
    stats_path = Path(trial_root) / 'work' / 'state' / 'stats.jsonl'
    if not stats_path.is_file():
        return latest

    for line in stats_path.read_text(encoding='utf-8', errors='ignore').splitlines():
        try:
            stats = json.loads(line)
        except json.JSONDecodeError:
            continue
        elapsed_s = stats.get('elapsed_s')
        if cutoff_elapsed_s is not None and elapsed_s is not None and elapsed_s > cutoff_elapsed_s:
            continue
        latest = stats
    return latest


def _config_section(name: str) -> dict[str, Any]:
    section = utils.get_fuzzer_config_value('runtime', name, default={})
    if not isinstance(section, dict):
        raise TypeError(f'Runtime {name} config must be a mapping')
    return section


def _configured_batch_size(generator_cfg: dict[str, Any]) -> int:
    value = generator_cfg.get(
        'batch_size',
        utils.get_fuzzer_config_value('runtime', 'batch_size', default=100),
    )
    batch_size = int(value)
    if batch_size < 1:
        raise ValueError('Generator batch_size must be positive')
    return batch_size


def _configured_command(config: dict[str, Any], default: list[str] | None) -> list[str]:
    command = _as_command(config.get('command')) or list(default or [])
    command.extend(_as_command(config.get('args')))
    if not command:
        raise RuntimeError('Generator command must be configured')
    return command


def _configured_target_command(config: dict[str, Any], target_binary: str, default_args: list[str]) -> list[str]:
    command = _as_command(config.get('command')) or [target_binary]
    command.extend(default_args)
    command.extend(_as_command(config.get('args')))
    return command


def _as_command(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    raise TypeError(f'Command config must be a string or list, got {type(value)!r}')


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _format_command(command: list[str], **values: Any) -> list[str]:
    formatted_values = {key: str(value) for key, value in values.items()}
    return [item.format(**formatted_values) for item in command]


def _generated_files(batch_dir: Path) -> list[Path]:
    return sorted(path for path in batch_dir.rglob('*') if path.is_file())


def _next_prefixed_id(directory: Path, prefix: str) -> int:
    next_id = 0
    for path in directory.iterdir():
        if not path.is_file():
            continue
        file_id = _prefixed_id(path.name, prefix)
        if file_id is not None:
            next_id = max(next_id, file_id + 1)
    return next_id


def _prefixed_id(name: str, prefix: str) -> int | None:
    if not name.startswith(prefix):
        return None

    digits = []
    for char in name[len(prefix):]:
        if not char.isdigit():
            break
        digits.append(char)
    return int(''.join(digits)) if digits else None


def _copy_without_overwrite(src: Path, dst: Path) -> Path:
    if not dst.exists():
        shutil.copy2(src, dst)
        return dst

    for index in range(1, 1000000):
        candidate = dst.with_name(f'{dst.name}.{index:06d}')
        if not candidate.exists():
            shutil.copy2(src, candidate)
            return candidate
    raise RuntimeError(f'Could not find free output path for {dst}')


def _target_command(command: list[str], *, input_path: Path, input_mode: str) -> list[str]:
    formatted = [item.replace('@@', str(input_path)) for item in _format_command(command, input=input_path)]
    if input_mode == 'file' and not any(str(input_path) in item for item in formatted):
        formatted.append(str(input_path))
    return formatted


def _stdin_data(input_path: Path, input_mode: str) -> bytes | None:
    if input_mode == 'file':
        return None
    return input_path.read_bytes()
