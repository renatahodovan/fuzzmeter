# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Collect resource telemetry for active fuzzing containers.'''

from __future__ import annotations

import json
import logging
import re
import subprocess

from pathlib import Path
from typing import Any

from ..db import DB
from ..db import resource_telemetry as db_resource_telemetry
from ..trial.models import ActiveTrial

LOG = logging.getLogger(__name__)

_SIZE_UNITS = {
    'b': 1,
    'k': 1024,
    'kb': 1024,
    'kib': 1024,
    'm': 1024**2,
    'mb': 1024**2,
    'mib': 1024**2,
    'g': 1024**3,
    'gb': 1024**3,
    'gib': 1024**3,
    't': 1024**4,
    'tb': 1024**4,
    'tib': 1024**4,
}


def _parse_percent(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().rstrip('%')
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_size(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    match = re.match(r'^([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)?$', text)
    if not match:
        return None
    unit = (match.group(2) or 'b').lower()
    factor = _SIZE_UNITS.get(unit)
    if factor is None:
        return None
    return int(float(match.group(1)) * factor)


def _run_text(cmd: list[str], *, timeout_s: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_s, check=False)


class ResourceTelemetryCollector:
    '''Collect docker stats and live corpus disk usage at tick-save time.'''

    def collect(self, *, db: DB, tick_idx: int, ts: int, active_trials: list[ActiveTrial]) -> None:
        '''Collect and persist one resource sample for each active trial.'''

        for trial in active_trials:
            if trial.replay_start_ts is not None or trial.replay_end_ts is not None:
                continue
            stats = self._docker_stats(trial.container_name)
            if stats is None:
                continue
            disk_human, disk_bytes = self._du_hs(trial.live_out)
            db_resource_telemetry.upsert_resource_telemetry(
                db,
                trial_row_id=trial.trial_row_id,
                idx=tick_idx,
                ts=ts,
                container_name=trial.container_name,
                cpu_percent=_parse_percent(stats.get('CPUPerc')),
                memory_usage_bytes=self._memory_usage_bytes(stats),
                memory_limit_bytes=self._memory_limit_bytes(stats),
                memory_percent=_parse_percent(stats.get('MemPerc')),
                corpus_disk_usage_bytes=disk_bytes,
                corpus_disk_usage_human=disk_human,
                stats=stats,
            )

    @staticmethod
    def _docker_stats(container_name: str) -> dict[str, Any] | None:
        try:
            result = _run_text(
                ['docker', 'stats', '--no-stream', '--format', '{{json .}}', str(container_name)],
                timeout_s=15,
            )
        except Exception as exc:
            LOG.error('Docker stats failed for %s: %s', container_name, exc)
            return None
        if result.returncode != 0:
            LOG.error('Docker stats skipped for %s: %s', container_name, (result.stderr or '').strip())
            return None
        lines = (result.stdout or '').strip().splitlines()
        if not lines:
            return None
        try:
            parsed = json.loads(lines[0])
        except json.JSONDecodeError:
            LOG.error('Docker stats returned non-json output for %s: %s', container_name, lines[0])
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _memory_usage_bytes(stats: dict[str, Any]) -> int | None:
        mem_usage = str(stats.get('MemUsage') or '')
        used = mem_usage.split('/', 1)[0].strip()
        return _parse_size(used)

    @staticmethod
    def _memory_limit_bytes(stats: dict[str, Any]) -> int | None:
        mem_usage = str(stats.get('MemUsage') or '')
        if '/' not in mem_usage:
            return None
        limit = mem_usage.split('/', 1)[1].strip()
        return _parse_size(limit)

    @staticmethod
    def _du_hs(path: Path) -> tuple[str | None, int | None]:
        if not path.exists():
            return None, None
        try:
            result = _run_text(['du', '-hs', str(path)], timeout_s=30)
        except Exception as exc:
            LOG.warning('du -hs failed for %s: %s', path, exc)
            return None, None
        if result.returncode != 0:
            LOG.debug('du -hs failed for %s: %s', path, (result.stderr or '').strip())
            return None, None
        size_text = (result.stdout or '').strip().split(maxsplit=1)[0]
        return size_text, _parse_size(size_text)
