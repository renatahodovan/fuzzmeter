#!/usr/bin/env python3
# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Replay coverage inputs and produce LLVM coverage artifacts in coverage containers.'''

from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import subprocess
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coverage_sets import (
    coverage_metrics_from_export,
    coverage_summary_from_export,
    write_coverage_sets,
)

LOG_LEVEL = getattr(logging, os.environ.get('FM_LOG_LEVEL', 'WARNING'))
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(levelname)-7s - %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
LOG = logging.getLogger(__name__)
PROFDATA_MERGE_CHUNK_SIZE = 512


@dataclass(frozen=True)
class WorkerConfig:
    '''Hold coverage worker environment values.'''

    cov_bin: Path
    input_mode: str
    out_dir: Path
    work_dir: Path
    input_list: Path
    prof_list: Path
    profdata: Path
    batch_profdata: Path | None
    coverage_sets: Path | None
    timeout_s: float

    @classmethod
    def from_env(cls) -> 'WorkerConfig':
        '''Build a worker config from environment variables.'''
        out_dir = Path(os.environ['FM_OUT_DIR'])
        work_dir_env = os.environ.get('FM_WORK_DIR', '').strip()
        profdata_env = os.environ.get('FM_PROFDATA_PATH', '').strip()
        batch_profdata_env = os.environ.get('FM_BATCH_PROFDATA_PATH', '').strip()
        coverage_sets_env = os.environ.get('FM_COVERAGE_SETS_JSON', '').strip()
        return cls(
            cov_bin=Path(f'/out/{os.environ["FM_TARGET_NAME"]}'),
            input_mode=os.environ.get('FM_INPUT_MODE', '').strip(),
            out_dir=out_dir,
            work_dir=Path(work_dir_env) if work_dir_env else out_dir / '_work',
            input_list=Path(os.environ.get('FM_INPUT_LIST', '')),
            prof_list=Path(os.environ.get('FM_PROF_LIST', '')),
            profdata=Path(profdata_env) if profdata_env else out_dir / 'merged.profdata',
            batch_profdata=Path(batch_profdata_env) if batch_profdata_env else None,
            coverage_sets=Path(coverage_sets_env) if coverage_sets_env else None,
            timeout_s=float(os.environ.get('FM_TIMEOUT_S', '2.0')),
        )


def main() -> None:
    '''Run the coverage worker command.'''
    cfg = WorkerConfig.from_env()
    if not cfg.cov_bin.is_file():
        raise SystemExit(f'Coverage bin not found in image: {cfg.cov_bin}')
    _ensure_dir(cfg.out_dir)
    _ensure_dir(cfg.work_dir)
    _ensure_dir(cfg.profdata.parent)

    if cfg.batch_profdata is not None:
        _run_batch_mode(cfg)
        return
    _run_finalize_mode(cfg)


def _run_batch_mode(cfg: WorkerConfig) -> None:
    inputs = _read_list_file(cfg.input_list)
    profraws_dir = cfg.work_dir / 'worker_tmp'
    _ensure_dir(profraws_dir)
    attempted = len(inputs)
    start_time = time.time()

    if inputs and cfg.input_mode == 'in_process':
        results = [_execute_inprocess_batch(cfg, inputs, profraws_dir)]
    else:
        results = [_execute_one_input(cfg, input_path, index, profraws_dir) for index, input_path in enumerate(inputs)]

    LOG.debug('Finished coverage batch with %d inputs in %.1f seconds', attempted, time.time() - start_time)
    new_profraws = sorted(glob.glob(str(profraws_dir / '*.tmp')))
    if attempted:
        _write_input_exec_diagnostics(
            out_dir=cfg.out_dir,
            attempted=attempted,
            timeout_s=cfg.timeout_s,
            results=results,
        )
    if new_profraws and cfg.batch_profdata is not None:
        _merge_profiles(
            inputs=new_profraws,
            output=cfg.batch_profdata,
            work_dir=cfg.work_dir,
            out_dir=cfg.out_dir,
            label='batch',
        )
    shutil.rmtree(cfg.work_dir, ignore_errors=True)


