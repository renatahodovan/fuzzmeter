# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Fuzzmeter integration for standalone Grammarinator blackbox fuzzing.'''

from __future__ import annotations

import os
import shlex
import shutil
import zipfile

from pathlib import Path
from typing import Any

import logging

from fuzzers import utils
from fuzzers.blackbox.run import fuzz as blackbox_fuzzer


LOG = logging.getLogger(__name__)


def fuzz(input_corpus: str, output_corpus: str, target_binary: str, input_mode: str) -> None:
    '''Run Grammarinator as a blackbox test generator.'''
    population_dir = _prepare_population(input_corpus=input_corpus, output_corpus=output_corpus, target_binary=target_binary)
    blackbox_fuzzer.fuzz_blackbox(
        input_corpus=input_corpus,
        output_corpus=output_corpus,
        target_binary=target_binary,
        input_mode=input_mode,
        generator_command=_generator_command(population_dir),
        target_args=['-runs=1', '@@'],
    )


def get_output_paths(live_out: Path) -> dict[str, Any]:
    '''Return blackbox output directories for live trial collection.'''
    return blackbox_fuzzer.get_output_paths(live_out)


def get_stats(trial_root: Path) -> dict[str, Any]:
    '''Return persisted blackbox statistics.'''
    return blackbox_fuzzer.get_stats(trial_root)


def get_stats_until(trial_root: Path, *, cutoff_elapsed_s: int | None = None) -> dict[str, Any]:
    '''Return persisted blackbox statistics up to the selected elapsed time.'''
    return blackbox_fuzzer.get_stats_until(trial_root, cutoff_elapsed_s=cutoff_elapsed_s)


def snapshot_preprocess_script() -> Path | None:
    '''Return no snapshot preprocessor because blackbox outputs are source-level tests.'''
    return None


def _prepare_population(*, input_corpus: str, output_corpus: str, target_binary: str) -> Path:
    population_dir = Path(output_corpus) / 'state' / 'population'
    shutil.rmtree(population_dir, ignore_errors=True)
    population_dir.mkdir(parents=True, exist_ok=True)

    target_name = os.environ.get('FM_TARGET_NAME') or os.environ.get('TARGET_NAME') or os.environ.get('FUZZ_TARGET')
    tree_archive = Path('/out') / f'{target_name or Path(target_binary).name}_seed_tree_corpus.zip'
    if tree_archive.is_file():
        with zipfile.ZipFile(tree_archive, 'r') as archive:
            _extract_archive(archive=archive, out_dir=population_dir)
    elif Path(input_corpus).exists() and any(Path(input_corpus).iterdir()):
        LOG.warning('Missing Grammarinator seed tree corpus archive: %s', tree_archive)
    return population_dir


def _extract_archive(*, archive: zipfile.ZipFile, out_dir: Path) -> None:
    resolved_out_dir = out_dir.resolve()
    for info in archive.infolist():
        if info.is_dir():
            continue
        out_path = (out_dir / info.filename).resolve()
        if resolved_out_dir not in (out_path, *out_path.parents):
            LOG.warning('Skipping unsafe population path: %s', info.filename)
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as src, out_path.open('wb') as dst:
            shutil.copyfileobj(src, dst)


def _generator_command(population_dir: Path) -> list[str]:
    command = [
        '/out/grammarinator-generate',
        '--out', '{batch_dir}/test_%d',
        '-n', '{batch_size}',
        '--population', str(population_dir),
    ]
    for arg in utils.get_runtime_args():
        command.extend(shlex.split(arg))
    return command
