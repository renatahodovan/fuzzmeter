# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for instrumentation utility context managers.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from fuzzmeter.resources.instrumentation.utils import restore_directory


class InstrumentationUtilsTest(unittest.TestCase):
    '''Verify instrumentation utility cleanup behavior.'''

    def test_restore_directory_restores_after_wrapped_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir) / 'work'
            directory.mkdir()
            (directory / 'original').write_text('original', encoding='utf-8')

            with (
                self.assertRaisesRegex(RuntimeError, 'wrapped failure'),
                restore_directory(directory),
            ):
                (directory / 'original').unlink()
                (directory / 'changed').write_text('changed', encoding='utf-8')
                raise RuntimeError('wrapped failure')

            self.assertEqual(['original'], [path.name for path in directory.iterdir()])
            self.assertEqual('original', (directory / 'original').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
