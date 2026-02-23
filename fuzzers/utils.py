# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Utility functions for running fuzzers."""

import contextlib
import json
import logging
import os
import shutil
import subprocess
import tempfile

from pathlib import Path

import yaml


LOG = logging.getLogger(__name__)

# Keep all fuzzers at same optimization level until fuzzer explicitly needs or
# specifies it.
DEFAULT_OPTIMIZATION_LEVEL = '-O3'
LIBCPLUSPLUS_FLAG = ''

NO_SANITIZER_COMPAT_CFLAGS = [
    '-pthread', '-Wl,--no-as-needed', '-Wl,-ldl', '-Wl,-lm',
    '-Wno-unused-command-line-argument'
]

FUZZING_CFLAGS = ['-DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION']

OSS_FUZZ_LIB_FUZZING_ENGINE_PATH = '/usr/lib/libFuzzingEngine.a'
BENCHMARK_CONFIG_YAML_PATH = '/benchmark.yaml'
FUZZERS_ROOT = Path('/opt/fuzzmeter/fuzzers')


def _default_fuzzing_engine(env):
    fuzzer = (env.get('FUZZER') or '').strip()
    mapping = {
        'libfuzzer': 'libfuzzer',
        'libfuzzer_grammarinator': 'libfuzzer',
        'coverage': 'libfuzzer',
        'asan': 'libfuzzer',
        'afl': 'afl',
        'aflplusplus': 'afl',
        'afl_grammarinator': 'afl',
    }
    return mapping.get(fuzzer)


def _default_sanitizer(env):
    fuzzer = (env.get('FUZZER') or '').strip()
    mapping = {
        'libfuzzer': 'address',
        'libfuzzer_grammarinator': 'address',
        'asan': 'address',
        'coverage': 'coverage',
    }
    return mapping.get(fuzzer)


def build_benchmark(env=None):
    """Build a benchmark using fuzzer library."""
    if not env:
        env = os.environ.copy()

    # Add OSS-Fuzz environment variable for fuzzer library.
    fuzzer_lib = env.get('FUZZER_LIB')
    if fuzzer_lib:
        env['LIB_FUZZING_ENGINE'] = fuzzer_lib
    env.setdefault('FUZZING_ENGINE', _default_fuzzing_engine(env) or '')
    env.setdefault('SANITIZER', _default_sanitizer(env) or '')
    if fuzzer_lib and os.path.exists(fuzzer_lib):
        # Make /usr/lib/libFuzzingEngine.a point to our library for OSS-Fuzz
        # so we can build projects that are using -lFuzzingEngine.
        shutil.copy(fuzzer_lib, OSS_FUZZ_LIB_FUZZING_ENGINE_PATH)

    build_script = os.path.join(env['SRC'], 'build.sh')
    with open(build_script, 'rb') as f:
        print(f.read().decode(errors='replace'))

    benchmark = env.get('BENCHMARK')
    fuzzer = env.get('FUZZER')
    build_cwd = env.get('BENCHMARK_WORKDIR') or env.get('SRC')
    LOG.debug(f'Building benchmark {benchmark} with fuzzer {fuzzer}')
    subprocess.check_call(['/bin/bash', '-ex', build_script], cwd=build_cwd, env=env)
    copy_target_runtime_artifacts(env=env)


def copy_target_runtime_artifacts(env=None):
    """Copy target sidecar runtime files next to the built binary in OUT."""
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


def append_flags(env_var, additional_flags, env=None):
    """Append |additional_flags| to those already set in the value of |env_var|
    and assign env_var to the result."""
    if env is None:
        env = os.environ

    env_var_value = env.get(env_var)
    flags = env_var_value.split(' ') if env_var_value else []
    flags.extend(additional_flags)
    env[env_var] = ' '.join(flags)


def _load_yaml_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    if not isinstance(data, dict):
        raise TypeError(f'Expected YAML mapping in {path}')
    return data


def _deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _base_fuzzer_name(base_fuzzer=None):
    if base_fuzzer:
        return str(base_fuzzer)
    fuzzer = (os.environ.get('FUZZER') or '').strip()
    if not fuzzer:
        raise RuntimeError('FUZZER environment variable is not set')
    return fuzzer


def get_benchmark_config():
    return _load_yaml_file(Path(BENCHMARK_CONFIG_YAML_PATH))


def get_benchmark_fuzzer_config(base_fuzzer=None):
    base_fuzzer = _base_fuzzer_name(base_fuzzer)
    data = get_benchmark_config()
    fuzzers = data.get('fuzzers') or {}
    if isinstance(fuzzers, dict):
        cfg = fuzzers.get(base_fuzzer) or {}
        if cfg:
            if not isinstance(cfg, dict):
                raise TypeError(f'benchmark fuzzers.{base_fuzzer} must be a mapping')
            return cfg

    return {}


def get_fuzzer_defaults(base_fuzzer=None):
    base_fuzzer = _base_fuzzer_name(base_fuzzer)
    fuzzer_root = FUZZERS_ROOT / base_fuzzer
    return _deep_merge(
        _load_yaml_file(fuzzer_root / 'build' / 'build.yaml'),
        _load_yaml_file(fuzzer_root / 'run' / 'run.yaml'),
    )


