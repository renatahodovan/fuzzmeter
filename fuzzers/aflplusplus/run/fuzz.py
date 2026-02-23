from __future__ import annotations

import os
import subprocess

from pathlib import Path
from typing import Any, Dict

from fuzzers import utils

# Optional benchmark metadata is exposed to fuzzer builds via FM_BENCHMARK_YAML.


# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""Integration code for AFLplusplus fuzzer."""

import os
import shutil

from fuzzers.afl.run import fuzz as afl_fuzzer
from fuzzers import utils
from fuzzers.aflplusplus.common import get_cmplog_build_directory

# Optional benchmark metadata is exposed to fuzzer builds via FM_BENCHMARK_YAML.


# pylint: disable=too-many-arguments
def fuzz(input_corpus,
         output_corpus,
         target_binary,
         input_mode: str,
         flags=tuple(),
         skip=False,
         no_cmplog=False):  # pylint: disable=too-many-arguments
    """Run fuzzer."""
    # Calculate CmpLog binary path from the instrumented target binary.
    target_binary_directory = os.path.dirname(target_binary)
    cmplog_target_binary_directory = (
        get_cmplog_build_directory(target_binary_directory))
    target_binary_name = os.path.basename(target_binary)
    cmplog_target_binary = os.path.join(cmplog_target_binary_directory,
                                        target_binary_name)

    afl_fuzzer.prepare_fuzz_environment(input_corpus)
    # decomment this to enable libdislocator.
    # os.environ['AFL_ALIGNED_ALLOC'] = '1' # align malloc to max_align_t
    # os.environ['AFL_PRELOAD'] = '/afl/libdislocator.so'
    # os.environ['AFL_DEBUG'] = '1'
    # os.environ['AFL_DEBUG_CHILD'] = '1'

    flags = list(flags)

    # dictionary_path = utils.get_dictionary_path(target_binary)
    # if dictionary_path:
    #     flags += ['-x', dictionary_path]
    if os.path.exists('./afl++.dict'):
        flags += ['-x', './afl++.dict']

    # Move the following to skip for upcoming _double tests:
    if os.path.exists(cmplog_target_binary) and no_cmplog is False:
        flags += ['-c', cmplog_target_binary]

    utils.apply_configured_env(utils.get_runtime_env())

    # if not skip:
    #     if 'ADDITIONAL_ARGS' in os.environ:
    #         flags += os.environ['ADDITIONAL_ARGS'].split(' ')

    afl_fuzzer.run_afl_fuzz(input_corpus,
                            output_corpus,
                            target_binary,
                            input_mode=input_mode,
                            additional_flags=flags)


def get_output_paths(live_out: Path) -> Dict[str, Any]:
    p = Path(live_out)
    # AFL++ writes into out_dir/default/{queue,crashes,hangs}
    return {
        "corpus_root": p / "default" / "queue",
        "crashes_root": p / "default" / "crashes",
        "hangs_root": p / "default" / "hangs",
    }


def get_stats(trial_root: Path) -> Dict[str, Any]:
    p = _stats_file(trial_root)
    if not p.exists():
        print(f"[aflplusplus] {p} doesn't exist.")
        return {}
    stats: Dict[str, str] = {}
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    k, v = k.strip(), v.strip()
                    if k in ["execs_done", "execs_per_sec"]:
                        stats[k] = float(v)
        return stats
    except Exception:
        pass
    return {}


def get_stats_until(trial_root: Path, *, cutoff_elapsed_s: int | None = None) -> Dict[str, Any]:
    if cutoff_elapsed_s is None:
        return get_stats(trial_root)

    p = _plot_data_file(trial_root)
    if not p.exists():
        return get_stats(trial_root)

    latest: dict[str, float] | None = None
    first_after: dict[str, float] | None = None
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [part.strip() for part in line.split(",")]
                if len(parts) < 12:
                    continue
                relative_time = int(float(parts[0]))
                parsed = {
                    "execs_per_sec": float(parts[10]),
                    "execs_done": float(parts[11]),
                }
                if relative_time > int(cutoff_elapsed_s):
                    if first_after is None:
                        first_after = parsed
                    continue
                latest = parsed
    except Exception:
        latest = None
        first_after = None
    return latest or first_after or {}


def _stats_file(trial_root: Path) -> Path:
    return Path(trial_root) / "work" / "default" / "fuzzer_stats"


def _plot_data_file(trial_root: Path) -> Path:
    return Path(trial_root) / "work" / "default" / "plot_data"
