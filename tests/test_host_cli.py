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

            with patch.object(webapp.Flask, 'run', autospec=True) as app_run:
                self.assertEqual(
                    0,
                    cli.main([
                        '--log-level', 'CRITICAL', 'serve', '--root', str(first), str(second), '--root', str(third),
                    ]),
                )

            app_run.assert_called_once()
            app = app_run.call_args.args[0]
            run_dirs = (first.resolve(), second.resolve(), third.resolve())
            self.assertEqual(run_dirs, app.config['RUN_DIRS_PROVIDER']())
            self.assertEqual(run_dirs, app.config['COMPOSITE_REGISTRY'].run_dirs)

    def test_serve_rejects_duplicate_run_directory_names(self) -> None:
        '''Verify run directories sharing a name are refused before the web app starts.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            first = root / 'one' / 'run'
            second = root / 'two' / 'run'
            for run_dir in (first, second):
                run_dir.mkdir(parents=True)
                (run_dir / 'fuzzmeter.db').write_text('', encoding='utf-8')

            self.assertEqual(
                1,
                cli.main(['--log-level', 'CRITICAL', 'serve', '--root', str(first), str(second)]),
            )


if __name__ == '__main__':
    unittest.main()
