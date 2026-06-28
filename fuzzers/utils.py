# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Compatibility module alias for fuzzer scripts not yet migrated.'''

from __future__ import annotations

import sys

from fuzzmeter.resources.instrumentation import utils

sys.modules[__name__] = utils
