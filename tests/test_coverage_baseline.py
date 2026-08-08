# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Characterization tests for seed baseline coverage orchestration.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path
from unittest.mock import Mock, patch

from fuzzmeter.artifacts.seeds import _collect_seed_baseline_jobs
from fuzzmeter.config import CampaignCase, CampaignConfig, CampaignSettings
from fuzzmeter.db import DB
from fuzzmeter.repro.coverage_baseline import SeedBaselineJob, measure_seed_baseline
from fuzzmeter.repro.coverage_state import seed_coverage_root
from tests.support.dbs import empty_run_db


class CoverageBaselineTest(unittest.TestCase):
    '''Verify seed baseline replay planning and persistence behavior.'''

    def test_collect_seed_baseline_jobs_skips_missing_and_empty_seed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            _seed_root(run_dir, 'full', 'bench', 'target').mkdir(parents=True)
            (_seed_root(run_dir, 'full', 'bench', 'target') / 'seed.txt').write_text('seed\n', encoding='utf-8')
            _seed_root(run_dir, 'empty', 'bench', 'target').mkdir(parents=True)

            loader = Mock()
            loader.load.return_value.snapshot_preprocess_script.return_value = Path('/preprocess.py')

            jobs = _collect_seed_baseline_jobs(
                campaign_config=CampaignConfig(
                    settings=CampaignSettings(),
                    cases=[
                        _case(fuzzer_name='missing', timeout_s=1.0),
                        _case(fuzzer_name='empty', timeout_s=2.0),
                        _case(fuzzer_name='full', timeout_s=3.5),
                    ],
                ),
                run_dir=run_dir,
                fuzzer_loader=loader,
            )

        self.assertEqual(1, len(jobs))
        self.assertEqual('full', jobs[0].fuzzer)
        self.assertEqual(3.5, jobs[0].timeout_s)
        self.assertEqual(Path('/preprocess.py'), jobs[0].snapshot_preprocess_script)

    def test_measure_seed_baseline_forwards_jobs_timeout_and_profile_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_dir = root / 'run'
            repo_root = root / 'repo'
            seed_root = root / 'seed'
            seed_root.mkdir(parents=True)
            repo_root.mkdir()
            run_dir.mkdir()
            (seed_root / 'a.txt').write_text('a\n', encoding='utf-8')
            (seed_root / 'nested').mkdir()
            (seed_root / 'nested' / 'b.txt').write_text('b\n', encoding='utf-8')
            db_path = root / 'run.db'
            empty_run_db(db_path)

            job = SeedBaselineJob(
                fuzzer='fuzzer',
                benchmark='bench',
                fuzz_target='target',
                input_mode='file',
                timeout_s=4.0,
                runner_image='runner-image',
                coverage_image='coverage-image',
                snapshot_preprocess_script=None,
                seed_root=seed_root,
            )

            with patch(
                'fuzzmeter.repro.coverage_baseline.prepare_snapshot_inputs',
                side_effect=_copy_prepared_inputs,
            ) as prepare_inputs, patch(
                'fuzzmeter.repro.coverage_baseline.replay_coverage_batches',
            ) as replay_batches, patch(
                'fuzzmeter.repro.coverage_baseline.merge_coverage_outputs',
                side_effect=_write_merge_outputs,
            ) as merge_outputs:
                measure_seed_baseline(
                    db_path=db_path,
                    job=job,
                    run_dir=run_dir,
                    run_id='run-id',
                    docker_runtime=Mock(),
                    jobs=5,
                )

            replay_kwargs = replay_batches.call_args.kwargs
            merge_kwargs = merge_outputs.call_args.kwargs
            base_root = seed_coverage_root(run_dir, 'fuzzer', 'bench', 'target')
            row = _seed_baseline_row(db_path)

        self.assertEqual(1, prepare_inputs.call_count)
        self.assertEqual(5, replay_kwargs['jobs'])
        self.assertEqual(1, len(replay_kwargs['batches']))
        self.assertEqual(8.0, replay_kwargs['batches'][0].timeout_s)
        self.assertEqual(
            [base_root / '_state' / '_batches_seed' / 'batch_000000.profdata'],
            merge_kwargs['profile_inputs'],
        )
        self.assertEqual('coverage_seed/fuzzer/bench/target/html/index.html', row['coverage_html_dir'])
        self.assertEqual('coverage_seed/fuzzer/bench/target/coverage-sets.json', row['coverage_sets_json_rel'])
        self.assertEqual(7, row['cov_lines_covered'])
        self.assertEqual(11, row['cov_lines_total'])


def _case(*, fuzzer_name: str, timeout_s: float) -> CampaignCase:
    return CampaignCase(
        fuzzer_name=fuzzer_name,
        fuzzer_chain=('plain',),
        benchmark='bench',
        fuzz_target='target',
        input_mode='file',
        target_timeout_s=timeout_s,
    )


def _seed_root(run_dir: Path, fuzzer: str, benchmark: str, fuzz_target: str) -> Path:
    return run_dir / 'seed_corpora' / f'{fuzzer}__{benchmark}__{fuzz_target}' / 'corpus'


def _copy_prepared_inputs(**kwargs) -> None:
    input_dir = kwargs['input_dir']
    input_dir.mkdir(parents=True, exist_ok=True)
    for input_file in kwargs['input_files']:
        dst = input_dir / input_file.rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(input_file.abs_src.read_bytes())


def _write_merge_outputs(**kwargs) -> dict[str, int]:
    out_root = kwargs['out_root']
    (out_root / 'html').mkdir(parents=True)
    (out_root / 'html' / 'index.html').write_text('<html></html>\n', encoding='utf-8')
    (out_root / 'coverage-sets.json').write_text('{}\n', encoding='utf-8')
    return {
        'cov_lines_covered': 7,
        'cov_lines_total': 11,
    }


def _seed_baseline_row(db_path: Path) -> dict:
    with DB.open(db_path) as db:
        return db.q(
            '''
            SELECT coverage_html_dir,
                   coverage_sets_json_rel,
                   cov_lines_covered,
                   cov_lines_total
              FROM agg_snapshots
            '''
        )[0]


if __name__ == '__main__':
    unittest.main()
