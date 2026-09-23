# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Reproduce crashing inputs and persist classified bug hits.'''

from __future__ import annotations

import hashlib
import json
import logging
import re

from collections import Counter
from pathlib import Path
from typing import Any

from ..db import open_db
from ..db.bug import BugRecord, ensure_bug, upsert_bug_hits
from ..docker import DockerClient, DockerRuntime
from ..trial.models import TrialInstance
from .ingest import DetectedFile

LOG = logging.getLogger(__name__)

_ISSUE_ASAN = re.compile(r'ERROR:\s*AddressSanitizer:\s*([^\s]+)', re.IGNORECASE)
_ISSUE_UBSAN = re.compile(r'runtime error:\s*([^\n]+)', re.IGNORECASE)
_ISSUE_MSAN = re.compile(r'WARNING:\s*MemorySanitizer:\s*([^\n]+)', re.IGNORECASE)
_ANY_FUNC = re.compile(r'^\s*#\d+\s+0x[0-9a-fA-F]+\s+in\s+([^\s(]+).*?/src/')
_MAX_COMPONENT = 120
# Workers run on Linux; the host's signal numbers can differ (e.g. macOS SIGBUS).
_CRASH_SIGNALS = {4, 5, 6, 7, 8, 11}  # SIGILL, SIGTRAP, SIGABRT, SIGBUS, SIGFPE, SIGSEGV.


def save_crash_hits(
    *,
    db_path: Path,
    run_id: str,
    trial: TrialInstance,
    snapshot_id: int,
    reproduced: list[tuple[str, dict[str, Any], int]],
) -> None:
    '''Persist the combined reproduction results of one complete snapshot.'''
    config = trial.config
    hits, bug_data_by_key = _collect_bug_hits(reproduced)

    with open_db(db_path) as db:
        for bug_key, count in hits.items():
            bug_data = bug_data_by_key[bug_key]
            metadata = bug_data['metadata']
            bug_id = ensure_bug(
                db,
                BugRecord(
                    run_id=run_id,
                    fuzzer=config.case.fuzzer.id,
                    benchmark=config.fuzz_target.benchmark.name,
                    fuzz_target=config.fuzz_target.fuzz_target,
                    bug_key=bug_key,
                    issue_type=metadata['issue_type'],
                    top_func=metadata['top_func'],
                    frames=metadata['frames'],
                    output=metadata['output'],
                    first_seen_ts=bug_data['first_seen_ts'],
                    first_seen_snapshot_id=snapshot_id,
                ),
            )
            upsert_bug_hits(db, bug_id=bug_id, snapshot_id=snapshot_id, hits=count)


def _collect_bug_hits(
    reproduced: list[tuple[str, dict[str, Any], int]],
) -> tuple[Counter, dict[str, dict[str, Any]]]:
    hits: Counter = Counter()
    bug_data_by_key: dict[str, dict[str, Any]] = {}

    for bug_key, bug_metadata, first_seen_ts in reproduced:
        hits[bug_key] += 1
        bug_data = bug_data_by_key.get(bug_key)
        if bug_data is None or first_seen_ts < bug_data['first_seen_ts']:
            bug_data_by_key[bug_key] = {'metadata': bug_metadata, 'first_seen_ts': first_seen_ts}

    return hits, bug_data_by_key


