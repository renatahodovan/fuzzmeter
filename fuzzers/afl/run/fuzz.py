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
"""Integration code for AFL fuzzer."""

import json
import os
from pathlib import Path
import shutil
import subprocess

from fuzzers import utils


def get_stats(output_corpus, fuzzer_log):  # pylint: disable=unused-argument
    """Gets fuzzer stats for AFL."""
    # Get a dictionary containing the stats AFL reports.
    stats_file = os.path.join(output_corpus, 'fuzzer_stats')
    if not os.path.exists(stats_file):
        print('Can\'t find fuzzer_stats')
        return '{}'
    with open(stats_file, encoding='utf-8') as file_handle:
        stats_file_lines = file_handle.read().splitlines()
    stats_file_dict = {}
    for stats_line in stats_file_lines:
        key, value = stats_line.split(': ')
        stats_file_dict[key.strip()] = value.strip()

    # Report to FuzzBench the stats it accepts.
    stats = {'execs_per_sec': float(stats_file_dict['execs_per_sec'])}
    return json.dumps(stats)


def prepare_fuzz_environment(input_corpus):
    """Prepare to fuzz with AFL or another AFL-based fuzzer."""
    utils.apply_configured_env(utils.get_runtime_env())

    # AFL needs at least one non-empty seed to start.
    Path(input_corpus).mkdir(parents=True, exist_ok=True)
    utils.create_seed_file_for_empty_corpus(input_corpus)


def check_skip_det_compatible(additional_flags):
    """ Checks if additional flags are compatible with '-d' option"""
    # AFL refuses to take in '-d' with '-M' or '-S' options for parallel mode.
    # (cf. https://github.com/google/AFL/blob/8da80951/afl-fuzz.c#L7477)
    if '-M' in additional_flags or '-S' in additional_flags:
        return False
    return True


def run_afl_fuzz(input_corpus,
                 output_corpus,
                 target_binary,
                 input_mode='file',
                 additional_flags=None,
                 hide_output=False):
    """Run afl-fuzz."""
    # Spawn the afl fuzzing process.
    print('[run_afl_fuzz] Running target with afl-fuzz')
    command = [
        '/out/afl-fuzz',
        '-i',
        input_corpus,
        '-o',
        output_corpus,
        # Use no memory limit as ASAN doesn't play nicely with one.
        '-m',
        'none',
        '-t',
        '1000',  # Use same default 1 sec timeout, but add '+' to skip hangs.
    ]
    # Use '-d' to skip deterministic mode, as long as it it compatible with
    # additional flags.
    if not additional_flags or check_skip_det_compatible(additional_flags):
        command.append('-z')
    if additional_flags:
        command.extend(additional_flags)
    dictionary_path = utils.get_dictionary_path(target_binary)
    if dictionary_path:
        command.extend(['-x', dictionary_path])
    command += ['--', target_binary]

    print('AFL input mode:', input_mode)
    if input_mode == 'file':
        command.append('@@')
    elif input_mode == 'in_process':
        # Pass INT_MAX to afl the maximize the number of persistent loops it
        # performs.
        command.append('2147483647')

    print('[run_afl_fuzz] AFL related envs: ', ' '.join(f"{k}={v}" for k, v in os.environ.items() if "AFL" in k))
    print('[run_afl_fuzz] Running command: ' + ' '.join(command) + " from " + os.getcwd())
    output_stream = subprocess.DEVNULL if hide_output else None
    output_stream = None
    cwd = f'/opt/fuzzmeter/fuzzers/{os.environ["FUZZER"]}'
    subprocess.run(command, cwd=cwd)


def fuzz(input_corpus, output_corpus, target_binary, input_mode: str):
    """Run afl-fuzz on target."""
    prepare_fuzz_environment(input_corpus)

    run_afl_fuzz(input_corpus, output_corpus, target_binary, input_mode)
