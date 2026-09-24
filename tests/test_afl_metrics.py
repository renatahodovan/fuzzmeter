'''Regression tests for AFL snapshot metric collection.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from fuzzers.afl.run import fuzz as afl_fuzzer


class AFLMetricsTest(unittest.TestCase):
    '''Verify mutator counts derived from AFL corpus file names.'''

    def test_get_custom_metrics_filters_orig_names_and_aggregates_mutators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot_dir = Path(tmp_dir) / 'snapshot'
            corpus_dir = snapshot_dir / 'corpus'
            nested_dir = corpus_dir / 'nested'
            nested_dir.mkdir(parents=True)
            for path in (
                corpus_dir / 'id:000001,execs:10,op:havoc',
                nested_dir / 'id:000002,execs:20,op:havoc',
                corpus_dir / 'id:000003,execs:30,splice',
                corpus_dir / 'id:000004,execs:40,orig:seed',
                corpus_dir / 'id:000005,src:000001',
            ):
                path.write_bytes(b'input')

            payload = afl_fuzzer.get_custom_metrics(
                Path(tmp_dir) / 'trial',
                snapshot_dir=snapshot_dir,
            )

        self.assertEqual(
            {
                'counts': {'havoc': 2, 'splice': 1},
            },
            payload,
        )


if __name__ == '__main__':
    unittest.main()
