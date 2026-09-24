# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Expose the simplified reporting API.'''

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ['build_composite_payload', 'build_payload', 'write_report']


def __getattr__(name: str) -> Any:
    '''Load public reporting entry points without importing unrelated pipelines.'''

    modules = {
        'build_composite_payload': '.composite',
        'build_payload': '.payload',
        'write_report': '.static_report',
    }
    if name in modules:
        return getattr(import_module(modules[name], __name__), name)
    raise AttributeError(name)
