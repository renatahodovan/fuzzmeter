# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Build the target binary used for LLVM source-based coverage measurement."""

from __future__ import annotations

import json
import os
import subprocess

from pathlib import Path

from fuzzmeter.resources.instrumentation import utils

COVERAGE_BUILD_METADATA_PATH = Path('/opt/fuzzmeter/meta/coverage-build.json')
COVERAGE_CFLAGS = [
    '-fprofile-instr-generate',
    '-fprofile-update=atomic',
    '-fcoverage-mapping',
    '-gline-tables-only',
    # '-fsanitize=fuzzer-no-link',
]


def build():
    """Build the coverage binary and record the compiler settings requested."""
    utils.append_flags('CFLAGS', COVERAGE_CFLAGS)
    utils.append_flags('CXXFLAGS', COVERAGE_CFLAGS)

    os.environ['CC'] = '/usr/bin/clang-18'
    os.environ['CXX'] = '/usr/bin/clang++-18'
    os.environ['FUZZER_LIB'] = '/opt/fuzzmeter/tools/lib/libFuzzer.a'
    utils.apply_configured_env(utils.get_build_env())

    COVERAGE_BUILD_METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    COVERAGE_BUILD_METADATA_PATH.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'type': 'fuzzmeter.coverage.build',
                'requested_cflags': os.environ.get('CFLAGS', ''),
                'requested_cxxflags': os.environ.get('CXXFLAGS', ''),
                'clang_version': subprocess.check_output(
                    [os.environ['CC'], '--version'],
                    text=True,
                ).strip(),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding='utf-8',
    )
    utils.build_benchmark()
