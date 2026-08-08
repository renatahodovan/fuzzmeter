# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Characterization tests for Docker bake and runtime helpers."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

from fuzzmeter.config import CampaignCase
from fuzzmeter.docker import DockerClient, DockerTimeoutError
from fuzzmeter.docker.bake import _entry_args, fuzzer_source_dirs, generate_run_bake_hcl
from fuzzmeter.docker.client import DEFAULT_DOCKER_TIMEOUT_S
from fuzzmeter.docker.runtime import DockerRuntime
from tests.support.bake import target_block


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

    def test_run_labels_and_sweep_use_the_runtime_run_id(self) -> None:
        runtime = DockerRuntime(
            fuzzers_root=Path('/repo/fuzzers'),
            out_src='/out',
            run_user=None,
            run_id='run-7',
        )
        docker = DockerClient(runtime)

        self.assertEqual(
            [
                '--label',
                'fuzzmeter.run=run-7',
                '--label',
                'fuzzmeter.kind=coverage',
                '--label',
                'fuzzmeter.trial=trial-2',
            ],
            docker._label_args(kind='coverage', trial_key='trial-2'),
        )

        ps_result = subprocess.CompletedProcess([], 0, stdout='abc\ndef\n', stderr='')
        rm_result = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        with patch.object(docker, '_run', side_effect=[ps_result, rm_result]) as run:
            self.assertEqual(2, docker.sweep_run())

        self.assertEqual(
            [
                call(
                    ['docker', 'ps', '-aq', '--filter', 'label=fuzzmeter.run=run-7'],
                    check=True,
                    capture=True,
                ),
                call(['docker', 'rm', '-f', 'abc', 'def'], check=False, capture=True, timeout_s=None),
            ],
            run.call_args_list,
        )

    def test_run_raises_distinct_timeout_error(self) -> None:
        with self.assertRaises(DockerTimeoutError):
            DockerClient._run(
                [sys.executable, '-c', 'import time; time.sleep(1)'],
                timeout_s=0.01,
            )

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
                        fuzzer_name='libfuzzer',
                        fuzzer_chain=('libfuzzer',),
                        benchmark='bench',
                        fuzz_target='target',
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
                        fuzzer_name='libfuzzer',
                        fuzzer_chain=('libfuzzer',),
                        benchmark='bench',
                        fuzz_target='target',
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

        libfuzzer_block = target_block(bake_hcl, 'runner_libfuzzer_bench-target')
        self.assertIn(f'fuzzer_build_sources = "{build_sources["libfuzzer"].resolve()}"', libfuzzer_block)
        self.assertIn(f'fuzzer_run_sources = "{run_sources["libfuzzer"].resolve()}"', libfuzzer_block)
        self.assertNotIn(str(build_sources['afl'].resolve()), libfuzzer_block)
        self.assertNotIn(str(run_sources['afl'].resolve()), libfuzzer_block)

    def test_fuzzer_source_dependencies_merge_build_and_run_yaml(self) -> None:
        """Verify build and run source dependencies are both available to campaign builds."""
        with TemporaryDirectory() as root:
            fuzzers_root = Path(root) / 'fuzzers'
            for fuzzer in ('grammarinator', 'libfuzzer', 'blackbox'):
                (fuzzers_root / fuzzer / 'build').mkdir(parents=True)
                (fuzzers_root / fuzzer / 'run').mkdir(parents=True)
            (fuzzers_root / 'grammarinator' / 'build' / 'build.yaml').write_text(
                'source_dependencies:\n'
                '  - libfuzzer\n',
                encoding='utf-8',
            )
            (fuzzers_root / 'grammarinator' / 'run' / 'run.yaml').write_text(
                'source_dependencies:\n'
                '  - blackbox\n',
                encoding='utf-8',
            )

            source_dirs = fuzzer_source_dirs(fuzzers_root, 'grammarinator')

        self.assertEqual(['grammarinator', 'blackbox', 'libfuzzer'], source_dirs)

    def test_fuzzer_builder_can_use_configured_local_checkout_context(self) -> None:
        """Verify local_repo_env can redirect a fuzzer builder to a host checkout."""
        with TemporaryDirectory() as root:
            root_path = Path(root)
            fuzzers_root = root_path / 'fuzzers'
            targets_root = root_path / 'targets'
            resources_root = root_path / 'docker'
            entrypoints_root = root_path / 'entrypoints'
            runtime_root = root_path / 'runtime'
            local_repo = root_path / 'private-fuzzer'
            build_sources = {'local': root_path / 'fuzzer_build' / 'local'}
            run_sources = {'local': root_path / 'fuzzer_run' / 'local'}
            instrumentation_sources = {
                'coverage': root_path / 'instrumentation_build' / 'coverage',
                'asan': root_path / 'instrumentation_build' / 'asan',
            }

            for path in (
                fuzzers_root / 'local' / 'build',
                targets_root / 'bench',
                resources_root,
                entrypoints_root,
                runtime_root,
                local_repo,
                *build_sources.values(),
                *run_sources.values(),
                *(path / name for name, path in instrumentation_sources.items()),
            ):
                path.mkdir(parents=True)
            (fuzzers_root / 'local' / 'build' / 'Dockerfile').write_text(
                'FROM parent_image\n',
                encoding='utf-8',
            )
            (fuzzers_root / 'local' / 'build' / 'build.yaml').write_text(
                'local_repo_env: FM_TEST_LOCAL_REPO\n',
                encoding='utf-8',
            )
            (targets_root / 'bench' / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')
            for name, root_dir in instrumentation_sources.items():
                (root_dir / name / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')

            with patch.dict(os.environ, {'FM_TEST_LOCAL_REPO': str(local_repo)}, clear=True):
                bake_hcl = generate_run_bake_hcl(
                    fuzzers_root=fuzzers_root,
                    targets_root=targets_root,
                    entries=[
                        CampaignCase(
                            fuzzer_name='local',
                            fuzzer_chain=('local',),
                            benchmark='bench',
                            fuzz_target='target',
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

        local_block = target_block(bake_hcl, 'fuzzer_builder_local')
        self.assertIn(f'context    = "{local_repo.resolve()}"', local_block)
        self.assertIn(
            f'dockerfile = "{(fuzzers_root / "local" / "build" / "Dockerfile").resolve()}"',
            local_block,
        )
        self.assertIn('FM_LOCAL_REPO = "1"', local_block)

    def test_fuzzer_builder_keeps_default_context_without_local_checkout_env(self) -> None:
        """Verify local_repo_env is opt-in only when its host env var is set."""
        with TemporaryDirectory() as root:
            root_path = Path(root)
            fuzzers_root = root_path / 'fuzzers'
            targets_root = root_path / 'targets'
            resources_root = root_path / 'docker'
            entrypoints_root = root_path / 'entrypoints'
            runtime_root = root_path / 'runtime'
            build_sources = {'local': root_path / 'fuzzer_build' / 'local'}
            run_sources = {'local': root_path / 'fuzzer_run' / 'local'}
            instrumentation_sources = {
                'coverage': root_path / 'instrumentation_build' / 'coverage',
                'asan': root_path / 'instrumentation_build' / 'asan',
            }

            for path in (
                fuzzers_root / 'local' / 'build',
                targets_root / 'bench',
                resources_root,
                entrypoints_root,
                runtime_root,
                *build_sources.values(),
                *run_sources.values(),
                *(path / name for name, path in instrumentation_sources.items()),
            ):
                path.mkdir(parents=True)
            (fuzzers_root / 'local' / 'build' / 'Dockerfile').write_text(
                'FROM parent_image\n',
                encoding='utf-8',
            )
            (fuzzers_root / 'local' / 'build' / 'build.yaml').write_text(
                'local_repo_env: FM_TEST_LOCAL_REPO\n',
                encoding='utf-8',
            )
            (targets_root / 'bench' / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')
            for name, root_dir in instrumentation_sources.items():
                (root_dir / name / 'Dockerfile').write_text('FROM parent_image\n', encoding='utf-8')

            with patch.dict(os.environ, {}, clear=True):
                bake_hcl = generate_run_bake_hcl(
                    fuzzers_root=fuzzers_root,
                    targets_root=targets_root,
                    entries=[
                        CampaignCase(
                            fuzzer_name='local',
                            fuzzer_chain=('local',),
                            benchmark='bench',
                            fuzz_target='target',
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

        local_block = target_block(bake_hcl, 'fuzzer_builder_local')
        self.assertIn(f'context    = "{(fuzzers_root / "local" / "build").resolve()}"', local_block)
        self.assertIn('dockerfile = "Dockerfile"', local_block)
        self.assertNotIn('FM_LOCAL_REPO = "1"', local_block)


    def test_worker_containers_stay_unbounded_while_control_plane_is_capped(self) -> None:
        """Verify measuring containers get no deadline and cleanup completes."""
        runtime = DockerRuntime(
            fuzzers_root=Path('/repo/fuzzers'),
            out_src='/out',
            run_user=None,
            run_id='run-1',
        )
        client = DockerClient(runtime)

        with patch('fuzzmeter.docker.client.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, '', '')
            client.run(image='img', kind='coverage', cmd=['python3', 'worker.py'])
            self.assertIsNone(run.call_args.kwargs['timeout'])

            run.reset_mock()
            client.rm('c1')
            self.assertIsNone(run.call_args.kwargs['timeout'])

            run.reset_mock()
            client.kill('c1')
            self.assertIsNone(run.call_args.kwargs['timeout'])

            run.reset_mock()
            client.is_running('c1')
            self.assertEqual(DEFAULT_DOCKER_TIMEOUT_S, run.call_args.kwargs['timeout'])

    def test_control_plane_timeout_raises_docker_timeout_error(self) -> None:
        """Verify a wedged control-plane command fails with a distinct error."""
        client = DockerClient()
        with patch(
            'fuzzmeter.docker.client.subprocess.run',
            side_effect=subprocess.TimeoutExpired(cmd=['docker', 'ps'], timeout=30),
        ):
            with self.assertRaises(DockerTimeoutError):
                client.is_running('c1')

if __name__ == '__main__':
    unittest.main()
