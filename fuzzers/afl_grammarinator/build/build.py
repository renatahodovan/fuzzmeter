# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''AFL++ + Grammarinator integration used to build and run GRAFL campaigns.'''

from __future__ import annotations

import logging
import os
import shutil

from pathlib import Path

from fuzzers.aflplusplus.build import build as aflplusplus_build
from fuzzers.grammarinator import common as grammarinator

LOG = logging.getLogger(__name__)


def build(*args: str) -> None:
    '''Build the AFL++ target together with the Grammarinator custom mutator.'''
    out_dir = Path(os.environ['OUT'])
    grafl_lib, _, _ = grammarinator.create_grammarinator_artifacts(
        mode='grafl',
        seed_prefix='afl_grammarinator_seed_',
    )
    LOG.info('Using Grammarinator mutator library: %s', grafl_lib)

    aflplusplus_build.build(*args)

    if not grafl_lib.is_file():
        raise RuntimeError(f'Missing Grammarinator mutator library: {grafl_lib}')
    shutil.copy2(grafl_lib, out_dir / 'grammarinator.so')

