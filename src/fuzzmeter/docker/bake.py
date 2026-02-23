# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Generate Docker Buildx bake definitions for fuzzmeter campaign images.'''

from __future__ import annotations

import json
import os
import re
import shlex

from pathlib import Path, PurePosixPath

import yaml

from ..config import CampaignCase

INTERNAL_BUILD_FUZZERS = ["coverage", "asan"]
ENTRY_BUILDER_MEMORY_LIMIT = "4g"
DEFAULT_DOCKER_PLATFORM = "linux/amd64"
PY_FUZZER_IMPORT_RE = re.compile(r"(?:from|import)\s+fuzzers\.([A-Za-z0-9_-]+)")
DOCKER_ENV_RE = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


def _hcl_str_list(items: list[str]) -> str:
    inner = ", ".join([f'"{x}"' for x in items])
    return f"[{inner}]"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _hcl_block(name: str, lines: list[str]) -> str:
    body = "\n".join(f"  {line}" if line else "" for line in lines)
    return f'target "{name}" {{\n{body}\n}}'


def _fuzzer_parent(repo_root: Path, fuzzer: str) -> str | None:
    data = _fuzzer_config(repo_root, fuzzer)
    if not isinstance(data, dict):
        return None
    parent = data.get("parent")
    return str(parent).strip() if parent else None


def _fuzzer_config(repo_root: Path, fuzzer: str) -> dict[str, object]:
    data: dict[str, object] = {}
    root = repo_root / "fuzzers" / fuzzer
    for path in (root / "build" / "build.yaml", root / "run" / "run.yaml"):
        if not path.is_file():
            continue
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data.update(loaded)
    return data


def _fuzzers_with_parents(repo_root: Path, fuzzers: list[str], extra: tuple[str, ...] | list[str] = ()) -> list[str]:
    seen: list[str] = []

    def add(name: str) -> None:
        if name in seen:
            return
        parent = _fuzzer_parent(repo_root, name)
        if parent:
            add(parent)
        seen.append(name)

    for name in [*fuzzers, *extra]:
        add(name)
    return seen


def _has_fuzzer_runner_dockerfile(repo_root: Path, fuzzer: str) -> bool:
    return (repo_root / "fuzzers" / fuzzer / "run" / "Dockerfile").is_file()


def _runner_parent_target(repo_root: Path, fuzzer: str) -> str:
    current = _fuzzer_parent(repo_root, fuzzer)
    while current:
        if _has_fuzzer_runner_dockerfile(repo_root, current):
            return f'fuzzer_runner_{_escape(current)}'
        current = _fuzzer_parent(repo_root, current)
    return 'runtime_base'


def _runner_base_target(repo_root: Path, fuzzer: str) -> str:
    if _has_fuzzer_runner_dockerfile(repo_root, fuzzer):
        return f"fuzzer_runner_{_escape(fuzzer)}"
    return _runner_parent_target(repo_root, fuzzer)


def _direct_fuzzer_imports(repo_root: Path, fuzzer: str) -> list[str]:
    fuzzer_dir = repo_root / "fuzzers" / fuzzer
    if not fuzzer_dir.is_dir():
        return []
    imports: set[str] = set()
    py_paths = [
        *fuzzer_dir.glob("*.py"),
        *(fuzzer_dir / "build").glob("*.py"),
        *(fuzzer_dir / "run").glob("*.py"),
    ]
    for path in py_paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in PY_FUZZER_IMPORT_RE.finditer(text):
            imported = match.group(1)
            if imported != fuzzer and (repo_root / "fuzzers" / imported).is_dir():
                imports.add(imported)
    return sorted(imports)


def _fuzzer_source_dirs(repo_root: Path, fuzzer: str) -> list[str]:
    seen: list[str] = []

    def add(name: str) -> None:
        if name in seen:
            return
        parent = _fuzzer_parent(repo_root, name)
        if parent:
            add(parent)
        seen.append(name)
        for imported in _direct_fuzzer_imports(repo_root, name):
            add(imported)

    add(fuzzer)
    return seen


