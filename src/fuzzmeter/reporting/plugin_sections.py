# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import json
import logging

from pathlib import Path
from typing import Any, Sequence

from .metrics import safe_int
from .plugin_api import ExtraSection, ReportingContext
from .plugins.loader import ReportingPluginLoader
from .web_payload import serialize_extra_sections, validate_extra_sections

LOG = logging.getLogger(__name__)


def attach_extra_sections(
    *,
    repo_root: Path,
    run_dir: Path,
    run_id: str,
    targets: list[dict[str, Any]],
    trials: list[dict[str, Any]],
    timeseries: dict[str, Any],
    bugs: list[dict[str, Any]],
) -> None:
    '''Attach plugin-provided extra report sections to target and fuzzer entries.'''

    repo_root = Path(repo_root)
    loader = ReportingPluginLoader(repo_root)
    fuzzer_candidates_by_name, fuzzer_base_by_name = _load_fuzzer_plugin_candidates(run_dir, repo_root)
    trial_snapshot_index = _build_trial_snapshot_index(run_dir)
    trials_by_target_fuzzer = _group_by_target_fuzzer(trials)
    bugs_by_target_fuzzer = _group_by_target_fuzzer(bugs)

    for target in targets:
        benchmark = str(target.get('benchmark') or '')
        fuzz_target = str(target.get('fuzz_target') or '')
        target_sections: list[ExtraSection] = []
        target_debug: list[dict[str, Any]] = []
        for fuzzer_entry in target.get('fuzzers') or []:
            fuzzer = str(fuzzer_entry.get('fuzzer') or '')
            if not fuzzer:
                continue
            plugin_candidates = _plugin_candidates_for(fuzzer, repo_root, fuzzer_candidates_by_name)
            plugin, matched_plugin_name = loader.load_first(plugin_candidates)
            reps = trials_by_target_fuzzer.get((benchmark, fuzz_target, fuzzer), [])
            ctx = _build_reporting_context(
                run_id=run_id,
                run_dir=run_dir,
                benchmark=benchmark,
                fuzz_target=fuzz_target,
                fuzzer=fuzzer,
                reps=reps,
                bugs=bugs_by_target_fuzzer.get((benchmark, fuzz_target, fuzzer), []),
                timeseries=timeseries,
                snapshot_dirs_by_trial=_snapshot_dirs_by_trial(
                    reps,
                    trial_snapshot_index,
                    plugin_candidates,
                    fuzzer_base_by_name.get(fuzzer),
                ),
            )
            fuzzer_sections, debug_info = _build_plugin_sections(
                plugin=plugin,
                matched_plugin_name=matched_plugin_name,
                plugin_candidates=plugin_candidates,
                base_name=fuzzer_base_by_name.get(fuzzer),
                ctx=ctx,
            )
            fuzzer_entry['extra_sections'] = serialize_extra_sections(
                [section for section in fuzzer_sections if section.scope == 'fuzzer'],
                default_owner_fuzzer=fuzzer,
            )
            debug_info['fuzzer_sections'] = len(fuzzer_entry['extra_sections'])
            target_only_sections = [section for section in fuzzer_sections if section.scope == 'target']
            debug_info['target_sections'] = len(target_only_sections)
            fuzzer_entry['extra_section_debug'] = [debug_info]
            target_debug.append(debug_info)
            target_sections.extend(target_only_sections)
        target['extra_sections'] = serialize_extra_sections(target_sections)
        target['extra_section_debug'] = target_debug


def _build_plugin_sections(
    *,
    plugin: Any,
    matched_plugin_name: str | None,
    plugin_candidates: list[str],
    base_name: str | None,
    ctx: ReportingContext,
) -> tuple[list[ExtraSection], dict[str, Any]]:
    debug_info: dict[str, Any] = {
        'fuzzer': ctx.fuzzer,
        'plugin_candidates': plugin_candidates,
        'matched_plugin': matched_plugin_name,
        'base_fuzzer': base_name,
        'trial_count': len(ctx.trials),
        'snapshot_dir_count': sum(len(paths) for paths in ctx.snapshot_dirs_by_trial.values()),
        'snapshot_dirs_by_trial': {str(trial_id): len(paths) for trial_id, paths in ctx.snapshot_dirs_by_trial.items()},
        'bug_count': len(ctx.bugs),
    }

    try:
        raw_sections = plugin.build_extra_sections(ctx)
    except Exception as exc:
        LOG.exception(
            'Extra section plugin failed for %s on %s:%s: %s',
            ctx.fuzzer,
            ctx.benchmark,
            ctx.fuzz_target,
            exc,
        )
        debug_info['status'] = 'error'
        debug_info['error'] = str(exc)
        raw_sections = []
    else:
        debug_info['status'] = 'ok'
        debug_info['returned_sections'] = len(raw_sections or [])

    debug_builder = getattr(plugin, 'build_debug_info', None)
    if callable(debug_builder):
        try:
            plugin_debug = debug_builder(ctx)
        except Exception as exc:
            debug_info['debug_error'] = str(exc)
        else:
            if isinstance(plugin_debug, dict):
                debug_info.update(plugin_debug)

    valid_sections, section_warnings = validate_extra_sections(raw_sections)
    if not matched_plugin_name:
        debug_info['status'] = 'no_plugin'
    elif matched_plugin_name != ctx.fuzzer:
        debug_info['plugin_resolution'] = 'base_fallback'
    if section_warnings:
        debug_info['validation_warnings'] = section_warnings
    if matched_plugin_name and not valid_sections:
        debug_info['reason'] = debug_info.get('reason') or 'plugin_returned_no_sections'
    return valid_sections, debug_info


