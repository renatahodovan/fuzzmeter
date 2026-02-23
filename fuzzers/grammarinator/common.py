# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Shared Grammarinator build helpers for guided and blackbox integrations.'''

from __future__ import annotations

import os
import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile

from pathlib import Path
from typing import Any

import logging

from fuzzers import utils


GRAMMARINATOR_DIR = Path('/grammarinator')
LOG = logging.getLogger(__name__)


def _build_env_cfg() -> dict[str, Any]:
    data = utils.get_build_env() or {}
    if not isinstance(data, dict):
        raise TypeError('Build.env must be a mapping')
    return data


def as_list(value: Any) -> list[str]:
    '''Return a normalized list from a scalar or sequence config value.'''
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value]
    raise TypeError(f'Expected string or list, got {type(value)!r}')


def resolve_paths(items: list[str]) -> list[str]:
    '''Resolve target-relative paths against the source directory.'''
    src = Path(os.environ['SRC'])
    out: list[str] = []
    for item in items:
        path = Path(item)
        if not path.is_absolute():
            path = src / path
        out.append(str(path))
    return out


def resolve_include_paths(items: list[str]) -> list[str]:
    '''Resolve include paths against the target and Grammarinator include directories.'''
    include_dir = Path(os.environ['SRC']) / 'grammarinator'
    src = Path(os.environ['SRC'])
    out: list[str] = []
    for item in items:
        path = Path(item)
        if not path.is_absolute():
            include_candidate = include_dir / path
            if include_candidate.exists():
                path = include_candidate
            else:
                path = src / path
        out.append(str(path))
    return out


def require_generator_grammars(cfg: dict[str, Any]) -> list[str]:
    '''Return configured generator grammars.'''
    grammars = resolve_paths(as_list(cfg.get('GRAMMARINATOR_GENERATOR_GRAMMARS')))
    if not grammars:
        raise RuntimeError('GRAMMARINATOR_GENERATOR_GRAMMARS must be configured')
    return [grammar for grammar in grammars if grammar.endswith('.g4')]


def require_parser_grammars(cfg: dict[str, Any]) -> list[str]:
    '''Return configured parser grammars.'''
    grammars = resolve_paths(as_list(cfg.get('GRAMMARINATOR_PARSER_GRAMMARS')))
    if not grammars:
        raise RuntimeError('GRAMMARINATOR_PARSER_GRAMMARS must be configured')
    return grammars


def run_process(*, out_dir: Path, generator_grammars: list[str], rule: str) -> None:
    '''Run grammarinator-process for the configured generator grammars.'''
    LOG.info('Running grammarinator-process for %s', out_dir)
    cmd = [
        'grammarinator-process',
        '-g',
        *generator_grammars,
        '--language=hpp',
        '--no-actions',
        '-DsuperClass=Generator',
        '--out',
        str(out_dir),
    ]
    if rule:
        cmd.append(f'--rule={rule}')
    if _is_verbose_logging():
        cmd.append('--log-level=DEBUG')
    subprocess.check_call(cmd)


def run_build(
    *,
    out_dir: Path,
    include_dir: Path,
    fuzz_target: str,
    cfg: dict[str, Any],
    mode: str,
    extra_args: list[str] | None = None,
) -> None:
    '''Build the selected Grammarinator C++ integration mode.'''
    build_cmd = [
        'python3',
        '/grammarinator/grammarinator-cxx/dev/build.py',
    ]
    serializer = resolve_include_paths(as_list(cfg.get('GRAMMARINATOR_SERIALIZER')))
    if serializer:
        build_cmd.extend(['--serializer', Path(serializer[0]).stem])
    model = resolve_include_paths(as_list(cfg.get('GRAMMARINATOR_MODEL')))
    if model:
        build_cmd.extend(['--model', Path(model[0]).stem])
    include = []
    for include in resolve_include_paths(as_list(cfg.get('GRAMMARINATOR_CONFIG'))):
        include = ['--include', Path(include).name]

    if include:
        build_cmd.extend(include)
    else:
        generator_options = [fn for fn in os.listdir(str(out_dir)) if 'Generator' in fn]
        if len(generator_options) != 1:
            raise RuntimeError(f'Ambiguous Generators: {generator_options}')
        build_cmd.extend(['--generator', Path(generator_options[0]).stem])

    build_cmd.extend([
        '--includedir', str(include_dir),
        '--includedir', str(out_dir),
        '--includedir', str('/src/grammarinator'),
        '--suffix', fuzz_target,
        '--clean',
    ])
    if _is_verbose_logging():
        build_cmd.append('--verbose')
    # build_cmd.extend(['--log-level', _grammarinator_log_level()])
    if mode == 'generate':
        build_cmd.extend(['--generate', '--decode'])
    elif mode == 'grafl':
        build_cmd.extend(['--afl-include', '/afl/include', '--grafl', '--decode'])
    elif mode == 'grlf':
        build_cmd.extend(['--grlf', '--decode'])
    else:
        raise ValueError(f'Unsupported grammarinator mode: {mode}')
    build_cmd.extend(extra_args or [])
    subprocess.check_call(build_cmd, cwd=str(out_dir))


