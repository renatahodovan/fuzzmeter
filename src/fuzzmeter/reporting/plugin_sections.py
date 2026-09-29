# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Load, execute, and serialize plugin-provided report sections.'''

from __future__ import annotations

import json
import logging

from pathlib import Path
from typing import Any, Sequence

from ..config.models import read_run_config
from .analyzers.trial_analysis import TrialReport
from .metrics import safe_int
from .plugin_api import ExtraSection, ReportingContext
from .plugins.loader import ReportingPluginLoader
from .web_payload import serialize_extra_sections, validate_extra_sections

LOG = logging.getLogger(__name__)


def attach_extra_sections(
    *,
    fuzzer_dirs: dict[str, Path],
    run_dir: Path,
    run_id: str,
    targets: list[dict[str, Any]],
    trials: list[TrialReport],
    timeseries: dict[str, Any],
    bugs: list[dict[str, Any]],
) -> None:
    '''Attach plugin-provided extra report sections to target and fuzzer entries.'''

    loader = ReportingPluginLoader(fuzzer_dirs)
    fuzzer_candidates_by_name, fuzzer_base_by_name = read_run_config(Path(run_dir))
    trial_snapshot_index = _build_trial_snapshot_index(run_dir)
    trials_by_target_fuzzer = _trials_by_target_fuzzer(trials)
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
            plugin_candidates = fuzzer_candidates_by_name.get(fuzzer) or [fuzzer]
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
            if loader.load_errors:
                debug_info['load_errors'] = list(loader.load_errors)
                if matched_plugin_name is None:
                    debug_info['status'] = 'load_error'
                    debug_info['error'] = loader.load_errors[-1]['error']
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
            json.dumps(plugin_debug, allow_nan=False)
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
    reps: Sequence[TrialReport],
    bugs: Sequence[dict[str, Any]],
    timeseries: dict[str, Any],
    snapshot_dirs_by_trial: dict[int, list[Path]],
) -> ReportingContext:
    timeseries_by_trial: dict[int, dict[str, Any]] = {}
    for trial in reps:
        timeseries_entry = (timeseries.get('per_trial') or {}).get(str(trial.trial_id))
        if not timeseries_entry:
            timeseries_entry = {'trial_id': trial.trial_id, 'points': []}
        timeseries_by_trial[trial.trial_id] = timeseries_entry
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
    reps: Sequence[TrialReport],
    trial_snapshot_index: dict[tuple[str, str, int], list[Path]],
    plugin_candidates: Sequence[str],
    base_name: str | None,
) -> dict[int, list[Path]]:
    return {
        trial.trial_id: _trial_snapshot_dirs(trial, trial_snapshot_index, plugin_candidates, base_name)
        for trial in reps
    }


def _trial_snapshot_dirs(
    trial: TrialReport,
    trial_snapshot_index: dict[tuple[str, str, int], list[Path]],
    plugin_candidates: Sequence[str],
    base_name: str | None,
) -> list[Path]:
    target_id = f'{trial.benchmark}-{trial.fuzz_target}'.replace('/', '_')
    for candidate in dedupe([trial.fuzzer, base_name, *plugin_candidates]):
        snapshots = trial_snapshot_index.get((candidate, target_id, trial.rep))
        if snapshots:
            return list(snapshots)
    return []


def dedupe(values: Sequence[str | None]) -> list[str]:
    '''Return non-empty strings without duplicates, preserving order.'''

    out: list[str] = []
    for value in values:
        text = str(value or '').strip()
        if text and text not in out:
            out.append(text)
    return out


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


def _trials_by_target_fuzzer(trials: Sequence[TrialReport]) -> dict[tuple[str, str, str], list[TrialReport]]:
    grouped: dict[tuple[str, str, str], list[TrialReport]] = {}
    for trial in trials:
        grouped.setdefault((trial.benchmark, trial.fuzz_target, trial.fuzzer), []).append(trial)
    return grouped


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
