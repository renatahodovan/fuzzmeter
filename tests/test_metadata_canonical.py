# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Regression tests for composite metadata canonicalization.'''

from __future__ import annotations

import unittest

from fuzzmeter.composite import canonical_digest, canonical_value


class MetadataCanonicalTest(unittest.TestCase):
    '''Verify stable metadata digest input rules.'''

    def test_digest_is_stable_for_dict_order(self) -> None:
        '''Different insertion order keeps the same digest.'''
        left = {'b': 2, 'a': {'d': 4, 'c': 3}}
        right = {'a': {'c': 3, 'd': 4}, 'b': 2}

        self.assertEqual(canonical_digest(left), canonical_digest(right))

    def test_none_values_are_omitted(self) -> None:
        '''None fields are absent from canonical dictionaries.'''
        self.assertEqual({'a': 1}, canonical_value({'a': 1, 'b': None}))

    def test_empty_list_empty_dict_and_missing_key_are_distinct(self) -> None:
        '''Empty containers keep their own canonical meaning.'''
        self.assertNotEqual(canonical_digest({'a': []}), canonical_digest({}))
        self.assertNotEqual(canonical_digest({'a': {}}), canonical_digest({}))
        self.assertNotEqual(canonical_digest({'a': []}), canonical_digest({'a': {}}))

    def test_list_order_is_preserved(self) -> None:
        '''List order remains part of the canonical value.'''
        self.assertNotEqual(
            canonical_digest({'chain': ['child', 'parent']}),
            canonical_digest({'chain': ['parent', 'child']}),
        )


if __name__ == '__main__':
    unittest.main()
