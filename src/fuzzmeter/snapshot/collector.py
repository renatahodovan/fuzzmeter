# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Collect per-tick snapshot inputs from live or replay trial outputs.'''

from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import time

from pathlib import Path
from typing import Any

from ..db import DB, open_db
from ..db import snapshot as db_snapshot
from ..docker import DockerRuntime
from ..fuzzers import FuzzerLoader
from ..repro import ingest as repro_ingest
from ..trial.models import TrialInstance
from .trial_snapshot import TrialCoverageSnapshot, TrialCrashSnapshot

LOG = logging.getLogger(__name__)


def collect_snapshots(
    *,
    db_path: Path,
    run_id: str,
    docker_runtime: DockerRuntime,
    tick_idx: int,
    end_ts: int,
    active_trials: list[TrialInstance],
    replay_mode: bool,
    jobs: int,
) -> tuple[list[TrialCoverageSnapshot], list[TrialCrashSnapshot]]:
    '''Collect snapshot work for all active trials at one tick.'''
    LOG.debug('\tCollect snapshot data for tick %s', tick_idx)
    trial_jobs = min(len(active_trials), max(1, jobs))
    preprocess_jobs = max(1, jobs // trial_jobs)

    start_time = time.time()
    if trial_jobs <= 1:
        collected = [
            _collect_trial_snapshot(
                db_path=db_path,
                run_id=run_id,
                docker_runtime=docker_runtime,
                tick_idx=tick_idx,
                end_ts=end_ts,
                trial=trial,
                replay_mode=replay_mode,
                preprocess_jobs=preprocess_jobs,
            )
            for trial in active_trials
        ]
    else:
        with cf.ThreadPoolExecutor(max_workers=trial_jobs) as executor:
            futures = [
                executor.submit(
                    _collect_trial_snapshot,
                    db_path=db_path,
                    run_id=run_id,
                    docker_runtime=docker_runtime,
                    tick_idx=tick_idx,
                    end_ts=end_ts,
                    trial=trial,
                    replay_mode=replay_mode,
                    preprocess_jobs=preprocess_jobs,
                )
                for trial in active_trials
            ]
            collected = [future.result() for future in futures]

    coverage_results, crash_results = zip(*collected)
    coverage_snapshots = [snapshot for snapshot in coverage_results if snapshot is not None]
    crash_snapshots = [snapshot for snapshot in crash_results if snapshot is not None]

    LOG.debug(
        '\tSnapshot collection finished in %.1f seconds with %d coverage snapshots and %d crash snapshots',
        time.time() - start_time,
        len(coverage_snapshots),
        len(crash_snapshots),
    )
    return coverage_snapshots, crash_snapshots


def _collect_trial_snapshot(
    *,
    db_path: Path,
    run_id: str,
    docker_runtime: DockerRuntime,
    tick_idx: int,
    end_ts: int,
    trial: TrialInstance,
    replay_mode: bool,
    preprocess_jobs: int,
) -> tuple[TrialCoverageSnapshot | None, TrialCrashSnapshot | None]:
    snapshot_dir = trial.layout.snapshots_dir / f'snap_{tick_idx:06d}'

    with open_db(db_path) as db:
        previous_snapshot = db_snapshot.latest_trial_snapshot(db, trial_row_id=trial.db_id)

    start_ts = trial.start_ts - 1 if previous_snapshot is None else int(previous_snapshot['ts'])
    processed_by_kind = _prepare_trial_snapshot_inputs(
        docker_runtime=docker_runtime,
        snapshot_dir=snapshot_dir,
        trial=trial,
        replay_mode=replay_mode,
        start_ts=start_ts,
        end_ts=end_ts,
        preprocess_jobs=preprocess_jobs,
    )
    prev_corpus_count = 0 if previous_snapshot is None else _safe_int(previous_snapshot.get('corpus_files')) or 0
    new_corpus_count = len(processed_by_kind['corpus'])
    stats = _read_stats(trial, tick_ts=end_ts)
    custom_metrics = _read_custom_metrics(trial, snapshot_dir=snapshot_dir, tick_ts=end_ts)
    if custom_metrics:
        stats = dict(stats)
        stats['custom_metrics_schema_version'] = 1
        stats['custom_metrics'] = custom_metrics

    with open_db(db_path) as db:
        snapshot_id = db_snapshot.save_snapshot_data(
            db,
            db_snapshot.SnapshotRecord(
                trial_db_id=trial.db_id,
                tick_idx=tick_idx,
                end_ts=end_ts,
                corpus_files=prev_corpus_count + new_corpus_count,
                execs_done=_safe_int(stats.get('execs_done')),
                stats=stats,
                crashes=len(processed_by_kind['crashes']),
                hangs=0,
            ),
        )
        if snapshot_id <= 0:
            raise RuntimeError(f'Could not save snapshot data for {tick_idx}. tick.')

        coverage_snapshot = _build_trial_coverage_snapshot(
            db=db,
            run_id=run_id,
            trial=trial,
            snapshot_id=snapshot_id,
            snapshot_dir=snapshot_dir,
            tick_idx=tick_idx,
            new_corpus_count=new_corpus_count,
            previous_snapshot=previous_snapshot,
        )

    crash_snapshot = _build_trial_crash_snapshot(
        trial=trial,
        snapshot_id=snapshot_id,
        snapshot_dir=snapshot_dir,
        tick_idx=tick_idx,
        crash_files=processed_by_kind['crashes'],
    )

    return coverage_snapshot, crash_snapshot


def _prepare_trial_snapshot_inputs(
    *,
    docker_runtime: DockerRuntime,
    snapshot_dir: Path,
    trial: TrialInstance,
    replay_mode: bool,
    start_ts: int,
    end_ts: int,
    preprocess_jobs: int,
) -> dict[str, list[Path]]:
    processed_by_kind: dict[str, list[Path]] = {}
    local_end_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_ts))

    for kind, src_root in (
        ('corpus', trial.layout.corpus_dir),
        ('crashes', trial.layout.crashes_dir),
    ):
        input_dir = snapshot_dir / kind
        new_files = (
            _detect_replay_files(kind=kind, trial=trial, src_root=src_root, start_ts=start_ts, end_ts=end_ts)
            if replay_mode
            else repro_ingest.detect_new_files(kind=kind, src_root=src_root, start_ts=start_ts, end_ts=end_ts)
        )

        LOG.debug(
            f'\t\tDetected {len(new_files)} new {kind} files for trial {trial.config.trial_key} '
            f'from {local_end_time}'
        )

        processed_by_kind[kind] = []
        if new_files:
            cur_time = time.time()
            processed_by_kind[kind] = repro_ingest.prepare_snapshot_inputs(
                docker_runtime=docker_runtime,
                snapshot_dir=snapshot_dir,
                input_dir=input_dir,
                input_files=new_files,
                snapshot_preprocess=trial.config.snapshot_preprocess,
                benchmark=trial.config.benchmark,
                fuzz_target=trial.config.fuzz_target,
                fuzzer=trial.config.fuzzer,
                runner_image=trial.config.images.runner,
                jobs=preprocess_jobs,
            )
            if trial.config.snapshot_preprocess:
                LOG.debug(
                    '\t\tPrepared snapshot inputs for %s in %.1f seconds with %s jobs for %s',
                    trial.config.fuzzer,
                    time.time() - cur_time,
                    preprocess_jobs,
                    kind,
                )

        collected_file_count = len(new_files)
        if collected_file_count != len(processed_by_kind[kind]):
            LOG.warning(
                '\t\tCould not process %s collected files.',
                collected_file_count - len(processed_by_kind[kind]),
            )

    return processed_by_kind