def fuzzer_source_dirs(repo_root: Path, fuzzer: str) -> list[str]:
    '''Return fuzzer source directories needed by a fuzzer implementation.'''
    return _fuzzer_source_dirs(repo_root, fuzzer)


def _benchmark_workdir(repo_root: Path, benchmark: str) -> str:
    path = repo_root / 'targets' / benchmark / 'Dockerfile'
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
        f'  FM_LOG_LEVEL  = "{_escape(os.environ.get("FM_LOG_LEVEL", os.environ.get("FUZZMETER_LOG_LEVEL", "INFO")))}"',
    ]
    if runner_base_image:
        lines.append(f'  RUNNER_BASE_IMAGE = "{runner_base_image}"')
    lines.append('}')
    return lines


def generate_run_bake_hcl(
    *,
    repo_root: Path,
    entries: list[CampaignCase],
    memory_limit: str | None = None,
    fuzzer_build_sources: Path | None = None,
    fuzzer_run_sources: Path | None = None,
) -> str:
    campaign_memory_limit = memory_limit or ENTRY_BUILDER_MEMORY_LIMIT
    hcl_parts: list[str] = []
    group_targets: list[str] = []
    docker_output_line = 'output = ["type=docker"]'

    entry_fuzzers = sorted({entry.fuzzer_base for entry in entries})
    campaign_fuzzers = _fuzzers_with_parents(repo_root, entry_fuzzers)
    build_fuzzers = _fuzzers_with_parents(repo_root, entry_fuzzers, INTERNAL_BUILD_FUZZERS)
    benchmark_workdirs = {
        benchmark: _escape(_benchmark_workdir(repo_root, benchmark))
        for benchmark in sorted({entry.benchmark for entry in entries})
    }

    base_targets = [
        ('runtime_tools', 'docker/runtime-tools.Dockerfile', 'fuzzmeter/runtime-tools:dev', [], []),
        (
            'build_base',
            'docker/build-base.Dockerfile',
            'fuzzmeter/build-base:dev',
            [('runtime_tools', 'runtime_tools')],
            ['runtime_tools'],
        ),
        (
            'runtime_base',
            'docker/runtime-base.Dockerfile',
            'fuzzmeter/runtime-base:dev',
            [('build_base', 'build_base')],
            ['build_base'],
        ),
        (
            'clang_base',
            'docker/clang-base.Dockerfile',
            'fuzzmeter/clang-base:dev',
            [('runtime_tools', 'runtime_tools')],
            ['runtime_tools'],
        ),
        (
            'benchmark_base',
            'docker/benchmark-base.Dockerfile',
            'fuzzmeter/benchmark-base:dev',
            [('parent_image', 'clang_base')],
            ['clang_base'],
        ),
    ]
    for name, dockerfile, tag, contexts, depends_on in base_targets:
        lines = [
            'context    = "."',
            f'dockerfile = "{dockerfile}"',
            f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
            f'tags       = ["{tag}"]',
        ]
        if contexts:
            lines.extend(['contexts = {', *[f'  {key} = "target:{target}"' for key, target in contexts], '}'])
        if depends_on:
            lines.append(f'depends_on = {_hcl_str_list(depends_on)}')
        lines.append(docker_output_line)
        hcl_parts.append(_hcl_block(name, lines))
        group_targets.append(name)

    for fuzzer in build_fuzzers:
        escaped_fuzzer = _escape(fuzzer)
        parent = _fuzzer_parent(repo_root, fuzzer)
        builder_parent = f"fuzzer_builder_{_escape(parent)}" if parent else "clang_base"
        builder_depends = [f'depends_on = ["{builder_parent}"]']
        hcl_parts.append(
            _hcl_block(
                f"fuzzer_builder_{escaped_fuzzer}",
                [
                    f'context    = "./fuzzers/{escaped_fuzzer}/build"',
                    'dockerfile = "Dockerfile"',
                    f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
                    f'tags       = ["fuzzmeter/fuzzer-builder-{escaped_fuzzer}:dev"]',
                    "contexts = {",
                    f'  parent_image = "target:{builder_parent}"',
                    "}",
                    *builder_depends,
                    docker_output_line,
                ],
            )
        )
        group_targets.append(f"fuzzer_builder_{escaped_fuzzer}")

    for fuzzer in campaign_fuzzers:
        if not _has_fuzzer_runner_dockerfile(repo_root, fuzzer):
            continue
        escaped_fuzzer = _escape(fuzzer)
        runner_parent = _runner_parent_target(repo_root, fuzzer)
        hcl_parts.append(
            _hcl_block(
                f"fuzzer_runner_{escaped_fuzzer}",
                [
                    f'context    = "./fuzzers/{escaped_fuzzer}/run"',
                    'dockerfile = "Dockerfile"',
                    f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
                    f'tags       = ["fuzzmeter/fuzzer-runner-{escaped_fuzzer}:dev"]',
                    "contexts = {",
                    f'  parent_image = "target:{runner_parent}"',
                    "}",
                    f'depends_on = ["{runner_parent}"]',
                    docker_output_line,
                ],
            )
        )
        group_targets.append(f"fuzzer_runner_{escaped_fuzzer}")

    seen_benchmarks: set[str] = set()
    for entry in entries:
        if entry.benchmark in seen_benchmarks:
            continue
        seen_benchmarks.add(entry.benchmark)
        escaped_benchmark = _escape(entry.benchmark)
        benchmark_name = f"benchmark_{escaped_benchmark}"
        hcl_parts.append(
            _hcl_block(
                benchmark_name,
                [
                    f'context    = "targets/{escaped_benchmark}"',
                    'dockerfile = "Dockerfile"',
                    f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
                    f'tags       = ["fuzzmeter/benchmark-{escaped_benchmark}:dev"]',
                    "contexts = {",
                    '  parent_image = "target:benchmark_base"',
                    "}",
                    'depends_on = ["benchmark_base"]',
                    docker_output_line,
                ],
            )
        )
        group_targets.append(benchmark_name)

    for entry in entries:
        escaped_fuzzer = _escape(entry.fuzzer_name)
        escaped_fuzzer_base = _escape(entry.fuzzer_base)
        escaped_benchmark = _escape(entry.benchmark)
        escaped_target = _escape(entry.fuzz_target)
        escaped_target_id = _escape(entry.target_id)
        benchmark_workdir = benchmark_workdirs[entry.benchmark]
        fuzzer_source_dirs = _fuzzer_source_dirs(repo_root, entry.fuzzer_base)
        runner_base = _runner_base_target(repo_root, entry.fuzzer_base)
        build_config_json = json.dumps(entry.build_config, sort_keys=True)
        args_lines = _entry_args(
            fuzzer=escaped_fuzzer_base,
            build_config_json=build_config_json,
            fuzzer_source_dirs=fuzzer_source_dirs,
            benchmark=escaped_benchmark,
            benchmark_workdir=benchmark_workdir,
            target_name=escaped_target,
        )
        build_depends = (
            f'depends_on = ["fuzzer_builder_{escaped_fuzzer_base}", '
            f'"benchmark_{escaped_benchmark}", "build_base"]'
        )

        campaign_build_name = f"campaign_build_{escaped_fuzzer}_{escaped_target_id}"
        hcl_parts.append(
            _hcl_block(
                campaign_build_name,
                [
                    'context    = "."',
                    'dockerfile = "docker/campaign.Dockerfile"',
                    'target     = "campaign_builder"',
                    f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
                    f'memory     = "{_escape(campaign_memory_limit)}"',
                    f'tags       = ["fuzzmeter/campaign-builder-{escaped_fuzzer}-{escaped_target_id}:dev"]',
                    docker_output_line,
                    'contexts = {',
                    f'  builder = "target:fuzzer_builder_{escaped_fuzzer_base}"',
                    f'  benchmark = "target:benchmark_{escaped_benchmark}"',
                    '  build_base = "target:build_base"',
                    f'  fuzzer_build_sources = "{_escape(str(fuzzer_build_sources or repo_root / "fuzzers"))}"',
                    '}',
                    *args_lines,
                    build_depends,
                ],
            )
        )
        group_targets.append(campaign_build_name)

        runner_name = f"runner_{escaped_fuzzer}_{escaped_target_id}"
        runner_depends = [campaign_build_name, 'runtime_base']
        if runner_base != 'runtime_base':
            runner_depends.append(runner_base)
        runner_args_lines = _entry_args(
            fuzzer=escaped_fuzzer_base,
            build_config_json=build_config_json,
            fuzzer_source_dirs=fuzzer_source_dirs,
            benchmark=escaped_benchmark,
            benchmark_workdir=benchmark_workdir,
            target_name=escaped_target,
            runner_base_image='runner_base',
        )
        hcl_parts.append(
            _hcl_block(
                runner_name,
                [
                    'context    = "."',
                    'dockerfile = "docker/campaign.Dockerfile"',
                    'target     = "runner"',
                    f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
                    f'memory     = "{_escape(campaign_memory_limit)}"',
                    f'tags       = ["fuzzmeter/runner-{escaped_fuzzer}-{escaped_target_id}:dev"]',
                    docker_output_line,
                    'contexts = {',
                    f'  builder = "target:fuzzer_builder_{escaped_fuzzer_base}"',
                    f'  benchmark = "target:benchmark_{escaped_benchmark}"',
                    '  build_base = "target:build_base"',
                    '  runtime_base = "target:runtime_base"',
                    f'  runner_base = "target:{runner_base}"',
                    f'  fuzzer_build_sources = "{_escape(str(fuzzer_build_sources or repo_root / "fuzzers"))}"',
                    f'  fuzzer_run_sources = "{_escape(str(fuzzer_run_sources or repo_root / "fuzzers"))}"',
                    '}',
                    *runner_args_lines,
                    f'depends_on = {_hcl_str_list(runner_depends)}',
                ],
            )
        )
        group_targets.append(runner_name)

    target_entries = {
        entry.target_id: entry
        for entry in entries
    }

    for internal_fuzzer, stage_name, image_prefix in (
        ("coverage", "coverage_runner", "coverage-runner"),
        ("asan", "crash_runner", "asan-runner"),
    ):
        internal_esc = _escape(internal_fuzzer)
        for entry in target_entries.values():
            escaped_benchmark = _escape(entry.benchmark)
            escaped_target_id = _escape(entry.target_id)
            fuzzer_source_dirs = _fuzzer_source_dirs(repo_root, internal_fuzzer)
            args_lines = _entry_args(
                fuzzer=internal_esc,
                build_config_json="{}",
                fuzzer_source_dirs=fuzzer_source_dirs,
                benchmark=escaped_benchmark,
                benchmark_workdir=benchmark_workdirs[entry.benchmark],
                target_name=_escape(entry.fuzz_target),
            )

            final_name = f"{stage_name}_{escaped_target_id}"
            hcl_parts.append(
                _hcl_block(
                    final_name,
                    [
                        'context    = "."',
                        'dockerfile = "docker/campaign.Dockerfile"',
                        f'target     = "{stage_name}"',
                        f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
                        f'memory     = "{_escape(campaign_memory_limit)}"',
                        f'tags       = ["fuzzmeter/{image_prefix}-{escaped_target_id}:dev"]',
                        docker_output_line,
                        'contexts = {',
                        f'  builder = "target:fuzzer_builder_{internal_esc}"',
                        f'  benchmark = "target:benchmark_{escaped_benchmark}"',
                        '  build_base = "target:build_base"',
                        '  runtime_base = "target:runtime_base"',
                        '  clang_base = "target:clang_base"',
                        f'  fuzzer_build_sources = "{_escape(str(fuzzer_build_sources or repo_root / "fuzzers"))}"',
                        '}',
                        *args_lines,
                        'depends_on = ["clang_base", "runtime_base"]',
                    ],
                )
            )
            group_targets.append(final_name)

    group_block = "\n".join([
        'group "fm" {',
        f"  targets = {_hcl_str_list(group_targets)}",
        "}",
    ])
    hcl_parts.insert(0, group_block)
    return "\n\n".join(hcl_parts) + "\n"
