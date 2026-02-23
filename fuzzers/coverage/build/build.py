# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import os

from fuzzers import utils


def build():
    cflags = [
        '-fprofile-instr-generate',
        '-fcoverage-mapping',
        '-gline-tables-only',
        # '-fsanitize=fuzzer-no-link',
    ]
    utils.append_flags('CFLAGS', cflags)
    utils.append_flags('CXXFLAGS', cflags)

    os.environ['CC'] = '/usr/bin/clang-18'
    os.environ['CXX'] = '/usr/bin/clang++-18'
    os.environ['FUZZER_LIB'] = '/opt/fuzzmeter/tools/lib/libFuzzer.a'
    utils.apply_configured_env(utils.get_build_env())

    utils.build_benchmark()

