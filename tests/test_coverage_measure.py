# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for host-side coverage replay batch planning.'''

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fuzzmeter.repro.coverage_measure import (
    CoverageBatch,
    _replace_out_root,
    build_coverage_replay_batches,
    replay_coverage_batches,
)


class CoverageMeasureTest(unittest.TestCase):
    '''Verify coverage batch planning behavior.'''

    def test_empty_inputs_create_no_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            profdata_paths, batches = build_coverage_replay_batches(
                image='coverage-image',
                fuzz_target='target',
                input_mode='file',
                inputs=[],
                state_dir=Path(tmp_dir),
                batch_tag='snap',
                timeout_s=3.0,
            )

        self.assertEqual([], profdata_paths)
        self.assertEqual([], batches)

    def test_single_input_creates_one_batch_with_matching_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            inputs = [state_dir / 'input-0']

            profdata_paths, batches = build_coverage_replay_batches(
                image='coverage-image',
                fuzz_target='target',
                input_mode='stdin',
                inputs=inputs,
                state_dir=state_dir,
                batch_tag='snap',
                timeout_s=7.5,
            )

        self.assertEqual(1, len(batches))
        self.assertEqual(inputs, batches[0].inputs)
        self.assertEqual('coverage-image', batches[0].image)
        self.assertEqual('target', batches[0].fuzz_target)
        self.assertEqual('stdin', batches[0].input_mode)
        self.assertEqual(7.5, batches[0].timeout_s)
        self.assertEqual(profdata_paths, [batch.profdata_path for batch in batches])

    def test_exact_batch_size_creates_one_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            inputs = [state_dir / f'input-{index}' for index in range(256)]

            profdata_paths, batches = build_coverage_replay_batches(
                image='coverage-image',
                fuzz_target='target',
                input_mode='file',
                inputs=inputs,
                state_dir=state_dir,
                batch_tag=4,
                timeout_s=1.0,
            )

        self.assertEqual(1, len(batches))
        self.assertEqual(inputs, batches[0].inputs)
        self.assertEqual(profdata_paths, [batch.profdata_path for batch in batches])

    def test_one_more_than_batch_size_creates_second_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            inputs = [state_dir / f'input-{index}' for index in range(257)]

            profdata_paths, batches = build_coverage_replay_batches(
                image='coverage-image',
                fuzz_target='target',
                input_mode='file',
                inputs=inputs,
                state_dir=state_dir,
                batch_tag=5,
                timeout_s=1.0,
            )

        self.assertEqual(2, len(batches))
        self.assertEqual(inputs[:256], batches[0].inputs)
        self.assertEqual(inputs[256:], batches[1].inputs)
        self.assertEqual(profdata_paths, [batch.profdata_path for batch in batches])

    def test_batch_and_diagnostics_paths_use_batch_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)

            profdata_paths, batches = build_coverage_replay_batches(
                image='coverage-image',
                fuzz_target='target',
                input_mode='file',
                inputs=[state_dir / f'input-{index}' for index in range(257)],
                state_dir=state_dir,
                batch_tag='tick-7',
                timeout_s=1.0,
            )

        self.assertEqual(
            [
                state_dir / '_batches_tick-7' / 'batch_000000.profdata',
                state_dir / '_batches_tick-7' / 'batch_000001.profdata',
            ],
            profdata_paths,
        )
        self.assertEqual(state_dir / '_batch_diag_tick-7' / '000000', batches[0].diagnostics_dir)
        self.assertEqual(state_dir / '_batch_diag_tick-7' / '000001', batches[1].diagnostics_dir)

    def test_replay_coverage_batches_calls_progress_for_each_batch(self) -> None:
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

        with patch('fuzzmeter.repro.coverage_measure.replay_coverage_batch') as replay_batch:
            replay_coverage_batches(
                docker_runtime=Mock(),
                batches=batches,
                jobs=2,
                on_batch_done=on_batch_done,
            )

        self.assertEqual(3, replay_batch.call_count)
        self.assertEqual(3, on_batch_done.call_count)

    def test_replay_coverage_batches_accepts_missing_progress_callback(self) -> None:
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

        with patch('fuzzmeter.repro.coverage_measure.replay_coverage_batch'):
            replay_coverage_batches(
                docker_runtime=Mock(),
                batches=batches,
                jobs=1,
                on_batch_done=None,
            )

    def test_replay_coverage_batches_accepts_empty_batch_list(self) -> None:
        replay_coverage_batches(
            docker_runtime=Mock(),
            batches=[],
            jobs=2,
        )

    def test_replay_coverage_batches_reports_every_failure(self) -> None:
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
                'fuzzmeter.repro.coverage_measure.replay_coverage_batch',
                side_effect=[RuntimeError('first failure'), ValueError('second failure')],
            ),
            self.assertRaises(RuntimeError) as raised,
        ):
            replay_coverage_batches(
                docker_runtime=Mock(),
                batches=batches,
                jobs=2,
            )

        self.assertIn('first failure', str(raised.exception))
        self.assertIn('second failure', str(raised.exception))

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
