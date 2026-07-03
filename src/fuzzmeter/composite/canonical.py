# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Canonicalize composite metadata for stable digests.'''

from __future__ import annotations

import hashlib
import json

from collections.abc import Mapping
from typing import Any, TypeAlias, cast

NoneType = type(None)
CanonicalValue: TypeAlias = (
    NoneType | bool | int | float | str | list['CanonicalValue'] | dict[str, 'CanonicalValue']
)


def canonical_value(value: Any) -> CanonicalValue:
    '''Return a deterministic JSON-compatible representation of value.'''
    if isinstance(value, Mapping):
        return {
            str(key): canonical_value(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            if child is not None
        }
    if isinstance(value, tuple):
        return [canonical_value(child) for child in value]
    if isinstance(value, list):
        return [canonical_value(child) for child in value]
    return cast(CanonicalValue, value)


def canonical_json(value: Any) -> str:
    '''Return stable compact JSON for digest input.'''
    return json.dumps(
        canonical_value(value),
        ensure_ascii=True,
        separators=(',', ':'),
        sort_keys=True,
    )


def canonical_digest(value: Any) -> str:
    '''Return a SHA-256 digest for the canonical representation.'''
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()
