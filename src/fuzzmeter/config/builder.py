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

from .models import CampaignCase, CampaignConfig, CampaignSettings, target_key

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


def _validate_benchmark_and_fuzz_target(benchmark: str, fuzz_target: str) -> None:
    if not IDENTIFIER_RE.fullmatch(benchmark):
        raise ValueError(f'Benchmark name must match [a-zA-Z0-9_.-]+: {benchmark!r}')
    if not IDENTIFIER_RE.fullmatch(fuzz_target):
        raise ValueError(f'Fuzz target name must match [a-zA-Z0-9_.-]+: {fuzz_target!r}')


def _load_yaml(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f'YAML file is not a file: {path}')

    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f'{path}: invalid YAML: {exc}') from exc

    if not isinstance(data, dict):
        raise TypeError(f'Expected mapping in {path}')
    return data


def _load_fuzz_target_config(path: Path, fuzz_target: str) -> dict[str, Any]:
    data = _load_yaml(path)

    benchmark = data.get('benchmark')
    if not benchmark or not isinstance(benchmark, str):
        raise ValueError(f'{path}: benchmark must be a non-empty string.')

    fuzz_targets_data = data.get('fuzz_targets')
    if not fuzz_targets_data or not isinstance(fuzz_targets_data, dict):
        raise ValueError(f'{path}: fuzz_targets must be a non-empty mapping.')

    fuzz_target_data = fuzz_targets_data.get(fuzz_target)
    if fuzz_target_data is None or not isinstance(fuzz_target_data, dict):
        raise ValueError(f'{path}: fuzz_targets[{fuzz_target!r}] must be a mapping.')

    input_mode = str(fuzz_target_data.get('input_mode') or '')
    if input_mode not in INPUT_MODE_OPTIONS:
        raise ValueError(f'{path}: fuzz_targets[{fuzz_target!r}].input_mode must be one of {INPUT_MODE_OPTIONS}; got {input_mode!r}.')

    timeout_value = fuzz_target_data.get('timeout_s')
    if timeout_value is None:
        LOG.debug(
            f'No fuzz target timeout was specified for {benchmark}:{fuzz_target}; '
            f'using {CampaignCase.target_timeout_s} as default.'
        )
        timeout_value = CampaignCase.target_timeout_s

    try:
        timeout_s = float(timeout_value)
        if timeout_s <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(
            f'{path}: fuzz_targets[{fuzz_target!r}].timeout_s '
            f'must be a positive number; got {timeout_value!r}.'
        ) from None

    fuzzer_overrides = fuzz_target_data.get('fuzzers') or {}
    if not isinstance(fuzzer_overrides, dict):
        raise TypeError(f'Fuzz target fuzzer overrides must be a mapping: {path}')
    if not all(isinstance(override, dict) for override in fuzzer_overrides.values()):
        raise ValueError('Fuzzer overrides in benchmark configs must be mappings.')

    return {
        'benchmark': benchmark,
        'fuzz_target': fuzz_target,
        'input_mode': input_mode,
        'timeout_s': timeout_s,
        'config_path': str(path),
        'fuzzers': fuzzer_overrides,
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
    source_info = run_data.get('source_info', run_data.get('identity', CampaignSettings.source_info))
    if not isinstance(source_info, bool):
        raise TypeError('run.source_info must be true or false.')
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
        source_info=source_info,
    )


def _build_fuzzer_config(fuzzer_name: str, fuzzer_data: dict[str, Any]) -> dict[str, Any]:
    allowed_fuzz_targets = fuzzer_data.get('allowed_fuzz_targets') or []
    if not isinstance(allowed_fuzz_targets, list):
        raise ValueError('allowed_fuzz_targets must be defined as a list.')

    replay_trials = []
    for replay_path in fuzzer_data.get('replay_trials') or []:
        path = Path(replay_path).expanduser().resolve()
        if not path.is_dir():
            raise NotADirectoryError(f'Replay trial directory is not a directory: {path}')
        replay_trials.append(path)
    return {
        'fuzzer_name': fuzzer_name,
        'allowed_fuzz_targets': allowed_fuzz_targets,
        'build': dict(fuzzer_data.get('build') or {}),
        'runtime': dict(fuzzer_data.get('runtime') or {}),
        'replay_trials': tuple(replay_trials),
    }


