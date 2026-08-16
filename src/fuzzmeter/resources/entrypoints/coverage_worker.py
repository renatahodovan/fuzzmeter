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
import re
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
TOOL_DIAGNOSTIC_LINE_LIMIT = 200
TOOL_TIMEOUT_ENV = 'FM_LLVM_TOOL_TIMEOUT_S'


@dataclass(frozen=True)
class WorkerConfig:
    '''Hold coverage worker environment values.'''

    cov_bin: Path
    out_dir: Path
    work_dir: Path
    profdata: Path
    coverage_sets: Path | None = None
    input_mode: str = ''
    input_list: Path = Path()
    prof_list: Path = Path()
    batch_profdata: Path | None = None
    timeout_s: float = 0.0
    path_eq_from: str = ''
    path_eq_to: str = ''
    skip_html: bool = False

    @classmethod
    def from_env(cls) -> WorkerConfig:
        '''Build a worker config from environment variables.'''
        out_dir = Path(os.environ['FM_OUT_DIR'])
        work_dir_env = os.environ.get('FM_WORK_DIR', '').strip()
        profdata_env = os.environ.get('FM_PROFDATA_PATH', '').strip()
        coverage_sets_env = os.environ.get('FM_COVERAGE_SETS_JSON', '').strip()
        batch_profdata_env = os.environ.get('FM_BATCH_PROFDATA_PATH', '').strip()
        cov_bin = Path(f'/out/{os.environ["FM_TARGET_NAME"]}')
        work_dir = Path(work_dir_env) if work_dir_env else out_dir / '_work'
        profdata = Path(profdata_env) if profdata_env else out_dir / 'merged.profdata'
        coverage_sets = Path(coverage_sets_env) if coverage_sets_env else None
        path_eq_from = os.environ.get('FM_PATH_EQ_FROM', '').strip()
        path_eq_to = os.environ.get('FM_PATH_EQ_TO', '').strip()
        skip_html = 'FM_SKIP_HTML' in os.environ

        if batch_profdata_env:
            return cls(
                cov_bin=cov_bin,
                out_dir=out_dir,
                work_dir=work_dir,
                profdata=profdata,
                coverage_sets=coverage_sets,
                input_mode=os.environ['FM_INPUT_MODE'].strip(),
                input_list=Path(os.environ['FM_INPUT_LIST']),
                batch_profdata=Path(batch_profdata_env),
                timeout_s=float(os.environ['FM_TIMEOUT_S']),
                path_eq_from=path_eq_from,
                path_eq_to=path_eq_to,
                skip_html=skip_html,
            )
        return cls(
            cov_bin=cov_bin,
            out_dir=out_dir,
            work_dir=work_dir,
            profdata=profdata,
            coverage_sets=coverage_sets,
            prof_list=Path(os.environ['FM_PROF_LIST']),
            path_eq_from=path_eq_from,
            path_eq_to=path_eq_to,
            skip_html=skip_html,
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
    inputs = _read_nonempty_lines(cfg.input_list)
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
    merge_inputs = [path for path in _read_nonempty_lines(cfg.prof_list) if Path(path).is_file()]

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
            check=False,
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
        stdout=cp.stdout.decode('utf-8', errors='replace') if cp.stdout else '',
        stderr=cp.stderr.decode('utf-8', errors='replace') if cp.stderr else '',
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
        check=False,
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
    pe_args = _path_equivalence_args(cfg)
    if not cfg.skip_html and 'FM_SKIP_HTML' not in os.environ:
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
    report_flags = [f'-instr-profile={cfg.profdata}', *pe_args]
    report = _run(
        ['llvm-cov', 'report', str(cfg.cov_bin), *report_flags],
        out_dir=cfg.out_dir,
        label='llvm_cov_report',
    )
    summary = _coverage_summary_from_report(report.stdout or '')

    if cfg.coverage_sets is not None:
        export_obj: dict[str, Any] = {}
        export_summary: dict[str, int | None] = {}
        metrics: dict[str, list[int]] = {}
        export_flags = [
            f'-instr-profile={cfg.profdata}',
            '-region-coverage-gt=0',
            '-skip-expansions',
            *pe_args,
        ]
        export = _run(
            [
                'llvm-cov',
                'export',
                *export_flags,
                str(cfg.cov_bin),
            ],
            out_dir=cfg.out_dir,
            label='llvm_cov_export',
        )
        try:
            export_obj = json.loads(export.stdout or '{}')
            metrics = coverage_metrics_from_export(export_obj)
            export_summary = coverage_summary_from_export(export_obj)
        except Exception as exc:
            (cfg.out_dir / 'export_parse_error.txt').write_text(repr(exc), encoding='utf-8', errors='replace')
        try:
            write_coverage_sets(
                cfg.coverage_sets,
                summary,
                export_summary,
                metrics,
                report_flags=report_flags,
                export_flags=export_flags,
            )
        except Exception as exc:
            (cfg.out_dir / 'coverage_sets_error.txt').write_text(repr(exc), encoding='utf-8', errors='replace')

    (cfg.out_dir / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8', errors='replace')


def _coverage_summary_from_report(report: str) -> dict[str, int | None]:
    header_columns: list[str] | None = None
    group_indexes: dict[str, tuple[int, int, int]] = {}
    total_parts: list[str] | None = None

    for line in report.splitlines():
        stripped = line.strip()
        columns = [column.strip() for column in re.split(r'\s{2,}', stripped)]
        if columns[0] == 'Filename':
            header_columns = columns[1:]
            group_indexes = {}
            for metric in ('regions', 'functions', 'lines', 'branches'):
                name = metric.title()
                percentage = 'Executed' if metric == 'functions' else 'Cover'
                expected = [name, f'Missed {name}', percentage]
                matches = [
                    index
                    for index in range(len(header_columns) - 2)
                    if header_columns[index:index + 3] == expected
                ]
                if len(matches) != 1:
                    raise ValueError(f'Cannot locate {metric} columns in llvm-cov report header')
                start = matches[0]
                group_indexes[metric] = (start, start + 1, start + 2)
            indexes = [index for group in group_indexes.values() for index in group]
            if sorted(indexes) != list(range(len(header_columns))):
                raise ValueError('Unexpected columns in llvm-cov report header')
            continue
        parts = stripped.split()
        if parts and parts[0] == 'TOTAL':
            total_parts = parts[1:]

    if header_columns is None:
        raise ValueError('Missing llvm-cov report header')
    if total_parts is None:
        raise ValueError('Missing TOTAL row in llvm-cov report')
    if len(total_parts) != len(header_columns):
        raise ValueError(
            f'llvm-cov TOTAL row has {len(total_parts)} columns, expected {len(header_columns)}'
        )
    return {
        key: value
        for metric, indexes in group_indexes.items()
        for key, value in _coverage_report_counts(
            metric,
            [total_parts[index] for index in indexes],
        ).items()
    }


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
    timeout_s = float(os.environ.get(TOOL_TIMEOUT_ENV, '600'))
    try:
        cp = subprocess.run(
            cmd,
            check=False,
            text=True,
            encoding='utf-8',
            errors='replace',
            capture_output=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ''
        stderr = exc.stderr or ''
        if isinstance(stdout, bytes):
            stdout = stdout.decode('utf-8', errors='replace')
        if isinstance(stderr, bytes):
            stderr = stderr.decode('utf-8', errors='replace')
        if stdout:
            (out_dir / f'{label}.stdout.txt').write_text(stdout, encoding='utf-8', errors='replace')
        if stderr:
            (out_dir / f'{label}.stderr.txt').write_text(stderr, encoding='utf-8', errors='replace')
        _record_tool_diagnostics(
            out_dir=out_dir,
            label=label,
            cmd=cmd,
            returncode=None,
            stderr=stderr,
            timed_out=True,
        )
        raise RuntimeError(f'{label} timed out after {timeout_s:g} seconds') from exc

    if cp.returncode != 0:
        (out_dir / f'{label}.stdout.txt').write_text(cp.stdout or '', encoding='utf-8', errors='replace')
    if cp.stderr:
        (out_dir / f'{label}.stderr.txt').write_text(cp.stderr, encoding='utf-8', errors='replace')
    _record_tool_diagnostics(
        out_dir=out_dir,
        label=label,
        cmd=cmd,
        returncode=cp.returncode,
        stderr=cp.stderr or '',
    )
    if cp.returncode == 0:
        return cp
    if not check:
        LOG.warning('%s failed rc=%d; continuing because checking is disabled', label, cp.returncode)
        return cp
    raise RuntimeError(f'{label} failed rc={cp.returncode}')


def _record_tool_diagnostics(
    *,
    out_dir: Path,
    label: str,
    cmd: list[str],
    returncode: int | None,
    stderr: str,
    timed_out: bool = False,
) -> None:
    diagnostics_path = out_dir / 'tool_diagnostics.json'
    diagnostics = json.loads(diagnostics_path.read_text(encoding='utf-8')) if diagnostics_path.exists() else {}
    stderr_lines = stderr.splitlines()
    entry: dict[str, Any] = {
        'command': cmd,
        'returncode': returncode,
        'stderr_line_count': len(stderr_lines),
        'warnings': stderr_lines[:TOOL_DIAGNOSTIC_LINE_LIMIT],
    }
    if len(stderr_lines) > TOOL_DIAGNOSTIC_LINE_LIMIT:
        entry['truncated'] = True
    if timed_out:
        entry['timed_out'] = True
    diagnostics[label] = entry
    diagnostics_path.write_text(json.dumps(diagnostics, indent=2), encoding='utf-8', errors='replace')


def _target_command(cfg: WorkerConfig, input_path: str) -> tuple[list[str], bytes | None]:
    if cfg.input_mode in {'in_process', 'file'}:
        return [str(cfg.cov_bin), input_path], None
    return [str(cfg.cov_bin)], Path(input_path).read_bytes()


def _path_equivalence_args(cfg: WorkerConfig) -> list[str]:
    path_eq_from = cfg.path_eq_from or os.environ.get('FM_PATH_EQ_FROM', '').strip()
    path_eq_to = cfg.path_eq_to or os.environ.get('FM_PATH_EQ_TO', '').strip()
    if path_eq_from and path_eq_to:
        return [f'--path-equivalence={path_eq_from},{path_eq_to}']
    return []


def _read_nonempty_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines()
        if line.strip()
    ]


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