def _run_finalize_mode(cfg: WorkerConfig) -> None:
    merge_inputs = [path for path in _read_list_file(cfg.prof_list) if Path(path).is_file()]
    if merge_inputs:
        tmp_profdata = cfg.profdata.with_suffix('.tmp')
        _merge_profiles(
            inputs=merge_inputs,
            output=tmp_profdata,
            work_dir=cfg.work_dir,
            out_dir=cfg.out_dir,
            label='final',
        )
        tmp_profdata.replace(cfg.profdata)
    shutil.rmtree(cfg.work_dir, ignore_errors=True)

    if not cfg.profdata.is_file():
        _write_text(cfg.out_dir / 'summary.json', '{}')
        return

    _write_coverage_outputs(cfg)


def _execute_one_input(cfg: WorkerConfig, input_path: str, index: int, profraws_dir: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env['LLVM_PROFILE_FILE'] = str(profraws_dir / f'i{index:08d}.%p.%m.tmp')
    _ensure_dir(profraws_dir.parent / 'artifacts')
    cmd, stdin_data = _target_command(cfg, input_path)
    try:
        cp = subprocess.run(
            cmd,
            input=stdin_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors='ignore',
            env=env,
            cwd=str(cfg.cov_bin.parent),
            timeout=cfg.timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            'index': index,
            'input': input_path,
            'status': 'timeout',
            'returncode': None,
            'profraws': _profraws_for_input(profraws_dir, index),
            'stdout': _truncate_text(exc.stdout or ''),
            'stderr': _truncate_text(exc.stderr or ''),
        }

    profraws = _profraws_for_input(profraws_dir, index)
    status = 'ok'
    if cp.returncode != 0:
        status = 'failed'
    elif not profraws:
        status = 'missing_profraw'
    return {
        'index': index,
        'input': input_path,
        'status': status,
        'returncode': int(cp.returncode),
        'profraws': profraws,
        'stdout': _truncate_text(cp.stdout or ''),
        'stderr': _truncate_text(cp.stderr or ''),
    }


def _execute_inprocess_batch(cfg: WorkerConfig, inputs: list[str], profraws_dir: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env['LLVM_PROFILE_FILE'] = str(profraws_dir / 'batch000000.%p.%m.tmp')
    _ensure_dir(profraws_dir.parent / 'artifacts')
    batch_input_dir = _link_batch_inputs(inputs=inputs, work_dir=cfg.work_dir)
    merge_output_dir = cfg.work_dir / 'merge_output'
    shutil.rmtree(merge_output_dir, ignore_errors=True)
    _ensure_dir(merge_output_dir)
    cmd = [
        str(cfg.cov_bin),
        '-merge=1',
        f'-timeout={max(1, int(cfg.timeout_s))}',
        f'-artifact_prefix={profraws_dir.parent / "artifacts"}/',
        str(merge_output_dir),
        str(batch_input_dir),
    ]
    cp = _target_run(cmd, env=env, cwd=cfg.cov_bin.parent)
    profraws = sorted(glob.glob(str(profraws_dir / 'batch*.tmp')))
    status = 'ok'
    if cp.returncode != 0:
        status = 'failed'
    elif not profraws:
        status = 'missing_profraw'
    return {
        'index': 0,
        'input': f'<batch:{len(inputs)}>',
        'status': status,
        'returncode': int(cp.returncode),
        'profraws': profraws,
        'stdout': _truncate_text(cp.stdout or ''),
        'stderr': _truncate_text(cp.stderr or ''),
    }


def _write_coverage_outputs(cfg: WorkerConfig) -> None:
    pe_args = _path_equivalence_args()
    if not _env_flag('FM_SKIP_HTML'):
        html_dir = cfg.out_dir / 'html'
        _ensure_dir(html_dir)
        _run(
            [
                'llvm-cov',
                'show',
                str(cfg.cov_bin),
                f'-instr-profile={cfg.profdata}',
                '--format=html',
                f'--output-dir={html_dir}',
                '--show-branches=count',
                '--show-line-counts-or-regions',
                *pe_args,
            ],
            out_dir=cfg.out_dir,
            label='llvm_cov_show',
            check=False,
        )
    report = _run(
        ['llvm-cov', 'report', str(cfg.cov_bin), f'-instr-profile={cfg.profdata}', *pe_args],
        out_dir=cfg.out_dir,
        label='llvm_cov_report',
    )
    summary = _coverage_summary_from_report(report.stdout or '')

    export_obj: dict[str, Any] = {}
    metrics: dict[str, list[int]] = {}
    if cfg.coverage_sets is not None:
        export = _run(
            [
                'llvm-cov',
                'export',
                f'-instr-profile={cfg.profdata}',
                '-region-coverage-gt=0',
                '-skip-expansions',
                str(cfg.cov_bin),
                *pe_args,
            ],
            out_dir=cfg.out_dir,
            label='llvm_cov_export',
        )
        try:
            export_obj = json.loads(export.stdout or '{}')
            metrics = coverage_metrics_from_export(export_obj)
            if not summary:
                summary = coverage_summary_from_export(export_obj, metrics=metrics)
        except Exception as exc:
            _write_text(cfg.out_dir / 'export_parse_error.txt', repr(exc))

    if cfg.coverage_sets is not None:
        try:
            write_coverage_sets(cfg.coverage_sets, summary, metrics)
        except Exception as exc:
            _write_text(cfg.out_dir / 'coverage_sets_error.txt', repr(exc))

    _write_text(cfg.out_dir / 'summary.json', json.dumps(summary, indent=2))


def _coverage_summary_from_report(report: str) -> dict[str, int | None]:
    for line in report.splitlines():
        stripped = line.strip()
        if not stripped.startswith('TOTAL'):
            continue
        parts = stripped.split()[1:]
        if len(parts) < 12:
            return {}
        groups = {
            'regions': parts[0:3],
            'functions': parts[3:6],
            'lines': parts[6:9],
            'branches': parts[9:12],
        }
        return {
            key: value
            for metric, group in groups.items()
            for key, value in _coverage_report_counts(metric, group).items()
        }
    return {}


def _coverage_report_counts(metric: str, group: list[str]) -> dict[str, int | None]:
    total = _token_int(group[0])
    missed = _token_int(group[1])
    covered = None if total is None or missed is None else max(0, total - missed)
    return {f'cov_{metric}_total': total, f'cov_{metric}_covered': covered}


def _merge_profiles(*, inputs: list[str], output: Path, work_dir: Path, out_dir: Path, label: str) -> bool:
    merge_inputs = [item for item in inputs if item]
    if not merge_inputs:
        return False
    round_idx = 0
    while len(merge_inputs) > PROFDATA_MERGE_CHUNK_SIZE:
        round_idx += 1
        chunk_dir = work_dir / f'{label}_chunks_{round_idx:02d}'
        shutil.rmtree(chunk_dir, ignore_errors=True)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        merge_inputs = [
            str(
                _merge_chunk(
                    chunk,
                    chunk_dir / f'chunk_{index:06d}.profdata',
                    out_dir,
                    f'{label}_{round_idx:02d}_{index:06d}',
                )
            )
            for index, chunk in enumerate(_chunks(merge_inputs, PROFDATA_MERGE_CHUNK_SIZE))
        ]
    _run(
        ['llvm-profdata', 'merge', '-sparse', *merge_inputs, '-o', str(output)],
        out_dir=out_dir,
        label=f'llvm_profdata_merge_{label}',
    )
    return True


def _merge_chunk(inputs: list[str], output: Path, out_dir: Path, label: str) -> Path:
    _run(
        ['llvm-profdata', 'merge', '-sparse', *inputs, '-o', str(output)],
        out_dir=out_dir,
        label=f'llvm_profdata_merge_{label}',
    )
    return output


def _run(cmd: list[str], *, out_dir: Path, label: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(cmd, text=True, capture_output=True, timeout=600.0, check=False)
    if cp.returncode == 0 or not check:
        if cp.returncode != 0:
            _write_text(out_dir / f'{label}.stdout.txt', cp.stdout or '')
            _write_text(out_dir / f'{label}.stderr.txt', cp.stderr or '')
        return cp
    _write_text(out_dir / f'{label}.stdout.txt', cp.stdout or '')
    _write_text(out_dir / f'{label}.stderr.txt', cp.stderr or '')
    raise SystemExit(f'{label} failed rc={cp.returncode}')


def _target_command(cfg: WorkerConfig, input_path: str) -> tuple[list[str], str | None]:
    if cfg.input_mode in {'in_process', 'file'}:
        return [str(cfg.cov_bin), input_path], None
    return [str(cfg.cov_bin)], Path(input_path).read_text(encoding='utf-8', errors='replace')


def _target_run(cmd: list[str], *, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors='ignore',
        env=env,
        cwd=str(cwd),
        check=False,
    )


def _write_input_exec_diagnostics(
    *,
    out_dir: Path,
    attempted: int,
    timeout_s: float,
    results: list[dict[str, Any]],
) -> None:
    status_counts: dict[str, int] = {}
    for result in results:
        status = str(result.get('status') or 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1

    produced_profraws = sum(len(result.get('profraws') or []) for result in results)
    problematic = [
        {
            'index': result.get('index'),
            'input': result.get('input'),
            'status': result.get('status'),
            'returncode': result.get('returncode'),
            'profraws': result.get('profraws'),
            'stdout': result.get('stdout'),
            'stderr': result.get('stderr'),
        }
        for result in results
        if result.get('status') != 'ok'
    ]
    payload = {
        'attempted': attempted,
        'timeout_s': timeout_s,
        'status_counts': status_counts,
        'produced_profraws': produced_profraws,
        'problematic_inputs': problematic,
    }
    _write_text(out_dir / 'input_exec_diagnostics.json', json.dumps(payload, indent=2))


def _token_int(value: str) -> int | None:
    try:
        return int(str(value).replace(',', ''))
    except Exception:
        return None


def _profraws_for_input(profraws_dir: Path, index: int) -> list[str]:
    return sorted(glob.glob(str(profraws_dir / f'i{index:08d}.*.tmp')))


def _link_batch_inputs(*, inputs: list[str], work_dir: Path) -> Path:
    batch_dir = work_dir / 'merge_inputs'
    shutil.rmtree(batch_dir, ignore_errors=True)
    batch_dir.mkdir(parents=True, exist_ok=True)
    for index, input_path in enumerate(inputs):
        dst = batch_dir / f'input_{index:08d}'
        try:
            os.symlink(Path(input_path), dst)
        except OSError:
            shutil.copy2(input_path, dst)
    return batch_dir


def _read_list_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding='utf-8', errors='replace').splitlines() if line.strip()]


def _path_equivalence_args() -> list[str]:
    path_eq_from = os.environ.get('FM_PATH_EQ_FROM', '').strip()
    path_eq_to = os.environ.get('FM_PATH_EQ_TO', '').strip()
    return [f'--path-equivalence={path_eq_from},{path_eq_to}'] if path_eq_from and path_eq_to else []


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', errors='replace')


def _env_flag(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _truncate_text(text: str | bytes, *, limit: int = 2000) -> str:
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='ignore')
    if len(text) <= limit:
        return text
    return f'{text[:limit]}\n...[truncated {len(text) - limit} chars]...'


if __name__ == '__main__':
    main()
