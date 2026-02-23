# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import re
import subprocess

from pathlib import Path

from ..db import DB
from ..db.bug import ensure_bug, get_bug_id, upsert_bug_hits
from ..docker import DockerClient, DockerRuntime
from ..trial.models import ActiveTrial
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
    trial: ActiveTrial,
    snapshot_id: int,
    ts: int,
    snapshot_crashes_dir: Path,
    new_crash_files: list[DetectedFile],
    repro_logs_dir: Path | None,
    jobs: int = 1,
) -> None:
    '''Reproduce new crashes in the sanitizer image and persist bug hits.'''
    if not new_crash_files:
        return

    if repro_logs_dir is not None:
        repro_logs_dir.mkdir(parents=True, exist_ok=True)

    hits: dict[str, int] = {}
    metadata: dict[str, dict] = {}
    first_seen_by_bug: dict[str, int] = {}
    for bug_key, bug_metadata, first_seen_ts in _reproduce_crashes(
        docker_runtime=docker_runtime,
        trial=trial,
        snapshot_crashes_dir=snapshot_crashes_dir,
        new_crash_files=new_crash_files,
        repro_logs_dir=repro_logs_dir,
        jobs=jobs,
    ):
        hits[bug_key] = hits.get(bug_key, 0) + 1
        previous_first_seen_ts = first_seen_by_bug.get(bug_key)
        if previous_first_seen_ts is None or int(first_seen_ts) < previous_first_seen_ts:
            metadata[bug_key] = bug_metadata
        first_seen_by_bug[bug_key] = min(previous_first_seen_ts or int(first_seen_ts), int(first_seen_ts))

    for bug_key, count in hits.items():
        bug_id = get_bug_id(
            db,
            run_id=run_id,
            fuzzer=trial.fuzzer,
            benchmark=trial.benchmark,
            fuzz_target=trial.fuzz_target,
            bug_key=bug_key,
        )
        if bug_id is None:
            bug_id = ensure_bug(
                db,
                run_id=run_id,
                fuzzer=trial.fuzzer,
                benchmark=trial.benchmark,
                fuzz_target=trial.fuzz_target,
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


def _reproduce_crashes(
    *,
    docker_runtime: DockerRuntime,
    trial: ActiveTrial,
    snapshot_crashes_dir: Path,
    new_crash_files: list[DetectedFile],
    repro_logs_dir: Path | None,
    jobs: int,
) -> list[tuple[str, dict, str, int]]:
    if jobs <= 1 or len(new_crash_files) <= 1:
        return _reproduce_crash_batch(
            docker_runtime=docker_runtime,
            trial=trial,
            snapshot_crashes_dir=snapshot_crashes_dir,
            new_files=new_crash_files,
            repro_logs_dir=repro_logs_dir,
            batch_index=0,
        )

    batches = list(_chunks(new_crash_files, 64))
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(int(jobs), len(batches))) as executor:
        futures = [
            executor.submit(
                _reproduce_crash_batch,
                docker_runtime=docker_runtime,
                trial=trial,
                snapshot_crashes_dir=snapshot_crashes_dir,
                new_files=batch,
                repro_logs_dir=repro_logs_dir,
                batch_index=batch_index,
            )
            for batch_index, batch in enumerate(batches)
        ]
        results: list[tuple[str, dict, str, int]] = []
        for future in concurrent.futures.as_completed(futures):
            results.extend(future.result())
        return results


