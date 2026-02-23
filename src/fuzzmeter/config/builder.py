# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build campaign configuration objects from YAML suite files.'''

from __future__ import annotations

import logging
import os

from pathlib import Path
from typing import Any

import yaml

from .models import CampaignCase, CampaignConfig, CampaignSettings

LOG = logging.getLogger(__name__)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if key not in out:
            out[key] = value
        elif isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        elif isinstance(out[key], list) and isinstance(value, list):
            out[key] = [*out[key], *value]
        elif isinstance(out[key], (dict, list)) != isinstance(value, (dict, list)):
            expected = 'dict' if isinstance(out[key], dict) else 'list'
            raise RuntimeError(f'{key} is not {expected} in override')
        else:
            out[key] = value
    return out


def _target_id(benchmark: str, fuzz_target: str) -> str:
    return f'{benchmark}-{fuzz_target}'.replace('/', '_')


def _parse_target_spec(spec: str) -> tuple[str, str, str]:
    if ':' not in spec:
        raise RuntimeError(f'Unexpected target spec format: %s (missinig \':\')', spec)
    project, fuzz_target = spec.split(':', 1)
    project = project.strip()
    fuzz_target = fuzz_target.strip()
    if not project or not fuzz_target:
        raise ValueError(f'Invalid target spec: {spec!r}')
    return project, fuzz_target, _target_id(project, fuzz_target)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    if not isinstance(data, dict):
        raise TypeError(f'Expected mapping in {path}')
    return data


def _load_target_config(path: Path) -> dict[str, Any]:
    data = _load_yaml(path)
    benchmark = str(data.get('project') or '')
    fuzz_target = str(data.get('fuzz_target') or '')
    input_mode = str(data.get('input_mode') or '')
    if not benchmark or not fuzz_target:
        raise RuntimeError(f'Missing {benchmark=} or {fuzz_target=}')
    return {
        'benchmark': benchmark,
        'fuzz_target': fuzz_target,
        'input_mode': input_mode,
        'target_id': _target_id(benchmark, fuzz_target),
        'config_path': str(path),
        'metadata': data,
    }


def _load_campaign_settings(data: dict[str, Any]) -> CampaignSettings:
    run_data = data.get('run') or {}
    snap_data = run_data.get('snapshot') or {}
    time_seconds = int(run_data.get('time_seconds', 3600))
    snapshot_every_seconds = int(snap_data.get('every_seconds', 1800))
    snapshot_jobs = snap_data.get('jobs')
    return CampaignSettings(
        time_seconds=time_seconds,
        repetitions=int(run_data.get('repetitions', 1)),
        parallel_jobs=int(max(1, run_data.get('parallel_jobs', os.cpu_count() or 1))),
        snapshot_jobs=None if snapshot_jobs is None else int(max(0, snapshot_jobs)),
        snapshot_every_seconds=snapshot_every_seconds,
        snapshot_export_every_ticks=_snapshot_export_every_ticks(
            snap_data=snap_data,
            time_seconds=time_seconds,
            snapshot_every_seconds=snapshot_every_seconds,
        ),
        memory=run_data.get('memory', '').strip() or None,
        memory_swap=run_data.get('memory_swap', '').strip() or None,
    )


