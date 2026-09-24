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
CUSTOM_METRICS_WARN_BYTES = 1024 * 1024


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
    if not active_trials:
        return [], []

    trial_jobs = min(len(active_trials), jobs)
    start_time = time.time()

    # Detect all trial inputs before assigning the shared preprocess budget.
    with cf.ThreadPoolExecutor(max_workers=trial_jobs) as executor:
        collection_futures = [
            executor.submit(
                _collect_trial_input_files,
                db_path=db_path,
                tick_idx=tick_idx,
                end_ts=end_ts,
                trial=trial,
                replay_mode=replay_mode,
            )
            for trial in active_trials
        ]
        collected = [future.result() for future in collection_futures]

    # Flatten corpus and crash inputs so they share one preprocess scheduler.
    snapshot_inputs = [
        repro_ingest.InputSet(
            snapshot_dir=snapshot_dir,
            input_dir=snapshot_dir / kind,
            input_files=tuple(input_files[kind]),
            snapshot_preprocess=trial.config.snapshot_preprocess,
            case=trial.config.case,
        )
        for trial, snapshot_dir, _, input_files in collected
        for kind in ('corpus', 'crashes')
    ]
    prepared_sets = repro_ingest.prepare_input_sets(
        docker_runtime=docker_runtime,
        input_sets=snapshot_inputs,
        jobs=jobs,
    )
    ready = []
    # Input sets are flattened as corpus/crashes pairs for each collected trial.
    for (
        (trial, snapshot_dir, previous_snapshot, _),
        corpus_files,
        crash_files,
    ) in zip(collected, prepared_sets[::2], prepared_sets[1::2], strict=True):
        processed_by_kind = {
            'corpus': corpus_files,
            'crashes': crash_files,
        }
        ready.append((trial, snapshot_dir, previous_snapshot, processed_by_kind))

    # Persist snapshots only after every trial's inputs have been prepared.
    with cf.ThreadPoolExecutor(max_workers=trial_jobs) as executor:
        finalize_futures = [
            executor.submit(
                _save_trial_snapshot,
                db_path=db_path,
                run_id=run_id,
                tick_idx=tick_idx,
                end_ts=end_ts,
                trial=trial,
                snapshot_dir=snapshot_dir,
                previous_snapshot=previous_snapshot,
                processed_by_kind=processed_by_kind,
            )
            for trial, snapshot_dir, previous_snapshot, processed_by_kind in ready
        ]
        finalized = [future.result() for future in finalize_futures]

    coverage_results, crash_results = zip(*finalized, strict=True)
    coverage_snapshots = [snapshot for snapshot in coverage_results if snapshot is not None]
    crash_snapshots = [snapshot for snapshot in crash_results if snapshot is not None]

    LOG.debug(
        '\tSnapshot collection finished in %.1f seconds with %d coverage snapshots and %d crash snapshots',
        time.time() - start_time,
        len(coverage_snapshots),
        len(crash_snapshots),
    )
    return coverage_snapshots, crash_snapshots


def _collect_trial_input_files(
    *,
    db_path: Path,
    tick_idx: int,
    end_ts: int,
    trial: TrialInstance,
    replay_mode: bool,
) -> tuple[TrialInstance, Path, dict[str, Any] | None, dict[str, list[repro_ingest.DetectedFile]]]:
    '''Collect one trial's newly visible corpus and crash files.'''
    snapshot_dir = trial.layout.snapshots_dir / f'snap_{tick_idx:06d}'

    with open_db(db_path) as db:
        previous_snapshot = db_snapshot.latest_trial_snapshot(db, trial_row_id=trial.db_id)

    start_ts = trial.start_ts - 1 if previous_snapshot is None else int(previous_snapshot['ts'])
    input_files: dict[str, list[repro_ingest.DetectedFile]] = {}
    local_end_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_ts))

    for kind, src_root in (
        ('corpus', trial.layout.corpus_dir),
        ('crashes', trial.layout.crashes_dir),
    ):
        input_files[kind] = (
            _detect_replay_files(kind=kind, trial=trial, src_root=src_root, start_ts=start_ts, end_ts=end_ts)
            if replay_mode
            else repro_ingest.detect_new_files(kind=kind, src_root=src_root, start_ts=start_ts, end_ts=end_ts)
        )

        LOG.debug(
            f'\t\tDetected {len(input_files[kind])} new {kind} files for trial {trial.config.trial_key} '
            f'from {local_end_time}'
        )

    return trial, snapshot_dir, previous_snapshot, input_files


def _save_trial_snapshot(
    *,
    db_path: Path,
    run_id: str,
    tick_idx: int,
    end_ts: int,
    trial: TrialInstance,
    snapshot_dir: Path,
    previous_snapshot: dict[str, Any] | None,
    processed_by_kind: dict[str, list[Path]],
) -> tuple[TrialCoverageSnapshot | None, TrialCrashSnapshot | None]:
    '''Store one collected trial snapshot and return its pending work.'''
    prev_corpus_count = 0 if previous_snapshot is None else _safe_int(previous_snapshot.get('corpus_files')) or 0
    new_corpus_count = len(processed_by_kind['corpus'])
    stats = _read_stats(trial, tick_ts=end_ts)
    custom_metrics = _read_custom_metrics(trial, snapshot_dir=snapshot_dir, tick_ts=end_ts)
    if custom_metrics is not None:
        stats = dict(stats)
        stats['custom_metrics'] = custom_metrics
        custom_metrics_size = len(
            json.dumps(custom_metrics, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
        )
        if custom_metrics_size > CUSTOM_METRICS_WARN_BYTES:
            LOG.warning(
                'Custom metrics payload for trial_row_id=%s is %s bytes; the soft limit is %s bytes.',
                trial.db_id,
                custom_metrics_size,
                CUSTOM_METRICS_WARN_BYTES,
            )

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

    return coverage_snapshot, _build_trial_crash_snapshot(
        trial=trial,
        snapshot_id=snapshot_id,
        snapshot_dir=snapshot_dir,
        tick_idx=tick_idx,
        crash_files=processed_by_kind['crashes'],
    )


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
            fuzzer=trial.config.case.fuzzer.id,
            benchmark=trial.config.fuzz_target.benchmark.name,
            fuzz_target=trial.config.fuzz_target.fuzz_target,
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
            rel_path=path.relative_to(snapshot_crashes_dir).as_posix(),
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
    prefix_path = root.relative_to(trial.layout.fuzz_dir).as_posix()
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
            FuzzerLoader(trial.fuzzer_dirs)
            .load(trial.config.case.fuzzer.name)
            .stats(trial.layout.trial_dir, cutoff_elapsed_s=tick_ts - trial.start_ts)
            or {}
        )
        return stats if isinstance(stats, dict) else {}
    except Exception as exc:
        LOG.warning(
            'Failed to get stats from %s adapter for trial_row_id=%s: %s',
            trial.config.case.fuzzer.name,
            trial.db_id,
            exc,
        )
        return {}


def _read_custom_metrics(trial: TrialInstance, *, snapshot_dir: Path, tick_ts: int) -> Any:
    try:
        return (
            FuzzerLoader(trial.fuzzer_dirs)
            .load(trial.config.case.fuzzer.name)
            .custom_metrics(
                trial.layout.trial_dir,
                snapshot_dir=snapshot_dir,
                cutoff_elapsed_s=tick_ts - trial.start_ts,
            )
        )
    except Exception as exc:
        LOG.warning(
            'Failed to get custom metrics from %s adapter for trial_row_id=%s: %s',
            trial.config.case.fuzzer.name,
            trial.db_id,
            exc,
        )
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
