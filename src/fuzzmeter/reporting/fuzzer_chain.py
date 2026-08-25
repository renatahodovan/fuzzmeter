# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Resolve fuzzer reporting plugin candidate chains from config files.'''

from __future__ import annotations

import json

from pathlib import Path
from typing import Any, Mapping, Sequence


def load_fuzzer_plugin_candidates(run_dir: Path, fuzzer_dirs: Mapping[str, Path]) -> tuple[dict[str, list[str]], dict[str, str]]:
    '''Load configured reporting plugin candidates for measured fuzzers.'''

    path = Path(run_dir) / 'benchmark_config.json'
    if not path.is_file():
        return {}, {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, {}
    if not isinstance(data, list):
        return {}, {}

    candidates_by_name: dict[str, list[str]] = {}
    base_by_name: dict[str, str] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        fuzzer_name = str(entry.get('fuzzer_name') or '').strip()
        if not fuzzer_name:
            continue
        chain = [str(name).strip() for name in entry.get('fuzzer_chain') or [] if str(name).strip()]
        if chain:
            base_by_name[fuzzer_name] = chain[1] if len(chain) > 1 else chain[0]
        candidates_by_name[fuzzer_name] = expand_reporting_candidates(fuzzer_dirs, chain or [fuzzer_name])
    return candidates_by_name, base_by_name


def plugin_candidates_for(fuzzer: str, fuzzer_dirs: Mapping[str, Path], candidates_by_name: dict[str, list[str]]) -> list[str]:
    '''Return the configured or inferred plugin candidate chain for a fuzzer.'''

    return candidates_by_name.get(fuzzer) or expand_reporting_candidates(fuzzer_dirs, [fuzzer])


def expand_reporting_candidates(fuzzer_dirs: Mapping[str, Path], names: Sequence[str | None]) -> list[str]:
    '''Expand fuzzer names through reporting_parent and parent YAML fields.'''

    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        _add_reporting_candidate(fuzzer_dirs, name, out, seen)
    return out


def dedupe(values: Sequence[str | None]) -> list[str]:
    '''Return non-empty strings without duplicates, preserving order.'''

    out: list[str] = []
    for value in values:
        text = str(value or '').strip()
        if text and text not in out:
            out.append(text)
    return out


def _add_reporting_candidate(fuzzer_dirs: Mapping[str, Path], name: str | None, out: list[str], seen: set[str]) -> None:
    normalized = str(name or '').strip()
    if not normalized or normalized in seen:
        return
    seen.add(normalized)
    out.append(normalized)
    config = _load_fuzzer_yaml(fuzzer_dirs, normalized)
    _add_reporting_candidate(fuzzer_dirs, config.get('reporting_parent'), out, seen)
    _add_reporting_candidate(fuzzer_dirs, config.get('parent'), out, seen)


def _load_fuzzer_yaml(fuzzer_dirs: Mapping[str, Path], fuzzer: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    root = fuzzer_dirs.get(fuzzer)
    if root is None:
        return out
    for path in (root / 'build' / 'build.yaml', root / 'run' / 'run.yaml'):
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or ':' not in stripped:
                continue
            if line[:1].isspace():
                continue
            key, value = stripped.split(':', 1)
            key = key.strip()
            if key in {'parent', 'reporting_parent'}:
                out[key] = value.strip()
    return out