def _load_fuzzer_chain(
    fuzzer_dirs: dict[str, Path],
    fuzzer_name: str,
    seen: set[str] | None = None,
) -> list[dict[str, Any]]:
    seen = seen or set()

    if not IDENTIFIER_RE.fullmatch(fuzzer_name):
        raise ValueError(f'Fuzzer name must match [a-zA-Z0-9_.-]+: {fuzzer_name!r}')
    if fuzzer_name not in fuzzer_dirs:
        raise ValueError(f'Fuzzer {fuzzer_name!r} is not configured; include it with --fuzzers.')
    if fuzzer_name in seen:
        raise ValueError(f'Cyclic fuzzer parent chain detected at {fuzzer_name}')
    seen.add(fuzzer_name)

    fuzzer_dir = fuzzer_dirs[fuzzer_name]
    fuzzer_data: dict[str, Any] = {}
    for path in (fuzzer_dir / 'build' / 'build.yaml', fuzzer_dir / 'run' / 'run.yaml'):
        if path.is_file():
            fuzzer_data = _merge(fuzzer_data, _load_yaml(path))
    fuzzer_chain = [_build_fuzzer_config(fuzzer_name, fuzzer_data)]
    parent_name = fuzzer_data.get('parent')
    if parent_name:
        fuzzer_chain.extend(_load_fuzzer_chain(fuzzer_dirs, parent_name, seen))
    return fuzzer_chain


def _load_fuzzer_configs(data: dict[str, Any], fuzzer_dirs: dict[str, Path]) -> dict[str, list[dict[str, Any]]]:
    fuzzers: dict[str, list[dict[str, Any]]] = {}
    for fuzzer_data in data.get('fuzzers', []):
        if isinstance(fuzzer_data, str):
            fuzzer_name, parent_name = fuzzer_data, fuzzer_data
            fuzzer_config: list[dict[str, Any]] = []
        elif isinstance(fuzzer_data, dict):
            fuzzer_name = fuzzer_data.get('fuzzer')
            if not fuzzer_name or not isinstance(fuzzer_name, str):
                raise ValueError(f'Fuzzer description must contain a "fuzzer" field of string value: {fuzzer_data!r}')
            parent_name = fuzzer_data.get('parent') or fuzzer_name
            if not isinstance(parent_name, str):
                raise ValueError('Parent fuzzer must be defined as string.')
            fuzzer_config = [_build_fuzzer_config(fuzzer_name, fuzzer_data)]
        else:
            raise TypeError(f'Unsupported fuzzer entry: {fuzzer_data!r}')

        if not IDENTIFIER_RE.fullmatch(fuzzer_name):
            raise ValueError(f'Fuzzer name must match [a-zA-Z0-9_.-]+: {fuzzer_name!r}')

        fuzzers[fuzzer_name] = fuzzer_config + _load_fuzzer_chain(fuzzer_dirs, parent_name)
    return fuzzers


def _load_fuzz_target_configs(data: dict[str, Any], benchmark_dirs: dict[str, Path]) -> dict[str, dict[str, Any]]:
    fuzz_target_configs: dict[str, dict[str, Any]] = {}
    for fuzz_target_spec in data.get('fuzz_targets', []):
        if ':' not in fuzz_target_spec:
            raise ValueError(f"Unexpected fuzz target spec format: {fuzz_target_spec!r} (missing ':')")
        benchmark, fuzz_target = fuzz_target_spec.split(':', 1)
        benchmark, fuzz_target = benchmark.strip(), fuzz_target.strip()
        _validate_benchmark_and_fuzz_target(benchmark, fuzz_target)

        if benchmark not in benchmark_dirs:
            raise ValueError(f'Benchmark {benchmark!r} is not configured; include it with --benchmarks.')

        path = benchmark_dirs[benchmark] / 'benchmark.yaml'
        fuzz_target_config = _load_fuzz_target_config(path, fuzz_target)
        fuzz_target_configs[target_key(fuzz_target_config['benchmark'], fuzz_target_config['fuzz_target'])] = fuzz_target_config

    return fuzz_target_configs


