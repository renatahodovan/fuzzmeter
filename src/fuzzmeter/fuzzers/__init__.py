# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Expose fuzzer adapter loading and hook interfaces."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .loader import FuzzerLoader, FuzzerModule
from .models import OutputPaths

__all__ = [
    'FuzzerLoader',
    'FuzzerModule',
    'HookRunner',
    'HookSpec',
    'OutputPaths',
]


def __getattr__(name: str) -> Any:
    '''Load hook interfaces only for callers that use hook execution.'''

    if name in {'HookRunner', 'HookSpec'}:
        return getattr(import_module('.hooks', __name__), name)
    raise AttributeError(name)
