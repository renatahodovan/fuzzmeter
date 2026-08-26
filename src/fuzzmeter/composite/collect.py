# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Collect composite measurement descriptors from campaign configuration.'''

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import time

from pathlib import Path

from ..config import CampaignCase, CampaignConfig
from ..db import metadata as db_metadata
from ..db.base import open_db
from .canonical import canonical_digest
from .models import MetadataTriplet
from .source_hook import run_source_hook, source_hook_context


def collect_records(
    *,
    run_id: str,
    campaign_config: CampaignConfig,
) -> list[db_metadata.MetadataRecord]:
    '''Collect composite descriptor records for all campaign cases.'''
    environment = collect_environment()
    created_at = int(time.time())
    return [
        _record_for_case(
            run_id=run_id,
            campaign_config=campaign_config,
            case=case,
            environment=environment,
            created_at=created_at,
        )
        for case in campaign_config.cases
    ]


def save_records(db_path: Path, records: list[db_metadata.MetadataRecord]) -> None:
    '''Persist collected composite descriptors.'''
    with open_db(Path(db_path)) as db:
        for record in records:
            db_metadata.upsert_metadata(db, record)


def collect_environment() -> dict[str, object]:
    '''Collect structured host, Docker, and toolchain metadata.'''
    return {
        'host': {
            'system': platform.system(),
            'release': platform.release(),
            'version': platform.version(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'python': sys.version.split()[0],
        },
        'docker': {
            'version': _stable_docker_version(_docker_json('version')),
            'info': _stable_docker_info(_docker_json('info')),
        },
        'toolchain': {
            'cc': _tool_version('cc'),
            'clang': _tool_version('clang'),
            'gcc': _tool_version('gcc'),
        },
    }


def collect_config(case: CampaignCase) -> dict[str, object]:
    '''Return the case configuration fields used in composite comparisons.'''
    return {
        'benchmark': case.benchmark,
        'fuzz_target': case.fuzz_target,
        'input_mode': case.input_mode,
        'timeout': case.target_timeout_s,
    }


def collect_source(
    case: CampaignCase,
    fuzzer_dirs: dict[str, Path],
    benchmark_dirs: dict[str, Path],
) -> dict[str, object]:
    '''Collect user-defined benchmark and fuzzer source metadata hook results.'''
    benchmark_hook = benchmark_dirs[case.benchmark] / 'source_info.py'
    fuzzer_hook = fuzzer_dirs[case.fuzzer_name] / 'source_info.py'
    return {
        'benchmark_source': run_source_hook(
            benchmark_hook,
            source_hook_context(case),
            'benchmark_source',
        ).to_json(),
        'fuzzer_version': run_source_hook(
            fuzzer_hook,
            source_hook_context(case),
            'fuzzer_version',
        ).to_json(),
    }


def metadata_for_case(
    *,
    case: CampaignCase,
    environment: dict[str, object],
    fuzzer_dirs: dict[str, Path],
    benchmark_dirs: dict[str, Path],
) -> MetadataTriplet:
    '''Build comparable metadata for one campaign case.'''
    config = collect_config(case)
    source = collect_source(case, fuzzer_dirs, benchmark_dirs)
    return MetadataTriplet(
        environment=environment,
        config=config,
        source=source,
        environment_digest=canonical_digest(environment),
        config_digest=canonical_digest(config),
        source_digest=canonical_digest(source),
    )


def _record_for_case(
    *,
    run_id: str,
    campaign_config: CampaignConfig,
    case: CampaignCase,
    environment: dict[str, object],
    created_at: int,
) -> db_metadata.MetadataRecord:
    metadata = metadata_for_case(
        case=case,
        environment=environment,
        fuzzer_dirs=campaign_config.fuzzer_dirs,
        benchmark_dirs=campaign_config.benchmark_dirs,
    )
    return db_metadata.MetadataRecord(
        run_id=run_id,
        fuzzer=case.fuzzer_id,
        benchmark=case.benchmark,
        fuzz_target=case.fuzz_target,
        repetitions=campaign_config.settings.repetitions,
        runtime_seconds=campaign_config.settings.time_seconds,
        environment_digest=metadata.environment_digest,
        config_digest=metadata.config_digest,
        source_digest=metadata.source_digest,
        metadata=metadata.to_json(),
        created_at=created_at,
    )


def _stable_docker_version(data: dict[str, object]) -> dict[str, object]:
    return _pick(data, ('Client.Version', 'Server.Version', 'Server.APIVersion', 'Server.Os', 'Server.Arch'))


def _stable_docker_info(data: dict[str, object]) -> dict[str, object]:
    return _pick(data, (
        'Architecture',
        'OSType',
        'OperatingSystem',
        'KernelVersion',
        'ServerVersion',
        'DockerRootDir',
        'Driver',
        'CgroupDriver',
        'CgroupVersion',
        'Runtimes',
        'DefaultRuntime',
        'SecurityOptions',
    ))


def _pick(data: dict[str, object], dotted_keys: tuple[str, ...]) -> dict[str, object]:
    out: dict[str, object] = {}
    for dotted_key in dotted_keys:
        value = _nested_value(data, dotted_key.split('.'))
        if value is not None:
            _set_nested_value(out, dotted_key.split('.'), value)
    return out


def _nested_value(data: dict[str, object], parts: list[str]) -> object | None:
    current: object = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _set_nested_value(data: dict[str, object], parts: list[str], value: object) -> None:
    current = data
    for part in parts[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            return
        current = child
    current[parts[-1]] = value


def _docker_json(command: str) -> dict[str, object]:
    docker = shutil.which('docker')
    if docker is None:
        return {}
    try:
        result = subprocess.run(
            [docker, command, '--format', '{{json .}}'],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _tool_version(name: str) -> str | None:
    tool = shutil.which(name)
    if tool is None:
        return None
    try:
        result = subprocess.run(
            [tool, '--version'],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    first_line = result.stdout.splitlines()[:1] or result.stderr.splitlines()[:1]
    return first_line[0] if first_line else None
