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

    def test_checkout_roots_use_cwd_when_it_has_resource_layout(self) -> None:
        '''Verify that running from a checkout discovers fuzzer and target roots.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fuzzers').mkdir()
            (root / 'targets').mkdir()

            with patch('pathlib.Path.cwd', return_value=root):
                roots = cli._checkout_roots()

            self.assertIsNotNone(roots)
            assert roots is not None
            self.assertEqual(root.resolve() / 'fuzzers', roots.fuzzers_root)
            self.assertEqual(root.resolve() / 'targets', roots.targets_root)

    def test_serve_accepts_direct_run_directories(self) -> None:
        '''Verify repeated and multi-value roots configure direct run directories.'''
        try:
            from fuzzmeter.web import app as webapp
        except ModuleNotFoundError as exc:
            if exc.name == 'flask':
                self.skipTest('Flask is not installed in this environment')
            raise

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            first = root / 'first'
            second = root / 'second'
            third = root / 'third'
            for run_dir in (first, second, third):
                run_dir.mkdir()
                (run_dir / 'fuzzmeter.db').write_text('', encoding='utf-8')

            with patch.object(webapp.app, 'run') as app_run:
                self.assertEqual(
                    0,
                    cli.main([
                        '--log-level', 'CRITICAL', 'serve', '--root', str(first), str(second), '--root', str(third),
                    ]),
                )

            run_dirs = (first.resolve(), second.resolve(), third.resolve())
            self.assertEqual(run_dirs, webapp.app.config['RUN_DIRS_PROVIDER']())
            self.assertEqual(run_dirs, webapp.app.config['COMPOSITE_REGISTRY'].run_dirs)
            app_run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
