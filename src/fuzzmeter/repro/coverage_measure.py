# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Run coverage replay containers and promote their output artifacts.'''

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import shutil

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import CampaignCase
from ..docker import DockerClient, DockerRuntime

LOG = logging.getLogger(__name__)
DEFAULT_COVERAGE_BATCH_SIZE = 256
COVERAGE_PIPELINE_ATTEMPTS = 3


class CoveragePipelineError(RuntimeError):
    '''Report an exhausted mandatory coverage processing step.'''


@dataclass(frozen=True)
class CoverageBatch:
    '''Describe one coverage replay batch.'''

    image: str
    fuzz_target: str
    input_mode: str
    inputs: list[Path]
    profdata_path: Path
    diagnostics_dir: Path
    timeout_s: float
    container_name: str | None = None
    trial_key: str | None = None


def build_coverage_replay_batches(
    *,
    image: str,
    fuzz_target: str,
    input_mode: str,
    inputs: list[Path],
    state_dir: Path,
    batch_tag: str | int,
    timeout_s: float,
    container_prefix: str | None = None,
    trial_key: str | None = None,
) -> tuple[list[Path], list[CoverageBatch]]:
    '''Create host-side coverage replay batches for one input set.'''
    if not inputs:
        return [], []

    batch_root = state_dir / f'_batches_{batch_tag}'
    diagnostics_root = state_dir / f'_batch_diag_{batch_tag}'
    input_batches = [
        inputs[index:index + DEFAULT_COVERAGE_BATCH_SIZE]
        for index in range(0, len(inputs), DEFAULT_COVERAGE_BATCH_SIZE)
    ]
    batch_root.mkdir(parents=True, exist_ok=True)
    batch_profdata_paths = [batch_root / f'batch_{index:06d}.profdata' for index in range(len(input_batches))]

    return batch_profdata_paths, [
        CoverageBatch(
            image=image,
            fuzz_target=fuzz_target,
            input_mode=input_mode,
            inputs=input_batch,
            profdata_path=batch_profdata_paths[index],
            diagnostics_dir=diagnostics_root / f'{index:06d}',
            timeout_s=timeout_s,
            container_name=f'{container_prefix}-{index:06d}' if container_prefix else None,
            trial_key=trial_key,
        )
        for index, input_batch in enumerate(input_batches)
    ]


def replay_coverage_batches(
    *,
    docker_runtime: DockerRuntime,
    batches: list[CoverageBatch],
    jobs: int,
    on_batch_done: Callable[[], None] | None = None,
) -> None:
    '''Replay planned coverage batches in parallel on the host.'''
    if not batches:
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(batches), jobs)) as executor:
        futures = [
            executor.submit(
                replay_coverage_batch,
                docker_runtime=docker_runtime,
                image=batch.image,
                fuzz_target=batch.fuzz_target,
                input_mode=batch.input_mode,
                inputs=batch.inputs,
                batch_profdata_path=batch.profdata_path,
                diagnostics_dir=batch.diagnostics_dir,
                timeout_s=batch.timeout_s,
                container_name=batch.container_name,
                trial_key=batch.trial_key,
            )
            for batch in batches
        ]
        failures = []
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                failures.append(exc)
            else:
                if on_batch_done is not None:
                    on_batch_done()

    if failures:
        details = '\n'.join(f'{index}. {type(exc).__name__}: {exc}' for index, exc in enumerate(failures, 1))
        raise CoveragePipelineError(f'Coverage replay failed in {len(failures)} batch(es):\n{details}')


