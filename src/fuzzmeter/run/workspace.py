# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Initialize on-disk run workspaces and metadata."""

from __future__ import annotations

import json
import time

from pathlib import Path

from ..composite.collect import collect_records, save_records
from ..config import CampaignConfig
from ..db import ensure_schema, open_db
from ..db import runs as db_runs


def initialize_run_dir(*, run_dir: Path, run_id: str, config_src: str, campaign_config: CampaignConfig) -> None:
    '''Initialize run metadata, config files, and database schema.'''
    (Path(run_dir) / 'config.yaml').write_text(config_src, encoding='utf-8')
    _initialize_db(run_dir=run_dir, run_id=run_id, config_src=config_src)
    _write_run_entries(run_dir=run_dir, run_id=run_id, campaign_config=campaign_config)


def _initialize_db(*, run_dir: Path, run_id: str, config_src: str) -> None:
    with open_db(Path(run_dir) / 'fuzzmeter.db') as db:
        ensure_schema(db)
        db_runs.upsert_run(db, run_id=run_id, created_ts=int(time.time()), config_src=config_src)


def _write_run_entries(*, run_dir: Path, run_id: str, campaign_config: CampaignConfig) -> None:
    (Path(run_dir) / 'benchmark_config.json').write_text(
        json.dumps(
            [
                {
                    'fuzzer_name': entry.fuzzer_name,
                    'fuzzer_chain': list(entry.fuzzer_chain),
                    'benchmark': entry.benchmark,
                    'fuzz_target': entry.fuzz_target,
                    'build_config': entry.build_config,
                    'runtime_config': entry.runtime_config,
                    'replay_trials': [str(path) for path in entry.replay_trials],
                }
                for entry in campaign_config.cases
            ],
            indent=2,
            sort_keys=True,
        ),
        encoding='utf-8',
    )
    save_records(
        Path(run_dir) / 'fuzzmeter.db',
        collect_records(run_id=run_id, campaign_config=campaign_config),
    )
