# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Write static report payloads and bundled web assets.'''

from __future__ import annotations

import json

from pathlib import Path

from .assets import write_assets
from .payload import build_payload


def write_report(run_dir: Path, *, out_dir: Path | None = None, fuzzers_root: Path | None = None) -> Path:
    '''Write a static web report directory for a fuzzmeter run.'''

    run_dir = Path(run_dir).resolve()
    report_dir = (out_dir or (run_dir / 'report')).resolve()
    payload = build_payload(run_dir, fuzzers_root=fuzzers_root)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / 'data.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    write_assets(report_dir, payload)
    return report_dir
