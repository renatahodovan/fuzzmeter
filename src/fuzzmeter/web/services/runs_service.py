# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Collect run metadata and mutate run directories for the web UI.'''

from __future__ import annotations

import shutil

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ...db.report_views import ReportingDB
from .file_service import require_run_dir


@dataclass(frozen=True)
class RunPolicy:
    '''Summarize execution policy values parsed from a run config.'''

    time_seconds: int = 0
    repetitions: int = 0
    parallel_jobs: int = 0
    snapshot_every_seconds: int = 0


@dataclass(frozen=True)
class RunConfig:
    '''Summarize fuzzer, target, and policy values parsed from run config YAML.'''

    fuzzers: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    policy: RunPolicy = field(default_factory=RunPolicy)


@dataclass(frozen=True)
class RunSummary:
    '''Summarize one run from its database and config files.'''

    created_ts: int | None = None
    trials: int = 0
    snapshots: int = 0
    bugs: int = 0
    benchmark_count: int = 0
    target_count: int = 0
    fuzzer_count: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    config: RunConfig = field(default_factory=RunConfig)


@dataclass(frozen=True)
class RunEntry:
    '''Describe one discovered run directory for the web run list.'''

    run_id: str
    directory_name: str
    label: str | None
    path: Path
    has_static_report: bool
    updated_ts: int | None
    summary: RunSummary
    error: str | None = None


def parse_config(config_src: str | None) -> RunConfig:
    '''Parse the web-facing summary fields from raw run config YAML.'''

    if not config_src:
        return RunConfig()
    try:
        data = yaml.safe_load(config_src) or {}
    except yaml.YAMLError:
        return RunConfig()
    if not isinstance(data, dict):
        return RunConfig()

    fuzzers = [_fuzzer_name(item) for item in data.get('fuzzers', [])]
    targets = [str(item) for item in data.get('targets', []) if str(item).strip()]
    run_cfg = data.get('run') or {}
    snapshot_cfg = run_cfg.get('snapshot') or {}
    return RunConfig(
        fuzzers=[name for name in fuzzers if name],
        targets=targets,
        policy=RunPolicy(
            time_seconds=int(run_cfg.get('time_seconds', 0) or 0),
            repetitions=int(run_cfg.get('repetitions', 0) or 0),
            parallel_jobs=int(run_cfg.get('parallel_jobs', 0) or 0),
            snapshot_every_seconds=int(snapshot_cfg.get('every_seconds', 0) or 0),
        ),
    )


def list_runs(run_dirs: Iterable[Path]) -> list[RunEntry]:
    '''List configured runs sorted by most recent activity.'''

    runs = [_list_run_entry(path) for path in run_dirs if Path(path).is_dir()]
    runs.sort(
        key=lambda item: (
            int(item.updated_ts or 0),
            int(item.summary.created_ts or 0),
            item.run_id,
        ),
        reverse=True,
    )
    return runs


def delete_run(run_dirs: Iterable[Path], run_id: str) -> None:
    '''Delete one run directory after validating its path.'''

    run_dir = require_run_dir(run_dirs, run_id)
    shutil.rmtree(run_dir, ignore_errors=False)


def delete_runs(run_dirs: Iterable[Path], run_ids: list[Any]) -> dict[str, Any]:
    '''Delete multiple runs and return a structured outcome summary.'''

    deleted: list[str] = []
    missing: list[str] = []
    failed: list[dict[str, str]] = []

    for run_id in [str(run_id) for run_id in run_ids if str(run_id).strip()]:
        try:
            delete_run(run_dirs, run_id)
            deleted.append(run_id)
        except FileNotFoundError:
            missing.append(run_id)
        except (OSError, ValueError) as exc:
            failed.append({'run_id': run_id, 'error': str(exc)})

    return {
        'ok': not failed,
        'deleted': deleted,
        'missing': missing,
        'failed': failed,
    }


def _fuzzer_name(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get('fuzzer') or item.get('name') or item.get('parent') or '').strip() or None
    return None


def _updated_ts(run_dir: Path) -> int | None:
    candidates = [
        run_dir,
        run_dir / 'fuzzmeter.db',
        run_dir / 'config.yaml',
        run_dir / 'report' / 'report.html',
        run_dir / 'report' / 'data.json',
    ]
    mtimes: list[int] = []
    for path in candidates:
        try:
            if path.exists():
                mtimes.append(int(path.stat().st_mtime))
        except OSError:
            continue
    return max(mtimes) if mtimes else None


def _list_run_entry(run_dir: Path) -> RunEntry:
    run_dir = Path(run_dir).resolve()
    updated_ts = _updated_ts(run_dir)
    directory_name = run_dir.name
    run_id = directory_name
    label: str | None = None
    has_static_report = (run_dir / 'report' / 'report.html').is_file()
    db_path = run_dir / 'fuzzmeter.db'
    config_path = run_dir / 'config.yaml'
    summary = RunSummary()
    error: str | None = None

    if config_path.is_file():
        try:
            summary = RunSummary(config=parse_config(config_path.read_text(encoding='utf-8')))
        except (OSError, TypeError, ValueError):
            pass

    if db_path.is_file():
        try:
            with ReportingDB(db_path) as db:
                inferred_run_id = db.infer_run_id(run_id)
                counts = db.run_summary_counts(inferred_run_id)
                config = parse_config(counts.get('config_src'))
                summary = RunSummary(
                    created_ts=counts['created_ts'],
                    trials=counts['trials'],
                    snapshots=counts['snapshots'],
                    bugs=counts['bugs'],
                    benchmark_count=counts['benchmark_count'],
                    target_count=counts['target_count'],
                    fuzzer_count=counts['fuzzer_count'] or len(config.fuzzers),
                    status_counts=counts['status_counts'],
                    config=config,
                )
                label = counts['label']
                run_id = inferred_run_id
        except Exception as exc:
            error = str(exc)
    return RunEntry(
        run_id=run_id,
        directory_name=directory_name,
        label=label,
        path=run_dir,
        has_static_report=has_static_report,
        updated_ts=updated_ts,
        summary=summary,
        error=error,
    )
