# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Characterization tests for Docker bake and runtime helpers."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fuzzmeter.config import CampaignCase
from fuzzmeter.docker.bake import _entry_args, generate_run_bake_hcl
from fuzzmeter.docker.runtime import DockerRuntime


class DockerHelperTest(unittest.TestCase):
    """Verify Docker helper environment handling."""

    def test_bake_log_level_uses_fm_log_level_default_and_escaping(self) -> None:
        with patch.dict('os.environ', {'FUZZMETER_LOG_LEVEL': 'DEBUG'}, clear=True):
            default_lines = _entry_args(
                fuzzer='fuzzer',
                build_config_json='{}',
                fuzzer_source_dirs=[],
                benchmark='bench',
                benchmark_workdir='/work',
                target_name='target',
            )

        with patch.dict('os.environ', {'FM_LOG_LEVEL': 'INFO"quoted', 'FUZZMETER_LOG_LEVEL': 'DEBUG'}, clear=True):
            escaped_lines = _entry_args(
                fuzzer='fuzzer',
                build_config_json='{}',
                fuzzer_source_dirs=[],
                benchmark='bench',
                benchmark_workdir='/work',
                target_name='target',
            )

        self.assertIn('  FM_LOG_LEVEL  = "INFO"', default_lines)
        self.assertIn('  FM_LOG_LEVEL  = "INFO\\"quoted"', escaped_lines)

    def test_hook_env_requires_fm_log_level_and_does_not_set_legacy_fallback(self) -> None:
        runtime = DockerRuntime(fuzzers_root=Path('/repo/fuzzers'), out_src='/out', run_user=None)

        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(KeyError):
                runtime.hook_env()

        with patch.dict('os.environ', {'FM_LOG_LEVEL': 'WARNING', 'PYTHONPATH': '/existing'}, clear=True):
            env = runtime.hook_env(extra={'COUNT': 3})

        self.assertEqual('WARNING', env['FM_LOG_LEVEL'])
        self.assertNotIn('FUZZMETER_LOG_LEVEL', env)
        self.assertEqual(f'/repo{os.pathsep}/existing', env['PYTHONPATH'])
        self.assertEqual('/repo/fuzzers', env['FM_FUZZERS_ROOT'])
        self.assertEqual('3', env['COUNT'])

    def test_instrumentation_runners_use_runtime_only_base(self) -> None:
        """Verify sanitizer and coverage runners do not inherit the full clang build image."""
        with TemporaryDirectory() as root:
            root_path = Path(root)
            fuzzers_root = root_path / 'fuzzers'
            targets_root = root_path / 'targets'
            resources_root = root_path / 'docker'
            entrypoints_root = root_path / 'entrypoints'
            runtime_root = root_path / 'runtime'
            build_sources = {'libfuzzer': root_path / 'fuzzer_build' / 'libfuzzer'}
            run_sources = {'libfuzzer': root_path / 'fuzzer_run' / 'libfuzzer'}
            instrumentation_sources = {
                'coverage': root_path / 'instrumentation_build' / 'coverage',
                'asan': root_path / 'instrumentation_build' / 'asan',
            }

            for path in (
                fuzzers_root / 'libfuzzer' / 'build',
                targets_root / 'bench',
                resources_root,
                entrypoints_root,
                runtime_root,
                *build_sources.values(),
                *run_sources.values(),
                *(path / name for name, path in instrumentation_sources.items()),
            ):
                path.mkdir(parents=True)
            (fuzzers_root / 'libfuzzer' / 'build' / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')
            (targets_root / 'bench' / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')
            for name, root_dir in instrumentation_sources.items():
                (root_dir / name / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')

            bake_hcl = generate_run_bake_hcl(
                fuzzers_root=fuzzers_root,
                targets_root=targets_root,
                entries=[
                    CampaignCase(
                        fuzzer_base='libfuzzer',
                        fuzzer_name='libfuzzer',
                        fuzzer_chain=('libfuzzer',),
                        benchmark='bench',
                        fuzz_target='target',
                        target_id='bench-target',
                        input_mode='file',
                    )
                ],
                fuzzer_build_sources=build_sources,
                fuzzer_run_sources=run_sources,
                instrumentation_build_sources=instrumentation_sources,
                docker_resources=resources_root,
                entrypoint_resources=entrypoints_root,
                fuzzmeter_resources=runtime_root,
            )

        self.assertIn('target "instrumentation_runtime"', bake_hcl)
        self.assertIn('dockerfile = "', bake_hcl)
        self.assertIn('/instrumentation-runtime.Dockerfile"', bake_hcl)
        self.assertIn('instrumentation_runtime = "target:instrumentation_runtime"', bake_hcl)
        self.assertNotIn('  clang_base = "target:clang_base"', bake_hcl)

    def test_bake_exports_only_final_runtime_images(self) -> None:
        """Verify intermediate build targets stay in BuildKit cache instead of the Docker image store."""
        with TemporaryDirectory() as root:
            root_path = Path(root)
            fuzzers_root = root_path / 'fuzzers'
            targets_root = root_path / 'targets'
            resources_root = root_path / 'docker'
            entrypoints_root = root_path / 'entrypoints'
            runtime_root = root_path / 'runtime'
            build_sources = {'libfuzzer': root_path / 'fuzzer_build' / 'libfuzzer'}
            run_sources = {'libfuzzer': root_path / 'fuzzer_run' / 'libfuzzer'}
            instrumentation_sources = {
                'coverage': root_path / 'instrumentation_build' / 'coverage',
                'asan': root_path / 'instrumentation_build' / 'asan',
            }

            for path in (
                fuzzers_root / 'libfuzzer' / 'build',
                targets_root / 'bench',
                resources_root,
                entrypoints_root,
                runtime_root,
                *build_sources.values(),
                *run_sources.values(),
                *(path / name for name, path in instrumentation_sources.items()),
            ):
                path.mkdir(parents=True)
            (fuzzers_root / 'libfuzzer' / 'build' / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')
            (targets_root / 'bench' / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')
            for name, root_dir in instrumentation_sources.items():
                (root_dir / name / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')

            bake_hcl = generate_run_bake_hcl(
                fuzzers_root=fuzzers_root,
                targets_root=targets_root,
                entries=[
                    CampaignCase(
                        fuzzer_base='libfuzzer',
                        fuzzer_name='libfuzzer',
                        fuzzer_chain=('libfuzzer',),
                        benchmark='bench',
                        fuzz_target='target',
                        target_id='bench-target',
                        input_mode='file',
                    )
                ],
                fuzzer_build_sources=build_sources,
                fuzzer_run_sources=run_sources,
                instrumentation_build_sources=instrumentation_sources,
                docker_resources=resources_root,
                entrypoint_resources=entrypoints_root,
                fuzzmeter_resources=runtime_root,
            )

        self.assertIn(
            'targets = ["runner_libfuzzer_bench-target", "coverage_runner_bench-target", "crash_runner_bench-target"]',
            bake_hcl,
        )
        self.assertIn('tags       = ["fuzzmeter/runner-libfuzzer-bench-target:dev"]', bake_hcl)
        self.assertIn('tags       = ["fuzzmeter/coverage-runner-bench-target:dev"]', bake_hcl)
        self.assertIn('tags       = ["fuzzmeter/asan-runner-bench-target:dev"]', bake_hcl)
        self.assertNotIn('fuzzmeter/campaign-builder-', bake_hcl)
        self.assertNotIn('fuzzmeter/fuzzer-builder-', bake_hcl)
        self.assertNotIn('fuzzmeter/instrumentation-builder-', bake_hcl)
        self.assertNotIn('fuzzmeter/benchmark-', bake_hcl)
        self.assertNotIn('fuzzmeter/build-base:dev', bake_hcl)
        self.assertNotIn('fuzzmeter/runtime-base:dev', bake_hcl)
        self.assertNotIn('fuzzmeter/clang-base:dev', bake_hcl)

    def test_runner_contexts_are_scoped_to_each_fuzzer(self) -> None:
        """Verify one fuzzer's runner does not depend on another fuzzer's copied sources."""
        with TemporaryDirectory() as root:
            root_path = Path(root)
            fuzzers_root = root_path / 'fuzzers'
            targets_root = root_path / 'targets'
            resources_root = root_path / 'docker'
            entrypoints_root = root_path / 'entrypoints'
            runtime_root = root_path / 'runtime'
            build_sources = {
                'afl': root_path / 'fuzzer_build' / 'afl',
                'libfuzzer': root_path / 'fuzzer_build' / 'libfuzzer',
            }
            run_sources = {
                'afl': root_path / 'fuzzer_run' / 'afl',
                'libfuzzer': root_path / 'fuzzer_run' / 'libfuzzer',
            }
            instrumentation_sources = {
                'coverage': root_path / 'instrumentation_build' / 'coverage',
                'asan': root_path / 'instrumentation_build' / 'asan',
            }

            for path in (
                fuzzers_root / 'afl' / 'build',
                fuzzers_root / 'libfuzzer' / 'build',
                targets_root / 'bench',
                resources_root,
                entrypoints_root,
                runtime_root,
                *build_sources.values(),
                *run_sources.values(),
                *(path / name for name, path in instrumentation_sources.items()),
            ):
                path.mkdir(parents=True)
            (fuzzers_root / 'afl' / 'build' / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')
            (fuzzers_root / 'libfuzzer' / 'build' / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')
            (targets_root / 'bench' / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')
            for name, root_dir in instrumentation_sources.items():
                (root_dir / name / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')

            bake_hcl = generate_run_bake_hcl(
                fuzzers_root=fuzzers_root,
                targets_root=targets_root,
                entries=[
                    CampaignCase(
                        fuzzer_name='afl',
                        fuzzer_chain=('afl',),
                        benchmark='bench',
                        fuzz_target='target',
                        input_mode='file',
                    ),
                    CampaignCase(
                        fuzzer_name='libfuzzer',
                        fuzzer_chain=('libfuzzer',),
                        benchmark='bench',
                        fuzz_target='target',
                        input_mode='file',
                    ),
                ],
                fuzzer_build_sources=build_sources,
                fuzzer_run_sources=run_sources,
                instrumentation_build_sources=instrumentation_sources,
                docker_resources=resources_root,
                entrypoint_resources=entrypoints_root,
                fuzzmeter_resources=runtime_root,
            )

        libfuzzer_block = _target_block(bake_hcl, 'runner_libfuzzer_bench-target')
        self.assertIn(f'fuzzer_build_sources = "{build_sources["libfuzzer"].resolve()}"', libfuzzer_block)
        self.assertIn(f'fuzzer_run_sources = "{run_sources["libfuzzer"].resolve()}"', libfuzzer_block)
        self.assertNotIn(str(build_sources['afl'].resolve()), libfuzzer_block)
        self.assertNotIn(str(run_sources['afl'].resolve()), libfuzzer_block)


def _target_block(bake_hcl: str, target: str) -> str:
    start = bake_hcl.index(f'target "{target}" {{')
    end = bake_hcl.index('\n}\n', start)
    return bake_hcl[start : end + 3]


if __name__ == '__main__':
    unittest.main()