def _snapshot_export_every_ticks(*, snap_data: dict[str, Any], time_seconds: int, snapshot_every_seconds: int) -> int:
    if snap_data.get('export_every_ticks') is not None:
        return int(snap_data['export_every_ticks'])

    if snapshot_every_seconds <= 0:
        return 1
    tick_count = max(1, int(time_seconds) // int(snapshot_every_seconds))
    return max(1, int(round(tick_count * 0.10)))


def _config_slice(key: str, data: dict[str, Any]) -> dict[str, Any]:
    allowed_benchmarks = data.get('allowed_benchmarks', [])
    allowed_benchmarks = set(allowed_benchmarks if isinstance(allowed_benchmarks, list) else [allowed_benchmarks])
    return {
        'key': key,
        'allowed_benchmarks': allowed_benchmarks,
        'build': dict(data.get('build') or {}),
        'runtime': dict(data.get('runtime') or {}),
        'replay_trials': tuple(Path(path).expanduser() for path in (data.get('replay_trials') or [])),
    }


def _load_fuzzer_config_chain(
    source_root: Path,
    fuzzer_name: str,
    seen: set[str] | None = None,
) -> list[dict[str, Any]]:
    seen = seen or set()
    if fuzzer_name in seen:
        raise ValueError(f'Cyclic fuzzer parent chain detected at {fuzzer_name}')
    seen.add(fuzzer_name)

    data = _load_fuzzer_config(source_root, fuzzer_name)

    chain = [_config_slice(fuzzer_name, data)]
    parent_name = str(data.get('parent') or '').strip()
    if not parent_name:
        return chain
    chain.extend(_load_fuzzer_config_chain(source_root, parent_name, seen))
    return chain


def _load_fuzzer_config(source_root: Path, fuzzer_name: str) -> dict[str, Any]:
    fuzzer_root = source_root / 'fuzzers' / fuzzer_name
    build_path = fuzzer_root / 'build' / 'build.yaml'
    run_path = fuzzer_root / 'run' / 'run.yaml'
    if not build_path.is_file() and not run_path.is_file():
        if fuzzer_root.is_dir():
            return {}
        raise FileNotFoundError(f'Fuzzer config not found: {build_path} or {run_path}')
    return _merge(_load_optional_fuzzer_yaml(build_path), _load_optional_fuzzer_yaml(run_path))


def _load_optional_fuzzer_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    if not isinstance(data, dict):
        raise TypeError(f'Expected mapping in {path}')
    return data


def _load_fuzzer_configs(data: dict[str, Any], source_root: Path) -> dict[str, list[dict[str, Any]]]:
    chains_by_name: dict[str, list[dict[str, Any]]] = {}
    for item in data.get('fuzzers', []):
        if isinstance(item, str):
            fuzzer_name = item.strip()
            if not fuzzer_name:
                raise ValueError('Fuzzer entry cannot be empty')
            base_name = fuzzer_name
            chain: list[dict[str, Any]] = []
        elif isinstance(item, dict):
            fuzzer_name = str(item.get('fuzzer') or '').strip()
            if not fuzzer_name:
                raise ValueError(f'Fuzzer entry must contain "fuzzer": {item!r}')
            base_name = str(item.get('parent') or fuzzer_name).strip()
            if not base_name:
                raise ValueError(f'Fuzzer entry must define a non-empty parent/base: {item!r}')
            chain = [_config_slice(fuzzer_name, item)]
        else:
            raise TypeError(f'Unsupported fuzzer entry: {item!r}')
        chain.extend(_load_fuzzer_config_chain(source_root, base_name))
        chains_by_name[fuzzer_name] = chain
    return chains_by_name


def _load_target_configs(data: dict[str, Any], source_root: Path) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for target_spec in data.get('targets', []):
        project, requested_fuzz_target, _ = _parse_target_spec(str(target_spec))
        path = source_root / 'targets' / project / 'benchmark.yaml'
        if not path.is_file():
            LOG.error('Missing benchmark config: %s', path)
            continue
        try:
            target_config = _load_target_config(path)
            benchmark = str(target_config['benchmark'])
            target_config['fuzz_target'] = requested_fuzz_target
            target_config['target_id'] = _target_id(benchmark, requested_fuzz_target)

            fuzzer_overrides = target_config['metadata'].get('fuzzers') or {}
            if not isinstance(fuzzer_overrides, dict):
                raise TypeError(f'Target fuzzers overrides must be a mapping: {path}')

            normalized_overrides: dict[str, dict[str, Any]] = {}
            for fuzzer_name, override in fuzzer_overrides.items():
                if not isinstance(override, dict):
                    raise TypeError(f'Benchmark fuzzers.{fuzzer_name} must be a mapping')
                normalized_overrides[str(fuzzer_name)] = override

            targets[str(target_config['target_id'])] = {
                'target_config': target_config,
                'fuzzer_configs': normalized_overrides,
            }
        except Exception as exc:
            LOG.error('Error loading benchmark config: %s: %s', path, exc)
            raise exc
    return targets


def _build_campaign_case(
    *,
    fuzzer_name: str,
    fuzzer_configs: list[dict[str, Any]],
    target_config: dict[str, Any],
    target_fuzzer_configs: dict[str, dict[str, Any]],
) -> CampaignCase:
    build_config: dict[str, Any] = {}
    runtime_config: dict[str, Any] = {}
    replay_trials: tuple[Path, ...] = ()
    fuzzer_chain: tuple[str, ...] = tuple(str(fuzzer_config['key']) for fuzzer_config in fuzzer_configs)

    for fuzzer_config in reversed(fuzzer_configs):
        level_key = str(fuzzer_config['key'])
        override = target_fuzzer_configs.get(level_key) or {}
        layer_build = _merge(dict(fuzzer_config.get('build') or {}), dict(override.get('build') or {}))
        layer_runtime = _merge(dict(fuzzer_config.get('runtime') or {}), dict(override.get('runtime') or {}))
        build_config = _merge(build_config, layer_build)
        runtime_config = _merge(runtime_config, layer_runtime)
        replay_trials = (*replay_trials, *tuple(fuzzer_config.get('replay_trials') or ()))
    runtime_config = _merge(_target_runtime_defaults(target_config), runtime_config)

    return CampaignCase(
        fuzzer_base=fuzzer_chain[1] if len(fuzzer_chain) > 1 else fuzzer_chain[0],
        fuzzer_name=fuzzer_name,
        fuzzer_chain=fuzzer_chain,
        benchmark=str(target_config['benchmark']),
        fuzz_target=str(target_config['fuzz_target']),
        target_id=str(target_config['target_id']),
        input_mode=str(target_config['input_mode']),
        build_config=build_config,
        runtime_config=runtime_config,
        replay_trials=replay_trials,
    )


def _target_runtime_defaults(target_config: dict[str, Any]) -> dict[str, Any]:
    metadata = target_config.get('metadata') or {}
    if not isinstance(metadata, dict):
        return {}

    timeout_s = metadata.get('timeout_s')
    if timeout_s is None:
        return {}
    return {
        'target': {
            'timeout_s': timeout_s,
        },
    }


def _fuzzer_allows_target(fuzzer_configs: list[dict[str, Any]], target_config: dict[str, Any]) -> bool:
    allowed_sets = [
        fuzzer_config['allowed_benchmarks']
        for fuzzer_config in fuzzer_configs
        if fuzzer_config.get('allowed_benchmarks')
    ]
    if not allowed_sets:
        return True

    benchmark = str(target_config['benchmark'])
    fuzz_target = str(target_config['fuzz_target'])
    target_spec = f'{benchmark}:{fuzz_target}'
    return all(target_spec in allowed for allowed in allowed_sets)


def load_campaign_config(source_root: Path, text: str) -> CampaignConfig:
    '''Load a campaign configuration from YAML text.'''
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise TypeError('Top-level config must be a mapping')

    fuzzer_configs = _load_fuzzer_configs(data, source_root)
    target_configs = _load_target_configs(data, source_root)
    cases = [
        _build_campaign_case(
            fuzzer_name=fuzzer_name,
            fuzzer_configs=fuzzer_config,
            target_config=target_data['target_config'],
            target_fuzzer_configs=target_data['fuzzer_configs'],
        )
        for fuzzer_name, fuzzer_config in fuzzer_configs.items()
        for target_data in target_configs.values()
        if _fuzzer_allows_target(fuzzer_config, target_data['target_config'])
    ]

    return CampaignConfig(
        settings=_load_campaign_settings(data),
        cases=cases,
    )