def replay_coverage_batch(
    *,
    docker_runtime: DockerRuntime,
    image: str,
    fuzz_target: str,
    input_mode: str,
    inputs: list[Path],
    batch_profdata_path: Path,
    diagnostics_dir: Path,
    timeout_s: float = 2.0,
    container_name: str | None = None,
    trial_key: str | None = None,
) -> None:
    '''Replay coverage inputs in one container and write their batch profile.'''
    if not inputs:
        return

    for attempt in range(1, COVERAGE_PIPELINE_ATTEMPTS + 1):
        try:
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            batch_profdata_path.parent.mkdir(parents=True, exist_ok=True)
            batch_profdata_path.unlink(missing_ok=True)

            docker = DockerClient(docker_runtime)
            input_list_path = diagnostics_dir / 'inputs.txt'
            input_list_path.write_text(
                '\n'.join(docker.container_path(path) for path in inputs) + '\n',
                encoding='utf-8',
            )

            out_dir = diagnostics_dir / 'out'
            work_dir = diagnostics_dir / 'work'
            shutil.rmtree(out_dir, ignore_errors=True)
            shutil.rmtree(work_dir, ignore_errors=True)
            out_dir.mkdir(parents=True, exist_ok=True)
            work_dir.mkdir(parents=True, exist_ok=True)

            docker.run(
                image=image,
                name=container_name,
                env={
                    'FM_OUT_DIR': docker.container_path(out_dir),
                    'FM_TARGET_NAME': fuzz_target,
                    'FM_INPUT_MODE': input_mode,
                    'FM_INPUT_LIST': docker.container_path(input_list_path),
                    'FM_BATCH_PROFDATA_PATH': docker.container_path(batch_profdata_path),
                    'FM_TIMEOUT_S': str(timeout_s),
                    'FM_WORK_DIR': docker.container_path(work_dir),
                    'FM_LOG_LEVEL': str(os.environ.get('FM_LOG_LEVEL', 'INFO')).upper(),
                },
                volumes=[docker.out_volume()],
                check=True,
                kind='coverage',
                trial_key=trial_key,
                cmd=['python3', '/opt/fuzzmeter/coverage_worker.py'],
            )
            return
        except Exception as exc:
            if attempt == COVERAGE_PIPELINE_ATTEMPTS:
                batch_name = container_name or str(batch_profdata_path)
                raise CoveragePipelineError(
                    f'Coverage batch {batch_name} failed after '
                    f'{COVERAGE_PIPELINE_ATTEMPTS} attempts: {exc}'
                ) from exc
            LOG.warning(
                'Coverage batch %s failed on attempt %s/%s; retrying: %s',
                container_name or batch_profdata_path,
                attempt,
                COVERAGE_PIPELINE_ATTEMPTS,
                exc,
            )


def merge_coverage_outputs(
    *,
    docker_runtime: DockerRuntime,
    run_dir: Path,
    case: CampaignCase,
    out_root: Path,
    state_dir: Path,
    work_dir: Path,
    profile_inputs: list[Path],
    render_html: bool = True,
    write_coverage_sets: bool = True,
    container_name: str | None = None,
    trial_key: str | None = None,
    measurement_context: dict[str, Any] | None = None,
) -> dict:
    '''Merge batch profiles into one coverage output root and refresh its artifacts.'''
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        for attempt in range(1, COVERAGE_PIPELINE_ATTEMPTS + 1):
            try:
                return _merge_coverage_outputs_once(
                    docker_runtime=docker_runtime,
                    run_dir=run_dir,
                    case=case,
                    out_root=out_root,
                    state_dir=state_dir,
                    work_dir=work_dir,
                    profile_inputs=profile_inputs,
                    render_html=render_html,
                    write_coverage_sets=write_coverage_sets,
                    container_name=container_name,
                    trial_key=trial_key,
                    measurement_context=measurement_context,
                )
            except Exception as exc:
                if attempt == COVERAGE_PIPELINE_ATTEMPTS:
                    merge_name = container_name or str(out_root)
                    raise CoveragePipelineError(
                        f'Coverage merge {merge_name} failed after '
                        f'{COVERAGE_PIPELINE_ATTEMPTS} attempts: {exc}'
                    ) from exc
                LOG.warning(
                    'Coverage merge %s failed on attempt %s/%s; retrying: %s',
                    container_name or out_root,
                    attempt,
                    COVERAGE_PIPELINE_ATTEMPTS,
                    exc,
                )
    finally:
        (state_dir / '.merged.profdata.candidate').unlink(missing_ok=True)

    raise AssertionError('Coverage retry loop exited without a result')