def get_experiment_fuzzer_config():
    config = {}
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


def get_fuzzer_config(base_fuzzer=None):
    resolved = get_experiment_fuzzer_config()
    if resolved:
        return resolved
    cfg = get_fuzzer_defaults(base_fuzzer)
    cfg = _deep_merge(cfg, get_benchmark_fuzzer_config(base_fuzzer))
    return cfg


def get_fuzzer_config_value(*keys, default=None, base_fuzzer=None):
    value = get_fuzzer_config(base_fuzzer)
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
        if value is None:
            return default
    return value


def apply_configured_env(config_section, *, env=None):
    if env is None:
        env = os.environ
    if not config_section:
        return
    if not isinstance(config_section, dict):
        raise TypeError('Configured env section must be a mapping')
    for key, value in config_section.items():
        env[str(key)] = str(value)


def get_build_env(base_fuzzer=None):
    value = get_fuzzer_config_value('build', 'env', default={}, base_fuzzer=base_fuzzer)
    if not isinstance(value, dict):
        raise TypeError('build.env must be a mapping')
    return value


def get_runtime_env(base_fuzzer=None):
    value = get_fuzzer_config_value('runtime', 'env', default={}, base_fuzzer=base_fuzzer)
    if not isinstance(value, dict):
        raise TypeError('runtime.env must be a mapping')
    return value


def expand_configured_args(config_section):
    """Convert an args mapping or list into a CLI argv list."""
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


def get_runtime_args(base_fuzzer=None):
    return expand_configured_args(get_fuzzer_config_value('runtime', 'args', default=[], base_fuzzer=base_fuzzer))


@contextlib.contextmanager
def restore_directory(directory, ignore_errors=False):
    """Helper contextmanager that when created saves a backup of |directory| and
    when closed/exited replaces |directory| with the backup.

    Example usage:

    directory = 'my-directory'
    with restore_directory(directory):
       shutil.rmtree(directory)
    # At this point directory is in the same state where it was before we
    # deleted it.
    """
    # TODO(metzman): Figure out if this is worth it, so far it only allows QSYM
    # to compile bloaty.
    if not directory:
        # Don't do anything if directory is None.
        yield
        return
    # Save cwd so that if it gets deleted we can just switch into the restored
    # version without code that runs after us running into issues.
    initial_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as temp_dir:
        backup = os.path.join(temp_dir, os.path.basename(directory))
        shutil.copytree(directory, backup, symlinks=True)
        yield
        shutil.rmtree(directory, ignore_errors=ignore_errors)
        shutil.move(backup, directory)
        try:
            os.getcwd()
        except FileNotFoundError:
            os.chdir(initial_cwd)


def get_dictionary_path(target_binary):
    """Return dictionary path for a target binary."""
    if get_env('NO_DICTIONARIES'):
        # Don't use dictionaries if experiment specifies not to.
        return None

    dictionary_path = target_binary + '.dict'
    if os.path.exists(dictionary_path):
        return dictionary_path
    return None


def set_fuzz_target(env=None):
    """Set |FUZZ_TARGET| env flag."""
    if env is None:
        env = os.environ

    env['FUZZ_TARGET'] = str(get_benchmark_config().get('fuzz_target') or '')


def set_compilation_flags(env=None):
    """Set compilation flags."""
    if env is None:
        env = os.environ

    env['CFLAGS'] = ''
    env['CXXFLAGS'] = ''
    append_flags(
        'CFLAGS',
        FUZZING_CFLAGS + NO_SANITIZER_COMPAT_CFLAGS + [DEFAULT_OPTIMIZATION_LEVEL],
        env=env,
    )
    append_flags(
        'CXXFLAGS',
        FUZZING_CFLAGS + NO_SANITIZER_COMPAT_CFLAGS + [LIBCPLUSPLUS_FLAG, DEFAULT_OPTIMIZATION_LEVEL],
        env=env,
    )


def initialize_env(env=None):
    """Set initial flags before fuzzer.build() is called."""
    if env is None:
        env = os.environ
    set_fuzz_target(env)
    set_compilation_flags(env)

    for env_var in ['FUZZ_TARGET', 'CFLAGS', 'CXXFLAGS']:
        print(f'{env_var} = {env.get(env_var)}')


def get_env(env_var, default_value=None):
    """Return an environment value with simple boolean normalization."""
    value = os.getenv(env_var)
    if value is None:
        return default_value
    normalized = value.strip().lower()
    if normalized in {'', '0', 'false', 'no', 'off'}:
        return False
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    return value


def create_seed_file_for_empty_corpus(input_corpus):
    """Create a fake seed file in an empty corpus, skip otherwise."""
    if os.listdir(input_corpus):
        # Input corpus has some files, no need of a seed file. Bail out.
        return

    LOG.debug('Creating a fake seed file in empty corpus directory.')
    default_seed_file = os.path.join(input_corpus, 'default_seed')
    with open(default_seed_file, 'w', encoding='utf-8') as file_handle:
        file_handle.write('hi')
        
