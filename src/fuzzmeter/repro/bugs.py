# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import hashlib
import json
import logging
import re

from collections import Counter
from pathlib import Path

from ..db import DB
from ..db.bug import ensure_bug, get_bug_id, upsert_bug_hits
from ..docker import DockerClient, DockerRuntime
from ..trial.models import TrialInstance
from .ingest import DetectedFile

LOG = logging.getLogger(__name__)

_ISSUE_ASAN = re.compile(r'ERROR:\s*AddressSanitizer:\s*([^\s]+)', re.IGNORECASE)
_ISSUE_UBSAN = re.compile(r'runtime error:\s*([^\n]+)', re.IGNORECASE)
_ISSUE_MSAN = re.compile(r'WARNING:\s*MemorySanitizer:\s*([^\n]+)', re.IGNORECASE)
_ANY_FUNC = re.compile(r'^\s*#\d+\s+0x[0-9a-fA-F]+\s+in\s+([^\s(]+).*?/src/')
_MAX_COMPONENT = 120


def reproduce_new_crashes(
    *,
    db: DB,
    docker_runtime: DockerRuntime,
    run_id: str,
    trial: TrialInstance,
    snapshot_id: int,
    ts: int,
    snapshot_crashes_dir: Path,
    new_crash_files: list[DetectedFile],
    repro_logs_dir: Path,
    batch_index: int,
) -> None:
    '''Reproduce new crashes in the sanitizer image and persist bug hits.'''
    if not new_crash_files:
        return

    repro_logs_dir.mkdir(parents=True, exist_ok=True)

    hits: Counter = Counter()
    metadata: dict[str, dict] = {}
    first_seen_by_bug: dict[str, int] = {}
    for bug_key, bug_metadata, first_seen_ts in _reproduce_crash_batch(
        docker_runtime=docker_runtime,
        trial=trial,
        snapshot_crashes_dir=snapshot_crashes_dir,
        new_files=new_crash_files,
        repro_logs_dir=repro_logs_dir,
        batch_index=batch_index,
    ):
        hits[bug_key] += 1
        previous_first_seen_ts = first_seen_by_bug.get(bug_key)
        if previous_first_seen_ts is None or int(first_seen_ts) < previous_first_seen_ts:
            metadata[bug_key] = bug_metadata
            first_seen_by_bug[bug_key] = int(first_seen_ts)

    for bug_key, count in hits.items():
        bug_id = get_bug_id(
            db,
            run_id=run_id,
            fuzzer=trial.config.fuzzer,
            benchmark=trial.config.benchmark,
            fuzz_target=trial.config.fuzz_target,
            bug_key=bug_key,
        )
        if bug_id is None:
            bug_id = ensure_bug(
                db,
                run_id=run_id,
                fuzzer=trial.config.fuzzer,
                benchmark=trial.config.benchmark,
                fuzz_target=trial.config.fuzz_target,
                bug_key=bug_key,
                issue_type=metadata[bug_key].get('issue_type'),
                top_func=metadata[bug_key].get('top_func'),
                frames=metadata[bug_key].get('frames') or [],
                output=metadata[bug_key].get('output'),
                first_seen_ts=first_seen_by_bug.get(bug_key, int(ts)),
                first_seen_snapshot_id=snapshot_id,
            )
        upsert_bug_hits(db, bug_id=bug_id, snapshot_id=snapshot_id, hits=count)

    db.commit()


def _reproduce_crash_batch(
    *,
    docker_runtime: DockerRuntime,
    trial: TrialInstance,
    snapshot_crashes_dir: Path,
    new_files: list[DetectedFile],
    repro_logs_dir: Path,
    batch_index: int,
) -> list[tuple[str, dict, int]]:
    if not new_files:
        return []

    docker = DockerClient(docker_runtime)
    batch_root = snapshot_crashes_dir.parent / '.crash_repro_batches' / f'{batch_index:06d}'
    batch_root.mkdir(parents=True, exist_ok=True)
    input_list = batch_root / 'inputs.txt'
    output_json = batch_root / 'results.json'
    input_list.write_text(
        '\n'.join(
            docker.container_path(_crash_input_path(snapshot_crashes_dir, new_file))
            for new_file in new_files
        ) + '\n',
        encoding='utf-8',
    )

    _run_repro_worker(
        docker=docker,
        trial=trial,
        env={
            'FM_CRASH_INPUT_LIST': docker.container_path(input_list),
            'FM_CRASH_OUTPUT_JSON': docker.container_path(output_json),
        },
    )

    outputs = json.loads(output_json.read_text(encoding='utf-8', errors='replace'))
    if len(outputs) != len(new_files):
        LOG.warning(
            'Crash repro worker returned %d outputs for %d inputs in %s',
            len(outputs),
            len(new_files),
            output_json,
        )

    results: list[tuple[str, dict, int]] = []
    for new_file, output in zip(new_files, outputs):
        output = output.get('stdout') + output.get('stderr')
        results.append(_classify_crash_output(
            trial=trial,
            new_file=new_file,
            output=output,
            repro_logs_dir=repro_logs_dir,
        ))

    return results