def _build_trial_coverage_snapshot(
    *,
    db: DB,
    run_id: str,
    trial: TrialInstance,
    snapshot_id: int,
    snapshot_dir: Path,
    tick_idx: int,
    new_corpus_count: int,
    previous_snapshot: dict[str, Any] | None,
) -> TrialCoverageSnapshot | None:
    if new_corpus_count > 0:
        return TrialCoverageSnapshot(
            trial=trial,
            snapshot_id=snapshot_id,
            snapshot_dir=snapshot_dir,
            tick_idx=tick_idx,
        )

    if previous_snapshot is None:
        db_snapshot.copy_seed_baseline_coverage_fields(
            db,
            run_id=run_id,
            fuzzer=trial.config.fuzzer,
            benchmark=trial.config.benchmark,
            fuzz_target=trial.config.fuzz_target,
            snapshot_id=snapshot_id,
        )
    else:
        db_snapshot.copy_previous_coverage_fields(
            db,
            trial_row_id=trial.db_id,
            snapshot_id=snapshot_id,
        )

    return None


def _build_trial_crash_snapshot(
    *,
    trial: TrialInstance,
    snapshot_id: int,
    snapshot_dir: Path,
    tick_idx: int,
    crash_files: list[Path],
) -> TrialCrashSnapshot | None:
    if not crash_files:
        return None

    snapshot_crashes_dir = snapshot_dir / 'crashes'
    snapshot_crash_files = [
        repro_ingest.DetectedFile(
            rel_path=str(path.relative_to(snapshot_crashes_dir)).replace('\\', '/'),
            abs_src=path,
            mtime_ns=path.stat().st_mtime_ns,
        )
        for path in crash_files
    ]
    return TrialCrashSnapshot(
        trial=trial,
        snapshot_id=snapshot_id,
        snapshot_dir=snapshot_dir,
        tick_idx=tick_idx,
        crash_files=snapshot_crash_files,
    )


