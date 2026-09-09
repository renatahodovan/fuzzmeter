# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Generate Docker Buildx bake definitions for fuzzmeter campaign images."""

from __future__ import annotations

import json
import os

from collections.abc import Mapping, Sequence
from pathlib import Path

from ..config import CampaignCase
from ..config.models import Fuzzer

INSTRUMENTATION_PROFILES = (
    ('coverage', 'coverage_runner'),
    ('asan', 'crash_runner'),
)
ENTRY_BUILDER_MEMORY_LIMIT = '4g'
DEFAULT_DOCKER_PLATFORM = 'linux/amd64'
LOCAL_REPO_BUILD_ARG = 'FM_LOCAL_REPO'


def _hcl_str_list(items: list[str]) -> str:
    return '[' + ', '.join(f'"{item}"' for item in items) + ']'


def _escape(value: str | Path) -> str:
    return str(value).replace('\\', '\\\\').replace('"', '\\"')


def _hcl_block(name: str, lines: list[str]) -> str:
    body = '\n'.join(f'  {line}' if line else '' for line in lines)
    return f'target "{name}" {{\n{body}\n}}'


def _image_block(name: str, *, context: str, dockerfile: str, parent: str, args: Sequence[str] = ()) -> str:
    """Render a target built from a single parent target."""
    return _hcl_block(name, [
        f'context    = "{context}"',
        f'dockerfile = "{dockerfile}"',
        f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
        'contexts = {',
        f'  parent_image = "target:{parent}"',
        '}',
        *args,
        f'depends_on = ["{parent}"]',
    ])


def _runner_target(fuzzers: Sequence[Fuzzer]) -> str:
    """Return the first runner image in the chain, or the plain runtime base."""
    return next((fuzzer.runner_image for fuzzer in fuzzers if fuzzer.runner_image), 'runtime_base')


def _entry_args(
    *,
    fuzzer: str,
    build_config_json: str,
    fuzzer_source_dirs: list[str],
    benchmark: str,
    benchmark_workdir: str,
    target_name: str,
    build_compile_jobs: int = 1,
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
        f'  FUZZER_SOURCE_DIRS = "{" ".join(fuzzer_source_dirs)}"',
        f'  BENCHMARK     = "{benchmark}"',
        f'  BENCHMARK_WORKDIR = "{benchmark_workdir}"',
        f'  TARGET_NAME   = "{target_name}"',
        f'  BUILD_COMPILE_JOBS = "{build_compile_jobs}"',
        f'  FM_LOG_LEVEL  = "{_escape(os.environ.get("FM_LOG_LEVEL", "INFO"))}"',
    ]
    if runner_base_image:
        lines.append(f'  RUNNER_BASE_IMAGE = "{runner_base_image}"')
    lines.append('}')
    return lines


BASE_TARGETS = [
    ('runtime_tools', 'runtime-tools.Dockerfile', [], []),
    ('build_base', 'build-base.Dockerfile', [('runtime_tools', 'runtime_tools')], ['runtime_tools']),
    ('runtime_base', 'runtime-base.Dockerfile', [('build_base', 'build_base')], ['build_base']),
    ('clang_base', 'clang-base.Dockerfile', [('runtime_tools', 'runtime_tools')], ['runtime_tools']),
    ('benchmark_base', 'benchmark-base.Dockerfile', [('parent_image', 'clang_base')], ['clang_base']),
    ('instrumentation_runtime', 'instrumentation-runtime.Dockerfile', [('runtime_base', 'runtime_base')], ['runtime_base']),
]


