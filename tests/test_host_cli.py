# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for host-side CLI path handling.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from fuzzmeter import cli


class HostCliTest(unittest.TestCase):
    '''Verify host-side CLI helpers.'''

    def test_default_repo_root_uses_cwd_when_it_has_repo_layout(self) -> None:
        '''Verify that running from the repo root keeps relative build contexts stable.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fuzzers').mkdir()
            (root / 'src').mkdir()

            with patch('pathlib.Path.cwd', return_value=root):
                self.assertEqual(root.resolve(), cli._default_repo_root())

    def test_resolve_runs_root_accepts_out_root(self) -> None:
        '''Verify that an output root containing runs resolves to its runs directory.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_root = Path(tmp_dir) / 'out'
            runs_root = out_root / 'runs'
            runs_root.mkdir(parents=True)

            self.assertEqual(runs_root.resolve(), cli._resolve_runs_root(out_root))


if __name__ == '__main__':
    unittest.main()
