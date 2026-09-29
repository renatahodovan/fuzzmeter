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
import math
import re
import subprocess

from pathlib import Path
from typing import Any

from ..db import DB
from ..db import resource_telemetry as db_resource_telemetry
from ..trial.models import TrialInstance

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
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


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


class ResourceTelemetryCollector:
    '''Collect docker stats and live corpus disk usage at tick-save time.'''

    def collect(self, *, db: DB, tick_idx: int, ts: int, active_trials: list[TrialInstance]) -> None:
        '''Collect and persist one resource sample for each active trial.'''
        stats_by_container = self._docker_stats_by_container([trial.container_name for trial in active_trials])
        for trial in active_trials:
            stats = {} if stats_by_container is None else stats_by_container.get(trial.container_name)
            if stats is None:
                LOG.warning('Container %s exited before resource telemetry collection', trial.container_name)
                stats = {}
            disk_kib = self._du_sk(trial.layout.fuzz_dir)
            disk_bytes = None if disk_kib is None else disk_kib * 1024
            db_resource_telemetry.upsert_resource_telemetry(
                db,
                db_resource_telemetry.TelemetrySample(
                    trial_id=trial.db_id,
                    idx=tick_idx,
                    ts=ts,
                    container_name=trial.container_name,
                    cpu_percent=_parse_percent(stats.get('CPUPerc')),
                    memory_usage_bytes=self._memory_usage_bytes(stats),
                    memory_limit_bytes=self._memory_limit_bytes(stats),
                    memory_percent=_parse_percent(stats.get('MemPerc')),
                    corpus_disk_usage_bytes=disk_bytes,
                ),
            )

    @staticmethod
    def _docker_stats_by_container(container_names: list[str]) -> dict[str, dict[str, Any]] | None:
        try:
            result = subprocess.run(
                ['docker', 'stats', '--no-stream', '--format', '{{json .}}', *container_names],
                timeout=15,
                text=True,
                capture_output=True,
                check=True,
            )
            lines = (result.stdout or '').strip().splitlines()
            if not lines:
                raise RuntimeError('Docker stats returned no output')

            return {
                str(parsed['Name']): parsed
                for parsed in (json.loads(line) for line in lines)
            }
        except (KeyError, RuntimeError, TypeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            message = (getattr(exc, 'stderr', '') or '').strip() or str(exc) or 'docker stats failed'
            LOG.warning('Docker stats failed for %d container(s): %s', len(container_names), message)
            return None

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
    def _du_sk(path: Path) -> int | None:
        try:
            result = subprocess.run(['du', '-sk', str(path)],
                                    timeout=30, text=True, capture_output=True, check=True)
            return int((result.stdout or '').strip().split(maxsplit=1)[0])
        except (IndexError, ValueError, subprocess.SubprocessError) as exc:
            LOG.warning('du -sk failed for %s: %s', path, exc)
            return None
