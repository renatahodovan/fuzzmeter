# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Verify Grammarinator snapshot preprocess diagnostics.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fuzzers.grammarinator.run import snapshot_preprocess


class GrammarinatorSnapshotPreprocessTest(unittest.TestCase):
    '''Verify decoder failures stay outside snapshot inputs.'''

    def test_decode_failures_use_the_input_set_artifact_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot_dir = Path(tmp_dir) / 'snapshot'
            input_dir = snapshot_dir / 'corpus'
            artifact_dir = snapshot_dir / '.artifacts' / 'preprocess' / 'corpus'
            input_dir.mkdir(parents=True)
            (input_dir / 'id:000001').write_text('tree', encoding='utf-8')

            with patch.dict(
                'os.environ',
                {
                    'FM_FUZZER': 'aflplusplus',
                    'FM_FUZZ_TARGET': 'target',
                    'FM_RUNNER_IMAGE': 'runner',
                    'FM_SNAPSHOT_DIR': str(snapshot_dir),
                    'FM_SNAPSHOT_INPUT_DIR': str(input_dir),
                    'FM_SNAPSHOT_ARTIFACT_DIR': str(artifact_dir),
                    'FM_JOBS': '1',
                },
                clear=True,
            ), patch.object(
                snapshot_preprocess.subprocess,
                'run',
                return_value=SimpleNamespace(returncode=1, stdout='', stderr='decode failed'),
            ):
                snapshot_preprocess.main()

            self.assertTrue((artifact_dir / 'decode-failures.json').is_file())
            self.assertEqual([], list(input_dir.iterdir()))


if __name__ == '__main__':
    unittest.main()
