# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for composite measurement compatibility signals.'''

from __future__ import annotations

import unittest

from fuzzmeter.composite import COMPATIBLE, INCOMPATIBLE, RISKY, MetadataTriplet, compare_metadata


class CompositeCompatibilityTest(unittest.TestCase):
    '''Verify the user-informing composite compatibility policy.'''

    def test_matching_triplets_are_compatible(self) -> None:
        '''Identical metadata has no risk signals.'''
        metadata = _metadata()

        result = compare_metadata(metadata, metadata)

        self.assertEqual(COMPATIBLE, result.level)
        self.assertEqual((), result.issues)

    def test_environment_diff_is_risky(self) -> None:
        '''Environment differences inform the user without blocking selection.'''
        result = compare_metadata(
            _metadata(environment={'host': {'kernel': '6.8'}}),
            _metadata(environment={'host': {'kernel': '6.9'}}),
        )

        self.assertEqual(RISKY, result.level)
        self.assertEqual('environment', result.issues[0].domain)
        self.assertEqual({'reference': '6.8', 'candidate': '6.9'}, result.environment_diff['host']['kernel'])

    def test_source_missing_is_risky(self) -> None:
        '''Missing user source metadata is a visible risk, not an incompatibility.'''
        result = compare_metadata(_metadata(source={}), _metadata())

        self.assertEqual(RISKY, result.level)
        self.assertEqual('source', result.issues[0].domain)

    def test_target_mismatch_is_incompatible(self) -> None:
        '''Different benchmark or fuzz target is the hard incompatibility.'''
        result = compare_metadata(_metadata(), _metadata(config={'benchmark': 'zlib', 'fuzz_target': 'inflate'}))

        self.assertEqual(INCOMPATIBLE, result.level)
        self.assertEqual('config', result.issues[0].domain)


def _metadata(
    *,
    environment: dict | None = None,
    config: dict | None = None,
    source: dict | None = None,
) -> MetadataTriplet:
    return MetadataTriplet(
        environment=environment or {'host': {'kernel': '6.8'}},
        config=config or {'benchmark': 'zlib', 'fuzz_target': 'compress', 'input_mode': 'file', 'timeout': 1.0},
        source=source
        if source is not None
        else {
            'target_source': {'status': 'ok', 'data': {'revision': 'abc'}},
            'fuzzer_version': {'status': 'ok', 'data': {'revision': 'def'}},
        },
    )


if __name__ == '__main__':
    unittest.main()
