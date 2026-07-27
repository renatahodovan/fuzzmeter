# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Shared instrumentation helpers for fuzzer build and run scripts.'''

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import subprocess
import tempfile

from pathlib import Path
from typing import Any, Iterator

import yaml


LOG = logging.getLogger(__name__)

DEFAULT_OPTIMIZATION_LEVEL = '-O3'

NO_SANITIZER_COMPAT_CFLAGS = [
    '-pthread',
    '-Wl,--no-as-needed',
    '-Wl,-ldl',
    '-Wl,-lm',
    '-Wno-unused-command-line-argument',
]

FUZZING_CFLAGS = ['-DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION']

BENCHMARK_CONFIG_PATH = '/benchmark.yaml'
FUZZERS_ROOT = Path(os.environ.get('FM_CONTAINER_FUZZERS_ROOT', '/opt/fuzzmeter/fuzzers'))


def build_benchmark(env: dict[str, str] | None = None) -> None:
    '''Build the configured benchmark and copy target runtime sidecars.'''
    if not env:
        env = os.environ.copy()

    fuzzer_lib = env.get('FUZZER_LIB')
    if fuzzer_lib:
        env['LIB_FUZZING_ENGINE'] = fuzzer_lib

    build_script = os.path.join(env['SRC'], 'build.sh')
    with open(build_script, 'rb') as file_handle:
        print(file_handle.read().decode(errors='replace'))

    benchmark = env.get('BENCHMARK')
    fuzzer = env.get('FUZZER')
    build_cwd = env.get('BENCHMARK_WORKDIR') or env.get('SRC')
    LOG.debug('Building benchmark %s with fuzzer %s', benchmark, fuzzer)
    subprocess.check_call(['/bin/bash', '-ex', build_script], cwd=build_cwd, env=env)
    copy_target_runtime_artifacts(env=env)


def copy_target_runtime_artifacts(env: dict[str, str] | None = None) -> None:
    '''Copy target sidecar runtime files next to the built binary in OUT.'''
    if env is None:
        env = os.environ

    target_name = (env.get('TARGET_NAME') or env.get('FUZZ_TARGET') or '').strip()
    src_dir = Path(env['SRC'])
    out_dir = Path(env['OUT'])
    if not target_name:
        return

    for suffix in ('.dict',):
        src_path = src_dir / f'{target_name}{suffix}'
        dst_path = out_dir / f'{target_name}{suffix}'
        if not src_path.is_file() or dst_path.exists():
            continue
        shutil.copy2(src_path, dst_path)
        LOG.info('Copied target runtime artifact: %s -> %s', src_path, dst_path)


def append_flags(env_var: str, additional_flags: list[str], env: dict[str, str] | None = None) -> None:
    '''Append additional compiler or linker flags to an environment variable.'''
    if env is None:
        env = os.environ

    env_var_value = env.get(env_var)
    flags = env_var_value.split(' ') if env_var_value else []
    flags.extend(additional_flags)
    env[env_var] = ' '.join(flags)


def get_benchmark_config() -> dict[str, Any]:
    '''Load the benchmark YAML configuration if present.'''
    return _load_yaml_file(Path(BENCHMARK_CONFIG_PATH))


def get_active_target_name(env: dict[str, str] | None = None) -> str:
    '''Return the active target name from the runtime environment.'''
    if env is None:
        env = os.environ
    return (env.get('TARGET_NAME') or env.get('FM_TARGET_NAME') or '').strip()


