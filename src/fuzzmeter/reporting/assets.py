# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Write static web report assets for generated reporting output."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from typing import Any

from jinja2 import Environment, FileSystemLoader


def write_assets(report_dir: Path, payload: dict[str, Any]) -> None:
    """Write static HTML, CSS, and JavaScript report assets."""
    report_dir.mkdir(parents=True, exist_ok=True)
    candidates = _asset_roots()
    for name in ('report.css',):
        source = _find_asset(candidates, name)
        if source is None:
            raise FileNotFoundError('Could not locate report assets (report.html/report.css/report.js)')
        shutil.copy2(source, report_dir / name)

    report_html = _find_asset(candidates, 'report.html')
    if report_html is None:
        raise FileNotFoundError('Could not locate report assets (report.html/report.css/report.js)')
    env = Environment(loader=FileSystemLoader(str(report_html.parent)))
    rendered_html = env.get_template(report_html.name).render(run_id=None, static_report=True)
    static_payload_script = f'<script>\nwindow.FM_STATIC_DATA = {json.dumps(payload, ensure_ascii=False)};\n</script>\n'
    (report_dir / 'report.html').write_text(
        rendered_html.replace('</body>', f'{static_payload_script}</body>'),
        encoding='utf-8',
    )

    module_dir = _find_report_module_dir(candidates)
    if module_dir is None:
        raise FileNotFoundError('Could not locate report module assets (static/report)')
    out_module_dir = report_dir / 'report'
    if out_module_dir.exists():
        shutil.rmtree(out_module_dir)
    shutil.copytree(module_dir, out_module_dir)
    (report_dir / 'report.js').write_text(_bundle_report_modules(module_dir), encoding='utf-8')


def _asset_roots() -> list[Path]:
    pkg_root = Path(__file__).resolve().parents[1]
    return [pkg_root / 'web', pkg_root / 'reporting']


def _find_asset(candidates: list[Path], name: str) -> Path | None:
    for base in candidates:
        for rel in (Path('templates') / name, Path('static') / name, Path(name)):
            candidate = base / rel
            if candidate.is_file():
                return candidate
    return None


def _find_report_module_dir(candidates: list[Path]) -> Path | None:
    for base in candidates:
        candidate = base / 'static' / 'report'
        if candidate.is_dir():
            return candidate
    return None


def _bundle_report_modules(module_dir: Path) -> str:
    order = [
        'state.js',
        'dom.js',
        'stats.js',
        'format.js',
        'report-data.js',
        'ui.js',
        'report-utils.js',
        'charts.js',
        'extras.js',
        'filters.js',
        'page.js',
        'composite-shared.js',
        'composite.js',
        'app.js',
    ]
    parts = [
        '/* Auto-generated static bundle for file:// report viewing. */',
        '',
    ]
    for name in order:
        source = module_dir / name
        if not source.is_file():
            raise FileNotFoundError(f'Could not locate report module: {source}')
        text = source.read_text(encoding='utf-8')
        text = re.sub(r'^\s*import\s+[\s\S]*?;\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*export\s+', '', text, flags=re.MULTILINE)
        parts.append(text.strip())
        parts.append('')
    return '\n'.join(parts)
