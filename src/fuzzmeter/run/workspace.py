# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Initialize on-disk run workspaces and metadata."""

from __future__ import annotations

import time

from pathlib import Path

from ..composite.collect import collect_records, save_records
from ..config import CampaignConfig
from ..db import ensure_schema, open_db
from ..db import runs as db_runs


def initialize_run_dir(
    *,
    run_dir: Path,
    run_id: str,
    config_src: str,
    campaign_config: CampaignConfig,
    label: str | None = None,
) -> None:
    '''Initialize run metadata, config files, and database schema.'''
    (Path(run_dir) / 'config.yaml').write_text(config_src, encoding='utf-8')
    with open_db(Path(run_dir) / 'fuzzmeter.db') as db:
        ensure_schema(db)
        db_runs.upsert_run(
            db,
            run_id=run_id,
            created_ts=int(time.time()),
            config_src=config_src,
            label=label,
        )
    _write_run_entries(run_dir=run_dir, run_id=run_id, campaign_config=campaign_config)


def _write_run_entries(*, run_dir: Path, run_id: str, campaign_config: CampaignConfig) -> None:
    campaign_config.write_run_config(Path(run_dir))
    save_records(
        Path(run_dir) / 'fuzzmeter.db',
        collect_records(run_id=run_id, campaign_config=campaign_config),
    )
