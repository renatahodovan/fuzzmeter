# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for AFL-specific report sections.'''

from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from fuzzers.afl.run.reporting import AFLReportingPlugin
from fuzzmeter.reporting.plugin_api import ReportingContext


class AFLReportingTest(unittest.TestCase):
    '''Verify AFL mutator reporting data sources.'''

    def test_uses_afl_mutator_manifest(self) -> None:
        '''AFL mutator reports are built from snapshot mutator manifests.'''
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            snapshot_dir = root / 'trials' / 'aflplusplus__bench-target__rep0' / 'snapshots' / 'snap_000001'
            corpus_dir = snapshot_dir / 'corpus'
            corpus_dir.mkdir(parents=True)
            (corpus_dir / 'id:000001,src:000000,time:1,execs:1,op:havoc,rep:2').write_text('a', encoding='utf-8')
            (corpus_dir / 'id:000002,src:000001,time:2,execs:2,op:splice,rep:1').write_text('b', encoding='utf-8')
            (snapshot_dir / '.fuzzmeter_mutators.json').write_text(
                '{"mutator_counts": {"havoc": 2, "splice": 1}}',
                encoding='utf-8',
            )

            ctx = ReportingContext(
                run_id='run',
                run_dir=root,
                benchmark='bench',
                fuzz_target='target',
                fuzzer='aflplusplus',
                trials=[{'trial_id': 1, 'started_ts': 100}],
                timeseries_by_trial={1: {'points': [{'idx': 1, 'ts': 160}]}},
                bugs=[],
                snapshot_dirs_by_trial={1: [snapshot_dir]},
            )

            plugin = AFLReportingPlugin()
            sections = plugin.build_extra_sections(ctx)
            debug = plugin.build_debug_info(ctx)

        self.assertEqual(1, len(sections))
        self.assertEqual(1, debug['manifest_snapshot_count'])
        self.assertEqual(['havoc', 'splice'], sorted(series.id for series in sections[0].charts[0].series))


if __name__ == '__main__':
    unittest.main()
