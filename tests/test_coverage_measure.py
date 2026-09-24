# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for host-side coverage batch planning.'''

from __future__ import annotations

import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import Mock, patch

from fuzzmeter.repro.coverage_measure import (
    CoverageBatch,
    CoveragePipelineError,
    _preserve_previous_artifacts,
    _replace_out_root,
    _synchronize_coverage_set_provenance,
    build_coverage_batches,
    coverage_measurement_context,
    execute_coverage_batch,
    execute_coverage_batches,
    merge_coverage_outputs,
)


class CoverageMeasureTest(unittest.TestCase):
    '''Verify coverage batch planning behavior.'''

    def test_empty_inputs_create_no_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            batches = build_coverage_batches(
                image='coverage-image',
                fuzz_target='target',
                input_mode='file',
                inputs=[],
                artifact_dir=Path(tmp_dir),
                timeout_s=3.0,
            )

        self.assertEqual([], batches)

    def test_single_input_creates_one_batch_with_matching_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_dir = Path(tmp_dir)
            inputs = [artifact_dir / 'input-0']

            batches = build_coverage_batches(
                image='coverage-image',
                fuzz_target='target',
                input_mode='stdin',
                inputs=inputs,
                artifact_dir=artifact_dir,
                timeout_s=7.5,
            )

        self.assertEqual(1, len(batches))
        self.assertEqual(inputs, batches[0].inputs)
        self.assertEqual('coverage-image', batches[0].image)
        self.assertEqual('target', batches[0].fuzz_target)
        self.assertEqual('stdin', batches[0].input_mode)
        self.assertEqual(7.5, batches[0].timeout_s)

    def test_exact_batch_size_creates_one_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_dir = Path(tmp_dir)
            inputs = [artifact_dir / f'input-{index}' for index in range(256)]

            batches = build_coverage_batches(
                image='coverage-image',
                fuzz_target='target',
                input_mode='file',
                inputs=inputs,
                artifact_dir=artifact_dir,
                timeout_s=1.0,
            )

        self.assertEqual(1, len(batches))
        self.assertEqual(inputs, batches[0].inputs)

    def test_one_more_than_batch_size_creates_second_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_dir = Path(tmp_dir)
            inputs = [artifact_dir / f'input-{index}' for index in range(257)]

            batches = build_coverage_batches(
                image='coverage-image',
                fuzz_target='target',
                input_mode='file',
                inputs=inputs,
                artifact_dir=artifact_dir,
                timeout_s=1.0,
            )

        self.assertEqual(2, len(batches))
        self.assertEqual(inputs[:256], batches[0].inputs)
        self.assertEqual(inputs[256:], batches[1].inputs)

    def test_batch_and_diagnostics_paths_use_artifact_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_dir = Path(tmp_dir)

            batches = build_coverage_batches(
                image='coverage-image',
                fuzz_target='target',
                input_mode='file',
                inputs=[artifact_dir / f'input-{index}' for index in range(257)],
                artifact_dir=artifact_dir,
                timeout_s=1.0,
                container_prefix='fm-run-cov-7-trial',
                trial_key='trial',
            )

        self.assertEqual(
            [
                artifact_dir / 'batches' / 'batch_000000.profdata',
                artifact_dir / 'batches' / 'batch_000001.profdata',
            ],
            [batch.profdata_path for batch in batches],
        )
        self.assertEqual(artifact_dir / 'batch-diagnostics' / '000000', batches[0].diagnostics_dir)
        self.assertEqual(artifact_dir / 'batch-diagnostics' / '000001', batches[1].diagnostics_dir)
        self.assertEqual('fm-run-cov-7-trial-000000', batches[0].container_name)
        self.assertEqual('trial', batches[0].trial_key)

    def test_execute_coverage_batches_calls_progress_for_each_batch(self) -> None:
        batches = [
            CoverageBatch(
                image='coverage-image',
                fuzz_target='target',
                input_mode='file',
                inputs=[Path(f'input-{index}')],
                profdata_path=Path(f'batch-{index}.profdata'),
                diagnostics_dir=Path(f'diag-{index}'),
                timeout_s=1.0,
            )
            for index in range(3)
        ]
        on_batch_done = Mock()

        with patch('fuzzmeter.repro.coverage_measure.execute_coverage_batch') as execute_batch:
            execute_coverage_batches(
                docker_runtime=Mock(),
                batches=batches,
                jobs=2,
                on_batch_done=on_batch_done,
            )

        self.assertEqual(3, execute_batch.call_count)
        self.assertEqual(3, on_batch_done.call_count)

    def test_execute_coverage_batches_accepts_missing_progress_callback(self) -> None:
        batches = [
            CoverageBatch(
                image='coverage-image',
                fuzz_target='target',
                input_mode='file',
                inputs=[Path('input')],
                profdata_path=Path('batch.profdata'),
                diagnostics_dir=Path('diag'),
                timeout_s=1.0,
            )
        ]

        with patch('fuzzmeter.repro.coverage_measure.execute_coverage_batch'):
            execute_coverage_batches(
                docker_runtime=Mock(),
                batches=batches,
                jobs=1,
                on_batch_done=None,
            )

    def test_execute_coverage_batches_accepts_empty_batch_list(self) -> None:
        execute_coverage_batches(
            docker_runtime=Mock(),
            batches=[],
            jobs=2,
        )

    def test_execute_coverage_batches_reports_every_failure(self) -> None:
        batches = [
            CoverageBatch(
                image='coverage-image',
                fuzz_target='target',
                input_mode='file',
                inputs=[Path(f'input-{index}')],
                profdata_path=Path(f'batch-{index}.profdata'),
                diagnostics_dir=Path(f'diag-{index}'),
                timeout_s=1.0,
            )
            for index in range(2)
        ]

        with (
            patch(
                'fuzzmeter.repro.coverage_measure.execute_coverage_batch',
                side_effect=[RuntimeError('first failure'), ValueError('second failure')],
            ),
            self.assertRaises(CoveragePipelineError) as raised,
        ):
            execute_coverage_batches(
                docker_runtime=Mock(),
                batches=batches,
                jobs=2,
            )

        self.assertIn('first failure', str(raised.exception))
        self.assertIn('second failure', str(raised.exception))

    def test_execute_coverage_batch_retries_pipeline_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            docker = Mock()
            docker.container_path.side_effect = str
            docker.out_volume.return_value = 'out-volume'
            docker.run.side_effect = [RuntimeError('first'), RuntimeError('second'), None]

            with patch('fuzzmeter.repro.coverage_measure.DockerClient', return_value=docker):
                execute_coverage_batch(
                    docker_runtime=Mock(),
                    image='coverage-image',
                    fuzz_target='target',
                    input_mode='file',
                    inputs=[root / 'input'],
                    batch_profdata_path=root / 'batch.profdata',
                    diagnostics_dir=root / 'diagnostics',
                    container_name='coverage-batch',
                )

        self.assertEqual(3, docker.run.call_count)

    def test_execute_coverage_batch_fails_after_three_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            docker = Mock()
            docker.container_path.side_effect = str
            docker.out_volume.return_value = 'out-volume'
            docker.run.side_effect = RuntimeError('docker unavailable')

            with patch('fuzzmeter.repro.coverage_measure.DockerClient', return_value=docker), \
                 self.assertRaisesRegex(CoveragePipelineError, 'failed after 3 attempts'):
                execute_coverage_batch(
                    docker_runtime=Mock(),
                    image='coverage-image',
                    fuzz_target='target',
                    input_mode='file',
                    inputs=[root / 'input'],
                    batch_profdata_path=root / 'batch.profdata',
                    diagnostics_dir=root / 'diagnostics',
                    container_name='coverage-batch',
                )

        self.assertEqual(3, docker.run.call_count)

    def test_coverage_merge_retries_without_changing_published_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_dir = root / 'state'
            state_dir.mkdir()
            profdata_path = state_dir / 'merged.profdata'
            profdata_path.write_bytes(b'old profile')
            observed_profiles = []

            def merge_once(**kwargs):
                observed_profiles.append(profdata_path.read_bytes())
                if len(observed_profiles) == 1:
                    raise RuntimeError('report failed')
                profdata_path.write_bytes(b'new profile')
                return {'cov_lines_covered': 1}

            with patch(
                'fuzzmeter.repro.coverage_measure._merge_coverage_outputs_once',
                side_effect=merge_once,
            ):
                summary = merge_coverage_outputs(
                    docker_runtime=Mock(),
                    run_dir=root,
                    case=Mock(),
                    out_root=root / 'out',
                    state_dir=state_dir,
                    work_dir=state_dir / 'work',
                    profile_inputs=[],
                )
            published_profile = profdata_path.read_bytes()

        self.assertEqual([b'old profile', b'old profile'], observed_profiles)
        self.assertEqual({'cov_lines_covered': 1}, summary)
        self.assertEqual(b'new profile', published_profile)

    def test_coverage_merge_preserves_profile_after_retry_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_dir = root / 'state'
            state_dir.mkdir()
            profdata_path = state_dir / 'merged.profdata'
            profdata_path.write_bytes(b'old profile')
            attempts = 0

            def merge_once(**kwargs):
                nonlocal attempts
                attempts += 1
                self.assertEqual(b'old profile', profdata_path.read_bytes())
                raise RuntimeError('export failed')

            with patch(
                'fuzzmeter.repro.coverage_measure._merge_coverage_outputs_once',
                side_effect=merge_once,
            ), self.assertRaisesRegex(CoveragePipelineError, 'failed after 3 attempts'):
                merge_coverage_outputs(
                    docker_runtime=Mock(),
                    run_dir=root,
                    case=Mock(),
                    out_root=root / 'out',
                    state_dir=state_dir,
                    work_dir=state_dir / 'work',
                    profile_inputs=[],
                )

            restored = profdata_path.read_bytes()

        self.assertEqual(b'old profile', restored)
        self.assertEqual(3, attempts)

    def test_coverage_merge_publishes_candidate_profile_after_outputs_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_dir = root / 'state'
            state_dir.mkdir()
            published_profile = state_dir / 'merged.profdata'
            published_profile.write_bytes(b'o' * 80)
            batch_profile = root / 'batch.profdata'
            batch_profile.write_bytes(b'b' * 80)
            case = Mock()
            case.images.coverage = 'coverage-image'
            case.fuzz_target.benchmark.name = 'benchmark'
            case.fuzz_target.fuzz_target = 'target'
            docker = Mock()
            docker.container_path.side_effect = str
            docker.image_id.return_value = 'sha256:image'
            docker.out_volume.return_value = 'out-volume'

            def run_worker(**kwargs):
                env = kwargs['env']
                candidate = Path(env['FM_PROFDATA_PATH'])
                out_dir = Path(env['FM_OUT_DIR'])
                self.assertNotEqual(published_profile, candidate)
                self.assertEqual(
                    [str(published_profile), str(batch_profile)],
                    Path(env['FM_PROF_LIST']).read_text(encoding='utf-8').splitlines(),
                )
                candidate.write_bytes(b'n' * 80)
                (out_dir / 'summary.json').write_text('{"cov_lines_covered": 1}', encoding='utf-8')
                (out_dir / 'measurement-provenance.json').write_text('{"schema_version": 2}', encoding='utf-8')
                (out_dir / 'coverage-sets.json').write_text('{"version": 5}', encoding='utf-8')

            docker.run.side_effect = run_worker
            with patch('fuzzmeter.repro.coverage_measure.DockerClient', return_value=docker):
                summary = merge_coverage_outputs(
                    docker_runtime=Mock(),
                    run_dir=root,
                    case=case,
                    out_root=root / 'coverage' / 'trial',
                    state_dir=state_dir,
                    work_dir=state_dir / 'work',
                    profile_inputs=[published_profile, batch_profile],
                )

            current_profile = published_profile.read_bytes()
            output_profile_exists = (root / 'coverage' / 'trial' / 'merged.profdata').exists()

        self.assertEqual({'cov_lines_covered': 1}, summary)
        self.assertEqual(b'n' * 80, current_profile)
        self.assertFalse(output_profile_exists)

    def test_measurement_context_records_batch_semantics_and_profile_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            batch = CoverageBatch(
                image='coverage-image@sha256:abc',
                fuzz_target='target',
                input_mode='in_process',
                inputs=[root / 'a', root / 'b', root / 'c'],
                profdata_path=root / 'batch.profdata',
                diagnostics_dir=root / 'diag',
                timeout_s=1.0,
            )
            diagnostics = batch.diagnostics_dir / 'out'
            diagnostics.mkdir(parents=True)
            (diagnostics / 'input_exec_diagnostics.json').write_text(
                json.dumps({'status_counts': {'failed': 1}}),
                encoding='utf-8',
            )

            context = coverage_measurement_context(
                batches=[batch],
                image=batch.image,
                snapshot_tick=7,
                repetitions=3,
            )

        self.assertEqual('batched-stateful', context['measurement']['mode'])
        self.assertEqual(3, context['measurement']['batch_size'])
        self.assertEqual(0, context['measurement']['artificial_restarts'])
        self.assertEqual('valid', context['validity']['status'])
        self.assertEqual(1, context['inputs']['status_counts']['failed'])
        self.assertEqual(3, context['inputs']['profiles_lost_to_batch_mate_crash'])
        self.assertEqual(3, context['repetitions']['n'])

    def test_carried_coverage_set_embeds_original_source_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            previous = root / 'previous'
            current = root / 'current'
            previous.mkdir()
            current.mkdir()
            (previous / 'coverage-sets.json').write_text(
                json.dumps({'version': 5, 'measurement_provenance': {'coverage_sets': {'freshness': 'fresh'}}}),
                encoding='utf-8',
            )
            carried = {
                'schema_version': 2,
                'coverage_sets': {
                    'freshness': 'carried_forward',
                    'source_tick': 4,
                    'source_profdata_sha256': 'abc',
                },
            }
            (current / 'measurement-provenance.json').write_text(
                json.dumps(carried),
                encoding='utf-8',
            )

            _preserve_previous_artifacts(
                out_root=previous,
                tmp_root=current,
                names=('coverage-sets.json',),
            )
            _synchronize_coverage_set_provenance(current)
            artifact = json.loads((current / 'coverage-sets.json').read_text(encoding='utf-8'))

        self.assertEqual(carried, artifact['measurement_provenance'])

    def test_replace_out_root_skips_unrelated_protected_directory_without_exception_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            out_root = root / 'out'
            tmp_root = root / 'tmp'
            protected_dir = root / 'trial' / 'state'
            out_root.mkdir()
            tmp_root.mkdir()
            protected_dir.mkdir(parents=True)

            with patch('fuzzmeter.repro.coverage_measure.LOG.debug') as debug:
                _replace_out_root(
                    out_root=out_root,
                    tmp_root=tmp_root,
                    protected_dir=protected_dir,
                )

        debug.assert_not_called()


if __name__ == '__main__':
    unittest.main()