def _reproduce_crash_batch(
    *,
    docker_runtime: DockerRuntime,
    trial: ActiveTrial,
    snapshot_crashes_dir: Path,
    new_files: list[DetectedFile],
    repro_logs_dir: Path | None,
    batch_index: int,
) -> list[tuple[str, dict, str, int]]:
    if not new_files:
        return []

    docker = DockerClient(docker_runtime)
    batch_root = snapshot_crashes_dir.parent / '.crash_repro_batches' / f'{batch_index:06d}'
    batch_root.mkdir(parents=True, exist_ok=True)
    input_list = batch_root / 'inputs.txt'
    output_jsonl = batch_root / 'results.jsonl'
    input_list.write_text(
        '\n'.join(
            str(Path(docker.container_path(_crash_input_path(snapshot_crashes_dir, new_file))))
            for new_file in new_files
        ) + '\n',
        encoding='utf-8',
    )

    _run_repro_worker(
        docker=docker,
        trial=trial,
        env={
            'FM_CRASH_INPUT_LIST': str(Path(docker.container_path(input_list))),
            'FM_CRASH_OUTPUT_JSONL': str(Path(docker.container_path(output_jsonl))),
        },
    )

    payloads = _read_batch_payloads(output_jsonl)
    if not payloads:
        return [
            _reproduce_crash(
                docker_runtime=docker_runtime,
                trial=trial,
                snapshot_crashes_dir=snapshot_crashes_dir,
                new_file=new_file,
                repro_logs_dir=repro_logs_dir,
            )
            for new_file in new_files
        ]

    results: list[tuple[str, dict, str, int]] = []
    for payload in payloads:
        try:
            new_file = new_files[int(payload.get('index'))]
        except (TypeError, ValueError, IndexError):
            continue
        output = (payload.get('stdout') or '') + (('\n' + payload.get('stderr')) if payload.get('stderr') else '')
        results.append(_classify_crash_output(
            trial=trial,
            new_file=new_file,
            output=output,
            repro_logs_dir=repro_logs_dir,
        ))
    return results


def _reproduce_crash(
    *,
    docker_runtime: DockerRuntime,
    trial: ActiveTrial,
    snapshot_crashes_dir: Path,
    new_file: DetectedFile,
    repro_logs_dir: Path | None,
) -> tuple[str, dict, str, int]:
    docker = DockerClient(docker_runtime)
    crash_input = _crash_input_path(snapshot_crashes_dir, new_file)
    result = _run_repro_worker(
        docker=docker,
        trial=trial,
        env={
            'FM_CRASH_INPUT': str(Path(docker.container_path(crash_input))),
        },
    )
    output = (result.stdout or '') + (('\n' + result.stderr) if result.stderr else '')

    return _classify_crash_output(
        trial=trial,
        new_file=new_file,
        output=output,
        repro_logs_dir=repro_logs_dir,
    )


def _crash_input_path(snapshot_crashes_dir: Path, new_file: DetectedFile) -> Path:
    crash_input = snapshot_crashes_dir / new_file.rel_path
    if crash_input.is_file():
        return crash_input
    return new_file.abs_src


def _run_repro_worker(*, docker: DockerClient, trial: ActiveTrial, env: dict[str, str]) -> subprocess.CompletedProcess:
    worker_env = {
        'FM_TARGET_NAME': trial.fuzz_target,
        'FM_INPUT_MODE': trial.input_mode,
        'FM_TIMEOUT_S': _format_timeout(_crash_timeout_s(trial)),
        **env,
    }
    return docker.run(
        image=trial.asan_image,
        volumes=[docker.out_volume()],
        env=worker_env,
        check=False,
        cmd=['python3', '/opt/fuzzmeter/crash_repro_worker.py'],
    )


def _crash_timeout_s(trial: ActiveTrial) -> float:
    timeout_s = getattr(trial, 'target_timeout_s', None)
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
    trial: ActiveTrial,
    new_file: DetectedFile,
    output: str,
    repro_logs_dir: Path | None,
) -> tuple[str, dict, str, int]:
    issue = _extract_issue_type(output)
    frames = _extract_frames(output, max_frames=5)
    top_func = frames[0] if frames else 'unknown'
    bug_key = f'{issue}|{",".join(frames)}'

    if repro_logs_dir is not None:
        _store_repro_output(
            repro_logs_dir,
            benchmark=trial.benchmark,
            fuzz_target=trial.fuzz_target,
            fuzzer=trial.fuzzer,
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


def _read_batch_payloads(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    payloads: list[dict] = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            payloads.append(value)
    return payloads


def _chunks(items: list[DetectedFile], size: int) -> list[list[DetectedFile]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


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
    safe_bug = _shorten_component(_sanitize_component(bug_key))
    output_dir = root / fuzzer / benchmark / fuzz_target / safe_bug
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f'{bug_key[:40]}.log').write_text(text, encoding='utf-8', errors='replace')


def _sanitize_component(value: str) -> str:
    value = value.replace('/', '_').replace('\\', '_')
    return re.sub(r'\s+', '_', value)


def _shorten_component(value: str) -> str:
    if len(value) <= _MAX_COMPONENT:
        return value
    digest = hashlib.sha1(value.encode()).hexdigest()[:12]
    return f'{value[:_MAX_COMPONENT]}_{digest}'
