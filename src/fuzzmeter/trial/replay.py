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

from ..db import open_db
from ..db import trials as db_trials
from ..docker import DockerRuntime
from .models import ReplayTrialInstance, TrialConfig
from .workspace import prepare_replay_workspace

LOG = logging.getLogger(__name__)


def prepare_replay_trial(
    *,
    db_path: Path,
    docker_runtime: DockerRuntime,
    run_dir: Path,
    run_id: str,
    cfg: TrialConfig,
) -> ReplayTrialInstance:
    '''Prepare one replay trial workspace and detect its replay time range.'''
    layout = prepare_replay_workspace(run_dir=run_dir, cfg=cfg)
    assert cfg.replay_dir is not None, 'Replay directory must be set for a replayed campaign.'
    LOG.info('Linking replay source from %s to %s', cfg.replay_dir, layout.fuzz_dir)
    layout.fuzz_dir.symlink_to(cfg.replay_dir, target_is_directory=True)

    replay_start_ns = cfg.replay_dir.stat().st_mtime_ns
    corpus_root = cfg.replay_dir / cfg.output_paths.corpus_root
    if not corpus_root.is_dir():
        raise RuntimeError(
            f'Replay trial path must contain the corpus root {cfg.output_paths.corpus_root}: {cfg.replay_dir}'
        )

    file_times_ns: dict[str, int] = {}
    for root in (corpus_root, cfg.replay_dir / cfg.output_paths.crashes_root):
        if not root.is_dir():
            continue
        for path in root.rglob('*'):
            if not path.is_file():
                continue

            rel_path = path.relative_to(cfg.replay_dir)
            if any(part.startswith('.') for part in rel_path.parts):
                continue

            file_times_ns[str(rel_path).replace('\\', '/')] = max(path.stat().st_mtime_ns, replay_start_ns)

    start_ts = replay_start_ns // 1_000_000_000
    end_ts = max(file_times_ns.values(), default=replay_start_ns) // 1_000_000_000
    (layout.trial_dir / 'replay_timeline.json').write_text(
        json.dumps(
            {
                'start_ts': start_ts,
                'end_ts': end_ts,
                'file_times_ns': dict(sorted(file_times_ns.items())),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding='utf-8',
    )

    with open_db(db_path) as db:
        trial_db_id = db_trials.ensure_trial_row(
            db,
            db_trials.TrialRecord(
                run_id=run_id,
                fuzzer=cfg.fuzzer,
                benchmark=cfg.benchmark,
                fuzz_target=cfg.fuzz_target,
                rep=cfg.rep_idx,
                time_seconds=cfg.trial_timeout,
                status='running',
                fuzzer_image=cfg.images.runner,
                build_config_json=json.dumps(cfg.build_config, sort_keys=True),
                runtime_config_json=json.dumps(cfg.runtime_config, sort_keys=True),
                start_ts=start_ts,
            ),
        )

    return ReplayTrialInstance(
        db_id=trial_db_id,
        config=cfg,
        layout=layout,
        container_name=f'replay-{cfg.trial_key}',
        fuzzer_dirs=docker_runtime.fuzzer_dirs,
        start_ts=start_ts,
        end_ts=end_ts,
    )