def _build_reporting_context(
    *,
    run_id: str,
    run_dir: Path,
    benchmark: str,
    fuzz_target: str,
    fuzzer: str,
    reps: Sequence[dict[str, Any]],
    bugs: Sequence[dict[str, Any]],
    timeseries: dict[str, Any],
    snapshot_dirs_by_trial: dict[int, list[Path]],
) -> ReportingContext:
    timeseries_by_trial: dict[int, dict[str, Any]] = {}
    for trial in reps:
        trial_id = int(trial.get('trial_id') or 0)
        timeseries_entry = (timeseries.get('per_trial') or {}).get(str(trial_id))
        if not timeseries_entry:
            timeseries_entry = {'trial_id': trial_id, 'points': []}
        timeseries_by_trial[trial_id] = timeseries_entry
    return ReportingContext(
        run_id=run_id,
        run_dir=run_dir,
        benchmark=benchmark,
        fuzz_target=fuzz_target,
        fuzzer=fuzzer,
        trials=list(reps),
        timeseries_by_trial=timeseries_by_trial,
        bugs=list(bugs),
        snapshot_dirs_by_trial=snapshot_dirs_by_trial,
    )


def _snapshot_dirs_by_trial(
    reps: Sequence[dict[str, Any]],
    trial_snapshot_index: dict[tuple[str, str, int], list[Path]],
    plugin_candidates: Sequence[str],
    base_name: str | None,
) -> dict[int, list[Path]]:
    out: dict[int, list[Path]] = {}
    for trial in reps:
        trial_id = int(trial.get('trial_id') or 0)
        out[trial_id] = _trial_snapshot_dirs(trial, trial_snapshot_index, plugin_candidates, base_name)
    return out


def _trial_snapshot_dirs(
    trial: dict[str, Any],
    trial_snapshot_index: dict[tuple[str, str, int], list[Path]],
    plugin_candidates: Sequence[str],
    base_name: str | None,
) -> list[Path]:
    fuzzer = str(trial.get('fuzzer') or '')
    benchmark = str(trial.get('benchmark') or '')
    fuzz_target = str(trial.get('fuzz_target') or '')
    rep = safe_int(trial.get('rep'))
    target_id = f'{benchmark}-{fuzz_target}'.replace('/', '_')
    if not fuzzer or rep is None:
        return []
    for candidate in _dedupe([fuzzer, base_name, *plugin_candidates]):
        snapshots = trial_snapshot_index.get((candidate, target_id, rep))
        if snapshots:
            return list(snapshots)
    return []


def _build_trial_snapshot_index(run_dir: Path) -> dict[tuple[str, str, int], list[Path]]:
    out: dict[tuple[str, str, int], list[Path]] = {}
    trials_root = Path(run_dir) / 'trials'
    if not trials_root.is_dir():
        return out

    for snapshots_root in trials_root.glob('*/snapshots'):
        if not snapshots_root.is_dir():
            continue
        try:
            fuzzer, target_id, rep_part = snapshots_root.parent.name.rsplit('__', 2)
        except ValueError:
            continue
        if not rep_part.startswith('rep'):
            continue
        rep = safe_int(rep_part[3:])
        if rep is None:
            continue
        snap_dirs = [path.resolve() for path in sorted(snapshots_root.glob('snap_*')) if path.is_dir()]
        out[(fuzzer, target_id, rep)] = snap_dirs
    return out


def _load_fuzzer_plugin_candidates(run_dir: Path, repo_root: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    path = Path(run_dir) / 'benchmark_config.json'
    if not path.is_file():
        return {}, {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
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
        fuzzer_base = str(entry.get('fuzzer_base') or '').strip()
        if fuzzer_base:
            base_by_name[fuzzer_name] = fuzzer_base
        chain = [str(name).strip() for name in entry.get('fuzzer_chain') or [] if str(name).strip()]
        candidates_by_name[fuzzer_name] = _expand_reporting_candidates(repo_root, chain or [fuzzer_name, fuzzer_base])
    return candidates_by_name, base_by_name


def _plugin_candidates_for(fuzzer: str, repo_root: Path, candidates_by_name: dict[str, list[str]]) -> list[str]:
    return candidates_by_name.get(fuzzer) or _expand_reporting_candidates(repo_root, [fuzzer])


def _expand_reporting_candidates(repo_root: Path, names: Sequence[str | None]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        _add_reporting_candidate(repo_root, name, out, seen)
    return out


def _add_reporting_candidate(repo_root: Path, name: str | None, out: list[str], seen: set[str]) -> None:
    normalized = str(name or '').strip()
    if not normalized or normalized in seen:
        return
    seen.add(normalized)
    out.append(normalized)
    config = _load_fuzzer_yaml(repo_root, normalized)
    _add_reporting_candidate(repo_root, config.get('reporting_parent'), out, seen)
    _add_reporting_candidate(repo_root, config.get('parent'), out, seen)


def _load_fuzzer_yaml(repo_root: Path, fuzzer: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    root = Path(repo_root) / 'fuzzers' / fuzzer
    for path in (root / 'build' / 'build.yaml', root / 'run' / 'run.yaml'):
        if not path.is_file():
            continue
        for line in path.read_text(encoding='utf-8').splitlines():
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


def _group_by_target_fuzzer(rows: Sequence[dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row.get('benchmark') or ''),
            str(row.get('fuzz_target') or ''),
            str(row.get('fuzzer') or ''),
        )
        grouped.setdefault(key, []).append(row)
    return grouped


def _dedupe(values: Sequence[str | None]) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value or '').strip()
        if text and text not in out:
            out.append(text)
    return out
