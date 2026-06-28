# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Test bug report analysis helpers.'''

import unittest

from fuzzmeter.reporting.analyzers.bug_analysis import BugAnalysis


class BugAnalysisTest(unittest.TestCase):
    '''Verify bug report analysis helpers.'''

    def test_collect_bugs_parses_frames_and_output(self):
        analysis = BugAnalysis()

        bugs = analysis.collect_bugs(
            bugs=[
                {
                    'bug_id': 7,
                    'frames_json': '["frame_a", "frame_b"]',
                    'output': 'assert failed\n',
                    'first_seen_ts': 123,
                }
            ],
            bug_hits_by_bug={7: 3},
            bug_trials_by_bug={7: [5, 4, 5]},
        )

        self.assertEqual(
            [
                {
                    'bug_id': 7,
                    'frames_json': '["frame_a", "frame_b"]',
                    'output': 'assert failed',
                    'first_seen_ts': 123,
                    'first_seen_at': '1970-01-01 00:02:03 UTC',
                    'hits_total': 3,
                    'trial_ids': [4, 5],
                    'frames': ['frame_a', 'frame_b'],
                }
            ],
            bugs,
        )

    def test_collect_bugs_drops_invalid_frames_json(self):
        analysis = BugAnalysis()

        bugs = analysis.collect_bugs(
            bugs=[
                {
                    'bug_id': 7,
                    'frames_json': '[not-json',
                    'output': '',
                    'first_seen_ts': 123,
                }
            ],
            bug_hits_by_bug={7: 3},
            bug_trials_by_bug={7: [5]},
        )

        self.assertEqual([], bugs[0]['frames'])
        self.assertIsNone(bugs[0]['output'])

    def test_compute_unique_bug_table_uses_earliest_output_hits_and_last_snapshot_time(self):
        table = BugAnalysis.compute_unique_bug_table(
            {
                'key': 'bench:target',
                'fuzzers': [
                    {
                        'fuzzer': 'alpha',
                        'trials': [{'elapsed_seconds': 120}],
                        'bugs': [
                            {
                                'bug_key': 'bug-1',
                                'issue_type': 'asan',
                                'top_func': 'func_a',
                                'frames': ['frame_a'],
                                'output': 'alpha output',
                                'first_seen_ts': 110,
                                'first_seen_at': 'alpha-first',
                                'hits_total': 4,
                            }
                        ],
                    },
                    {
                        'fuzzer': 'beta',
                        'trials': [{'elapsed_seconds': 90}],
                        'bugs': [
                            {
                                'bug_key': 'bug-1',
                                'issue_type': 'ubsan',
                                'top_func': 'func_b',
                                'frames': ['frame_b'],
                                'output': 'beta output',
                                'first_seen_ts': 105,
                                'first_seen_at': 'beta-first',
                                'hits_total': 9,
                            }
                        ],
                    },
                ],
            }
        )

        self.assertEqual(120, table['last_snapshot_elapsed_seconds'])
        self.assertEqual(
            [
                {
                    'index': 1,
                    'bug_key': 'bug-1',
                    'issue_type': 'ubsan',
                    'top_func': 'func_b',
                    'frames': ['frame_b'],
                    'output': 'beta output',
                    'global_first_seen_ts': 105,
                    'global_first_seen_at': 'beta-first',
                    'cells': [5, 0],
                    'hit_counts': [4, 9],
                }
            ],
            table['rows'],
        )


if __name__ == '__main__':
    unittest.main()
