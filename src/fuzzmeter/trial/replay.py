# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Prepare replay trials from previously recorded fuzzer outputs.'''

from __future__ import annotations

import datetime
import json
import logging
import re
import shutil
import subprocess

from dataclasses import dataclass
from pathlib import Path

from .models import ActiveTrial, TrialConfig
from .runner import TrialRunner

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedReplayTrial:
    '''Describe one prepared replay trial and its replay timing window.'''

    trial_row_id: int
    trial_id: str
    replay_start_ts: int
    replay_end_ts: int
    active_trial: ActiveTrial


@dataclass(frozen=True)
class ReplayTimeline:
    '''Store a replay-visible timestamp for each recorded output file.'''

    replay_start_ts: int
    replay_end_ts: int
    file_times_ns: dict[str, int]


class ReplayTrialRunner(TrialRunner):
    '''Prepare replay trials without duplicating their recorded outputs.'''

    _STAT_BIRTHTIME_RE = re.compile(
        r'^(?P<date>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\.(?P<fraction>\d+))? (?P<offset>[+-]\d{4})$'
    )

    def prepare(
        self,
        *,
        run_dir: Path,
        cfg: TrialConfig,
        jobs: int,
    ) -> PreparedReplayTrial:
        '''Prepare one replay trial workspace and detect its replay time range.'''
        if cfg.replay_trial_path is None:
            raise RuntimeError(f'Replay trial is missing replay source path: {cfg.trial_key}')

        workspace = self._prepare_workspace(run_dir=run_dir, cfg=cfg)
        replay_path = Path(cfg.replay_trial_path).resolve()
        if not replay_path.is_dir():
            raise RuntimeError(f'Replay corpus dir does not exist: {replay_path}')

        source_live_out_root = self._resolve_source_live_out_root(cfg=cfg, replay_path=replay_path)
        self._link_replay_live_out(
            source_live_out_root=source_live_out_root,
            dest_live_out_root=workspace.paths.live_out_root,
        )

        timeline = self._build_replay_timeline(
            cfg=cfg,
            replay_path=replay_path,
            source_live_out_root=source_live_out_root,
        )
        self._write_replay_timeline(trial_root=workspace.paths.trial_dir, timeline=timeline)

        trial_row_id = self._insert_trial_row(cfg=cfg, jobs=jobs, started_ts=timeline.replay_start_ts)
        active_trial = ActiveTrial(
            trial_row_id=trial_row_id,
            trial_id=cfg.trial_key,
            container_name=f'replay-{cfg.trial_key}',
            fuzzer=cfg.fuzzer,
            fuzzer_base=cfg.fuzzer_base,
            benchmark=cfg.benchmark,
            fuzz_target=cfg.fuzz_target,
            input_mode=cfg.input_mode,
            target_timeout_s=cfg.target_timeout_s,
            rep=cfg.rep,
            runner_image=cfg.runner_image,
            coverage_image=cfg.coverage_image,
            asan_image=cfg.asan_image,
            snapshot_preprocess_script=cfg.snapshot_preprocess_script,
            trial_root=workspace.paths.trial_dir,
            live_out=workspace.paths.live_out_root,
            fuzzer_log=workspace.paths.fuzzer_log,
            corpus_root=workspace.paths.corpus_root,
            crashes_root=workspace.paths.crashes_root,
            snapshots_root=workspace.paths.snapshots_root,
            seed_root=workspace.seed_root,
            repo_root=self.docker_runtime.repo_root,
            started_ts=timeline.replay_start_ts,
            replay_start_ts=timeline.replay_start_ts,
            replay_end_ts=timeline.replay_end_ts,
        )
        return PreparedReplayTrial(
            trial_row_id=trial_row_id,
            trial_id=cfg.trial_key,
            replay_start_ts=timeline.replay_start_ts,
            replay_end_ts=timeline.replay_end_ts,
            active_trial=active_trial,
        )

    @staticmethod
    def _resolve_source_live_out_root(*, cfg: TrialConfig, replay_path: Path) -> Path:
        expected_corpus_root = cfg.paths.output_paths.corpus_root
        max_ancestor_depth = len(expected_corpus_root.parts)

        for depth in range(max_ancestor_depth + 1):
            candidate = replay_path if depth == 0 else replay_path.parents[depth - 1]
            if (candidate / expected_corpus_root).is_dir():
                return candidate

        raise RuntimeError(
            f'Replay path does not contain the expected corpus root {expected_corpus_root}: {replay_path}'
        )

    @staticmethod
    def _link_replay_live_out(*, source_live_out_root: Path, dest_live_out_root: Path) -> None:
        LOG.info('Linking replay source from %s to %s', source_live_out_root, dest_live_out_root)
        if dest_live_out_root.is_symlink() or dest_live_out_root.is_file():
            dest_live_out_root.unlink()
        elif dest_live_out_root.exists():
            shutil.rmtree(dest_live_out_root)
        dest_live_out_root.symlink_to(source_live_out_root, target_is_directory=True)

    @classmethod
    def _build_replay_timeline(
        cls,
        *,
        cfg: TrialConfig,
        replay_path: Path,
        source_live_out_root: Path,
    ) -> ReplayTimeline:
        corpus_root = source_live_out_root / cfg.paths.output_paths.corpus_root
        crashes_root = source_live_out_root / cfg.paths.output_paths.crashes_root
        replay_start_ns = cls._creationish_ns(replay_path if replay_path.exists() else source_live_out_root)

        corpus_times_ns = cls._replay_file_times_ns(
            root=corpus_root,
            live_out_root=source_live_out_root,
            floor_ns=replay_start_ns,
        )
        crash_times_ns = cls._replay_file_times_ns(
            root=crashes_root,
            live_out_root=source_live_out_root,
            floor_ns=replay_start_ns,
        )

        all_times_ns = list(corpus_times_ns.values()) + list(crash_times_ns.values())
        replay_start_ts = int(replay_start_ns // 1_000_000_000)
        if not all_times_ns:
            return ReplayTimeline(replay_start_ts=replay_start_ts, replay_end_ts=replay_start_ts, file_times_ns={})

        replay_end_ts = int(max(all_times_ns) // 1_000_000_000)
        if replay_end_ts < replay_start_ts:
            replay_end_ts = replay_start_ts

        file_times_ns = {**corpus_times_ns, **crash_times_ns}
        return ReplayTimeline(
            replay_start_ts=replay_start_ts,
            replay_end_ts=replay_end_ts,
            file_times_ns=file_times_ns,
        )

    @classmethod
    def _replay_file_times_ns(cls, *, root: Path, live_out_root: Path, floor_ns: int) -> dict[str, int]:
        file_times_ns: dict[str, int] = {}
        if not root.exists():
            return {}

        for path in root.rglob('*'):
            if not path.is_file():
                continue

            rel_path = path.relative_to(live_out_root)
            if any(part.startswith('.') for part in rel_path.parts):
                continue

            try:
                mtime_ns = int(path.stat().st_mtime_ns)
            except OSError:
                continue

            file_times_ns[str(rel_path).replace('\\', '/')] = max(int(mtime_ns), int(floor_ns))

        return file_times_ns

    @staticmethod
    def _write_replay_timeline(*, trial_root: Path, timeline: ReplayTimeline) -> None:
        (trial_root / 'replay_timeline.json').write_text(
            json.dumps(
                {
                    'replay_start_ts': int(timeline.replay_start_ts),
                    'replay_end_ts': int(timeline.replay_end_ts),
                    'file_times_ns': {path: int(ts) for path, ts in sorted(timeline.file_times_ns.items())},
                },
                indent=2,
                sort_keys=True,
            ),
            encoding='utf-8',
        )

    @staticmethod
    def _creationish_ns(path: Path) -> int:
        stat = path.stat()
        birth_ts = getattr(stat, 'st_birthtime_ns', None)
        if birth_ts is not None:
            return int(birth_ts)
        birth_ts = getattr(stat, 'st_birthtime', None)
        if birth_ts is not None:
            return int(float(birth_ts) * 1_000_000_000)
        birth_ts = ReplayTrialRunner._linux_birthtime_ns(path)
        if birth_ts is not None:
            return birth_ts
        return int(stat.st_mtime_ns)

    @classmethod
    def _linux_birthtime_ns(cls, path: Path) -> int | None:
        try:
            result = subprocess.run(
                ['stat', '-c', '%w', str(path)],
                capture_output=True,
                check=False,
                encoding='utf-8',
            )
        except OSError:
            return None

        if result.returncode != 0:
            return None

        value = result.stdout.strip()
        if not value or value == '-':
            return None

        match = cls._STAT_BIRTHTIME_RE.match(value)
        if match is None:
            return None

        try:
            dt = datetime.datetime.strptime(
                f'{match.group("date")} {match.group("offset")}',
                '%Y-%m-%d %H:%M:%S %z',
            )
        except ValueError:
            return None

        seconds_ns = int(dt.timestamp()) * 1_000_000_000
        fraction = (match.group('fraction') or '')[:9].ljust(9, '0')
        return seconds_ns + int(fraction)
