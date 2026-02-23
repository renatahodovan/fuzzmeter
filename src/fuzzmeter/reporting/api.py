# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import json
import re
import shutil

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader


def build_payload(run_dir: Path, *, run_id: str | None = None, url_prefix: str | None = None) -> dict[str, Any]:
    '''Build the JSON payload consumed by the web report.'''

    from .generate import ReportBuilder

    builder = ReportBuilder(run_dir, run_id=run_id, url_prefix=url_prefix)
    return builder.build()


def generate_report(run_dir: Path, *, out_dir: Path | None = None, template_dir: Path | None = None) -> Path:
    '''Generate a static report directory for a fuzzmeter run.'''

    run_dir = Path(run_dir).resolve()
    report_dir = (out_dir or (run_dir / 'report')).resolve()
    payload = build_payload(run_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / 'data.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    _write_assets(report_dir, template_dir, payload)
    return report_dir


def _write_assets(report_dir: Path, template_dir: Path | None, payload: dict[str, Any]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    candidates = _asset_roots(template_dir)
    for name in ('report.css',):
        source = _find_asset(candidates, name)
        if source is None:
            raise FileNotFoundError('Could not locate report assets (report.html/report.css/report.js)')
        shutil.copy2(source, report_dir / name)

    report_html = _find_asset(candidates, 'report.html')
    if report_html is None:
        raise FileNotFoundError('Could not locate report assets (report.html/report.css/report.js)')
    env = Environment(loader=FileSystemLoader(str(report_html.parent)))
    rendered_html = env.get_template(report_html.name).render(run_id=None)
    rendered_html = rendered_html.replace(
        '<script type="module" src="report.js"></script>',
        '<script src="report.js"></script>',
    )
    static_payload_script = (
        '<script>\n'
        f'window.FM_STATIC_DATA = {json.dumps(payload, ensure_ascii=False)};\n'
        '</script>\n'
    )
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


def _asset_roots(template_dir: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if template_dir:
        candidate = template_dir.resolve()
        if not candidate.is_dir():
            raise FileNotFoundError(f'--templates is not a directory: {candidate}')
        candidates.append(candidate)
    pkg_root = Path(__file__).resolve().parents[1]
    candidates.extend([pkg_root / 'web', pkg_root / 'reporting'])
    return candidates


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
    order = ['report-utils.js', 'charts.js', 'extras.js', 'filters.js', 'page.js', 'app.js']
    parts = [
        '/* Auto-generated static bundle for file:// report viewing. */',
        '',
    ]
    for name in order:
        source = module_dir / name
        if not source.is_file():
            raise FileNotFoundError(f'Could not locate report module: {source}')
        text = source.read_text(encoding='utf-8')
        text = re.sub(r"^\s*import\s+[\s\S]*?;\s*$", '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*export\s+', '', text, flags=re.MULTILINE)
        parts.append(text.strip())
        parts.append('')
    return '\n'.join(parts)
