# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import importlib
import os


def main():
    fuzzer = os.environ['FUZZER']
    mod = importlib.import_module(f'fuzzers.{fuzzer}.run.fuzz')

    input_dir = os.environ['FM_INPUT']
    output_dir = os.environ['FM_OUTPUT']
    target_bin = os.environ.get('FM_TARGET_BIN', 'file')
    input_mode = os.environ['FM_INPUT_MODE']

    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    if hasattr(mod, 'fuzz'):
        mod.fuzz(input_dir, output_dir, target_bin, input_mode)
    else:
        raise RuntimeError('No fuzz entrypoint')


if __name__ == '__main__':
    main()