def _crash_input_path(snapshot_crashes_dir: Path, new_file: DetectedFile) -> Path:
    crash_input = snapshot_crashes_dir / new_file.rel_path
    if crash_input.is_file():
        return crash_input
    return new_file.abs_src


def _run_repro_worker(*, docker: DockerClient, trial: TrialInstance, env: dict[str, str]) -> None:
    worker_env = {
        'FM_TARGET_NAME': trial.config.fuzz_target,
        'FM_INPUT_MODE': trial.config.fuzz_target_input_mode,
        'FM_TIMEOUT_S': _format_timeout(_crash_timeout_s(trial)),
        **env,
    }
    docker.run(
        image=trial.config.images.asan,
        volumes=[docker.out_volume()],
        env=worker_env,
        check=False,
        cmd=['python3', '/opt/fuzzmeter/crash_repro_worker.py'],
    )


def _crash_timeout_s(trial: TrialInstance) -> float:
    timeout_s = trial.config.fuzz_target_timeout
    if timeout_s is None:
        return 10.0
    try:
        return max(1.0, float(timeout_s))
    except (TypeError, ValueError):
        return 10.0


def _format_timeout(timeout_s: float) -> str:
    if float(timeout_s).is_integer():
        return str(int(timeout_s))
    return f'{float(timeout_s):.3f}'.rstrip('0').rstrip('.')


def _classify_crash_output(
    *,
    trial: TrialInstance,
    new_file: DetectedFile,
    output: str,
    repro_logs_dir: Path,
) -> tuple[str, dict, int]:
    issue = _extract_issue_type(output)
    frames = _extract_frames(output, max_frames=5)
    top_func = frames[0] if frames else 'unknown'
    bug_key = f'{issue}|{",".join(frames)}'

    _store_repro_output(
        repro_logs_dir,
        benchmark=trial.config.benchmark,
        fuzz_target=trial.config.fuzz_target,
        fuzzer=trial.config.fuzzer,
        bug_key=bug_key,
        text=output,
    )

    first_seen_ts = int(new_file.mtime_ns // 1_000_000_000)
    return (
        bug_key,
        {
            'issue_type': issue,
            'top_func': top_func,
            'frames': frames[:5],
            'output': output,
        },
        first_seen_ts,
    )


def _extract_issue_type(log_text: str) -> str:
    for regex in (_ISSUE_ASAN, _ISSUE_MSAN, _ISSUE_UBSAN):
        match = regex.search(log_text)
        if match:
            return match.group(1).strip()
    return 'crash'


def _extract_frames(log_text: str, *, max_frames: int = 8) -> list[str]:
    frames: list[str] = []
    for line in log_text.splitlines():
        match = _ANY_FUNC.match(line)
        if match:
            frames.append(match.group(1).strip())
            if len(frames) >= max_frames:
                break
    return frames


def _store_repro_output(
    root: Path,
    *,
    benchmark: str,
    fuzz_target: str,
    fuzzer: str,
    bug_key: str,
    text: str,
) -> None:
    safe_bug_key = re.sub(r'\s+', '_', bug_key.replace('/', '_').replace('\\', '_'))
    if len(safe_bug_key) > _MAX_COMPONENT:
        safe_bug_key = safe_bug_key[:_MAX_COMPONENT] + '_' + hashlib.sha1(safe_bug_key.encode()).hexdigest()[:12]
    output_dir = root / fuzzer / benchmark / fuzz_target / safe_bug_key
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f'{safe_bug_key[:40]}.log').write_text(text, encoding='utf-8', errors='replace')
