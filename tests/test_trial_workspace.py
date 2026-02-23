# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Unit tests for trial workspace seed corpus handling.'''

from __future__ import annotations

import tempfile
import unittest
import zipfile

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fuzzmeter.trial import workspace


class _SeedDocker:
    def __init__(self) -> None:
        self.probed: list[str] = []

    def copy_from_image(self, *, image: str, src_path: str, dst_path: str | Path) -> None:
        self.probed.append(src_path)
        if src_path != '/out/sqlite_seed_corpus.zip':
            raise RuntimeError(f'Docker image path is missing in {image}: {src_path}')
        with zipfile.ZipFile(dst_path, 'w') as archive:
            archive.writestr('seed.sql', 'select 1;\n')


class TrialWorkspaceTest(unittest.TestCase):
    '''Verify seed corpus extraction from runner images.'''

    def test_seed_corpus_uses_fuzz_target_out_archive(self) -> None:
        '''Seed zips are looked up by fuzz target name in /out.'''
        docker = _SeedDocker()
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch('fuzzmeter.trial.workspace.DockerClient', return_value=docker):
                seed_root = workspace.TrialWorkspacePreparer.extract_seed_corpus_from_image(
                    image='runner',
                    fuzzer='grafl',
                    benchmark='sqlite3',
                    fuzz_target='sqlite',
                    out_dir=Path(tmp_dir),
                )

            self.assertEqual(['/out/sqlite_seed_corpus.zip'], docker.probed)
            self.assertIsNotNone(seed_root)
            assert seed_root is not None
            self.assertEqual('select 1;\n', (seed_root / 'seed.sql').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
