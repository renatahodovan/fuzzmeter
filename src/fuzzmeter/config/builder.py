# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Build campaign configuration objects from YAML config files."""

from __future__ import annotations

import logging
import re

from pathlib import Path
from typing import Any

import yaml

from .models import CampaignCase, CampaignConfig, CampaignSettings

IDENTIFIER_RE = re.compile(r'^[a-zA-Z0-9_.-]+$')
INPUT_MODE_OPTIONS = ('in_process', 'file', 'stdin')
LOG = logging.getLogger(__name__)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if key in out and type(out[key]) is not type(value):
            raise ValueError(f'The type of {key} mismatches in configs to be merged.')

        if key not in out:
            out[key] = value
        elif isinstance(out[key], dict):
            out[key] = _merge(out[key], value)
        elif isinstance(out[key], list):
            out[key] = [*out[key], *value]
        else:
            out[key] = value
    return out


def _validate_benchmark_and_target(benchmark: str, fuzz_target: str) -> None:
    if not IDENTIFIER_RE.fullmatch(benchmark):
        raise ValueError(f'Target spec benchmark must match [a-zA-Z0-9_.-]+: {benchmark!r}')
    if not IDENTIFIER_RE.fullmatch(fuzz_target):
        raise ValueError(f'Target spec target must match [a-zA-Z0-9_.-]+: {fuzz_target!r}')


def _load_yaml(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f'YAML file is not a file: {path}')
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    if not isinstance(data, dict):
        raise TypeError(f'Expected mapping in {path}')
    return data


def _load_target_config(path: Path, requested_fuzz_target: str) -> dict[str, Any]:
    data = _load_yaml(path)

    benchmark = str(data.get('project') or '').strip()
    legacy_fuzz_target = str(data.get('fuzz_target') or '').strip()
    multi_target_data = data.get('fuzz_targets')

    has_legacy_target = bool(legacy_fuzz_target)
    has_multi_target = multi_target_data is not None
    if has_legacy_target and has_multi_target:
        raise ValueError(f'Benchmark config must define exactly one of fuzz_target or fuzz_targets: {path}')
    if not has_legacy_target and not has_multi_target:
        raise ValueError(f'Benchmark config must define fuzz_target or fuzz_targets: {path}')

    if has_multi_target:
        if not isinstance(multi_target_data, dict) or not multi_target_data:
            raise ValueError(f'Benchmark config fuzz_targets must be a non-empty mapping: {path}')
        if data.get('fuzzers') is not None:
            raise ValueError(f'Benchmark config with fuzz_targets must not define root-level fuzzers: {path}')
        target_data = multi_target_data.get(requested_fuzz_target)
        if target_data is None:
            raise ValueError(
                f'The requested fuzz target {requested_fuzz_target!r} is not defined in the {benchmark!r} benchmark.'
            )
        if not isinstance(target_data, dict):
            raise ValueError(f'Benchmark config fuzz_targets.{requested_fuzz_target} must be a mapping: {path}')
        fuzz_target = requested_fuzz_target
    else:
        fuzz_target = legacy_fuzz_target
        _validate_benchmark_and_target(benchmark, fuzz_target)
        if fuzz_target != requested_fuzz_target:
            raise ValueError(
                f'The requested fuzz target {requested_fuzz_target!r} is not defined in the {benchmark!r} benchmark.'
            )
        target_data = data

    _validate_benchmark_and_target(benchmark, fuzz_target)

    input_mode = str(target_data.get('input_mode') or '')
    if input_mode not in INPUT_MODE_OPTIONS:
        raise ValueError(f"Target config' input_mode must be one of {INPUT_MODE_OPTIONS} but got {input_mode}.")

    timeout_s = target_data.get('timeout_s')
    if timeout_s is None:
        LOG.debug(
            f'No target timeout was specified for {benchmark}:{fuzz_target}; using {CampaignCase.target_timeout_s} as default.'
        )
        timeout_s = CampaignCase.target_timeout_s
    timeout_s = float(timeout_s)
    if timeout_s <= 0:
        raise ValueError(f'Target timeout must be greater than 0, but {benchmark}:{fuzz_target} has {timeout_s}.')

    return {
        'benchmark': benchmark,
        'fuzz_target': fuzz_target,
        'input_mode': input_mode,
        'timeout_s': timeout_s,
        'target_id': f'{benchmark}-{fuzz_target}',
        'config_path': str(path),
        'fuzzers': target_data.get('fuzzers'),
    }


