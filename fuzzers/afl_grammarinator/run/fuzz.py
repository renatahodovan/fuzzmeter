# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''AFL++ + Grammarinator integration used to build and run GRAFL campaigns.'''

from __future__ import annotations

import logging

from pathlib import Path
from typing import Any, Dict

from fuzzers import utils
from fuzzers.aflplusplus.run import fuzz as aflplusplus_fuzzer

LOG = logging.getLogger(__name__)


def fuzz(input_corpus: str, output_corpus: str, target_binary: str, input_mode: str) -> None:
    '''Run AFL++ with the Grammarinator custom mutator enabled.'''
    cfg = utils.get_experiment_fuzzer_config()
    utils.apply_configured_env(cfg.get('env', {}))
    mutator_library = Path('/out/grammarinator.so')
    if not mutator_library.is_file():
        raise RuntimeError(f'Missing AFL custom mutator library in runner image: {mutator_library}')
    aflplusplus_fuzzer.fuzz(input_corpus, output_corpus, target_binary, input_mode)


def get_output_paths(live_out: Path) -> Dict[str, Any]:
    '''Return AFL++ output directories for live trial collection.'''
    return aflplusplus_fuzzer.get_output_paths(live_out)


def get_stats(trial_root: Path) -> Dict[str, Any]:
    '''Return AFL++ statistics extracted from the trial workspace.'''
    return aflplusplus_fuzzer.get_stats(trial_root)