def _build_campaign_case(
    *,
    fuzzer_config_chain: list[dict[str, Any]],
    fuzz_target_config: dict[str, Any],
) -> CampaignCase:
    build_config: dict[str, Any] = {}
    runtime_config: dict[str, Any] = {}
    replay_trials: tuple[Path, ...] = ()
    fuzzer_name = str(fuzzer_config_chain[0]['fuzzer_name'])
    fuzzer_chain = tuple(str(fuzzer_config['fuzzer_name']) for fuzzer_config in fuzzer_config_chain)
    fuzzer_overrides = fuzz_target_config['fuzzers']

    for fuzzer_config in reversed(fuzzer_config_chain):
        cur_fuzz_id = str(fuzzer_config['fuzzer_name'])
        fuzz_target_override = fuzzer_overrides.get(cur_fuzz_id) or {}
        cur_fuzz_build = _merge(fuzzer_config.get('build') or {}, fuzz_target_override.get('build') or {})
        curr_fuzz_runtime = _merge(fuzzer_config.get('runtime') or {}, fuzz_target_override.get('runtime') or {})
        build_config = _merge(build_config, cur_fuzz_build)
        runtime_config = _merge(runtime_config, curr_fuzz_runtime)
        replay_trials = (*replay_trials, *tuple(fuzzer_config.get('replay_trials') or ()))

    return CampaignCase(
        fuzzer_name=fuzzer_name,
        fuzzer_chain=fuzzer_chain,
        benchmark=fuzz_target_config['benchmark'],
        fuzz_target=fuzz_target_config['fuzz_target'],
        input_mode=fuzz_target_config['input_mode'],
        target_timeout_s=fuzz_target_config['timeout_s'],
        build_config=build_config,
        runtime_config=runtime_config,
        replay_trials=replay_trials,
    )


def _fuzzer_allows_fuzz_target(fuzzer_config_chain: list[dict[str, Any]], fuzz_target_config: dict) -> bool:
    allowed_sets = [
        fuzzer_config['allowed_fuzz_targets']
        for fuzzer_config in fuzzer_config_chain
        if fuzzer_config.get('allowed_fuzz_targets')
    ]
    if not allowed_sets:
        return True

    return all(
        f'{fuzz_target_config["benchmark"]}:{fuzz_target_config["fuzz_target"]}' in allowed
        for allowed in allowed_sets
    )


def load_campaign_config(*, fuzzer_dirs: dict[str, Path], benchmark_dirs: dict[str, Path], text: str) -> CampaignConfig:
    """Load a campaign configuration from YAML text."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f'Invalid campaign YAML: {exc}') from exc

    if not data or not isinstance(data, dict):
        raise TypeError('Campaign config is empty or not a mapping.')

    fuzzer_config_chains = _load_fuzzer_configs(data, fuzzer_dirs)
    fuzz_target_configs = _load_fuzz_target_configs(data, benchmark_dirs)
    cases = [
        _build_campaign_case(
            fuzzer_config_chain=fuzzer_config_chain,
            fuzz_target_config=fuzz_target_config,
        )
        for fuzzer_config_chain in fuzzer_config_chains.values()
        for fuzz_target_config in fuzz_target_configs.values()
        if _fuzzer_allows_fuzz_target(fuzzer_config_chain, fuzz_target_config)
    ]

    return CampaignConfig(
        settings=_load_campaign_settings(data),
        cases=cases,
        fuzzer_dirs=fuzzer_dirs,
        benchmark_dirs=benchmark_dirs,
    )
