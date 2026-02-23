# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Shared AFL++ path helpers used by build and runtime modules.'''

from __future__ import annotations

import os


def get_cmplog_build_directory(target_directory: str) -> str:
    '''Return the path to the CmpLog target directory.'''
    return os.path.join(target_directory, 'cmplog')
