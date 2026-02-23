# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Run coverage replay containers and promote their output artifacts.'''

from __future__ import annotations

import logging
import os
import shutil
import uuid

from pathlib import Path

from ..docker import DockerClient, DockerRuntime
from .coverage_state import load_coverage_summary

LOG = logging.getLogger(__name__)


def run_coverage_batch(
    *,
    docker_runtime: DockerRuntime,
    image: str,
    fuzz_target: str,
    input_mode: str,
    inputs: list[Path],
    batch_profdata_path: Path,
    diagnostics_dir: Path,
    timeout_s: float = 2.0,
    input_jobs: int | None = None,
) -> None:
    '''Replay one batch of coverage inputs in one coverage container.'''
    if not inputs:
        return

    docker = DockerClient(docker_runtime)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    batch_profdata_path.parent.mkdir(parents=True, exist_ok=True)
    batch_profdata_path.unlink(missing_ok=True)

    input_list_path = diagnostics_dir / 'inputs.txt'
    input_list_path.write_text(
        '\n'.join(str(Path(docker.container_path(path))) for path in inputs) + '\n',
        encoding='utf-8',
    )

    out_dir = diagnostics_dir / 'out'
    work_dir = diagnostics_dir / 'work'
    shutil.rmtree(out_dir, ignore_errors=True)
    shutil.rmtree(work_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    env = {
        'FM_OUT_DIR': str(Path(docker.container_path(out_dir))),
        'FM_TARGET_NAME': fuzz_target,
        'FM_INPUT_MODE': input_mode,
        'FM_INPUT_LIST': str(Path(docker.container_path(input_list_path))),
        'FM_BATCH_PROFDATA_PATH': str(Path(docker.container_path(batch_profdata_path))),
        'FM_TIMEOUT_S': str(float(timeout_s)),
        'FM_WORK_DIR': str(Path(docker.container_path(work_dir))),
        'FM_INPUT_JOBS': str(max(1, int(input_jobs or 1))),
        'FM_LOG_LEVEL': str(os.environ.get('FM_LOG_LEVEL', 'INFO')).upper(),
    }

    docker.run(
        image=image,
        env=env,
        volumes=[docker.out_volume()],
        check=True,
        cmd=['python3', '/opt/fuzzmeter/coverage_repro_worker.py'],
    )


def finalize_coverage(
    *,
    docker_runtime: DockerRuntime,
    run_dir: Path,
    image: str,
    benchmark: str,
    fuzz_target: str,
    state_dir: Path,
    work_dir: Path,
    out_root: Path,
    profile_inputs: list[Path],
    render_html: bool = True,
    write_coverage_sets: bool = True,
) -> dict:
    '''Merge batch profiles into the trial state and refresh coverage artifacts.'''
    docker = DockerClient(docker_runtime)
    state_dir.mkdir(parents=True, exist_ok=True)
    profdata_path = state_dir / 'merged.profdata'
    existing_profiles: list[Path] = []
    if profdata_path.is_file() and profdata_path.stat().st_size > 64:
        existing_profiles.append(profdata_path)

    merge_profiles = existing_profiles + [path for path in profile_inputs if path.is_file() and path.stat().st_size > 64]

    src_root = Path(run_dir) / 'coverage_src' / f'{benchmark}/{fuzz_target}'
    tmp_root = Path(out_root).parent / f'.{Path(out_root).name}.tmp'
    shutil.rmtree(tmp_root, ignore_errors=True)
    tmp_root.mkdir(parents=True, exist_ok=True)

    prof_list_path = tmp_root / 'profdata_inputs.txt'
    prof_list_path.write_text(
        '\n'.join(str(Path(docker.container_path(path))) for path in merge_profiles) + ('\n' if merge_profiles else ''),
        encoding='utf-8',
    )
    coverage_sets_path = tmp_root / 'coverage-sets.json'

    env = {
        'FM_OUT_DIR': str(Path(docker.container_path(tmp_root))),
        'FM_TARGET_NAME': fuzz_target,
        'FM_PROF_LIST': str(Path(docker.container_path(prof_list_path))),
        'FM_PROFDATA_PATH': str(Path(docker.container_path(profdata_path))),
        'FM_WORK_DIR': str(Path(docker.container_path(work_dir))),
        'FM_LOG_LEVEL': str(os.environ.get('FM_LOG_LEVEL', 'INFO')).upper(),
    }
    if src_root.is_dir():
        env['FM_PATH_EQ_FROM'] = '/src'
        env['FM_PATH_EQ_TO'] = str(Path(docker.container_path(src_root)))
    if not render_html:
        env['FM_SKIP_HTML'] = '1'
    if write_coverage_sets:
        env['FM_COVERAGE_SETS_JSON'] = str(Path(docker.container_path(coverage_sets_path)))

    docker.run(
        image=image,
        env=env,
        volumes=[docker.out_volume()],
        check=True,
        cmd=['python3', '/opt/fuzzmeter/coverage_repro_worker.py'],
    )

    if not write_coverage_sets:
        _preserve_previous_artifacts(out_root=Path(out_root), tmp_root=tmp_root, names=('coverage-sets.json',))
    _replace_out_root(out_root=Path(out_root), tmp_root=tmp_root, protected_dir=state_dir)
    return load_coverage_summary(Path(out_root) / 'summary.json')


def _preserve_previous_artifacts(*, out_root: Path, tmp_root: Path, names: tuple[str, ...]) -> None:
    for name in names:
        src = Path(out_root) / name
        if not src.is_file():
            continue
        dst = Path(tmp_root) / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except OSError:
            LOG.debug('Could not preserve previous coverage artifact: %s', src)


def _replace_out_root(*, out_root: Path, tmp_root: Path, protected_dir: Path | None = None) -> None:
    saved_state = None
    final_state = None
    if protected_dir is not None:
        try:
            protected_dir = Path(protected_dir).resolve()
            out_root_resolved = Path(out_root).resolve()
            protected_dir.relative_to(out_root_resolved)
            final_state = protected_dir
            saved_state = out_root_resolved.parent / f'.{out_root_resolved.name}.{protected_dir.name}.preserved'
            shutil.rmtree(saved_state, ignore_errors=True)
            if protected_dir.exists():
                protected_dir.rename(saved_state)
        except Exception:
            saved_state = None
            final_state = None

    if Path(out_root).exists():
        shutil.rmtree(out_root, ignore_errors=True)
    _promote_dir(tmp_root, Path(out_root))

    if saved_state is not None and final_state is not None:
        final_state.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(final_state, ignore_errors=True)
        saved_state.rename(final_state)


def _promote_dir(src: Path, dst: Path) -> None:
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    backup = dst.parent / f'.{dst.name}.old.{uuid.uuid4().hex}'
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
