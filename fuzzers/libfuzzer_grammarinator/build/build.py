# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

import os

from fuzzers import utils
from fuzzers.grammarinator import common as grammarinator

def build(*args: str) -> None:
    grlf_lib, _, _ = grammarinator.create_grammarinator_artifacts(
        mode="grlf",
        seed_prefix="libfuzzer_grammarinator_seed_",
    )
    if not grlf_lib.is_file():
        raise RuntimeError(f"Missing Grammarinator mutator library: {grlf_lib}")

    cflags = ['-fsanitize=fuzzer-no-link']
    lf_flags = [
        '-include', '/src/grammarinator_libfuzzer_integration.hpp',
        '-I/grammarinator/grammarinator-cxx/libgrammarinator/include/',
        '-I/grammarinator/grammarinator-cxx/libgrlf/include/',
    ]
    utils.append_flags('CFLAGS', cflags)
    utils.append_flags('CXXFLAGS', cflags)
    utils.append_flags("LIBFUZZER_FLAGS", lf_flags)

    os.environ['CC'] = '/usr/bin/clang-18'
    os.environ['CXX'] = '/usr/bin/clang++-18'
    os.environ['FUZZER_LIB'] = f'/opt/fuzzmeter/tools/lib/libFuzzer.a {grlf_lib}'

    utils.build_benchmark()

