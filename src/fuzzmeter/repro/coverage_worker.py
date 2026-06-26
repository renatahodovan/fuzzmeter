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

level = getattr(logging, os.environ.get('FM_LOG_LEVEL', 'WARNING'))
logging.basicConfig(
    level=level,
    format='%(asctime)s - %(levelname)-7s - %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
LOG = logging.getLogger(__name__)
PROFDATA_MERGE_CHUNK_SIZE = 512


@dataclass(frozen=True)
class WorkerConfig:
    '''Hold coverage worker environment values.'''

    cov_bin: Path
    out_dir: Path
    work_dir: Path
    input_list: Path
    profdata: Path
    coverage_sets: Path | None
    input_mode: str = ''
    prof_list: Path = Path()
    batch_profdata: Path | None = None
    timeout_s: float = 0.0

    @classmethod
    def from_env(cls) -> WorkerConfig:
        '''Build a worker config from environment variables.'''
        out_dir = Path(os.environ['FM_OUT_DIR'])
        work_dir_env = os.environ.get('FM_WORK_DIR', '').strip()
        profdata_env = os.environ.get('FM_PROFDATA_PATH', '').strip()
        coverage_sets_env = os.environ.get('FM_COVERAGE_SETS_JSON', '').strip()
        batch_profdata_env = os.environ.get('FM_BATCH_PROFDATA_PATH', '').strip()
        common = {
            'cov_bin': Path(f'/out/{os.environ["FM_TARGET_NAME"]}'),
            'out_dir': out_dir,
            'work_dir': Path(work_dir_env) if work_dir_env else out_dir / '_work',
            'profdata': Path(profdata_env) if profdata_env else out_dir / 'merged.profdata',
            'coverage_sets': Path(coverage_sets_env) if coverage_sets_env else None,
        }
        if batch_profdata_env:
            return cls(
                **common,
                input_mode=os.environ['FM_INPUT_MODE'].strip(),
                input_list=Path(os.environ['FM_INPUT_LIST']),
                batch_profdata=Path(batch_profdata_env),
                timeout_s=float(os.environ['FM_TIMEOUT_S']),
            )
        return cls(
            **common,
            prof_list=Path(os.environ['FM_PROF_LIST']),
        )


def main() -> None:
    '''Run the coverage worker command.'''
    cfg = WorkerConfig.from_env()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    cfg.profdata.parent.mkdir(parents=True, exist_ok=True)

    if cfg.batch_profdata is not None:
        _run_batch_mode(cfg)
        return
    _run_finalize_mode(cfg)


def _run_batch_mode(cfg: WorkerConfig) -> None:
    inputs = [line.strip() for line in cfg.input_list.read_text(encoding='utf-8', errors='replace').splitlines() if line.strip()]
    profraws_dir = cfg.work_dir / 'worker_tmp'
    profraws_dir.mkdir(parents=True, exist_ok=True)
    attempted = len(inputs)
    start_time = time.time()

    (profraws_dir.parent / 'artifacts').mkdir(parents=True, exist_ok=True)
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
    lines = cfg.prof_list.read_text(encoding='utf-8', errors='replace').splitlines()
    merge_inputs = [path for path in lines if path and Path(path).is_file()]

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
        (cfg.out_dir / 'summary.json').write_text('{}', encoding='utf-8', errors='replace')
        return

    _write_coverage_outputs(cfg)


def _result_payload(
    *,
    index: int,
    input_path: str,
    returncode: int | None,
    profraws: list[str],
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    status = 'ok'
    if returncode is None:
        status = 'timeout'
    elif returncode != 0:
        status = 'failed'
    elif not profraws:
        status = 'missing_profraw'
    return {
        'index': index,
        'input': input_path,
        'status': status,
        'returncode': returncode,
        'profraws': profraws,
        'stdout': _truncate_text(stdout),
        'stderr': _truncate_text(stderr),
    }


def _execute_one_input(cfg: WorkerConfig, input_path: str, index: int, profraws_dir: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env['LLVM_PROFILE_FILE'] = str(profraws_dir / f'i{index:08d}.%p.%m.tmp')
    cmd, stdin_data = _target_command(cfg, input_path)
    try:
        cp = subprocess.run(
            cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env,
            cwd=str(cfg.cov_bin.parent),
            timeout=cfg.timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        profraws = _profraws_for_input(profraws_dir, index)
        stdout = exc.stdout.decode('utf-8', errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
        stderr = exc.stderr.decode('utf-8', errors='replace') if isinstance(exc.stderr, bytes) else (exc.stderr or '')
        return _result_payload(
            index=index,
            input_path=input_path,
            returncode=None,
            profraws=profraws,
            stdout=stdout,
            stderr=stderr,
        )

    profraws = _profraws_for_input(profraws_dir, index)
    return _result_payload(
        index=index,
        input_path=input_path,
        returncode=int(cp.returncode),
        profraws=profraws,
        stdout=cp.stdout or '',
        stderr=cp.stderr or '',
    )


def _execute_inprocess_batch(cfg: WorkerConfig, inputs: list[str], profraws_dir: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env['LLVM_PROFILE_FILE'] = str(profraws_dir / 'batch000000.%p.%m.tmp')
    batch_input_dir = _link_batch_inputs(inputs=inputs, work_dir=cfg.work_dir)
    merge_output_dir = cfg.work_dir / 'merge_output'
    shutil.rmtree(merge_output_dir, ignore_errors=True)
    merge_output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(cfg.cov_bin),
        '-merge=1',
        f'-timeout={max(1, int(cfg.timeout_s))}',
        f'-artifact_prefix={profraws_dir.parent / "artifacts"}/',
        str(merge_output_dir),
        str(batch_input_dir),
    ]
    cp = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        env=env,
        cwd=str(cfg.cov_bin.parent),
    )
    profraws = sorted(glob.glob(str(profraws_dir / 'batch*.tmp')))
    return _result_payload(
        index=0,
        input_path=f'<batch:{len(inputs)}>',
        returncode=int(cp.returncode),
        profraws=profraws,
        stdout=cp.stdout or '',
        stderr=cp.stderr or '',
    )


def _write_coverage_outputs(cfg: WorkerConfig) -> None:
    path_eq_from = os.environ.get('FM_PATH_EQ_FROM', '').strip()
    path_eq_to = os.environ.get('FM_PATH_EQ_TO', '').strip()
    pe_args = [f'--path-equivalence={path_eq_from},{path_eq_to}'] if path_eq_from and path_eq_to else []
    if 'FM_SKIP_HTML' not in os.environ:
        html_dir = cfg.out_dir / 'html'
        html_dir.mkdir(parents=True, exist_ok=True)
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

    if cfg.coverage_sets is not None:
        export_obj: dict[str, Any] = {}
        metrics: dict[str, list[int]] = {}
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
            (cfg.out_dir / 'export_parse_error.txt').write_text(repr(exc), encoding='utf-8', errors='replace')
        try:
            write_coverage_sets(cfg.coverage_sets, summary, metrics)
        except Exception as exc:
            (cfg.out_dir / 'coverage_sets_error.txt').write_text(repr(exc), encoding='utf-8', errors='replace')

    (cfg.out_dir / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8', errors='replace')


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
    try:
        total = int(group[0].replace(',', ''))
    except ValueError:
        total = None
    try:
        missed = int(group[1].replace(',', ''))
    except ValueError:
        missed = None
    covered = None if total is None or missed is None else max(0, total - missed)
    return {f'cov_{metric}_total': total, f'cov_{metric}_covered': covered}


def _merge_profiles(*, inputs: list[str], output: Path, work_dir: Path, out_dir: Path, label: str) -> None:
    round_idx = 0
    while len(inputs) > PROFDATA_MERGE_CHUNK_SIZE:
        round_idx += 1
        chunk_dir = work_dir / f'{label}_chunks_{round_idx:02d}'
        shutil.rmtree(chunk_dir, ignore_errors=True)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_outputs = []
        for index, start in enumerate(range(0, len(inputs), PROFDATA_MERGE_CHUNK_SIZE)):
            chunk = inputs[start:start + PROFDATA_MERGE_CHUNK_SIZE]
            chunk_output = chunk_dir / f'chunk_{index:06d}.profdata'
            _run(
                ['llvm-profdata', 'merge', '-sparse', *chunk, '-o', str(chunk_output)],
                out_dir=out_dir,
                label=f'llvm_profdata_merge_{label}_{round_idx:02d}_{index:06d}',
            )
            chunk_outputs.append(str(chunk_output))
        inputs = chunk_outputs
    _run(
        ['llvm-profdata', 'merge', '-sparse', *inputs, '-o', str(output)],
        out_dir=out_dir,
        label=f'llvm_profdata_merge_{label}',
    )


def _run(cmd: list[str], *, out_dir: Path, label: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(cmd, text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=600.0)
    if cp.returncode == 0 or not check:
        return cp
    (out_dir / f'{label}.stdout.txt').write_text(cp.stdout or '', encoding='utf-8', errors='replace')
    (out_dir / f'{label}.stderr.txt').write_text(cp.stderr or '', encoding='utf-8', errors='replace')
    raise RuntimeError(f'{label} failed rc={cp.returncode}')


def _target_command(cfg: WorkerConfig, input_path: str) -> tuple[list[str], str | None]:
    if cfg.input_mode in {'in_process', 'file'}:
        return [str(cfg.cov_bin), input_path], None
    return [str(cfg.cov_bin)], Path(input_path).read_text(encoding='utf-8', errors='replace')


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
    problematic = [result for result in results if result.get('status') != 'ok']
    payload = {
        'attempted': attempted,
        'timeout_s': timeout_s,
        'status_counts': status_counts,
        'produced_profraws': produced_profraws,
        'problematic_inputs': problematic,
    }
    (out_dir / 'input_exec_diagnostics.json').write_text(json.dumps(payload, indent=2), encoding='utf-8', errors='replace')


def _profraws_for_input(profraws_dir: Path, index: int) -> list[str]:
    return sorted(glob.glob(str(profraws_dir / f'i{index:08d}.*.tmp')))


def _link_batch_inputs(*, inputs: list[str], work_dir: Path) -> Path:
    batch_dir = work_dir / 'merge_inputs'
    shutil.rmtree(batch_dir, ignore_errors=True)
    batch_dir.mkdir(parents=True, exist_ok=True)
    for index, input_path in enumerate(inputs):
        dst = batch_dir / f'input_{index:08d}'
        try:
            os.symlink(input_path, dst)
        except OSError:
            shutil.copy2(input_path, dst)
    return batch_dir


def _truncate_text(text: str, *, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return f'{text[:limit]}\n...[truncated {len(text) - limit} chars]...'


if __name__ == '__main__':
    main()