def _merge_coverage_outputs_once(
    *,
    docker_runtime: DockerRuntime,
    run_dir: Path,
    case: CampaignCase,
    out_root: Path,
    state_dir: Path,
    work_dir: Path,
    profile_inputs: list[Path],
    render_html: bool,
    write_coverage_sets: bool,
    container_name: str | None,
    trial_key: str | None,
    measurement_context: dict[str, Any] | None,
) -> dict:
    '''Perform one coverage merge attempt.'''
    docker = DockerClient(docker_runtime)
    image = case.images.coverage
    profdata_path = state_dir / 'merged.profdata'
    merge_profiles = _usable_profiles([profdata_path, *profile_inputs])

    src_root = run_dir / 'coverage_src' / case.fuzz_target.benchmark.name / case.fuzz_target.fuzz_target
    tmp_root = out_root.parent / f'.{out_root.name}.tmp'
    shutil.rmtree(tmp_root, ignore_errors=True)
    tmp_root.mkdir(parents=True, exist_ok=True)
    candidate_profdata = tmp_root / 'merged.profdata'

    prof_list_path = tmp_root / 'profdata_inputs.txt'
    prof_list_path.write_text(
        '\n'.join(docker.container_path(path) for path in merge_profiles) + ('\n' if merge_profiles else ''),
        encoding='utf-8',
    )
    coverage_sets_path = tmp_root / 'coverage-sets.json'

    context = dict(measurement_context or {})
    images = dict(context.get('images') or {})
    images['coverage'] = image
    images['fuzzer_target_digest'] = docker.image_id(image)
    images['digest_scope'] = 'combined-fuzzer-target-coverage-image'
    images.setdefault('fuzzer_digest', None)
    images.setdefault('target_digest', None)
    context['images'] = images
    if images['fuzzer_target_digest'] is None:
        LOG.warning('Coverage image digest is unavailable for %s', image)
    if write_coverage_sets:
        context['coverage_sets'] = {
            'freshness': 'fresh',
            'source_tick': context.get('snapshot_tick'),
            'source_profdata_sha256': None,
        }
    else:
        previous_provenance = _load_json(out_root / 'measurement-provenance.json')
        previous_sets = previous_provenance.get('coverage_sets') or {}
        context['coverage_sets'] = {
            'freshness': 'carried_forward' if (out_root / 'coverage-sets.json').is_file() else 'unavailable',
            'source_tick': previous_sets.get('source_tick'),
            'source_profdata_sha256': previous_sets.get('source_profdata_sha256'),
        }

    env = {
        'FM_OUT_DIR': docker.container_path(tmp_root),
        'FM_TARGET_NAME': case.fuzz_target.fuzz_target,
        'FM_PROF_LIST': docker.container_path(prof_list_path),
        'FM_PROFDATA_PATH': docker.container_path(candidate_profdata),
        'FM_WORK_DIR': docker.container_path(work_dir),
        'FM_LOG_LEVEL': str(os.environ.get('FM_LOG_LEVEL', 'INFO')).upper(),
        'FM_MEASUREMENT_CONTEXT': json.dumps(context, sort_keys=True, separators=(',', ':')),
    }
    if src_root.is_dir():
        env['FM_PATH_EQ_FROM'] = '/src'
        env['FM_PATH_EQ_TO'] = docker.container_path(src_root)
    if not render_html:
        env['FM_SKIP_HTML'] = '1'
    if write_coverage_sets:
        env['FM_COVERAGE_SETS_JSON'] = docker.container_path(coverage_sets_path)

    docker.run(
        image=image,
        name=container_name,
        env=env,
        volumes=[docker.out_volume()],
        check=True,
        kind='coverage',
        trial_key=trial_key,
        cmd=['python3', '/opt/fuzzmeter/coverage_worker.py'],
    )

    if candidate_profdata not in _usable_profiles([candidate_profdata]):
        raise RuntimeError('Coverage worker did not produce a usable merged profile')
    summary = _load_required_mapping(tmp_root / 'summary.json')
    _load_required_mapping(tmp_root / 'measurement-provenance.json')
    if write_coverage_sets:
        _load_required_mapping(coverage_sets_path)
    if not write_coverage_sets:
        _preserve_previous_artifacts(out_root=out_root, tmp_root=tmp_root, names=('coverage-sets.json',))
    _synchronize_coverage_set_provenance(tmp_root)
    state_candidate = state_dir / '.merged.profdata.candidate'
    shutil.copy2(candidate_profdata, state_candidate)
    candidate_profdata.unlink()
    _replace_out_root(out_root=out_root, tmp_root=tmp_root, protected_dir=state_dir)
    state_candidate.replace(profdata_path)
    return summary


