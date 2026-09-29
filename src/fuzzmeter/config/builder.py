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

from .models import Benchmark, CampaignCase, CampaignConfig, CampaignSettings, Fuzzer, FuzzTarget

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


def load_yaml(path: Path) -> dict[str, Any]:
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


def _fuzz_target_from_config(benchmark_dir: Path, required_benchmark: str, required_fuzz_target: str) -> FuzzTarget:
    path = benchmark_dir / 'benchmark.yaml'
    data = load_yaml(path)

    benchmark = data.get('benchmark')
    if not benchmark or not isinstance(benchmark, str):
        raise ValueError(f'{path}: benchmark must be a non-empty string.')

    if required_benchmark != benchmark:
        raise ValueError('')

    fuzz_targets_data = data.get('fuzz_targets')
    if not fuzz_targets_data or not isinstance(fuzz_targets_data, dict):
        raise ValueError(f'{path}: fuzz_targets must be a non-empty mapping.')

    fuzz_target_data = fuzz_targets_data.get(required_fuzz_target)
    if fuzz_target_data is None or not isinstance(fuzz_target_data, dict):
        raise ValueError(f'{path}: fuzz_targets[{required_fuzz_target!r}] must be a mapping.')

    input_mode = str(fuzz_target_data.get('input_mode') or '')
    if input_mode not in INPUT_MODE_OPTIONS:
        raise ValueError(f'{path}: fuzz_targets[{required_fuzz_target!r}].input_mode must be one of {INPUT_MODE_OPTIONS}; got {input_mode!r}.')

    timeout_value = fuzz_target_data.get('timeout_s')
    if timeout_value is None:
        LOG.debug(
            f'No fuzz target timeout was specified for {benchmark}:{required_fuzz_target}; '
            f'using {FuzzTarget.target_timeout_s} as default.'
        )
        timeout_value = FuzzTarget.target_timeout_s

    try:
        timeout_s = float(timeout_value)
        if timeout_s <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(
            f'{path}: fuzz_targets[{required_fuzz_target!r}].timeout_s '
            f'must be a positive number; got {timeout_value!r}.'
        ) from None

    fuzzer_overrides = fuzz_target_data.get('fuzzers') or {}
    if not isinstance(fuzzer_overrides, dict):
        raise TypeError(f'Fuzz target fuzzer overrides must be a mapping: {path}')
    if not all(isinstance(override, dict) for override in fuzzer_overrides.values()):
        raise ValueError('Fuzzer overrides in benchmark configs must be mappings.')

    build_data = fuzz_target_data.get('build') or {}
    if not isinstance(build_data, dict):
        raise TypeError(f'Fuzz target build configuration must be a mapping: {path}')
    compile_jobs = build_data.get('compile_jobs')
    if compile_jobs is not None:
        compile_jobs = _normalized_int_value('build.compile_jobs', compile_jobs, 1)

    return FuzzTarget(benchmark=Benchmark(name=benchmark, src_dir=benchmark_dir, config_path=path),
                      fuzz_target=required_fuzz_target,
                      input_mode=input_mode,
                      target_timeout_s=timeout_s,
                      fuzzer_overrides=fuzzer_overrides,
                      build_compile_jobs=compile_jobs)


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
    build_data = data.get('build') or {}
    if not isinstance(build_data, dict):
        raise TypeError('Campaign build configuration must be a mapping.')

    unknown_run_keys = set(run_data) - {
        'memory', 'memory_swap', 'parallel_jobs', 'repetitions', 'snapshot', 'time_seconds',
    }
    if unknown_run_keys:
        LOG.warning('Unknown campaign run keys: %s', ', '.join(sorted(map(str, unknown_run_keys))))
    unknown_snapshot_keys = set(snap_data) - {'every_seconds', 'export_every_ticks', 'jobs'}
    if unknown_snapshot_keys:
        LOG.warning('Unknown campaign snapshot keys: %s', ', '.join(sorted(map(str, unknown_snapshot_keys))))
    unknown_build_keys = set(build_data) - {'compile_jobs', 'jobs'}
    if unknown_build_keys:
        LOG.warning('Unknown campaign build keys: %s', ', '.join(sorted(map(str, unknown_build_keys))))

    return CampaignSettings(
        time_seconds=_normalized_int_value(
            'time_seconds', run_data.get('time_seconds', CampaignSettings.time_seconds), 60
        ),
        repetitions=_normalized_int_value('repetitions', run_data.get('repetitions', CampaignSettings.repetitions), 1),
        build_jobs=_normalized_int_value('build.jobs', build_data.get('jobs', CampaignSettings.build_jobs), 1),
        build_compile_jobs=_normalized_int_value(
            'build.compile_jobs', build_data.get('compile_jobs', CampaignSettings.build_compile_jobs), 1
        ),
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
            0,
        ),
        memory=run_data.get('memory', '') or None,
        memory_swap=run_data.get('memory_swap', '') or None,
    )


