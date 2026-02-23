# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Run libFuzzer with the Grammarinator custom mutator integration.'''

from __future__ import annotations

from pathlib import Path

from fuzzers.libfuzzer.run import fuzz as libfuzzer_fuzzer


def fuzz(input_corpus: str, output_corpus: str, target_binary: str, input_mode: str) -> None:
    '''Run the target with libFuzzer and Grammarinator runtime configuration.'''
    libfuzzer_fuzzer.run_fuzzer(input_corpus, output_corpus, target_binary)


def get_output_paths(live_out: Path) -> dict[str, object]:
    '''Return live corpus, crash, and hang directories for the runner.'''
    return libfuzzer_fuzzer.get_output_paths(live_out)


def get_stats(trial_root: Path) -> dict[str, object]:
    '''Return best-effort libFuzzer statistics for a trial.'''
    return libfuzzer_fuzzer.get_stats(trial_root)


def get_stats_until(trial_root: Path, *, cutoff_elapsed_s: int | None = None) -> dict[str, object]:
    '''Return best-effort libFuzzer statistics up to a logical elapsed time.'''
    return libfuzzer_fuzzer.get_stats_until(trial_root, cutoff_elapsed_s=cutoff_elapsed_s)