def build_library_path(*, fuzz_target: str, mode: str) -> Path:
    '''Return the expected path of the generated mutator library.'''
    suffix = '.so' if mode == 'grafl' else '.a'
    prefix = 'libgrafl-' if mode == 'grafl' else 'libgrlf-'
    return GRAMMARINATOR_DIR / 'grammarinator-cxx' / 'build' / 'lib' / f'{prefix}{fuzz_target}{suffix}'


def build_generator_path(*, fuzz_target: str) -> Path:
    '''Return the path of the generated standalone Grammarinator binary.'''
    return GRAMMARINATOR_DIR / 'grammarinator-cxx' / 'build' / 'bin' / f'grammarinator-generate-{fuzz_target}'


def copy_decode_bin(*, out_dir: Path, target_name: str) -> None:
    '''Copy the Grammarinator decode binary into the benchmark output directory.'''
    decode_bin = GRAMMARINATOR_DIR / 'grammarinator-cxx' / 'build' / 'bin' / f'grammarinator-decode-{target_name}'
    if not decode_bin.is_file():
        raise RuntimeError(f'Missing Grammarinator decode binary: {decode_bin}')
    decode_out = out_dir / f'grammarinator-decode-{target_name}'
    subprocess.check_call(['cp', str(decode_bin), str(decode_out)])
    decode_out.chmod(0o755)


def copy_generator_bin(*, out_dir: Path, fuzz_target: str) -> Path:
    '''Copy the standalone Grammarinator generator into the benchmark output directory.'''
    generator_bin = build_generator_path(fuzz_target=fuzz_target)
    if not generator_bin.is_file():
        raise RuntimeError(f'Missing Grammarinator generator binary: {generator_bin}')
    generator_out = out_dir / 'grammarinator-generate'
    subprocess.check_call(['cp', str(generator_bin), str(generator_out)])
    generator_out.chmod(0o755)
    return generator_out


def rewrite_seed_corpus_zips(*, parser_grammars: list[str], rule: str, out_dir: Path, prefix: str) -> None:
    '''Rewrite source seed corpus archives into Grammarinator tree archives.'''
    for archive in sorted(out_dir.glob('*_seed_corpus.zip')):
        cached = _cached_seed_tree_archive(archive=archive, parser_grammars=parser_grammars, rule=rule)
        if cached:
            shutil.copy2(cached, archive)
            LOG.info('Reused cached Grammarinator seed tree corpus: %s', archive)
            continue

        with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
            trees_root = _parse_seed_archive(archive=archive, parser_grammars=parser_grammars, rule=rule, tmp_root=Path(tmp))
            rewritten = archive.with_suffix(archive.suffix + '.tmp')
            rewritten.unlink(missing_ok=True)
            _write_tree_archive(archive=rewritten, trees_root=trees_root)
            _store_seed_tree_archive(archive=archive, tree_archive=rewritten, parser_grammars=parser_grammars, rule=rule)
            rewritten.replace(archive)


