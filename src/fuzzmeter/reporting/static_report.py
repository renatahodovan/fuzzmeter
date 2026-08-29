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


def write_report(run_dir: Path, *, out_dir: Path, fuzzer_dirs: dict[str, Path] | None = None) -> Path:
    '''Write a static web report directory for a resolved fuzzmeter run directory.'''

    payload = build_payload(run_dir, fuzzer_dirs=fuzzer_dirs)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'data.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    write_assets(out_dir, payload)
    return out_dir