def _check_id_format(src: Any, name: str) -> None:
    if not src or not isinstance(src, str):
        raise ValueError(f'Input field {name!r} must be a string value: {src!r}')

    if not IDENTIFIER_RE.fullmatch(src):
        raise ValueError(f'Input field {name!r} must match [a-zA-Z0-9_.-]+: {src!r}')


def _replay_trials(data: dict[str, Any]) -> dict[str, tuple[Path, ...]]:
    specs = data.get('replay_trials') or {}
    if not isinstance(specs, dict) or not all(isinstance(paths, list) for paths in specs.values()):
        raise ValueError('replay_trials must map "benchmark:fuzz_target" specs to lists of directories.')
    resolved = {spec: tuple(Path(p).expanduser().resolve() for p in paths) for spec, paths in specs.items()}
    for path in (path for paths in resolved.values() for path in paths):
        if not path.is_dir():
            raise NotADirectoryError(f'Replay trial directory is not a directory: {path}')
    return resolved


def _effective_allowed(own: list[str], inherited: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if not own:
        return inherited
    if inherited is None:
        return tuple(own)
    return tuple(spec for spec in own if spec in inherited)


def _load_fuzzer_from_config(
    fuzzer_name: str,
    fuzzer_entries: dict[str, Fuzzer | None],
    fuzzer_dirs: dict[str, Path],
) -> Fuzzer:
    if fuzzer_name in fuzzer_entries:
        fuzzer = fuzzer_entries[fuzzer_name]
        if fuzzer is None:
            raise ValueError(f'Cyclic fuzzer dependency detected at {fuzzer_name!r}.')
        return fuzzer

    fuzzer_dir = fuzzer_dirs.get(fuzzer_name)
    if not fuzzer_dir or not fuzzer_dir.is_dir():
        raise ValueError(f'Fuzzer {fuzzer_name!r} is not configured; include it with --fuzzers.')

    fuzzer_entries[fuzzer_name] = None
    build_path = fuzzer_dir / 'build' / 'build.yaml'
    run_path = fuzzer_dir / 'run' / 'run.yaml'
    data = _merge(
        load_yaml(build_path) if build_path.is_file() else {},
        load_yaml(run_path) if run_path.is_file() else {},
    )
    parent_name = data.get('parent')
    if parent_name is not None:
        _check_id_format(parent_name, 'fuzzer parent')
    source_names = data.get('source_dependencies') or []
    if not isinstance(source_names, list) or not all(isinstance(name, str) and name for name in source_names):
        raise ValueError('source_dependencies must be defined as a list of non-empty strings.')
    allowed = data.get('allowed_fuzz_targets') or []
    if not isinstance(allowed, list) or not all(isinstance(spec, str) and spec for spec in allowed):
        raise ValueError('allowed_fuzz_targets must be defined as a list of non-empty strings.')
    build_config = data.get('build') or {}
    run_config = data.get('runtime') or {}
    if not isinstance(build_config, dict) or not isinstance(run_config, dict):
        raise ValueError('Fuzzer build and runtime configuration must be mappings.')

    parent = _load_fuzzer_from_config(parent_name, fuzzer_entries, fuzzer_dirs) if parent_name else None
    fuzzer = Fuzzer(
        id=fuzzer_name,
        name=fuzzer_name,
        src_dir=fuzzer_dir,
        parent=parent,
        allowed_fuzz_targets=_effective_allowed(allowed, parent.allowed_fuzz_targets if parent else None),
        build_config=build_config,
        run_config=run_config,
        local_repo_env=str(data.get('local_repo_env') or '').strip() or None,
    )
    fuzzer.source_dependencies = [
        _load_fuzzer_from_config(name, fuzzer_entries, fuzzer_dirs)
        for name in source_names
    ]
    fuzzer_entries[fuzzer_name] = fuzzer
    return fuzzer


def _load_fuzzers(
    data: dict[str, Any],
    fuzzer_dirs: dict[str, Path],
) -> list[tuple[Fuzzer, dict[str, tuple[Path, ...]]]]:
    fuzzers = data.get('fuzzers', [])
    if not isinstance(fuzzers, list) or not fuzzers:
        raise ValueError('Campaign fuzzers must be a non-empty list.')

    fuzzer_entries: dict[str, Fuzzer | None] = {}
    campaign_ids: set[str] = set()
    campaign_fuzzers: list[tuple[Fuzzer, dict[str, tuple[Path, ...]]]] = []
    for fuzzer_data in fuzzers:
        if isinstance(fuzzer_data, str):
            fuzzer_id, fuzzer_name = fuzzer_data, fuzzer_data
        elif isinstance(fuzzer_data, dict):
            unknown_keys = set(fuzzer_data) - {
                'allowed_fuzz_targets', 'build', 'id', 'parent', 'replay_trials', 'runtime',
            }
            if unknown_keys:
                LOG.warning(
                    'Unknown campaign fuzzer keys for %r: %s',
                    fuzzer_data.get('id'),
                    ', '.join(sorted(map(str, unknown_keys))),
                )
            if 'id' not in fuzzer_data:
                raise ValueError('"id" field must be defined in a fuzzer mapping.')
            fuzzer_id = fuzzer_data['id']
            fuzzer_name = fuzzer_data.get('parent') or fuzzer_id
        else:
            raise TypeError(f'Unsupported fuzzer entry: {fuzzer_data!r}')

        _check_id_format(fuzzer_id, 'fuzzer id')
        _check_id_format(fuzzer_name, 'fuzzer name')

        if fuzzer_id in campaign_ids:
            raise ValueError(f'Fuzzer {fuzzer_id!r} is defined more than once.')
        campaign_ids.add(fuzzer_id)

        base_fuzzer = _load_fuzzer_from_config(fuzzer_name, fuzzer_entries, fuzzer_dirs)
        if isinstance(fuzzer_data, dict):
            allowed = fuzzer_data.get('allowed_fuzz_targets')
            if allowed is not None and (
                not isinstance(allowed, list) or not all(isinstance(spec, str) and spec for spec in allowed)
            ):
                raise ValueError('allowed_fuzz_targets must be defined as a list of non-empty strings.')
            build_override = fuzzer_data.get('build') or {}
            run_override = fuzzer_data.get('runtime') or {}
            if not isinstance(build_override, dict) or not isinstance(run_override, dict):
                raise ValueError('Campaign fuzzer build and runtime configuration must be mappings.')
            fuzzer = Fuzzer(
                id=fuzzer_id,
                name=base_fuzzer.name,
                src_dir=base_fuzzer.src_dir,
                parent=base_fuzzer,
                allowed_fuzz_targets=_effective_allowed(allowed or [], base_fuzzer.allowed_fuzz_targets),
                build_config=build_override,
                run_config=run_override,
            )
            replay_trials = _replay_trials(fuzzer_data)
        else:
            fuzzer, replay_trials = base_fuzzer, {}

        campaign_fuzzers.append((fuzzer, replay_trials))

    return campaign_fuzzers


def _load_fuzz_targets(data: dict[str, Any], benchmark_dirs: dict[str, Path]) -> list[FuzzTarget]:
    fuzz_target_specs = data.get('fuzz_targets', [])
    if not isinstance(fuzz_target_specs, list) or not fuzz_target_specs:
        raise ValueError('Campaign fuzz_targets must be a non-empty list.')

    fuzz_targets: list[FuzzTarget] = []
    benchmarks: dict[str, Benchmark] = {}
    seen_idents: set[str] = set()
    for fuzz_target_spec in fuzz_target_specs:
        if not isinstance(fuzz_target_spec, str):
            raise TypeError(f'Unsupported fuzz target entry: {fuzz_target_spec!r}')

        if ':' not in fuzz_target_spec:
            raise ValueError(f"Unexpected fuzz target spec format: {fuzz_target_spec!r} (missing ':')")

        benchmark, fuzz_target_name = fuzz_target_spec.split(':', 1)
        benchmark, fuzz_target_name = benchmark.strip(), fuzz_target_name.strip()
        _check_id_format(benchmark, 'benchmark')
        _check_id_format(fuzz_target_name, 'fuzz_target_name')

        if benchmark not in benchmark_dirs:
            raise ValueError(f'Benchmark {benchmark!r} is not configured; include it with --benchmarks.')


        fuzz_target = _fuzz_target_from_config(benchmark_dirs[benchmark], benchmark, fuzz_target_name)
        fuzz_target.benchmark = benchmarks.setdefault(benchmark, fuzz_target.benchmark)
        if fuzz_target.ident in seen_idents:
            raise ValueError(f'Fuzz target {fuzz_target.ident} is defined more than once.')
        seen_idents.add(fuzz_target.ident)
        fuzz_targets.append(fuzz_target)

    return fuzz_targets


def _build_campaign_case(
    *,
    fuzzer: Fuzzer,
    fuzz_target: FuzzTarget,
    replay_trials: tuple[Path, ...],
) -> CampaignCase:
    build_config: dict[str, Any] = {}
    run_config: dict[str, Any] = {}
    fuzzer_overrides = fuzz_target.fuzzer_overrides

    for parent_fuzzer in reversed([fuzzer, *fuzzer.parents]):
        fuzz_target_override = fuzzer_overrides.get(parent_fuzzer.id) or {}

        build_config = _merge(build_config, parent_fuzzer.build_config)
        build_config = _merge(build_config, fuzz_target_override.get('build') or {})

        run_config = _merge(run_config, parent_fuzzer.run_config)
        run_config = _merge(run_config, fuzz_target_override.get('runtime') or {})

    return CampaignCase(
        fuzzer=fuzzer,
        fuzz_target=fuzz_target,

        build_config=build_config,
        run_config=run_config,
        replay_trials=replay_trials,
    )


def load_campaign_config(*, fuzzer_dirs: dict[str, Path], benchmark_dirs: dict[str, Path], text: str) -> CampaignConfig:
    """Load a campaign configuration from YAML text."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f'Invalid campaign YAML: {exc}') from exc

    if not data or not isinstance(data, dict):
        raise TypeError('Campaign config is empty or not a mapping.')

    unknown_keys = set(data) - {'build', 'fuzz_targets', 'fuzzers', 'run'}
    if unknown_keys:
        LOG.warning('Unknown campaign keys: %s', ', '.join(sorted(map(str, unknown_keys))))

    fuzzers = _load_fuzzers(data, fuzzer_dirs)
    fuzz_targets = _load_fuzz_targets(data, benchmark_dirs)

    cases = []
    for fuzzer, replay_trials in fuzzers:
        unselected = set(replay_trials)
        for fuzz_target in fuzz_targets:
            if fuzzer.allowed_fuzz_targets is None or fuzz_target.spec in fuzzer.allowed_fuzz_targets:
                unselected.discard(fuzz_target.spec)
                cases.append(_build_campaign_case(
                    fuzzer=fuzzer,
                    fuzz_target=fuzz_target,
                    replay_trials=replay_trials.get(fuzz_target.spec, ()),
                ))
        if unselected:
            raise ValueError(
                f'Fuzzer {fuzzer.id!r} has replay_trials for unselected fuzz targets: {sorted(unselected)}'
            )

    if not cases:
        raise ValueError('No selected fuzzer supports any selected fuzz target.')

    settings = _load_campaign_settings(data)
    replay_counts = [len(case.replay_trials) for case in cases]
    if any(replay_counts) and set(replay_counts) != {settings.repetitions}:
        raise ValueError(
            f'replay_trials must list exactly run.repetitions ({settings.repetitions}) directories '
            'for every campaign case, or for none of them.'
        )

    return CampaignConfig(
        settings=settings,
        cases=cases,
    )
