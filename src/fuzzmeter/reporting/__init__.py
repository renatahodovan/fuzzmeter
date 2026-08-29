# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Expose the simplified reporting API.'''

from __future__ import annotations

from .composite import build_composite_payload
from .payload import build_payload
from .static_report import write_report

__all__ = ['build_composite_payload', 'build_payload', 'write_report']
