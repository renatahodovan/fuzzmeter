# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

import importlib
import os

from fuzzers import utils


def main() -> None:
    '''Dispatch the fuzzer-specific build with benchmark metadata loaded.'''
    fuzzer = os.environ['FUZZER']
    utils.initialize_env()
    mod = importlib.import_module(f'fuzzers.{fuzzer}.build.build')
    mod.build()


if __name__ == '__main__':
    main()
