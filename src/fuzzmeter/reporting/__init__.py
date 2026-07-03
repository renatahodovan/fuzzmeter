# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Expose the simplified reporting API.'''

from __future__ import annotations

from .export import write_report
from .composite import build_composite_payload
from .payload import build_payload

__all__ = ['build_composite_payload', 'build_payload', 'write_report']
