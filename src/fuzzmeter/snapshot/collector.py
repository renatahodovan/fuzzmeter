# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..db import DB, open_db
from ..db import snapshot as db_snapshot
from ..docker import DockerRuntime
from ..fuzzers import FuzzerLoader, HookRunner, HookSpec
from ..repro import ingest as repro_ingest
from ..repro.coverage_state import seed_coverage_root
from ..trial.models import TrialInstance
from .models import CrashTask, CoverageTask, SnapshotTickPlan

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CollectedTrialSnapshot:
    coverage_task: CoverageTask | None = None
    crash_task: CrashTask | None = None


@dataclass
class _ReplayTimelineIndex:
    entries_by_kind: dict[str, list[tuple[int, str]]]
    cursors_by_kind: dict[str, int]


class SnapshotCollector:
    '''Collect live fuzzer outputs into snapshot tasks.'''

    def __init__(self, *, db_path: Path, run_id: str, docker_runtime: DockerRuntime) -> None:
        self.db_path = Path(db_path)
        self.run_id = str(run_id)
        self.docker_runtime = docker_runtime
        self._replay_timeline_cache: dict[Path, _ReplayTimelineIndex] = {}

    def collect(
        self,
        *,
        tick_idx: int,
        ts: int,
        active_trials: list[TrialInstance],
        jobs: int | None = None,
        render_heavy: bool = False,
    ) -> SnapshotTickPlan:
        '''Collect snapshot work for all active trials at one tick.'''
        LOG.debug('\tCollect data for tick_idx=%s' % tick_idx)
        start_time = time.time()
        coverage_tasks: list[CoverageTask] = []
        crash_tasks: list[CrashTask] = []
        active_trials = list(active_trials)
        trial_jobs = self._trial_jobs_for_tick(total_trials=len(active_trials), jobs=jobs)
        preprocess_jobs = self._preprocess_jobs_for_tick(concurrent_trials=trial_jobs, jobs=jobs)

        if trial_jobs <= 1:
            collected = [
                self._collect_trial_snapshot(
                    tick_idx=tick_idx,
                    ts=ts,
                    trial=trial,
                    preprocess_jobs=preprocess_jobs,
                    render_heavy=render_heavy,
                )
                for trial in active_trials
            ]
        else:
            with cf.ThreadPoolExecutor(max_workers=trial_jobs) as executor:
                futures = [
                    executor.submit(
                        self._collect_trial_snapshot,
                        tick_idx=tick_idx,
                        ts=ts,
                        trial=trial,
                        preprocess_jobs=preprocess_jobs,
                        render_heavy=render_heavy,
                    )
                    for trial in active_trials
                ]
                collected = [future.result() for future in cf.as_completed(futures)]

        for entry in sorted(collected, key=lambda item: self._sort_key(item)):
            if entry.coverage_task is not None:
                coverage_tasks.append(entry.coverage_task)
            if entry.crash_task is not None:
                crash_tasks.append(entry.crash_task)

        LOG.debug(
            '\tSnapshot collection finished in %.1f seconds with %d coverage tasks and %d crash tasks',
            time.time() - start_time,
            len(coverage_tasks),
            len(crash_tasks),
        )
        return SnapshotTickPlan(
            active_trials=active_trials,
            coverage_tasks=coverage_tasks,
            crash_tasks=crash_tasks,
        )

    def _collect_trial_snapshot(
        self,
        *,
        tick_idx: int,
        ts: int,
        trial: TrialInstance,
        preprocess_jobs: int,
        render_heavy: bool,
    ) -> _CollectedTrialSnapshot:
        with open_db(self.db_path) as db:
            snapshot_dir_idx = self._next_snapshot_dir_idx(db=db, trial=trial)
            snap_dir = trial.layout.snapshots_dir / f'snap_{snapshot_dir_idx:06d}'
            snap_corpus = snap_dir / 'corpus'
            snap_crashes = snap_dir / 'crashes'
            snap_corpus.mkdir(parents=True, exist_ok=False)
            snap_crashes.mkdir(parents=True, exist_ok=False)

            stats = self._read_stats(trial, tick_ts=ts)
            execs_done = self._safe_int(stats.get('execs_done'))
            previous_snapshot = db_snapshot.latest_trial_snapshot(db, trial_row_id=trial.db_id)
            interval_start_ts = self._snapshot_interval_start_ts(trial=trial, previous_snapshot=previous_snapshot)
            new_corpus_files = self._detect_new_files(
                kind='corpus',
                trial=trial,
                src_root=trial.layout.corpus_dir,
                start_ts=interval_start_ts,
                end_ts=ts,
            )

            previous_count = (
                0 if previous_snapshot is None
                else SnapshotCollector._safe_int(previous_snapshot.get('corpus_files')) or 0
            )
            live_corpus_files = previous_count + len(new_corpus_files)

            ts_text = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
            LOG.debug(
                f'\t\tDetected {len(new_corpus_files)} new corpus files for trial {trial.config.trial_key} '
                f'from {ts_text}'
            )
            copied_corpus = self._copy_new_corpus(
                trial=trial,
                snap_dir=snap_dir,
                snap_corpus=snap_corpus,
                new_corpus_files=new_corpus_files,
                jobs=preprocess_jobs,
            )
            new_crash_files = self._detect_new_files(
                kind='crashes',
                trial=trial,
                src_root=trial.layout.crashes_dir,
                start_ts=interval_start_ts,
                end_ts=ts,
            )

            snapshot_id = db_snapshot.ensure_snapshot_row(
                db,
                trial_row_id=trial.db_id,
                idx=tick_idx,
                ts=ts,
                corpus_files=live_corpus_files,
                execs_done=execs_done,
                stats=stats,
                crashes=len(new_crash_files),
                hangs=0,
            )
            if snapshot_id <= 0:
                return _CollectedTrialSnapshot()

            coverage_task = None
            if self._should_run_coverage(db=db, trial=trial, copied_corpus=copied_corpus):
                coverage_task = CoverageTask(
                    trial=trial,
                    snap_dir=snap_dir,
                    snapshot_id=snapshot_id,
                    tick_idx=tick_idx,
                    render_heavy=render_heavy,
                )
            else:
                db_snapshot.copy_previous_coverage_fields(
                    db,
                    trial_row_id=trial.db_id,
                    snapshot_id=snapshot_id,
                )

            crash_task = None
            if new_crash_files:
                repro_ingest.copy_into_snapshot(new_crash_files, snap_dir=snap_dir, subdir='crashes')
                if trial.config.snapshot_preprocess:
                    cur_time = time.time()
                    self._run_snapshot_preprocess(
                        trial=trial,
                        snap_dir=snap_dir,
                        target_dir=snap_crashes,
                        jobs=preprocess_jobs,
                    )
                    LOG.debug(
                        f'\t\tCrashes preprocess hook {trial.config.fuzzer} finished in '
                        f'{time.time() - cur_time:.1f} seconds'
                    )
                snapshot_crash_files = self._snapshot_crash_files(snap_crashes)
                crash_task = CrashTask(
                    trial=trial,
                    snapshot_id=snapshot_id,
                    ts=ts,
                    snapshot_crashes_dir=snap_crashes,
                    new_crash_files=snapshot_crash_files,
                )

            return _CollectedTrialSnapshot(
                coverage_task=coverage_task,
                crash_task=crash_task,
            )

    @staticmethod
    def _next_snapshot_dir_idx(*, db: DB, trial: TrialInstance) -> int:
        existing = db.scalar(
            'SELECT COUNT(*) FROM snapshots WHERE trial_id=?',
            (int(trial.db_id),),
        )
        return int(existing or 0) + 1

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _detect_new_files(
        self,
        *,
        kind: repro_ingest.OutputFileKind,
        trial: TrialInstance,
        src_root: Path,
        start_ts: int,
        end_ts: int,
    ) -> list[repro_ingest.DetectedFile]:
        if trial.end_ts is not None:
            return self._detect_replay_files(
                kind=kind,
                trial=trial,
                src_root=src_root,
                start_ts=start_ts,
                end_ts=end_ts,
            )
        return repro_ingest.detect_new_files(
            kind=kind,
            src_root=src_root,
            start_ts=start_ts,
            end_ts=end_ts,
            replay_time_fn=None,
        )

    def _detect_replay_files(
        self,
        *,
        kind: repro_ingest.OutputFileKind,
        trial: TrialInstance,
        src_root: Path,
        start_ts: int,
        end_ts: int,
    ) -> list[repro_ingest.DetectedFile]:
        index = self._replay_timeline_index(trial)
        entries = index.entries_by_kind.get(kind, [])
        start_ns = int(start_ts) * 1_000_000_000
        end_ns = int(end_ts) * 1_000_000_000
        pos = index.cursors_by_kind.get(kind, 0)
        while pos < len(entries) and entries[pos][0] < start_ns:
            pos += 1

        detected: list[repro_ingest.DetectedFile] = []
        while pos < len(entries) and entries[pos][0] <= end_ns:
            mtime_ns, rel_path = entries[pos]
            src = src_root / rel_path
            if src.is_file():
                detected.append(
                    repro_ingest.DetectedFile(
                        kind=kind,
                        rel_path=rel_path,
                        db_rel_path=self._db_rel_path(Path(rel_path)),
                        abs_src=src,
                        mtime_ns=mtime_ns,
                    )
                )
            pos += 1

        index.cursors_by_kind[kind] = pos
        LOG.debug(
            'Detected %d new/changed %s files in %s from %s',
            len(detected),
            kind,
            src_root,
            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_ts)),
        )
        return detected

    def _replay_timeline_index(self, trial: TrialInstance) -> _ReplayTimelineIndex:
        timeline_path = trial.layout.trial_dir / 'replay_timeline.json'
        cached = self._replay_timeline_cache.get(timeline_path)
        if cached is not None:
            return cached

        raw = json.loads(timeline_path.read_text(encoding='utf-8'))
        raw_times = raw.get('file_times_ns') or {}
        entries_by_kind: dict[str, list[tuple[int, str]]] = {'corpus': [], 'crashes': []}
        prefixes = {
            'corpus': self._timeline_prefix(root=trial.layout.corpus_dir, live_out=trial.layout.fuzz_dir),
            'crashes': self._timeline_prefix(root=trial.layout.crashes_dir, live_out=trial.layout.fuzz_dir),
        }
        for rel_path, logical_ns in raw_times.items():
            rel_text = str(rel_path).replace('\\', '/')
            for kind, prefix in prefixes.items():
                if not rel_text.startswith(prefix):
                    continue
                entries_by_kind[kind].append((int(logical_ns), rel_text[len(prefix):]))
                break

        for entries in entries_by_kind.values():
            entries.sort()
        cached = _ReplayTimelineIndex(entries_by_kind=entries_by_kind, cursors_by_kind={'corpus': 0, 'crashes': 0})
        self._replay_timeline_cache[timeline_path] = cached
        return cached

    @staticmethod
    def _timeline_prefix(*, root: Path, live_out: Path) -> str:
        rel_path = root.relative_to(live_out)
        rel_text = str(rel_path).replace('\\', '/')
        return f'{rel_text}/'

    @staticmethod
    def _db_rel_path(rel_path: Path) -> str:
        return b'/'.join(os.fsencode(part) for part in rel_path.parts).hex()

    @staticmethod
    def _read_stats(trial: TrialInstance, *, tick_ts: int | None = None) -> dict[str, Any]:
        try:
            cutoff_elapsed_s = None
            if tick_ts is not None:
                cutoff_elapsed_s = max(0, int(tick_ts) - int(trial.start_ts))
            stats = (
                FuzzerLoader(trial.repo_root)
                .load(trial.config.fuzzer_base)
                .stats(trial.layout.trial_dir, cutoff_elapsed_s=cutoff_elapsed_s)
                or {}
            )
            return stats if isinstance(stats, dict) else {}
        except Exception as exc:
            LOG.warning(
                'Failed to get stats from %s adapter for trial_row_id=%s: %s',
                trial.config.fuzzer_base,
                trial.db_id,
                exc,
            )
            return {}

    @staticmethod
    def _snapshot_interval_start_ts(*, trial: TrialInstance, previous_snapshot: dict[str, Any] | None) -> int | None:
        if previous_snapshot is not None:
            return SnapshotCollector._safe_int(previous_snapshot.get('ts'))
        return int(trial.start_ts)

    def _copy_new_corpus(
        self,
        *,
        trial: TrialInstance,
        snap_dir: Path,
        snap_corpus: Path,
        new_corpus_files: list[repro_ingest.DetectedFile],
        jobs: int | None = None,
    ) -> int:
        if not new_corpus_files:
            return 0

        copied_corpus = repro_ingest.copy_into_snapshot(new_corpus_files, snap_dir=snap_dir, subdir='corpus')
        if trial.config.snapshot_preprocess:
            cur_time = time.time()
            self._run_snapshot_preprocess(trial=trial, snap_dir=snap_dir, target_dir=snap_corpus, jobs=jobs)
            LOG.debug(
                f'\t\tCorpus preprocess hook {trial.config.fuzzer} finished in {time.time() - cur_time:.1f} seconds '
                f'with {jobs} jobs'
            )
            copied_corpus = sum(1 for path in snap_corpus.rglob('*') if path.is_file())

        return copied_corpus

    @staticmethod
    def _should_run_coverage(*, db: DB, trial: TrialInstance, copied_corpus: int) -> bool:
        if (
            SnapshotCollector._seed_baseline_exists(trial)
            and not db_snapshot.trial_has_coverage_snapshots(db, trial_row_id=trial.db_id)
        ):
            return True
        return copied_corpus > 0

    @staticmethod
    def _seed_baseline_exists(trial: TrialInstance) -> bool:
        run_dir = trial.layout.trial_dir.parent.parent
        base_root = seed_coverage_root(run_dir, trial.config.fuzzer, trial.config.benchmark, trial.config.fuzz_target)
        return (base_root / 'summary.json').is_file() and (base_root / '_state' / 'merged.profdata').is_file()

    def _run_snapshot_preprocess(self, *, trial: TrialInstance, snap_dir: Path, target_dir: Path, jobs: int) -> None:
        HookRunner(docker_runtime=self.docker_runtime).run(
            HookSpec(
                name='snapshot_preprocess',
                script=trial.config.snapshot_preprocess,
                env={
                    'FM_SNAPSHOT_DIR': str(snap_dir),
                    'FM_SNAPSHOT_CORPUS_DIR': str(target_dir),
                    'FM_BENCHMARK': trial.config.benchmark,
                    'FM_FUZZ_TARGET': trial.config.fuzz_target,
                    'FM_FUZZER': trial.config.fuzzer,
                    'FM_RUNNER_IMAGE': trial.config.images.runner,
                    'FM_REPO_ROOT': str(trial.repo_root),
                    'FM_JOBS': str(jobs),
                },
                cwd=snap_dir,
            )
        )

    @staticmethod
    def _snapshot_crash_files(snapshot_crashes_dir: Path) -> list[repro_ingest.DetectedFile]:
        crash_files: list[repro_ingest.DetectedFile] = []
        for path in sorted(snapshot_crashes_dir.rglob('*')):
            if not path.is_file():
                continue
            rel_path = path.relative_to(snapshot_crashes_dir)
            rel_text = str(rel_path).replace('\\', '/')
            stat = path.stat()
            crash_files.append(
                repro_ingest.DetectedFile(
                    kind='crashes',
                    rel_path=rel_text,
                    db_rel_path=rel_text,
                    abs_src=path,
                    mtime_ns=int(stat.st_mtime_ns),
                )
            )
        return crash_files


    @staticmethod
    def _trial_jobs_for_tick(*, total_trials: int, jobs: int | None) -> int:
        if total_trials <= 0:
            return 1
        budget = max(1, int(jobs or 1))
        return max(1, min(budget, total_trials))

    @staticmethod
    def _preprocess_jobs_for_tick(*, concurrent_trials: int, jobs: int | None) -> int:
        budget = max(1, int(jobs or 1))
        cpu_budget = max(1, os.cpu_count() or 1)
        return max(1, min(4, budget, cpu_budget // max(1, concurrent_trials)))

    @staticmethod
    def _sort_key(item: _CollectedTrialSnapshot) -> tuple[str, int]:
        if item.coverage_task is not None:
            trial = item.coverage_task.trial
        elif item.crash_task is not None:
            trial = item.crash_task.trial
        else:
            return ('', -1)
        return (trial.config.trial_key, trial.db_id)
