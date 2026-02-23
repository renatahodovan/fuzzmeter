# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Fuzzmeter integration for standalone Grammarinator blackbox fuzzing.'''

import logging

from fuzzers.grammarinator import common as grammarinator
from fuzzers.libfuzzer.build import build as libfuzzer_build


LOG = logging.getLogger(__name__)


def build(*args: str) -> None:
    '''Build the benchmark and the standalone Grammarinator generator.'''
    generator_bin = grammarinator.create_grammarinator_generator_artifact()
    LOG.info('Using Grammarinator generator binary: %s', generator_bin)
    libfuzzer_build.build(*args)

