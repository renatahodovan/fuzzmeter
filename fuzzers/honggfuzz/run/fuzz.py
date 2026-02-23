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
"""Integration code for Honggfuzz fuzzer."""

import os
import shutil
import subprocess

from pathlib import Path
from typing import Any, Dict

from fuzzers import utils


def fuzz(input_corpus, output_corpus, target_binary, input_mode: str):
    """Run fuzzer."""
    # Seperate out corpus and crash directories as sub-directories of
    # |output_corpus| to avoid conflicts when corpus directory is reloaded.
    output_dir = os.path.join(output_corpus, 'corpus')
    crashes_dir = os.path.join(output_corpus, 'crashes')
    workspace_dir = os.path.join(output_corpus, 'workspace')
    stats_file = os.path.join(output_corpus, 'stats.txt')
    log_file = os.path.join(output_corpus, 'log.txt')
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(crashes_dir, exist_ok=True)
    os.makedirs(workspace_dir, exist_ok=True)

    print('[fuzz] Running target with honggfuzz')
    command = [
        '/out/honggfuzz',
        '--threads', '1',
        '--rlimit_rss',
        '2048',
        '--sanitizers_del_report=true',
        '--input',
        input_corpus,
        '--output',
        output_dir,
        '--workspace',
        workspace_dir,

        # Store crashes along with corpus for bug based benchmarking.
        '--crashdir',
        crashes_dir,
        '--statsfile',
        stats_file,
        '--logfile',
        log_file,
    ]
    dictionary_path = utils.get_dictionary_path(target_binary)
    if dictionary_path:
        command.extend(['--dict', dictionary_path])
    command.extend(['--', target_binary])
    
    if input_mode == 'file':
        command.append('___FILE___')

    print('[fuzz] Running command: ' + ' '.join(command))
    subprocess.check_call(command)

def get_output_paths(live_out: Path) -> Dict[str, Any]:
    p = Path(live_out)
    return {
        "corpus_root": p / "corpus",
        "crashes_root": p / "crashes",
    }

def get_stats(trial_root: Path) -> Dict[str, Any]:
    p = Path(trial_root) / "work" / "stats.txt"
    if not p.exists():
        print(f"[honggfuzz] {p} doesn't exist.")
        return {}
    
    stats: Dict[str, str] = {}
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            last_line = lines[-1]
            # unix_time, last_cov_update, total_exec, exec_per_sec, crashes, unique_crashes, hangs, edge_cov, block_cov
            items = last_line.split(',')
            stats['execs_done'] = int(items[2].strip())
        return stats
    except Exception:
        pass
    return {}
