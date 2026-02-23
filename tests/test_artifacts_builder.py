# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for campaign artifact building.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from fuzzmeter.artifacts.builder import _build_images
from fuzzmeter.config import CampaignCase, CampaignConfig, CampaignSettings


class ArtifactBuilderTest(unittest.TestCase):
    '''Verify campaign image build orchestration.'''

    def test_buildx_bake_runs_from_repo_root(self) -> None:
        '''Verify that relative bake contexts resolve from the fuzzmeter repo root.'''
        with tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as out_dir:
            repo_root = Path(repo_dir)
            run_dir = Path(out_dir) / 'runs' / 'run'
            run_dir.mkdir(parents=True)
            _write_repo_sources(repo_root)

            with patch('fuzzmeter.artifacts.builder.subprocess.run') as run:
                _build_images(
                    campaign_config=CampaignConfig(
                        settings=CampaignSettings(),
                        cases=[
                            CampaignCase(
                                fuzzer_base='plain',
                                fuzzer_name='plain',
                                fuzzer_chain=('plain',),
                                benchmark='bench',
                                fuzz_target='target',
                                target_id='bench-target',
                                input_mode='file',
                            ),
                        ],
                    ),
                    run_dir=run_dir,
                    repo_root=repo_root,
                )

            self.assertEqual(repo_root, run.call_args.kwargs['cwd'])
            self.assertTrue((run_dir / 'bake.hcl').is_file())


def _write_repo_sources(repo_root: Path) -> None:
    fuzzers_root = repo_root / 'fuzzers'
    (fuzzers_root / '_common').mkdir(parents=True)
    (fuzzers_root / '__init__.py').write_text('', encoding='utf-8')
    (fuzzers_root / 'utils.py').write_text('', encoding='utf-8')
    (fuzzers_root / '_common' / '__init__.py').write_text('', encoding='utf-8')
    for fuzzer in ('plain', 'coverage', 'asan'):
        for phase in ('build', 'run'):
            phase_dir = fuzzers_root / fuzzer / phase
            phase_dir.mkdir(parents=True)
            (phase_dir / 'Dockerfile').write_text('FROM scratch\n', encoding='utf-8')

    target_dir = repo_root / 'targets' / 'bench'
    target_dir.mkdir(parents=True)
    (target_dir / 'Dockerfile').write_text('FROM scratch\n', encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
