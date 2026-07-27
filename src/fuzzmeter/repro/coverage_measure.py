# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Run coverage replay containers and promote their output artifacts.'''

from __future__ import annotations

import concurrent.futures
import logging
import os
import shutil

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..docker import DockerClient, DockerRuntime
from .coverage_state import load_coverage_summary

LOG = logging.getLogger(__name__)
DEFAULT_COVERAGE_BATCH_SIZE = 256


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


def build_coverage_replay_batches(
    *,
    image: str,
    fuzz_target: str,
    input_mode: str,
    inputs: list[Path],
    state_dir: Path,
    batch_tag: str | int,
    timeout_s: float,
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
        raise RuntimeError(f'Coverage replay failed in {len(failures)} batch(es):\n{details}')


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
) -> None:
    '''Replay coverage inputs in one container and write their batch profile.'''
    if not inputs:
        return

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

    env = {
        'FM_OUT_DIR': docker.container_path(out_dir),
        'FM_TARGET_NAME': fuzz_target,
        'FM_INPUT_MODE': input_mode,
        'FM_INPUT_LIST': docker.container_path(input_list_path),
        'FM_BATCH_PROFDATA_PATH': docker.container_path(batch_profdata_path),
        'FM_TIMEOUT_S': str(timeout_s),
        'FM_WORK_DIR': docker.container_path(work_dir),
        'FM_LOG_LEVEL': str(os.environ.get('FM_LOG_LEVEL', 'INFO')).upper(),
    }

    docker.run(
        image=image,
        env=env,
        volumes=[docker.out_volume()],
        check=True,
        cmd=['python3', '/opt/fuzzmeter/coverage_worker.py'],
    )


def merge_coverage_outputs(
    *,
    docker_runtime: DockerRuntime,
    run_dir: Path,
    image: str,
    out_root: Path,
    benchmark: str,
    fuzz_target: str,
    state_dir: Path,
    work_dir: Path,
    profile_inputs: list[Path],
    render_html: bool = True,
    write_coverage_sets: bool = True,
) -> dict:
    '''Merge batch profiles into one coverage output root and refresh its artifacts.'''
    docker = DockerClient(docker_runtime)
    state_dir.mkdir(parents=True, exist_ok=True)
    profdata_path = state_dir / 'merged.profdata'
    merge_profiles = _usable_profiles([profdata_path, *profile_inputs])

    src_root = run_dir / 'coverage_src' / f'{benchmark}/{fuzz_target}'
    tmp_root = out_root.parent / f'.{out_root.name}.tmp'
    shutil.rmtree(tmp_root, ignore_errors=True)
    tmp_root.mkdir(parents=True, exist_ok=True)

    prof_list_path = tmp_root / 'profdata_inputs.txt'
    prof_list_path.write_text(
        '\n'.join(docker.container_path(path) for path in merge_profiles) + ('\n' if merge_profiles else ''),
        encoding='utf-8',
    )
    coverage_sets_path = tmp_root / 'coverage-sets.json'

    env = {
        'FM_OUT_DIR': docker.container_path(tmp_root),
        'FM_TARGET_NAME': fuzz_target,
        'FM_PROF_LIST': docker.container_path(prof_list_path),
        'FM_PROFDATA_PATH': docker.container_path(profdata_path),
        'FM_WORK_DIR': docker.container_path(work_dir),
        'FM_LOG_LEVEL': str(os.environ.get('FM_LOG_LEVEL', 'INFO')).upper(),
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
        env=env,
        volumes=[docker.out_volume()],
        check=True,
        cmd=['python3', '/opt/fuzzmeter/coverage_worker.py'],
    )

    if not write_coverage_sets:
        _preserve_previous_artifacts(out_root=out_root, tmp_root=tmp_root, names=('coverage-sets.json',))
    _replace_out_root(out_root=out_root, tmp_root=tmp_root, protected_dir=state_dir)
    return load_coverage_summary(out_root / 'summary.json')


def _usable_profiles(paths: list[Path]) -> list[Path]:
    return [path for path in paths if path.is_file() and path.stat().st_size > 64]


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
