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
    def test_custom_metrics_preserve_the_adapter_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fuzzer_dir = Path(tmp) / 'metrics'
            run_dir = fuzzer_dir / 'run'
            run_dir.mkdir(parents=True)
            (run_dir / 'fuzz.py').write_text(
                'def get_custom_metrics(trial_root, *, snapshot_dir, cutoff_elapsed_s=None):\n'
                '    return {"nested": [1, "two"]}\n',
                encoding='utf-8',
            )

            payload = FuzzerLoader({'metrics': fuzzer_dir}).load('metrics').custom_metrics(
                Path('/trial'),
                snapshot_dir=Path('/snapshot'),
            )

        self.assertEqual({'nested': [1, 'two']}, payload)

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

            stats = FuzzerLoader({'base': fuzzers_root / 'base'}).load('base').stats(Path('/trial'))

        self.assertEqual({'trial_root': '/trial'}, stats)


if __name__ == '__main__':
    unittest.main()