def create_seed_tree_corpus_zips(*, parser_grammars: list[str], rule: str, out_dir: Path, prefix: str) -> None:
    '''Create Grammarinator tree population archives without replacing source seed archives.'''
    for archive in sorted(out_dir.glob('*_seed_corpus.zip')):
        seed_stem = archive.stem.removesuffix('_corpus')
        tree_archive = archive.with_name(f'{seed_stem}_tree_corpus{archive.suffix}')
        cached = _cached_seed_tree_archive(archive=archive, parser_grammars=parser_grammars, rule=rule)
        if cached:
            shutil.copy2(cached, tree_archive)
            LOG.info('Reused cached Grammarinator seed tree corpus: %s', tree_archive)
            continue

        with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
            trees_root = _parse_seed_archive(archive=archive, parser_grammars=parser_grammars, rule=rule, tmp_root=Path(tmp))
            tree_archive.unlink(missing_ok=True)
            _write_tree_archive(archive=tree_archive, trees_root=trees_root)
            _store_seed_tree_archive(archive=archive, tree_archive=tree_archive, parser_grammars=parser_grammars, rule=rule)


def _parse_seed_archive(*, archive: Path, parser_grammars: list[str], rule: str, tmp_root: Path) -> Path:
    input_root = tmp_root / 'input'
    trees_root = tmp_root / 'trees'
    input_root.mkdir(parents=True, exist_ok=True)
    trees_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive, 'r') as zf:
        zf.extractall(input_root)

    subprocess.check_call([
        'grammarinator-parse',
        '-g', *parser_grammars,
        '-r', rule,
        '--tree-format', 'flatbuffers',
        '-o', str(trees_root),
        str(input_root),
    ])
    return trees_root


def _write_tree_archive(*, archive: Path, trees_root: Path) -> None:
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(trees_root.rglob('*')):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(trees_root)))


def _cached_seed_tree_archive(*, archive: Path, parser_grammars: list[str], rule: str) -> Path | None:
    cfg = _seed_cache_config()
    if not cfg.get('enabled', True):
        return None
    path = _seed_cache_path(archive=archive, parser_grammars=parser_grammars, rule=rule, cfg=cfg)
    return path if path.is_file() else None