def _normalized_int_value(name: str, value: str, min_value: int, max_value: int | None = None) -> int:
    int_value = int(value)
    if int_value < min_value:
        raise ValueError(f'{name!r} value must be greater than {min_value}.')
    if max_value is not None and int_value > max_value:
        raise ValueError(f'{name!r} value must be less than {max_value}.')
    return int_value


def _load_campaign_settings(data: dict[str, Any]) -> CampaignSettings:
    run_data = data.get('run') or {}
    snap_data = run_data.get('snapshot') or {}
    return CampaignSettings(
        time_seconds=_normalized_int_value(
            'time_seconds', run_data.get('time_seconds', CampaignSettings.time_seconds), 60
        ),
        repetitions=_normalized_int_value('repetitions', run_data.get('repetitions', CampaignSettings.repetitions), 1),
        parallel_jobs=_normalized_int_value(
            'parallel_jobs', run_data.get('parallel_jobs', CampaignSettings.parallel_jobs), 1
        ),
        snapshot_jobs=_normalized_int_value('snapshot.jobs', snap_data.get('jobs', CampaignSettings.snapshot_jobs), 0),
        snapshot_every_seconds=_normalized_int_value(
            'snapshot.every_seconds', snap_data.get('every_seconds', CampaignSettings.snapshot_every_seconds), 60
        ),
        snapshot_export_every_ticks=_normalized_int_value(
            'snapshot.export_every_ticks',
            snap_data.get('export_every_ticks', CampaignSettings.snapshot_export_every_ticks),
            1,
        ),
        memory=run_data.get('memory', '') or None,
        memory_swap=run_data.get('memory_swap', '') or None,
    )


def _build_fuzzer_config(fuzzer_name: str, fuzzer_data: dict[str, Any]) -> dict[str, Any]:
    allowed_benchmarks = fuzzer_data.get('allowed_benchmarks') or []
    if not isinstance(allowed_benchmarks, list):
        raise ValueError('allowed_benchmarks must be defined as a list.')

    replay_trials = []
    for path in fuzzer_data.get('replay_trials') or []:
        path = Path(path).expanduser().resolve()
        if not path.is_dir():
            raise NotADirectoryError(f'Replay trial directory is not a directory: {path}')
        replay_trials.append(path)
    return {
        'fuzzer_name': fuzzer_name,
        'allowed_benchmarks': allowed_benchmarks,
        'build': dict(fuzzer_data.get('build') or {}),
        'runtime': dict(fuzzer_data.get('runtime') or {}),
        'replay_trials': tuple(replay_trials),
    }


def _build_fuzzer_hierarchy(
    source_root: Path,
    fuzzer_name: str,
    seen: set[str] | None = None,
) -> list[dict[str, Any]]:
    seen = seen or set()

    if not IDENTIFIER_RE.fullmatch(fuzzer_name):
        raise ValueError(f'Fuzzer name must match [a-zA-Z0-9_.-]+: {fuzzer_name!r}')
    if fuzzer_name in seen:
        raise ValueError(f'Cyclic fuzzer parent chain detected at {fuzzer_name}')
    seen.add(fuzzer_name)

    fuzzer_data = _load_fuzzer_config(source_root, fuzzer_name)
    fuzzer_hierarchy = [_build_fuzzer_config(fuzzer_name, fuzzer_data)]
    parent_name = fuzzer_data.get('parent')
    if parent_name:
        fuzzer_hierarchy.extend(_build_fuzzer_hierarchy(source_root, parent_name, seen))
    return fuzzer_hierarchy


def _load_fuzzer_config(source_root: Path, fuzzer_name: str) -> dict[str, Any]:
    fuzzer_root = (source_root / 'fuzzers' / fuzzer_name).resolve()
    if not fuzzer_root.is_dir():
        raise NotADirectoryError(f'Fuzzer directory is not a directory: {fuzzer_root}')

    yaml_data = []
    for path in (fuzzer_root / 'build' / 'build.yaml', fuzzer_root / 'run' / 'run.yaml'):
        if path.is_file():
            yaml_data.append(_load_yaml(path))

    if not yaml_data:
        return {}
    return yaml_data[0] if len(yaml_data) == 1 else _merge(*yaml_data)


