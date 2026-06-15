# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Prepare replay trials from previously recorded fuzzer outputs.'''

from __future__ import annotations

import json
import logging

from pathlib import Path

from .models import TrialConfig, TrialInstance
from .runner import TrialRunner
from .workspace import prepare_replay_workspace

LOG = logging.getLogger(__name__)


class ReplayTrialRunner(TrialRunner):
    '''Prepare replay trials without duplicating their recorded outputs.'''

    def prepare(
        self,
        *,
        run_dir: Path,
        cfg: TrialConfig,
    ) -> TrialInstance:
        '''Prepare one replay trial workspace and detect its replay time range.'''
        layout = prepare_replay_workspace(run_dir=run_dir, cfg=cfg)
        assert cfg.replay_dir is not None, 'Replay directory must be set for a replayed campaign.'
        LOG.info('Linking replay source from %s to %s', cfg.replay_dir, layout.fuzz_dir)
        layout.fuzz_dir.symlink_to(cfg.replay_dir, target_is_directory=True)

        start_ts, end_ts = self._prepare_replay_timeline(
            trial_root=layout.trial_dir,
            cfg=cfg,
            replay_dir=cfg.replay_dir,
        )

        trial_row_id = self._record_trial(config=cfg, start_ts=start_ts)
        return TrialInstance(
            db_id=trial_row_id,
            config=cfg,
            layout=layout,
            container_name=f'replay-{cfg.trial_key}',
            repo_root=self.docker_runtime.repo_root,
            start_ts=start_ts,
            end_ts=end_ts,
        )

    @classmethod
    def _prepare_replay_timeline(
        cls,
        *,
        trial_root: Path,
        cfg: TrialConfig,
        replay_dir: Path,
    ) -> tuple[int, int]:
        replay_start_ns = replay_dir.stat().st_mtime_ns
        corpus_root = replay_dir / cfg.output_paths.corpus_root
        if not corpus_root.is_dir():
            raise RuntimeError(
                f'Replay trial path must contain the corpus root {cfg.output_paths.corpus_root}: {replay_dir}'
            )

        file_times_ns = cls._replay_file_times_ns(
            root=corpus_root,
            replay_dir=replay_dir,
            floor_ns=replay_start_ns,
        )
        crashes_root = replay_dir / cfg.output_paths.crashes_root
        if crashes_root.is_dir():
            file_times_ns.update(
                cls._replay_file_times_ns(
                    root=crashes_root,
                    replay_dir=replay_dir,
                    floor_ns=replay_start_ns,
                )
            )
        start_ts = replay_start_ns // 1_000_000_000
        end_ts = max(file_times_ns.values(), default=replay_start_ns) // 1_000_000_000
        (trial_root / 'replay_timeline.json').write_text(
            json.dumps(
                {
                    'start_ts': start_ts,
                    'end_ts': end_ts,
                    'file_times_ns': {path: ts for path, ts in sorted(file_times_ns.items())},
                },
                indent=2,
                sort_keys=True,
            ),
            encoding='utf-8',
        )
        return start_ts, end_ts

    @staticmethod
    def _replay_file_times_ns(*, root: Path, replay_dir: Path, floor_ns: int) -> dict[str, int]:
        file_times_ns: dict[str, int] = {}
        for path in root.rglob('*'):
            if not path.is_file():
                continue

            rel_path = path.relative_to(replay_dir)
            if any(part.startswith('.') for part in rel_path.parts):
                continue

            file_times_ns[str(rel_path).replace('\\', '/')] = max(path.stat().st_mtime_ns, floor_ns)

        return file_times_ns
