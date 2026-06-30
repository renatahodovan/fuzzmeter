# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Generate Docker Buildx bake definitions for fuzzmeter campaign images."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex

import yaml

from ..config import CampaignCase

INSTRUMENTATION_PROFILES = (
    ('coverage', 'coverage_runner', 'coverage-runner'),
    ('asan', 'crash_runner', 'asan-runner'),
)
ENTRY_BUILDER_MEMORY_LIMIT = '4g'
DEFAULT_DOCKER_PLATFORM = 'linux/amd64'
DOCKER_ENV_RE = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


def _hcl_str_list(items: list[str]) -> str:
    inner = ', '.join([f'"{x}"' for x in items])
    return f'[{inner}]'


def _escape(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')


def _context_path(contexts: Mapping[str, Path], key: str, label: str) -> str:
    try:
        return _escape(str(Path(contexts[key]).resolve()))
    except KeyError as exc:
        raise ValueError(f'Missing {label} context for {key}') from exc


def _hcl_block(name: str, lines: list[str]) -> str:
    body = '\n'.join(f'  {line}' if line else '' for line in lines)
    return f'target "{name}" {{\n{body}\n}}'


def _fuzzer_parent(fuzzers_root: Path, fuzzer: str) -> str | None:
    data = _fuzzer_config(fuzzers_root, fuzzer)
    if not isinstance(data, dict):
        return None
    parent = data.get('parent')
    return str(parent).strip() if parent else None


def _fuzzer_config(fuzzers_root: Path, fuzzer: str) -> dict[str, object]:
    data: dict[str, object] = {}
    root = fuzzers_root / fuzzer
    for path in (root / 'build' / 'build.yaml', root / 'run' / 'run.yaml'):
        if not path.is_file():
            continue
        loaded = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        if isinstance(loaded, dict):
            data.update(loaded)
    return data


def _fuzzers_with_parents(fuzzers_root: Path, fuzzers: list[str]) -> list[str]:
    seen: list[str] = []

    def add(name: str) -> None:
        if name in seen:
            return
        parent = _fuzzer_parent(fuzzers_root, name)
        if parent:
            add(parent)
        seen.append(name)

    for name in fuzzers:
        add(name)
    return seen


def _has_fuzzer_runner_dockerfile(fuzzers_root: Path, fuzzer: str) -> bool:
    return (fuzzers_root / fuzzer / 'run' / 'Dockerfile').is_file()


def _runner_parent_target(fuzzers_root: Path, fuzzer: str) -> str:
    current = _fuzzer_parent(fuzzers_root, fuzzer)
    while current:
        if _has_fuzzer_runner_dockerfile(fuzzers_root, current):
            return f'fuzzer_runner_{current}'
        current = _fuzzer_parent(fuzzers_root, current)
    return 'runtime_base'


def _runner_base_target(fuzzers_root: Path, fuzzer: str) -> str:
    if _has_fuzzer_runner_dockerfile(fuzzers_root, fuzzer):
        return f'fuzzer_runner_{fuzzer}'
    return _runner_parent_target(fuzzers_root, fuzzer)


def _fuzzer_source_dependencies(fuzzers_root: Path, fuzzer: str) -> list[str]:
    config = _fuzzer_config(fuzzers_root, fuzzer)
    dependencies = config.get('source_dependencies') or []
    if isinstance(dependencies, str):
        dependencies = [dependencies]
    if not isinstance(dependencies, list):
        return []
    return sorted(
        {
            str(dependency).strip()
            for dependency in dependencies
            if str(dependency).strip() and (fuzzers_root / str(dependency).strip()).is_dir()
        }
    )


def _fuzzer_source_dirs(fuzzers_root: Path, fuzzer: str) -> list[str]:
    seen: list[str] = []

    def add(name: str) -> None:
        if name in seen:
            return
        parent = _fuzzer_parent(fuzzers_root, name)
        if parent:
            add(parent)
        seen.append(name)
        for dependency in _fuzzer_source_dependencies(fuzzers_root, name):
            add(dependency)

    add(fuzzer)
    return seen


def fuzzer_source_dirs(fuzzers_root: Path, fuzzer: str) -> list[str]:
    """Return fuzzer source directories needed by a fuzzer implementation."""
    return _fuzzer_source_dirs(fuzzers_root, fuzzer)


def _benchmark_workdir(targets_root: Path, benchmark: str) -> str:
    path = targets_root / benchmark / 'Dockerfile'
    env = {'OUT': '/out', 'SRC': '/src', 'WORK': '/work'}
    workdir = env['SRC']
    if not path.is_file():
        return workdir

    for raw_line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if not line:
            continue
        instruction, _, value = line.partition(' ')
        instruction = instruction.upper()
        value = value.strip()
        if instruction == 'ENV':
            _update_docker_env(env, value)
        elif instruction == 'WORKDIR':
            workdir = _resolve_workdir(value, env, workdir)
    return workdir


def _update_docker_env(env: dict[str, str], value: str) -> None:
    try:
        parts = shlex.split(value)
    except ValueError:
        return
    if len(parts) == 2 and '=' not in parts[0]:
        env[parts[0]] = _expand_docker_env(parts[1], env)
        return
    for part in parts:
        key, sep, raw_value = part.partition('=')
        if sep and key:
            env[key] = _expand_docker_env(raw_value, env)


def _resolve_workdir(value: str, env: dict[str, str], current: str) -> str:
    try:
        parts = shlex.split(value)
    except ValueError:
        parts = []
    raw_workdir = parts[0] if parts else value
    workdir = _expand_docker_env(raw_workdir, env)
    if not workdir.startswith('/'):
        workdir = str(PurePosixPath(current) / workdir)
    return str(PurePosixPath(workdir))


def _expand_docker_env(value: str, env: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return env.get(match.group(1) or match.group(2) or '', match.group(0))

    return DOCKER_ENV_RE.sub(replace, value)


def _entry_args(
    *,
    fuzzer: str,
    build_config_json: str,
    fuzzer_source_dirs: list[str],
    benchmark: str,
    benchmark_workdir: str,
    target_name: str,
    runner_base_image: str | None = None,
) -> list[str]:
    lines = [
        'args = {',
        '  BUILDER_IMAGE = "builder"',
        '  BENCHMARK_IMAGE = "benchmark"',
        '  BUILD_BASE_IMAGE = "build_base"',
        '  RUNTIME_BASE_IMAGE = "runtime_base"',
        '  CLANG_BASE_IMAGE = "clang_base"',
        f'  FUZZER        = "{fuzzer}"',
        f'  FUZZER_BUILD_CONFIG_JSON = "{_escape(build_config_json)}"',
        f'  FUZZER_SOURCE_DIRS = "{_escape(" ".join(fuzzer_source_dirs))}"',
        f'  BENCHMARK     = "{benchmark}"',
        f'  BENCHMARK_WORKDIR = "{benchmark_workdir}"',
        f'  TARGET_NAME   = "{target_name}"',
        f'  FM_LOG_LEVEL  = "{_escape(os.environ.get("FM_LOG_LEVEL", "INFO"))}"',
    ]
    if runner_base_image:
        lines.append(f'  RUNNER_BASE_IMAGE = "{runner_base_image}"')
    lines.append('}')
    return lines


def generate_run_bake_hcl(
    *,
    fuzzers_root: Path,
    targets_root: Path,
    entries: list[CampaignCase],
    fuzzer_build_sources: Mapping[str, Path],
    fuzzer_run_sources: Mapping[str, Path],
    instrumentation_build_sources: Mapping[str, Path],
    docker_resources: Path,
    entrypoint_resources: Path,
    fuzzmeter_resources: Path,
    memory_limit: str | None = None,
) -> str:
    campaign_memory_limit = memory_limit or ENTRY_BUILDER_MEMORY_LIMIT
    hcl_parts: list[str] = []
    group_targets: list[str] = []
    docker_output_line = 'output = ["type=docker"]'

    fuzzers_root = Path(fuzzers_root).resolve()
    targets_root = Path(targets_root).resolve()
    docker_resources_arg = _escape(str(Path(docker_resources).resolve()))
    entrypoint_resources_arg = _escape(str(Path(entrypoint_resources).resolve()))
    fuzzmeter_resources_arg = _escape(str(Path(fuzzmeter_resources).resolve()))
    campaign_dockerfile = f'{docker_resources_arg}/campaign.Dockerfile'

    entry_fuzzers = sorted({entry.fuzzer_base for entry in entries})
    campaign_fuzzers = _fuzzers_with_parents(fuzzers_root, entry_fuzzers)
    build_fuzzers = list(campaign_fuzzers)
    benchmark_workdirs = {
        benchmark: _escape(_benchmark_workdir(targets_root, benchmark))
        for benchmark in sorted({entry.benchmark for entry in entries})
    }

    base_targets = [
        ('runtime_tools', 'runtime-tools.Dockerfile', [], []),
        (
            'build_base',
            'build-base.Dockerfile',
            [('runtime_tools', 'runtime_tools')],
            ['runtime_tools'],
        ),
        (
            'runtime_base',
            'runtime-base.Dockerfile',
            [('build_base', 'build_base')],
            ['build_base'],
        ),
        (
            'clang_base',
            'clang-base.Dockerfile',
            [('runtime_tools', 'runtime_tools')],
            ['runtime_tools'],
        ),
        (
            'benchmark_base',
            'benchmark-base.Dockerfile',
            [('parent_image', 'clang_base')],
            ['clang_base'],
        ),
        (
            'instrumentation_runtime',
            'instrumentation-runtime.Dockerfile',
            [('runtime_base', 'runtime_base')],
            ['runtime_base'],
        ),
    ]
    for name, dockerfile, base_contexts, depends_on in base_targets:
        contexts = list(base_contexts)
        lines = [
            f'context    = "{docker_resources_arg}"',
            f'dockerfile = "{docker_resources_arg}/{dockerfile}"',
            f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
        ]
        if name in {'build_base', 'runtime_base'}:
            contexts.append(('entrypoints', entrypoint_resources_arg))
        if name == 'build_base':
            contexts = [*contexts, ('fuzzmeter_resources', fuzzmeter_resources_arg)]
        if contexts:
            lines.extend(
                [
                    'contexts = {',
                    *[
                        f'  {key} = "{target}"' if '/' in target else f'  {key} = "target:{target}"'
                        for key, target in contexts
                    ],
                    '}',
                ]
            )
        if depends_on:
            lines.append(f'depends_on = {_hcl_str_list(depends_on)}')
        hcl_parts.append(_hcl_block(name, lines))

    for fuzzer in build_fuzzers:
        parent = _fuzzer_parent(fuzzers_root, fuzzer)
        builder_parent = f'fuzzer_builder_{parent}' if parent else 'clang_base'
        builder_depends = [f'depends_on = ["{builder_parent}"]']
        hcl_parts.append(
            _hcl_block(
                f'fuzzer_builder_{fuzzer}',
                [
                    f'context    = "{_escape(str(fuzzers_root / fuzzer / "build"))}"',
                    'dockerfile = "Dockerfile"',
                    f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
                    'contexts = {',
                    f'  parent_image = "target:{builder_parent}"',
                    '}',
                    *builder_depends,
                ],
            )
        )

    for profile, _, _ in INSTRUMENTATION_PROFILES:
        builder_name = f'instrumentation_builder_{profile}'
        instrumentation_build_sources_arg = _context_path(
            instrumentation_build_sources,
            profile,
            'instrumentation build',
        )
        hcl_parts.append(
            _hcl_block(
                builder_name,
                [
                    f'context    = "{instrumentation_build_sources_arg}/{profile}"',
                    'dockerfile = "Dockerfile"',
                    f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
                    'contexts = {',
                    '  parent_image = "target:clang_base"',
                    '}',
                    'depends_on = ["clang_base"]',
                ],
            )
        )

    for fuzzer in campaign_fuzzers:
        if not _has_fuzzer_runner_dockerfile(fuzzers_root, fuzzer):
            continue
        runner_parent = _runner_parent_target(fuzzers_root, fuzzer)
        hcl_parts.append(
            _hcl_block(
                f'fuzzer_runner_{fuzzer}',
                [
                    f'context    = "{_escape(str(fuzzers_root / fuzzer / "run"))}"',
                    'dockerfile = "Dockerfile"',
                    f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
                    'contexts = {',
                    f'  parent_image = "target:{runner_parent}"',
                    '}',
                    f'depends_on = ["{runner_parent}"]',
                ],
            )
        )

    seen_benchmarks: set[str] = set()
    for entry in entries:
        if entry.benchmark in seen_benchmarks:
            continue
        seen_benchmarks.add(entry.benchmark)
        benchmark_name = f'benchmark_{entry.benchmark}'
        hcl_parts.append(
            _hcl_block(
                benchmark_name,
                [
                    f'context    = "{_escape(str(targets_root / entry.benchmark))}"',
                    'dockerfile = "Dockerfile"',
                    f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
                    'contexts = {',
                    '  parent_image = "target:benchmark_base"',
                    '}',
                    'depends_on = ["benchmark_base"]',
                ],
            )
        )

    for entry in entries:
        benchmark_workdir = benchmark_workdirs[entry.benchmark]
        fuzzer_source_dirs = _fuzzer_source_dirs(fuzzers_root, entry.fuzzer_base)
        runner_base = _runner_base_target(fuzzers_root, entry.fuzzer_base)
        build_config_json = json.dumps(entry.build_config, sort_keys=True)
        fuzzer_build_sources_arg = _context_path(fuzzer_build_sources, entry.fuzzer_base, 'fuzzer build')
        fuzzer_run_sources_arg = _context_path(fuzzer_run_sources, entry.fuzzer_base, 'fuzzer run')

        runner_name = f'runner_{entry.fuzzer_name}_{entry.target_id}'
        runner_depends = [
            f'fuzzer_builder_{entry.fuzzer_base}',
            f'benchmark_{entry.benchmark}',
            'build_base',
            'runtime_base',
        ]
        if runner_base != 'runtime_base':
            runner_depends.append(runner_base)
        runner_args_lines = _entry_args(
            fuzzer=entry.fuzzer_base,
            build_config_json=build_config_json,
            fuzzer_source_dirs=fuzzer_source_dirs,
            benchmark=entry.benchmark,
            benchmark_workdir=benchmark_workdir,
            target_name=entry.fuzz_target,
            runner_base_image='runner_base',
        )
        hcl_parts.append(
            _hcl_block(
                runner_name,
                [
                    f'context    = "{docker_resources_arg}"',
                    f'dockerfile = "{campaign_dockerfile}"',
                    'target     = "runner"',
                    f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
                    f'memory     = "{_escape(campaign_memory_limit)}"',
                    f'tags       = ["fuzzmeter/runner-{entry.fuzzer_name}-{entry.target_id}:dev"]',
                    docker_output_line,
                    'contexts = {',
                    f'  builder = "target:fuzzer_builder_{entry.fuzzer_base}"',
                    f'  benchmark = "target:benchmark_{entry.benchmark}"',
                    '  build_base = "target:build_base"',
                    '  runtime_base = "target:runtime_base"',
                    f'  runner_base = "target:{runner_base}"',
                    f'  fuzzer_build_sources = "{fuzzer_build_sources_arg}"',
                    f'  fuzzer_run_sources = "{fuzzer_run_sources_arg}"',
                    '}',
                    *runner_args_lines,
                    f'depends_on = {_hcl_str_list(runner_depends)}',
                ],
            )
        )
        group_targets.append(runner_name)

    target_entries = {entry.target_id: entry for entry in entries}

    for internal_fuzzer, stage_name, image_prefix in INSTRUMENTATION_PROFILES:
        for entry in target_entries.values():
            instrumentation_builder = f'instrumentation_builder_{internal_fuzzer}'
            instrumentation_build_sources_arg = _context_path(
                instrumentation_build_sources,
                internal_fuzzer,
                'instrumentation build',
            )
            instrumentation_depends = [
                instrumentation_builder,
                f'benchmark_{entry.benchmark}',
                'build_base',
                'runtime_base',
                'instrumentation_runtime',
            ]
            args_lines = _entry_args(
                fuzzer=internal_fuzzer,
                build_config_json='{}',
                fuzzer_source_dirs=[internal_fuzzer],
                benchmark=entry.benchmark,
                benchmark_workdir=benchmark_workdirs[entry.benchmark],
                target_name=entry.fuzz_target,
            )

            final_name = f'{stage_name}_{entry.target_id}'
            hcl_parts.append(
                _hcl_block(
                    final_name,
                    [
                        f'context    = "{docker_resources_arg}"',
                        f'dockerfile = "{campaign_dockerfile}"',
                        f'target     = "{stage_name}"',
                        f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
                        f'memory     = "{_escape(campaign_memory_limit)}"',
                        f'tags       = ["fuzzmeter/{image_prefix}-{entry.target_id}:dev"]',
                        docker_output_line,
                        'contexts = {',
                        f'  builder = "target:instrumentation_builder_{internal_fuzzer}"',
                        f'  benchmark = "target:benchmark_{entry.benchmark}"',
                        '  build_base = "target:build_base"',
                        '  runtime_base = "target:runtime_base"',
                        '  instrumentation_runtime = "target:instrumentation_runtime"',
                        f'  fuzzer_build_sources = "{instrumentation_build_sources_arg}"',
                        '}',
                        *args_lines,
                        f'depends_on = {_hcl_str_list(instrumentation_depends)}',
                    ],
                )
            )
            group_targets.append(final_name)

    group_block = '\n'.join(
        [
            'group "fm" {',
            f'  targets = {_hcl_str_list(group_targets)}',
            '}',
        ]
    )
    hcl_parts.insert(0, group_block)
    return '\n\n'.join(hcl_parts) + '\n'
