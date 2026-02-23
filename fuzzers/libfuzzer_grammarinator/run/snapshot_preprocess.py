#!/usr/bin/env python3
# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Decode GRLF snapshot corpora through the shared Grammarinator preprocessor.'''

from __future__ import annotations

from fuzzers.grammarinator.run import snapshot_preprocess as grammarinator_preprocess


if __name__ == '__main__':
    grammarinator_preprocess.main()