def _store_seed_tree_archive(*, archive: Path, tree_archive: Path, parser_grammars: list[str], rule: str) -> None:
    cfg = _seed_cache_config()
    if not cfg.get('enabled', True):
        return
    path = _seed_cache_path(archive=archive, parser_grammars=parser_grammars, rule=rule, cfg=cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    shutil.copy2(tree_archive, tmp)
    tmp.replace(path)
    LOG.info('Stored Grammarinator seed tree corpus cache: %s', path.name)


def _seed_cache_config() -> dict[str, Any]:
    cfg = utils.get_fuzzer_config_value('build', 'seed_cache', default={})
    if not isinstance(cfg, dict):
        raise TypeError('build.seed_cache must be a mapping')
    return cfg


def _seed_cache_path(*, archive: Path, parser_grammars: list[str], rule: str, cfg: dict[str, Any]) -> Path:
    cache_root = Path(os.environ.get('FM_FUZZER_BUILD_CACHE_DIR', '/var/cache/fuzzmeter/fuzzer-build'))
    key = _seed_cache_key(archive=archive, parser_grammars=parser_grammars, rule=rule, cfg=cfg)
    return cache_root / 'grammarinator-seeds' / f'{key}.zip'


def _seed_cache_key(*, archive: Path, parser_grammars: list[str], rule: str, cfg: dict[str, Any]) -> str:
    payload = {
        'kind': str(cfg.get('kind', 'grammarinator-parse')),
        'version': str(cfg.get('version', 1)),
        'tree_format': str(cfg.get('tree_format', 'flatbuffers')),
        'rule': rule,
        'parser_grammars': [str(path) for path in parser_grammars],
        'parser_grammar_digest': _paths_digest([Path(path) for path in parser_grammars]),
        'extra_digest': _paths_digest(_seed_cache_extra_paths(cfg)),
        'tool_digest': _grammarinator_parse_digest(),
        'seed_digest': _zip_content_digest(archive),
    }
    data = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def _seed_cache_extra_paths(cfg: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    src = Path(os.environ['SRC'])
    for item in as_list(cfg.get('extra_paths')):
        path = Path(item)
        if not path.is_absolute():
            path = src / path
        if path.is_dir():
            paths.extend(sorted(child for child in path.rglob('*') if child.is_file()))
        else:
            paths.extend(sorted(path.parent.glob(path.name)))
    return paths


def _paths_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        if not path.is_file():
            continue
        digest.update(str(path).encode('utf-8'))
        digest.update(b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()


def _zip_content_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with zipfile.ZipFile(path, 'r') as archive:
        for info in sorted((item for item in archive.infolist() if not item.is_dir()), key=lambda item: item.filename):
            digest.update(info.filename.encode('utf-8'))
            digest.update(b'\0')
            digest.update(archive.read(info))
            digest.update(b'\0')
    return digest.hexdigest()


def _grammarinator_parse_digest() -> str:
    parser = shutil.which('grammarinator-parse')
    if not parser:
        return 'missing'
    digest = hashlib.sha256()
    digest.update(Path(parser).read_bytes())
    try:
        version = subprocess.check_output(
            ['grammarinator-parse', '--version'],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
    except Exception:
        version = ''
    digest.update(version.encode('utf-8'))
    return digest.hexdigest()


def create_grammarinator_artifacts(*, mode: str, seed_prefix: str) -> tuple[Path, list[str], str]:
    '''Build Grammarinator artifacts for the selected integration mode.'''
    cfg = _build_env_cfg()
    rule = str(cfg.get('GRAMMARINATOR_RULE') or '').strip()
    generator_grammars = require_generator_grammars(cfg)
    parser_grammars = require_parser_grammars(cfg)

    out_dir = Path(os.environ['OUT'])
    include_dir = Path(os.environ['SRC']) / 'grammarinator'
    fuzz_target = os.environ['FUZZ_TARGET']
    target_name = os.environ.get('TARGET_NAME', '').strip()
    if not target_name:
        raise RuntimeError('TARGET_NAME must be set for Grammarinator build')

    run_process(out_dir=out_dir, generator_grammars=generator_grammars, rule=rule)
    run_build(
        out_dir=out_dir,
        include_dir=include_dir,
        fuzz_target=fuzz_target,
        cfg=cfg,
        mode=mode,
        extra_args=list(utils.get_fuzzer_config_value('build', 'extra_args', default=[])),
    )
    copy_decode_bin(out_dir=out_dir, target_name=target_name)
    rewrite_seed_corpus_zips(
        parser_grammars=parser_grammars,
        rule=rule,
        out_dir=out_dir,
        prefix=seed_prefix,
    )
    if mode == 'generate':
        artifact = copy_generator_bin(out_dir=out_dir, fuzz_target=fuzz_target)
    else:
        artifact = build_library_path(fuzz_target=fuzz_target, mode=mode)
    return artifact, parser_grammars, rule


def create_grammarinator_generator_artifact() -> Path:
    '''Build and copy the standalone Grammarinator blackbox generator.'''
    cfg = _build_env_cfg()
    rule = str(cfg.get('GRAMMARINATOR_RULE') or '').strip()
    generator_grammars = require_generator_grammars(cfg)
    parser_grammars = require_parser_grammars(cfg)

    out_dir = Path(os.environ['OUT'])
    include_dir = Path(os.environ['SRC']) / 'grammarinator'
    fuzz_target = os.environ['FUZZ_TARGET']
    target_name = os.environ.get('TARGET_NAME', '').strip()
    if not target_name:
        raise RuntimeError('TARGET_NAME must be set for Grammarinator build')

    run_process(out_dir=out_dir, generator_grammars=generator_grammars, rule=rule)
    run_build(
        out_dir=out_dir,
        include_dir=include_dir,
        fuzz_target=fuzz_target,
        cfg=cfg,
        mode='generate',
        extra_args=list(utils.get_fuzzer_config_value('build', 'extra_args', default=[])),
    )
    copy_decode_bin(out_dir=out_dir, target_name=target_name)
    create_seed_tree_corpus_zips(
        parser_grammars=parser_grammars,
        rule=rule,
        out_dir=out_dir,
        prefix='grammarinator_seed_',
    )
    return copy_generator_bin(out_dir=out_dir, fuzz_target=fuzz_target)


def _grammarinator_log_level() -> str:
    level = str(os.environ.get('FM_LOG_LEVEL', os.environ.get('FUZZMETER_LOG_LEVEL', 'INFO'))).strip().upper()
    return {
        'CRITICAL': 'fatal',
        'ERROR': 'error',
        'WARNING': 'warn',
        'INFO': 'info',
        'DEBUG': 'debug',
        'TRACE': 'trace',
    }.get(level, 'info')


def _is_verbose_logging() -> bool:
    return _grammarinator_log_level() in {'debug', 'trace'}
