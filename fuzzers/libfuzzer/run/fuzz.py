from __future__ import annotations

import logging
import os
import re
import subprocess

from pathlib import Path
from typing import Any, Dict

from fuzzers import utils


LOG = logging.getLogger(__name__)


def fuzz(input_corpus, output_corpus, target_binary, input_mode: str):
    """Run fuzzer. Wrapper that uses the defaults when calling
    run_fuzzer."""
    run_fuzzer(input_corpus, output_corpus, target_binary)


def run_fuzzer(input_corpus, output_corpus, target_binary, extra_flags=None):
    """Run fuzzer."""
    if extra_flags is None:
        extra_flags = []

    # Seperate out corpus and crash directories as sub-directories of
    # |output_corpus| to avoid conflicts when corpus directory is reloaded.
    crashes_dir = os.path.join(output_corpus, 'crashes')
    output_corpus = os.path.join(output_corpus, 'corpus')
    os.makedirs(crashes_dir, exist_ok=True)
    os.makedirs(output_corpus, exist_ok=True)

    utils.apply_configured_env(utils.get_runtime_env())
    extra_flags = list(utils.get_runtime_args()) + list(extra_flags)

    # Enable symbolization if needed.
    # Note: if the flags are like `symbolize=0:..:symbolize=1` then
    # only symbolize=1 is respected.
    for flag in extra_flags:
        if flag.startswith('-focus_function'):
            if 'ASAN_OPTIONS' in os.environ:
                os.environ['ASAN_OPTIONS'] += ':symbolize=1'
            else:
                os.environ['ASAN_OPTIONS'] = 'symbolize=1'
            if 'UBSAN_OPTIONS' in os.environ:
                os.environ['UBSAN_OPTIONS'] += ':symbolize=1'
            else:
                os.environ['UBSAN_OPTIONS'] = 'symbolize=1'
            break

    flags = [f'-artifact_prefix={crashes_dir}/']
    dictionary_path = utils.get_dictionary_path(target_binary)
    if dictionary_path:
        flags.append('-dict=' + dictionary_path)

    command = [target_binary] + flags + [output_corpus, input_corpus] + extra_flags
    print('Running libFuzzer command:', ' '.join(command))
    subprocess.check_output(command)


def get_output_paths(live_out: Path) -> Dict[str, Any]:
    """Tell the runner where to find corpus/crashes/hangs inside live_out."""
    p = Path(live_out)
    return {
        # The runner hands us the parent output directory. LibFuzzer stores
        # the live corpus in the dedicated corpus/ subdirectory.
        "corpus_root": p / "corpus",
        "crashes_root": p / "crashes",
        "hangs_root": p / "hangs",
    }

# #73348: cov: 44138 ft: 40833 corp: 1553 exec/s: 2237 oom/timeout/crash: 0/0/1 time: 52s job: 8 dft_time: 0
_LIBFUZZER_DONE = re.compile(
    r"^#(?P<execs_done>\d+):.*?exec/s:\s+(?P<execs_per_sec>[0-9.]+).*?time:\s+(?P<time_s>\d+)s",
    re.IGNORECASE | re.MULTILINE,
)

def get_stats(trial_root: Path) -> Dict[str, Any]:
    """Best-effort stats extraction (optional)."""
    return get_stats_until(trial_root)


def get_stats_until(trial_root: Path, *, cutoff_elapsed_s: int | None = None) -> Dict[str, Any]:
    """Best-effort stats extraction up to a logical trial elapsed time."""
    stats_path = Path(trial_root) / "logs" / "fuzzer.log"
    if not stats_path.exists():
        return {}
    try:
        text = stats_path.read_text(encoding="utf-8", errors="ignore")
        latest = None
        for match in _LIBFUZZER_DONE.finditer(text):
            elapsed_s = int(match.group("time_s"))
            if cutoff_elapsed_s is not None and elapsed_s > int(cutoff_elapsed_s):
                continue
            latest = match
        if latest is None:
            return {}
        return {
            "execs_per_sec": float(latest.group("execs_per_sec")),
            "execs_done": float(latest.group("execs_done")),
        }
    except Exception as e:
        LOG.warning("Failed to extract libFuzzer stats: %s", e)
        return {}