def get_active_target_config(env: dict[str, str] | None = None) -> dict[str, Any]:
    '''Return the active target config from the benchmark YAML.'''
    if env is None:
        env = os.environ

    data = get_benchmark_config()
    legacy_fuzz_target = str(data.get('fuzz_target') or '').strip()
    multi_target_data = data.get('fuzz_targets')

    has_legacy_target = bool(legacy_fuzz_target)
    has_multi_target = multi_target_data is not None
    if has_legacy_target and has_multi_target:
        raise ValueError('benchmark.yaml must define exactly one of fuzz_target or fuzz_targets')
    if not has_legacy_target and not has_multi_target:
        raise ValueError('benchmark.yaml must define fuzz_target or fuzz_targets')

    if has_multi_target:
        if not isinstance(multi_target_data, dict) or not multi_target_data:
            raise ValueError('benchmark.yaml fuzz_targets must be a non-empty mapping')
        if data.get('fuzzers') is not None:
            raise ValueError('benchmark.yaml with fuzz_targets must not define root-level fuzzers')

        active_target = get_active_target_name(env)
        if not active_target:
            raise RuntimeError('TARGET_NAME must be set when benchmark.yaml uses fuzz_targets')
        target_data = multi_target_data.get(active_target)
        if target_data is None:
            raise ValueError(f'benchmark.yaml does not define target {active_target!r}')
        if not isinstance(target_data, dict):
            raise TypeError(f'benchmark.yaml fuzz_targets.{active_target} must be a mapping')
        return {'name': active_target, 'config': target_data}

    return {'name': legacy_fuzz_target, 'config': data}


def get_benchmark_fuzzer_config(base_fuzzer: str | None = None) -> dict[str, Any]:
    '''Return benchmark-local overrides for the active fuzzer.'''
    base_fuzzer = _base_fuzzer_name(base_fuzzer)
    target_config = get_active_target_config()['config']
    fuzzers = target_config.get('fuzzers') or {}
    if isinstance(fuzzers, dict):
        cfg = fuzzers.get(base_fuzzer) or {}
        if cfg:
            if not isinstance(cfg, dict):
                raise TypeError(f'benchmark fuzzers.{base_fuzzer} must be a mapping')
            return cfg

    return {}


def get_fuzzer_defaults(base_fuzzer: str | None = None) -> dict[str, Any]:
    '''Return default build and runtime config for the selected fuzzer.'''
    base_fuzzer = _base_fuzzer_name(base_fuzzer)
    fuzzer_root = FUZZERS_ROOT / base_fuzzer
    return _deep_merge(
        _load_yaml_file(fuzzer_root / 'build' / 'build.yaml'),
        _load_yaml_file(fuzzer_root / 'run' / 'run.yaml'),
    )


def get_experiment_fuzzer_config() -> dict[str, Any]:
    '''Return explicit runtime JSON config overrides from the environment.'''
    config: dict[str, Any] = {}
    build_raw = (os.environ.get('FM_FUZZER_BUILD_CONFIG_JSON') or '').strip()
    if build_raw:
        data = json.loads(build_raw)
        if not isinstance(data, dict):
            raise TypeError('FM_FUZZER_BUILD_CONFIG_JSON must decode to a mapping')
        config['build'] = data

    runtime_raw = (os.environ.get('FM_FUZZER_RUNTIME_CONFIG_JSON') or '').strip()
    if runtime_raw:
        data = json.loads(runtime_raw)
        if not isinstance(data, dict):
            raise TypeError('FM_FUZZER_RUNTIME_CONFIG_JSON must decode to a mapping')
        config['runtime'] = data

    return config


def get_fuzzer_config(base_fuzzer: str | None = None) -> dict[str, Any]:
    '''Return the effective merged config for the selected fuzzer.'''
    resolved = get_experiment_fuzzer_config()
    if resolved:
        return resolved
    cfg = get_fuzzer_defaults(base_fuzzer)
    return _deep_merge(cfg, get_benchmark_fuzzer_config(base_fuzzer))


def get_fuzzer_config_value(*keys: str, default: Any = None, base_fuzzer: str | None = None) -> Any:
    '''Return a nested fuzzer config value or the provided default.'''
    value: Any = get_fuzzer_config(base_fuzzer)
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
        if value is None:
            return default
    return value


def apply_configured_env(config_section: dict[str, Any] | None, *, env: dict[str, str] | None = None) -> None:
    '''Apply a configured environment mapping to the target environment.'''
    if env is None:
        env = os.environ
    if not config_section:
        return
    if not isinstance(config_section, dict):
        raise TypeError('Configured env section must be a mapping')
    for key, value in config_section.items():
        env[str(key)] = str(value)


