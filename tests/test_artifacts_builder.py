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
from tests.support.bake import target_block


class ArtifactBuilderTest(unittest.TestCase):
    '''Verify campaign image build orchestration.'''

    def test_buildx_bake_uses_configured_roots_and_absolute_contexts(self) -> None:
        '''Verify that generated bake contexts do not rely on a repository cwd.'''
        with tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as out_dir:
            repo_root = Path(repo_dir)
            run_dir = Path(out_dir) / 'run'
            run_dir.mkdir(parents=True)
            _write_repo_sources(repo_root)

            with patch('fuzzmeter.artifacts.builder.subprocess.run') as run:
                _build_images(
                    campaign_config=CampaignConfig(
                        settings=CampaignSettings(),
                        cases=[
                            CampaignCase(
                                fuzzer_name='plain',
                                fuzzer_chain=('plain',),
                                benchmark='bench',
                                fuzz_target='target',
                                input_mode='file',
                            ),
                        ],
                    ),
                    run_dir=run_dir,
                    fuzzers_root=repo_root / 'fuzzers',
                    targets_root=repo_root / 'targets',
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
            self.assertIn(
                'COPY --from=build_base /opt/fuzzmeter/fuzzmeter /opt/fuzzmeter/fuzzmeter',
                campaign_dockerfile,
            )
            self.assertIn(
                'COPY --from=campaign_builder /opt/fuzzmeter/meta/coverage-build.json '
                '/opt/fuzzmeter/meta/coverage-build.json',
                campaign_dockerfile,
            )

    def test_buildx_bake_scopes_copied_sources_to_each_fuzzer(self) -> None:
        '''Verify that changing the campaign fuzzer set does not change unrelated fuzzer contexts.'''
        with tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as out_dir:
            repo_root = Path(repo_dir)
            run_dir = Path(out_dir) / 'run'
            run_dir.mkdir(parents=True)
            _write_repo_sources(repo_root, fuzzers=('other', 'plain'))

            with patch('fuzzmeter.artifacts.builder.subprocess.run'):
                _build_images(
                    campaign_config=CampaignConfig(
                        settings=CampaignSettings(),
                        cases=[
                            CampaignCase(
                                fuzzer_name='other',
                                fuzzer_chain=('other',),
                                benchmark='bench',
                                fuzz_target='target',
                                input_mode='file',
                            ),
                            CampaignCase(
                                fuzzer_name='plain',
                                fuzzer_chain=('plain',),
                                benchmark='bench',
                                fuzz_target='target',
                                input_mode='file',
                            ),
                        ],
                    ),
                    run_dir=run_dir,
                    fuzzers_root=repo_root / 'fuzzers',
                    targets_root=repo_root / 'targets',
                )

            plain_build_context = run_dir / 'fuzzer_resources' / 'build' / 'plain'
            self.assertTrue((plain_build_context / 'plain' / 'build' / 'Dockerfile').is_file())
            self.assertFalse((plain_build_context / 'other').exists())

            bake_hcl = (run_dir / 'bake.hcl').read_text(encoding='utf-8')
            plain_block = target_block(bake_hcl, 'runner_plain_bench-target')
            self.assertIn(f'fuzzer_build_sources = "{plain_build_context.resolve()}"', plain_block)
            self.assertNotIn(str((run_dir / 'fuzzer_resources' / 'build' / 'other').resolve()), plain_block)

    def test_buildx_bake_allows_configured_local_fuzzer_repo(self) -> None:
        '''Verify local fuzzer source checkouts are allowed as BuildKit inputs.'''
        with tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as out_dir:
            repo_root = Path(repo_dir)
            run_dir = Path(out_dir) / 'run'
            local_repo = Path(out_dir) / 'local-fuzzer'
            run_dir.mkdir(parents=True)
            local_repo.mkdir()
            _write_repo_sources(repo_root, local_repo_env='FM_TEST_LOCAL_REPO')

            with (
                patch.dict('os.environ', {'FM_TEST_LOCAL_REPO': str(local_repo)}, clear=True),
                patch('fuzzmeter.artifacts.builder.subprocess.run') as run,
            ):
                _build_images(
                    campaign_config=CampaignConfig(
                        settings=CampaignSettings(),
                        cases=[
                            CampaignCase(
                                fuzzer_name='plain',
                                fuzzer_chain=('plain',),
                                benchmark='bench',
                                fuzz_target='target',
                                input_mode='file',
                            ),
                        ],
                    ),
                    run_dir=run_dir,
                    fuzzers_root=repo_root / 'fuzzers',
                    targets_root=repo_root / 'targets',
                )

            self.assertIn(f'--allow=fs.read={local_repo.resolve()}', run.call_args.args[0])


def _write_repo_sources(
    repo_root: Path,
    *,
    fuzzers: tuple[str, ...] = ('plain',),
    local_repo_env: str | None = None,
) -> None:
    fuzzers_root = repo_root / 'fuzzers'
    for fuzzer in fuzzers:
        for phase in ('build', 'run'):
            phase_dir = fuzzers_root / fuzzer / phase
            phase_dir.mkdir(parents=True)
            (phase_dir / 'Dockerfile').write_text('FROM scratch\n', encoding='utf-8')
        if local_repo_env:
            (fuzzers_root / fuzzer / 'build' / 'build.yaml').write_text(
                f'local_repo_env: {local_repo_env}\n',
                encoding='utf-8',
            )

    target_dir = repo_root / 'targets' / 'bench'
    target_dir.mkdir(parents=True)
    (target_dir / 'Dockerfile').write_text('FROM scratch\n', encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
