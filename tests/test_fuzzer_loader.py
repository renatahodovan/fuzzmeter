# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Tests for loading external fuzzer entrypoints."""

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from fuzzmeter.fuzzers.loader import FuzzerLoader


class FuzzerLoaderTest(unittest.TestCase):
    def test_cross_fuzzer_imports_use_configured_root_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fuzzers_root = Path(tmp) / 'external-fuzzer-root'
            base_run = fuzzers_root / 'base' / 'run'
            helper_run = fuzzers_root / 'helper' / 'run'
            base_run.mkdir(parents=True)
            helper_run.mkdir(parents=True)

            (base_run / 'fuzz.py').write_text(
                '''
from fuzzers.helper.run import fuzz as helper_fuzz


def get_stats(trial_root):
    return helper_fuzz.get_stats(trial_root)
'''.lstrip(),
                encoding='utf-8',
            )
            (helper_run / 'fuzz.py').write_text(
                '''
def get_stats(trial_root):
    return {'trial_root': str(trial_root)}
'''.lstrip(),
                encoding='utf-8',
            )

            stats = FuzzerLoader(fuzzers_root).load('base').stats(Path('/trial'))

        self.assertEqual({'trial_root': '/trial'}, stats)


if __name__ == '__main__':
    unittest.main()