def get_build_env(base_fuzzer: str | None = None) -> dict[str, Any]:
    '''Return the configured build environment overrides.'''
    value = get_fuzzer_config_value('build', 'env', default={}, base_fuzzer=base_fuzzer)
    if not isinstance(value, dict):
        raise TypeError('build.env must be a mapping')
    return value


def get_runtime_env(base_fuzzer: str | None = None) -> dict[str, Any]:
    '''Return the configured runtime environment overrides.'''
    value = get_fuzzer_config_value('runtime', 'env', default={}, base_fuzzer=base_fuzzer)
    if not isinstance(value, dict):
        raise TypeError('runtime.env must be a mapping')
    return value


def expand_configured_args(config_section: dict[str, Any] | list[Any] | None) -> list[str]:
    '''Convert an args mapping or list into a CLI argv list.'''
    if not config_section:
        return []
    if isinstance(config_section, list):
        return [str(item) for item in config_section]
    if not isinstance(config_section, dict):
        raise TypeError('Configured args section must be a mapping or list')

    argv = []
    for key, value in config_section.items():
        flag = str(key)
        if not flag.startswith('-'):
            flag = f'-{flag}'
        if value is None or value is True:
            argv.append(flag)
        elif value is False:
            continue
        else:
            argv.append(f'{flag}={value}')
    return argv


def get_runtime_args(base_fuzzer: str | None = None) -> list[str]:
    '''Return configured runtime CLI arguments for the selected fuzzer.'''
    return expand_configured_args(get_fuzzer_config_value('runtime', 'args', default=[], base_fuzzer=base_fuzzer))


def get_fuzz_target_timeout_s(default: float | None = None, base_fuzzer: str | None = None) -> float | None:
    '''Return the configured per-input fuzz target timeout in seconds.'''
    del base_fuzzer
    value = os.environ.get('FM_FUZZ_TARGET_TIMEOUT')
    if value is None:
        return default

    timeout_s = float(value)
    if timeout_s <= 0:
        raise ValueError(f'Fuzz target timeout must be positive, got {timeout_s}.')
    return timeout_s


@contextlib.contextmanager
def restore_directory(directory: str | os.PathLike[str] | None, ignore_errors: bool = False) -> Iterator[None]:
    '''Restore a directory to its original state after the wrapped block exits.'''
    if not directory:
        yield
        return

    initial_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as temp_dir:
        backup = os.path.join(temp_dir, os.path.basename(directory))
        shutil.copytree(directory, backup, symlinks=True)
        try:
            yield
        finally:
            try:
                shutil.rmtree(directory, ignore_errors=ignore_errors)
                shutil.move(backup, directory)
            finally:
                try:
                    os.getcwd()
                except FileNotFoundError:
                    os.chdir(initial_cwd)


def get_dictionary_path(target_binary: str) -> str | None:
    '''Return the runtime dictionary path for a target binary, if enabled.'''
    if get_env('NO_DICTIONARIES'):
        return None

    dictionary_path = target_binary + '.dict'
    if os.path.exists(dictionary_path):
        return dictionary_path
    return None


def get_env(env_var: str, default_value: Any = None) -> Any:
    '''Return an environment value with simple boolean normalization.'''
    value = os.getenv(env_var)
    if value is None:
        return default_value
    normalized = value.strip().lower()
    if normalized in {'', '0', 'false', 'no', 'off'}:
        return False
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    return value


def create_seed_file_for_empty_corpus(input_corpus: str) -> None:
    '''Create a fake seed file in an empty corpus directory.'''
    if os.listdir(input_corpus):
        return

    LOG.debug('Creating a fake seed file in empty corpus directory.')
    default_seed_file = os.path.join(input_corpus, 'default_seed')
    with open(default_seed_file, 'w', encoding='utf-8') as file_handle:
        file_handle.write('hi')


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    if not isinstance(data, dict):
        raise TypeError(f'Expected YAML mapping in {path}')
    return data


def _deep_merge(base: Any, override: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _base_fuzzer_name(base_fuzzer: str | None = None) -> str:
    if base_fuzzer:
        return str(base_fuzzer)
    fuzzer = (os.environ.get('FUZZER') or '').strip()
    if not fuzzer:
        raise RuntimeError('FUZZER environment variable is not set')
    return fuzzer