def reproduce_crash_batch(
    *,
    docker_runtime: DockerRuntime,
    trial: TrialInstance,
    snapshot_crashes_dir: Path,
    crash_tests: list[DetectedFile],
    batch_index: int,
    tick_idx: int,
) -> list[tuple[str, dict[str, Any], int]]:
    '''Reproduce a crash batch without persisting partial snapshot hit counts.'''
    docker = DockerClient(docker_runtime)
    batch_root = (
        snapshot_crashes_dir.parent
        / '.artifacts'
        / 'crash-repro'
        / 'batches'
        / f'{batch_index:06d}'
    )
    batch_root.mkdir(parents=True, exist_ok=True)
    input_list = batch_root / 'inputs.txt'
    output_json = batch_root / 'results.json'

    crash_inputs = []
    for new_file in crash_tests:
        crash_input = snapshot_crashes_dir / new_file.rel_path
        crash_inputs.append(docker.container_path(crash_input if crash_input.is_file() else new_file.abs_src))
    input_list.write_text('\n'.join(crash_inputs) + '\n', encoding='utf-8')

    docker.run(
        image=trial.config.case.images.asan,
        name=f'fm-{docker_runtime.run_id or "run"}-crash-{tick_idx}-{trial.config.trial_key}-{batch_index:06d}',
        volumes=[docker.out_volume()],
        env={
            'FM_TARGET_NAME': trial.config.fuzz_target.fuzz_target,
            'FM_INPUT_MODE': trial.config.fuzz_target.input_mode,
            'FM_TIMEOUT_S': str(trial.config.fuzz_target.target_timeout_s * 2),
            'FM_CRASH_INPUT_LIST': docker.container_path(input_list),
            'FM_CRASH_OUTPUT_JSON': docker.container_path(output_json),
        },
        check=True,
        kind='crash',
        trial_key=trial.config.trial_key,
        cmd=['python3', '/opt/fuzzmeter/crash_worker.py'],
    )

    outputs = json.loads(output_json.read_text(encoding='utf-8', errors='replace'))
    if len(outputs) != len(crash_tests):
        LOG.warning(
            'Crash repro worker returned %d outputs for %d inputs in %s',
            len(outputs),
            len(crash_tests),
            output_json,
        )

    results: list[tuple[str, dict[str, Any], int]] = []
    for new_file, worker_output in zip(crash_tests, outputs, strict=False):
        output = (worker_output.get('stdout') or '') + (worker_output.get('stderr') or '')
        classified = _classify_crash_output(
            new_file=new_file,
            output=output,
            returncode=worker_output['returncode'],
            timed_out=worker_output['timeout'],
            artifact_dir=snapshot_crashes_dir.parent / '.artifacts' / 'crash-repro',
        )
        if classified is not None:
            results.append(classified)

    return results


def _classify_crash_output(
    *,
    new_file: DetectedFile,
    output: str,
    returncode: int,
    timed_out: bool,
    artifact_dir: Path,
) -> tuple[str, dict[str, Any], int] | None:
    issue = None
    for regex in (_ISSUE_ASAN, _ISSUE_MSAN, _ISSUE_UBSAN):
        match = regex.search(output)
        if match:
            issue = match.group(1).strip()
            break

    if timed_out or (issue is None and -returncode not in _CRASH_SIGNALS):
        LOG.warning('Crash did not reproduce for %s: returncode=%s, timeout=%s',
                    new_file.abs_src, returncode, timed_out)
        return None
    issue = issue or 'crash'

    frames: list[str] = []
    for line in output.splitlines():
        match = _ANY_FUNC.match(line)
        if match:
            frames.append(match.group(1).strip())
            if len(frames) >= 5:
                break

    top_func = frames[0] if frames else 'unknown'
    bug_key = f'{issue}|{",".join(frames)}'

    safe_input_id = re.sub(r'\s+', '_', new_file.rel_path.replace('/', '_').replace('\\', '_'))
    if len(safe_input_id) > _MAX_COMPONENT:
        safe_input_id = (
            safe_input_id[:_MAX_COMPONENT]
            + '_'
            + hashlib.sha1(new_file.rel_path.encode()).hexdigest()[:12]
        )
    output_dir = artifact_dir / safe_input_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'output.log').write_text(output, encoding='utf-8', errors='replace')

    first_seen_ts = int(new_file.mtime_ns // 1_000_000_000)
    return (
        bug_key,
        {
            'issue_type': issue,
            'top_func': top_func,
            'frames': frames,
            'output': output,
        },
        first_seen_ts,
    )