def generate_run_bake_hcl(
    *,
    campaign_cases: list[CampaignCase],
    fuzzer_build_sources: Mapping[str, Path],
    fuzzer_run_sources: Mapping[str, Path],
    instrumentation_build_sources: Mapping[str, Path],
    docker_resources: Path,
    entrypoint_resources: Path,
    fuzzmeter_resources: Path,
    memory_limit: str | None,
    build_compile_jobs: int = 1,
) -> str:
    benchmarks = {case.fuzz_target.benchmark.name: case.fuzz_target.benchmark for case in campaign_cases}

    docker_resources_arg = _escape(docker_resources)
    entrypoint_resources_arg = _escape(entrypoint_resources)
    fuzzmeter_resources_arg = _escape(fuzzmeter_resources)
    campaign_dockerfile = f'{docker_resources_arg}/campaign.Dockerfile'
    extra_base_contexts = {
        'build_base': [('entrypoints', entrypoint_resources_arg), ('fuzzmeter_resources', fuzzmeter_resources_arg)],
        'runtime_base': [('entrypoints', entrypoint_resources_arg)],
    }

    hcl_parts: list[str] = []
    for name, dockerfile, base_contexts, depends_on in BASE_TARGETS:
        lines = [
            f'context    = "{docker_resources_arg}"',
            f'dockerfile = "{docker_resources_arg}/{dockerfile}"',
            f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
        ]

        contexts = [
            *[(key, f'target:{parent}') for key, parent in base_contexts],
            *extra_base_contexts.get(name, ()),
        ]
        if contexts:
            lines.extend(['contexts = {', *[f'  {key} = "{value}"' for key, value in contexts], '}'])
        if depends_on:
            lines.append(f'depends_on = {_hcl_str_list(depends_on)}')
        hcl_parts.append(_hcl_block(name, lines))

    fuzzers = list({
        fuzzer.name: fuzzer for case in campaign_cases for fuzzer in case.fuzzer.dependencies
    }.values())

    for fuzzer in fuzzers:
        args: tuple[str, ...] = ()
        local_repo = fuzzer.local_repo
        if local_repo:
            context, dockerfile = _escape(local_repo), _escape(fuzzer.src_dir / 'build' / 'Dockerfile')
            args = ('args = {', f'  {LOCAL_REPO_BUILD_ARG} = "1"', '}')
        else:
            context, dockerfile = _escape(fuzzer.src_dir / 'build'), 'Dockerfile'
        hcl_parts.append(_image_block(
            f'fuzzer_builder_{fuzzer.name}',
            context=context,
            dockerfile=dockerfile,
            parent=f'fuzzer_builder_{fuzzer.parent.name}' if fuzzer.parent else 'clang_base',
            args=args,
        ))

    for profile, _ in INSTRUMENTATION_PROFILES:
        sources = _escape(instrumentation_build_sources[profile])
        hcl_parts.append(_image_block(
            f'instrumentation_builder_{profile}',
            context=_escape(f'{sources}/{profile}'),
            dockerfile='Dockerfile',
            parent='clang_base',
        ))

    for fuzzer in fuzzers:
        if fuzzer.runner_image:
            hcl_parts.append(_image_block(
                fuzzer.runner_image,
                context=_escape(fuzzer.src_dir / 'run'),
                dockerfile='Dockerfile',
                parent=_runner_target(fuzzer.parents),
            ))

    for name, benchmark in benchmarks.items():
        hcl_parts.append(_image_block(
            f'benchmark_{name}',
            context=_escape(benchmark.src_dir),
            dockerfile='Dockerfile',
            parent='benchmark_base',
        ))


    campaign_memory_limit = memory_limit or ENTRY_BUILDER_MEMORY_LIMIT

    def campaign_block(
        name: str, *, stage: str, tag: str, contexts: list[str], args: list[str], depends_on: list[str]
    ) -> str:
        return _hcl_block(name, [
            f'context    = "{docker_resources_arg}"',
            f'dockerfile = "{campaign_dockerfile}"',
            f'target     = "{stage}"',
            f'platforms  = ["{DEFAULT_DOCKER_PLATFORM}"]',
            f'memory     = "{_escape(campaign_memory_limit)}"',
            f'tags       = ["{tag}"]',
            'output = ["type=docker"]',
            'contexts = {',
            *contexts,
            '}',
            *args,
            f'depends_on = {_hcl_str_list(depends_on)}',
        ])

    group_targets: list[str] = []
    for case in campaign_cases:
        fuzzer, fuzz_target_id = case.fuzzer, case.fuzz_target.ident
        runner_base = _runner_target([fuzzer, *fuzzer.parents])
        runner_name = f'runner_{fuzzer.id}_{fuzz_target_id}'
        runner_depends = [
            f'fuzzer_builder_{fuzzer.name}',
            f'benchmark_{case.fuzz_target.benchmark.name}',
            'build_base',
            'runtime_base',
        ]
        if runner_base != 'runtime_base':
            runner_depends.append(runner_base)
        hcl_parts.append(campaign_block(
            runner_name,
            stage='runner',
            tag=case.images.runner,
            contexts=[
                f'  builder = "target:fuzzer_builder_{fuzzer.name}"',
                f'  benchmark = "target:benchmark_{case.fuzz_target.benchmark.name}"',
                '  build_base = "target:build_base"',
                '  runtime_base = "target:runtime_base"',
                f'  runner_base = "target:{runner_base}"',
                f'  fuzzer_build_sources = "{fuzzer_build_sources[fuzzer.name]}"',
                f'  fuzzer_run_sources = "{fuzzer_run_sources[fuzzer.name]}"',
            ],
            args=_entry_args(
                fuzzer=fuzzer.name,
                build_config_json=json.dumps(case.build_config, sort_keys=True),
                fuzzer_source_dirs=[dep.name for dep in fuzzer.dependencies],
                benchmark=case.fuzz_target.benchmark.name,
                benchmark_workdir=_escape(case.fuzz_target.benchmark.workdir),
                target_name=case.fuzz_target.fuzz_target,
                build_compile_jobs=case.fuzz_target.build_compile_jobs or build_compile_jobs,
                runner_base_image='runner_base',
            ),
            depends_on=runner_depends,
        ))
        group_targets.append(runner_name)

    target_cases = {case.fuzz_target.ident: case for case in campaign_cases}
    for internal_fuzzer, stage_name in INSTRUMENTATION_PROFILES:
        sources = _escape(instrumentation_build_sources[internal_fuzzer])
        for fuzz_target_id, case in target_cases.items():
            final_name = f'{stage_name}_{fuzz_target_id}'
            hcl_parts.append(campaign_block(
                final_name,
                stage=stage_name,
                tag=getattr(case.images, internal_fuzzer),
                contexts=[
                    f'  builder = "target:instrumentation_builder_{internal_fuzzer}"',
                    f'  benchmark = "target:benchmark_{case.fuzz_target.benchmark.name}"',
                    '  build_base = "target:build_base"',
                    '  runtime_base = "target:runtime_base"',
                    '  instrumentation_runtime = "target:instrumentation_runtime"',
                    f'  fuzzer_build_sources = "{sources}"',
                ],
                args=_entry_args(
                    fuzzer=internal_fuzzer,
                    build_config_json='{}',
                    fuzzer_source_dirs=[internal_fuzzer],
                    benchmark=case.fuzz_target.benchmark.name,
                    benchmark_workdir=_escape(case.fuzz_target.benchmark.workdir),
                    target_name=case.fuzz_target.fuzz_target,
                    build_compile_jobs=case.fuzz_target.build_compile_jobs or build_compile_jobs,
                ),
                depends_on=[
                    f'instrumentation_builder_{internal_fuzzer}',
                    f'benchmark_{case.fuzz_target.benchmark.name}',
                    'build_base',
                    'runtime_base',
                    'instrumentation_runtime',
                ],
            ))
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