def _detect_replay_files(
    *,
    kind: str,
    trial: TrialInstance,
    src_root: Path,
    start_ts: int,
    end_ts: int,
) -> list[repro_ingest.DetectedFile]:
    start_ns = start_ts * 1_000_000_000
    end_ns = end_ts * 1_000_000_000
    detected = [
        repro_ingest.DetectedFile(rel_path=rel_path, abs_src=src, mtime_ns=mtime_ns)
        for mtime_ns, rel_path in _replay_timeline_entries(trial=trial, kind=kind)
        for src in [src_root / rel_path]
        if start_ns < mtime_ns <= end_ns and src.is_file()
    ]
    LOG.debug(
        'Detected %d new/changed %s files in %s from %s',
        len(detected),
        kind,
        src_root,
        time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_ts)),
    )
    return detected


def _replay_timeline_entries(*, trial: TrialInstance, kind: str) -> list[tuple[int, str]]:
    timeline_path = trial.layout.trial_dir / 'replay_timeline.json'
    raw = json.loads(timeline_path.read_text(encoding='utf-8'))
    raw_times = raw.get('file_times_ns') or {}
    root = trial.layout.corpus_dir if kind == 'corpus' else trial.layout.crashes_dir
    prefix_path = str(root.relative_to(trial.layout.fuzz_dir)).replace('\\', '/')
    prefix = f'{prefix_path}/'
    entries = [
        (int(logical_ns), rel_text[len(prefix):])
        for rel_path, logical_ns in raw_times.items()
        for rel_text in [str(rel_path).replace('\\', '/')]
        if rel_text.startswith(prefix)
    ]
    return sorted(entries)


def _read_stats(trial: TrialInstance, *, tick_ts: int) -> dict[str, Any]:
    try:
        stats = (
            FuzzerLoader(trial.fuzzers_root)
            .load(trial.config.fuzzer_impl)
            .stats(trial.layout.trial_dir, cutoff_elapsed_s=tick_ts - trial.start_ts)
            or {}
        )
        return stats if isinstance(stats, dict) else {}
    except Exception as exc:
        LOG.warning(
            'Failed to get stats from %s adapter for trial_row_id=%s: %s',
            trial.config.fuzzer_impl,
            trial.db_id,
            exc,
        )
        return {}


def _read_custom_metrics(trial: TrialInstance, *, snapshot_dir: Path, tick_ts: int) -> list[dict[str, Any]]:
    try:
        metrics = (
            FuzzerLoader(trial.fuzzers_root)
            .load(trial.config.fuzzer_impl)
            .custom_metrics(
                trial.layout.trial_dir,
                snapshot_dir=snapshot_dir,
                cutoff_elapsed_s=tick_ts - trial.start_ts,
            )
            or []
        )
        return metrics if isinstance(metrics, list) else []
    except Exception as exc:
        LOG.warning(
            'Failed to get custom metrics from %s adapter for trial_row_id=%s: %s',
            trial.config.fuzzer_impl,
            trial.db_id,
            exc,
        )
        return []


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
