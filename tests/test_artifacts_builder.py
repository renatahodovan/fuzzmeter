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
from fuzzmeter.paths import ExternalRoots


class ArtifactBuilderTest(unittest.TestCase):
    '''Verify campaign image build orchestration.'''

    def test_buildx_bake_uses_external_roots_and_absolute_contexts(self) -> None:
        '''Verify that generated bake contexts do not rely on a repository cwd.'''
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
                    external_roots=ExternalRoots.from_checkout(repo_root),
                )

            self.assertEqual(run_dir, run.call_args.kwargs['cwd'])
            self.assertTrue((run_dir / 'bake.hcl').is_file())
            bake_hcl = (run_dir / 'bake.hcl').read_text(encoding='utf-8')
            resolved_root = repo_root.resolve()
            self.assertIn(f'context    = "{resolved_root / "fuzzers" / "plain" / "build"}"', bake_hcl)
            self.assertIn(f'context    = "{resolved_root / "targets" / "bench"}"', bake_hcl)

            campaign_dockerfile = Path('src/fuzzmeter/resources/docker/campaign.Dockerfile').read_text(
                encoding='utf-8'
            )
            self.assertIn('COPY --from=build_base /opt/fuzzmeter/fuzzmeter /opt/fuzzmeter/fuzzmeter', campaign_dockerfile)


def _write_repo_sources(repo_root: Path) -> None:
    fuzzers_root = repo_root / 'fuzzers'
    for fuzzer in ('plain',):
        for phase in ('build', 'run'):
            phase_dir = fuzzers_root / fuzzer / phase
            phase_dir.mkdir(parents=True)
            (phase_dir / 'Dockerfile').write_text('FROM scratch\n', encoding='utf-8')

    target_dir = repo_root / 'targets' / 'bench'
    target_dir.mkdir(parents=True)
    (target_dir / 'Dockerfile').write_text('FROM scratch\n', encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
