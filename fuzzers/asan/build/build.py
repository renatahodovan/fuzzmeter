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
    SANITIZER_FLAGS = [
        '-fsanitize=address',
        '-fsanitize=array-bounds,bool,builtin,enum,float-divide-by-zero,function,'
        'integer-divide-by-zero,null,object-size,return,returns-nonnull-attribute,'
        'shift,signed-integer-overflow,unreachable,vla-bound,vptr',
        '-fno-sanitize-recover=array-bounds,bool,builtin,enum,float-divide-by-zero,'
        'function,integer-divide-by-zero,null,object-size,return,'
        'returns-nonnull-attribute,shift,signed-integer-overflow,unreachable,'
        'vla-bound,vptr',
    ]
    cflags = ['-O1', '-g', '-fno-omit-frame-pointer', '-fno-optimize-sibling-calls'] + SANITIZER_FLAGS

    utils.append_flags('CFLAGS', cflags)
    utils.append_flags('CXXFLAGS', cflags)
    utils.append_flags('LDFLAGS', ['-fsanitize=address'])

    os.environ['CC'] = '/usr/bin/clang-18'
    os.environ['CXX'] = '/usr/bin/clang++-18'
    os.environ['FUZZER_LIB'] = '/opt/fuzzmeter/tools/lib/libFuzzer.a'
    utils.apply_configured_env(utils.get_build_env())

    utils.build_benchmark()