def coverage_measurement_context(
    *,
    batches: list[CoverageBatch],
    image: str,
    snapshot_tick: int,
    repetitions: int,
) -> dict[str, Any]:
    '''Summarize replay semantics and diagnostics for persisted provenance.'''

    status_counts = dict.fromkeys(('ok', 'timeout', 'failed', 'missing_profraw'), 0)
    for batch in batches:
        payload = _load_json(batch.diagnostics_dir / 'out' / 'input_exec_diagnostics.json')
        for status, count in (payload.get('status_counts') or {}).items():
            status_counts[str(status)] = status_counts.get(str(status), 0) + int(count)
    input_mode = batches[0].input_mode if batches else 'unknown'
    batched = input_mode == 'in_process'
    lost_profiles = 0
    if batched:
        for batch in batches:
            batch_counts = _load_json(
                batch.diagnostics_dir / 'out' / 'input_exec_diagnostics.json'
            ).get('status_counts') or {}
            if any(batch_counts.get(status, 0) for status in ('timeout', 'failed', 'missing_profraw')):
                lost_profiles += len(batch.inputs)
    return {
        'snapshot_tick': snapshot_tick,
        'measurement': {
            'mode': 'batched-stateful' if batched else 'stateless',
            'batch_size': max((len(batch.inputs) for batch in batches), default=0),
            'ordering': 'path-sorted; libFuzzer merge order for batched-stateful replay' if batched else 'path-sorted',
            'artificial_restarts': (
                max(0, len(batches) - 1)
                if batched
                else max(0, sum(len(batch.inputs) for batch in batches) - 1)
            ),
        },
        'validity': {
            'status': 'valid',
            'diagnostics': [],
        },
        'repetitions': {
            'n': repetitions,
            'threshold': None,
            'threshold_met': None,
        },
        'images': {
            'coverage': image,
            'fuzzer_digest': None,
            'target_digest': None,
        },
        'inputs': {
            'scope': 'current_snapshot_replay',
            'status_counts': status_counts,
            'profiles_lost_to_batch_mate_crash': lost_profiles,
        },
    }


def _load_required_mapping(path: Path) -> dict[str, Any]:
    '''Load one mandatory coverage artifact and reject missing or malformed data.'''
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f'Coverage worker did not produce valid {path.name}') from exc
    if not isinstance(value, dict):
        raise RuntimeError(f'Coverage worker produced non-object {path.name}')
    return value


def _usable_profiles(paths: list[Path]) -> list[Path]:
    return [path for path in paths if path.is_file() and path.stat().st_size > 64]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _synchronize_coverage_set_provenance(out_root: Path) -> None:
    artifact_path = out_root / 'coverage-sets.json'
    provenance = _load_json(out_root / 'measurement-provenance.json')
    artifact = _load_json(artifact_path)
    if not provenance or not artifact:
        return
    artifact['measurement_provenance'] = provenance
    artifact_path.write_text(
        json.dumps(artifact, sort_keys=True, separators=(',', ':')),
        encoding='utf-8',
    )


def _preserve_previous_artifacts(*, out_root: Path, tmp_root: Path, names: tuple[str, ...]) -> None:
    for name in names:
        src = out_root / name
        if not src.is_file():
            continue
        dst = tmp_root / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except OSError:
            LOG.debug('Could not preserve previous coverage artifact: %s', src)


def _replace_out_root(*, out_root: Path, tmp_root: Path, protected_dir: Path | None = None) -> None:
    saved_protected_dir = None
    final_protected_dir = None
    if protected_dir is not None:
        protected_dir = protected_dir.resolve()
        out_root_resolved = out_root.resolve()
        if out_root_resolved in protected_dir.parents:
            try:
                final_protected_dir = protected_dir
                preserved_name = f'.{out_root_resolved.name}.{protected_dir.name}.preserved'
                saved_protected_dir = out_root_resolved.parent / preserved_name
                shutil.rmtree(saved_protected_dir, ignore_errors=True)
                if protected_dir.exists():
                    protected_dir.rename(saved_protected_dir)
            except OSError:
                LOG.debug('Could not preserve protected dir %s under %s', protected_dir, out_root)
                saved_protected_dir = None
                final_protected_dir = None

    if out_root.exists():
        shutil.rmtree(out_root, ignore_errors=True)
    _promote_dir(tmp_root, out_root)

    if saved_protected_dir is not None and final_protected_dir is not None:
        final_protected_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(final_protected_dir, ignore_errors=True)
        saved_protected_dir.rename(final_protected_dir)


def _promote_dir(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    backup = dst.parent / f'.{dst.name}.old.{os.urandom(8).hex()}'
    if src.resolve() == dst.resolve():
        return
    try:
        if dst.exists():
            dst.rename(backup)
        src.rename(dst)
    except Exception:
        if not dst.exists() and backup.exists():
            backup.rename(dst)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
