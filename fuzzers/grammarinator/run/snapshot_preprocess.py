#!/usr/bin/env python3
# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Decode Grammarinator tree corpora before coverage reproduction.'''

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import traceback

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


LOG = logging.getLogger(__name__)
RUNNER_OUT_ROOT = Path('/tmp/fuzzmeter/out')
MUTATOR_RE = re.compile(r'(?:^|,)execs:\d+,(?:op:)?([^,]+)')
MUTATOR_MANIFEST = '.fuzzmeter_mutators.json'
DECODE_FAILURE_MANIFEST = '.fuzzmeter_decode_failures.json'


def _container_path(path: Path, root: Path) -> str:
    return f'/data/{path.relative_to(root)}'


def _map_to_host(path: Path) -> Path:
    out_src = os.environ.get('FM_OUT_SRC', '').strip()
    if not out_src:
        return path
    out_src_path = Path(out_src)
    if not out_src_path.is_absolute():
        return path
    try:
        rel = path.resolve().relative_to(RUNNER_OUT_ROOT.resolve())
    except Exception:
        return path
    return out_src_path / rel


def _collect_mutator_counts(input_root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not input_root.is_dir():
        return counts
    for path in input_root.rglob('*'):
        if not path.is_file():
            continue
        match = MUTATOR_RE.search(path.name)
        if not match:
            continue
        mutator = match.group(1).strip()
        if not mutator or mutator.startswith('orig:'):
            continue
        counts[mutator] = counts.get(mutator, 0) + 1
    return counts


def _is_snapshot_input_file(path: Path, root: Path) -> bool:
    if not path.is_file():
        return False
    rel_path = path.relative_to(root)
    return all(not part.startswith('.') for part in rel_path.parts)


def main() -> None:
    '''Decode snapshot corpus files in-place when they are Grammarinator trees.'''
    logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')

    fuzzer = os.environ['FM_FUZZER']
    if fuzzer == 'grammarinator':
        return

    fuzz_target = os.environ['FM_FUZZ_TARGET']
    runner_image = os.environ['FM_RUNNER_IMAGE']
    snapshot_dir = Path(os.environ['FM_SNAPSHOT_DIR']).resolve()
    corpus_dir = Path(os.environ.get('FM_SNAPSHOT_CORPUS_DIR', snapshot_dir / 'corpus')).resolve()
    jobs = int(os.environ.get('FM_JOBS', '1'))
    tmp_dir = corpus_dir.with_name(f'{corpus_dir.name}_tmp')
    host_snapshot_dir = _map_to_host(corpus_dir)
    host_tmp_dir = _map_to_host(tmp_dir)
    LOG.debug(
        'Decoding snapshot corpus %s using host mount %s (tmp=%s host_tmp=%s)',
        corpus_dir,
        host_snapshot_dir,
        tmp_dir,
        host_tmp_dir,
    )

    shutil.rmtree(tmp_dir, ignore_errors=True)
    if tmp_dir.exists():
        raise SystemExit(f'Temporary decode dir still exists: {tmp_dir}')

    corpus_dir.rename(tmp_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)

    input_files = sorted(p for p in tmp_dir.rglob('*') if _is_snapshot_input_file(p, tmp_dir))
    if not input_files:
        tmp_dir.rename(corpus_dir)
        return

    mutator_counts = _collect_mutator_counts(tmp_dir)
    (snapshot_dir / MUTATOR_MANIFEST).write_text(
        json.dumps(
            {
                'source': 'preprocess_tmp_corpus',
                'mutator_counts': mutator_counts,
                'total_files': sum(mutator_counts.values()),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    mount_root = host_snapshot_dir.parent
    decode_bin = f'/out/grammarinator-decode-{fuzz_target}'
    LOG.debug('Decoding %d snapshot trees with %s with %d jobs', len(input_files), decode_bin, jobs)

    def _chunks(seq, n):
        if n <= 0:
            raise ValueError('n must be > 0')
        chunk_size = math.ceil(len(seq) / n)
        return [seq[i : i + chunk_size] for i in range(0, len(seq), chunk_size)]


    def _decode_command(batch_files):
        return [
            'docker',
            'run',
            '--rm',
            '-v',
            f'{mount_root}:/data',
            runner_image,
            decode_bin,
            '-o',
            _container_path(host_snapshot_dir, mount_root),
            *[
                _container_path(host_tmp_dir / path.relative_to(tmp_dir), mount_root)
                for path in batch_files
            ],
        ]


    def _run_decode_batch(batch_files):
        result = subprocess.run(_decode_command(batch_files), check=False, capture_output=True, text=True)
        if result.returncode == 0:
            return []

        if len(batch_files) == 1:
            output = (result.stdout or '') + '\n' + (result.stderr or '')
            rel_path = batch_files[0].relative_to(tmp_dir)
            LOG.warning('Failed to decode snapshot corpus file %s with exit code %s', rel_path, result.returncode)
            return [{
                'path': str(rel_path),
                'returncode': result.returncode,
                'output': output.strip(),
            }]

        middle = max(1, len(batch_files) // 2)
        return [
            *_run_decode_batch(batch_files[:middle]),
            *_run_decode_batch(batch_files[middle:]),
        ]

    try:
        if len(input_files) > 1 and jobs > 1:
            batches = _chunks(input_files, min(jobs, len(input_files)))

            with ThreadPoolExecutor(max_workers=len(batches)) as executor:
                decode_failures = [
                    failure
                    for failures in executor.map(_run_decode_batch, batches)
                    for failure in failures
                ]
        else:
            decode_failures = _run_decode_batch(input_files)
    except Exception:
        _write_preprocess_error(snapshot_dir=snapshot_dir)
        shutil.rmtree(corpus_dir, ignore_errors=True)
        if tmp_dir.exists():
            tmp_dir.rename(corpus_dir)
        raise
    else:
        if decode_failures:
            (snapshot_dir / DECODE_FAILURE_MANIFEST).write_text(
                json.dumps(decode_failures, indent=2, ensure_ascii=False),
                encoding='utf-8',
            )
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _write_preprocess_error(*, snapshot_dir: Path) -> None:
    try:
        (snapshot_dir / '.fuzzmeter_preprocess_error.log').write_text(traceback.format_exc(), encoding='utf-8')
    except Exception:
        LOG.exception('Failed to write snapshot preprocess error log')


if __name__ == '__main__':
    main()