def _load_fuzzer_configs(data: dict[str, Any], source_root: Path) -> dict[str, list[dict[str, Any]]]:
    fuzzers: dict[str, list[dict[str, Any]]] = {}
    for fuzzer_data in data.get('fuzzers', []):
        if isinstance(fuzzer_data, str):
            fuzzer_name, parent_name = fuzzer_data, fuzzer_data
            fuzzer_hierarchy: list[dict[str, Any]] = []
        elif isinstance(fuzzer_data, dict):
            fuzzer_name = fuzzer_data.get('fuzzer')
            if not fuzzer_name:
                raise ValueError('Missing value field from fuzzer defintion.')
            if not isinstance(fuzzer_name, str):
                raise ValueError('Fuzzer name must be defined as string.')
            parent_name = fuzzer_data.get('parent') or fuzzer_name
            if not isinstance(parent_name, str):
                raise ValueError('Parent fuzzer must be defined as string.')
            fuzzer_hierarchy = [_build_fuzzer_config(fuzzer_name, fuzzer_data)]
        else:
            raise TypeError(f'Unsupported fuzzer entry: {fuzzer_data!r}')

        if not IDENTIFIER_RE.fullmatch(fuzzer_name):
            raise ValueError(f'Fuzzer name must match [a-zA-Z0-9_.-]+: {fuzzer_name!r}')

        fuzzers[fuzzer_name] = fuzzer_hierarchy + _build_fuzzer_hierarchy(source_root, parent_name)
    return fuzzers


def _load_target_configs(data: dict[str, Any], source_root: Path) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for target_spec in data.get('targets', []):
        if ':' not in target_spec:
            raise ValueError(f"Unexpected target spec format: {target_spec!r} (missing ':')")
        benchmark, fuzz_target = target_spec.split(':', 1)
        benchmark, fuzz_target = benchmark.strip(), fuzz_target.strip()
        _validate_benchmark_and_target(benchmark, fuzz_target)

        path = source_root / 'targets' / benchmark / 'benchmark.yaml'
        try:
            target_config = _load_target_config(path, fuzz_target)

            fuzzer_overrides = target_config.get('fuzzers') or {}
            if fuzzer_overrides:
                if not isinstance(fuzzer_overrides, dict):
                    raise TypeError(f'Target fuzzers overrides must be a mapping: {path}')

                if not all(isinstance(override, dict) for override in fuzzer_overrides.values()):
                    raise ValueError('Fuzzer overrides in benchmark configs must be mappings.')

            targets[target_config['target_id']] = {
                'target_config': target_config,
                'fuzzer_configs': fuzzer_overrides,
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
    fuzzer_chain: tuple[str, ...] = tuple(str(fuzzer_config['fuzzer_name']) for fuzzer_config in fuzzer_configs)

    for fuzzer_config in reversed(fuzzer_configs):
        cur_fuzz_id = str(fuzzer_config['fuzzer_name'])
        target_override = target_fuzzer_configs.get(cur_fuzz_id) or {}
        cur_fuzz_build = _merge(fuzzer_config.get('build') or {}, target_override.get('build') or {})
        curr_fuzz_runtime = _merge(fuzzer_config.get('runtime') or {}, target_override.get('runtime') or {})
        build_config = _merge(build_config, cur_fuzz_build)
        runtime_config = _merge(runtime_config, curr_fuzz_runtime)
        replay_trials = (*replay_trials, *tuple(fuzzer_config.get('replay_trials') or ()))

    return CampaignCase(
        fuzzer_base=fuzzer_chain[1] if len(fuzzer_chain) > 1 else fuzzer_chain[0],
        fuzzer_name=fuzzer_name,
        fuzzer_chain=fuzzer_chain,
        benchmark=target_config['benchmark'],
        fuzz_target=target_config['fuzz_target'],
        target_id=target_config['target_id'],
        input_mode=target_config['input_mode'],
        target_timeout_s=target_config['timeout_s'],
        build_config=build_config,
        runtime_config=runtime_config,
        replay_trials=replay_trials,
    )


def _fuzzer_allows_target(fuzzer_configs: list[dict[str, Any]], target_config: dict) -> bool:
    allowed_sets = [
        fuzzer_config['allowed_benchmarks']
        for fuzzer_config in fuzzer_configs
        if fuzzer_config.get('allowed_benchmarks')
    ]
    if not allowed_sets:
        return True

    return all(f'{target_config["benchmark"]}:{target_config["fuzz_target"]}' in allowed for allowed in allowed_sets)


def load_campaign_config(source_root: Path, text: str) -> CampaignConfig:
    """Load a campaign configuration from YAML text."""
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
