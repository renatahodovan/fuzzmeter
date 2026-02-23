#!/usr/bin/env python3
# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Replay coverage inputs and produce LLVM coverage artifacts in coverage containers.'''

from __future__ import annotations

import base64
import concurrent.futures
import glob
import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
import zlib

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

LOG_LEVEL = getattr(logging, os.environ.get('FM_LOG_LEVEL', 'WARNING'))
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)-7s - %(name)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
LOG = logging.getLogger(__name__)
PROFDATA_MERGE_CHUNK_SIZE = 512
COVERAGE_METRICS = ('lines', 'branches', 'functions', 'regions')


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
    input_jobs: int
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
            input_jobs=max(1, int(os.environ.get('FM_INPUT_JOBS', '1'))),
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
        jobs = 1
        results = [_execute_inprocess_batch(cfg, inputs, profraws_dir)]
    else:
        jobs = max(1, min(cfg.input_jobs, max(1, attempted)))
        results = _execute_inputs(cfg, inputs, profraws_dir, jobs)

    LOG.debug('Finished coverage batch with %d inputs in %.1f seconds', attempted, time.time() - start_time)
    new_profraws = sorted(glob.glob(str(profraws_dir / '*.tmp')))
    if attempted:
        _write_input_exec_diagnostics(
            out_dir=cfg.out_dir,
            attempted=attempted,
            timeout_s=cfg.timeout_s,
            jobs=jobs,
            results=results,
        )
    if new_profraws and cfg.batch_profdata is not None:
        _merge_profiles(inputs=new_profraws, output=cfg.batch_profdata, work_dir=cfg.work_dir, out_dir=cfg.out_dir, label='batch')
    shutil.rmtree(cfg.work_dir, ignore_errors=True)


def _run_finalize_mode(cfg: WorkerConfig) -> None:
    merge_inputs = [path for path in _read_list_file(cfg.prof_list) if Path(path).is_file()]
    if merge_inputs:
        tmp_profdata = cfg.profdata.with_suffix('.tmp')
        _merge_profiles(inputs=merge_inputs, output=tmp_profdata, work_dir=cfg.work_dir, out_dir=cfg.out_dir, label='final')
        tmp_profdata.replace(cfg.profdata)
    shutil.rmtree(cfg.work_dir, ignore_errors=True)

    if not cfg.profdata.is_file():
        _write_text(cfg.out_dir / 'summary.json', '{}')
        return

    _write_coverage_outputs(cfg)


def _execute_inputs(cfg: WorkerConfig, inputs: list[str], profraws_dir: Path, jobs: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any] | None] = [None] * len(inputs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(_execute_one_input, cfg, input_path, index, profraws_dir): index
            for index, input_path in enumerate(inputs)
        }
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                results[index] = _worker_error_result(index=index, input_path=inputs[index], exc=exc)
    return [result for result in results if result is not None]


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
            metrics = _coverage_metrics_from_export(export_obj)
            if not summary:
                summary = coverage_summary_from_export(export_obj, metrics=metrics)
        except Exception as exc:
            _write_text(cfg.out_dir / 'export_parse_error.txt', repr(exc))

    if cfg.coverage_sets is not None:
        try:
            _write_compact_coverage_sets(cfg.coverage_sets, summary, metrics)
        except Exception as exc:
            _write_text(cfg.out_dir / 'coverage_sets_error.txt', repr(exc))

    _write_text(cfg.out_dir / 'summary.json', json.dumps(summary, indent=2))


def coverage_summary_from_export(export_obj: dict[str, Any], *, metrics: dict[str, list[int]] | None = None) -> dict[str, int | None]:
    '''Return fuzzmeter coverage counters from an llvm-cov export object.'''
    totals = (((export_obj.get('data') or [{}])[0] or {}).get('totals') or {}) if isinstance(export_obj.get('data'), list) else {}
    summary = {
        key: _nested_int(totals, metric, field)
        for metric in COVERAGE_METRICS
        for key, field in ((f'cov_{metric}_total', 'count'), (f'cov_{metric}_covered', 'covered'))
    }
    for metric, values in (metrics or {}).items():
        summary[f'cov_{metric}_covered'] = len(values)
    return summary


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


def _write_compact_coverage_sets(path: Path, summary: dict[str, Any], metrics: dict[str, list[int]]) -> None:
    doc = {
        'version': 1,
        'type': 'fuzzmeter.coverage.sets',
        'encoding': 'blake2b64-delta-uvarint-zlib-base64',
        'metrics': {
            metric: {
                'covered_count': len(metrics.get(metric, [])),
                'total_count': summary.get(f'cov_{metric}_total'),
                'payload': base64.b64encode(zlib.compress(_encode_delta_varints(metrics.get(metric, [])), level=9)).decode('ascii'),
            }
            for metric in COVERAGE_METRICS
        },
    }
    _write_text(path, json.dumps(doc, separators=(',', ':')))


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
            str(_merge_chunk(chunk, chunk_dir / f'chunk_{index:06d}.profdata', out_dir, f'{label}_{round_idx:02d}_{index:06d}'))
            for index, chunk in enumerate(_chunks(merge_inputs, PROFDATA_MERGE_CHUNK_SIZE))
        ]
    _run(['llvm-profdata', 'merge', '-sparse', *merge_inputs, '-o', str(output)], out_dir=out_dir, label=f'llvm_profdata_merge_{label}')
    return True


def _merge_chunk(inputs: list[str], output: Path, out_dir: Path, label: str) -> Path:
    _run(['llvm-profdata', 'merge', '-sparse', *inputs, '-o', str(output)], out_dir=out_dir, label=f'llvm_profdata_merge_{label}')
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
    jobs: int,
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
        'jobs': jobs,
        'status_counts': status_counts,
        'produced_profraws': produced_profraws,
        'problematic_inputs': problematic,
    }
    _write_text(out_dir / 'input_exec_diagnostics.json', json.dumps(payload, indent=2))


def _worker_error_result(*, index: int, input_path: str, exc: Exception) -> dict[str, Any]:
    return {
        'index': index,
        'input': input_path,
        'status': 'worker_error',
        'returncode': None,
        'profraws': [],
        'stdout': '',
        'stderr': repr(exc),
    }


def _coverage_metrics_from_export(export_obj: dict[str, Any]) -> dict[str, list[int]]:
    return {metric: _covered_hashes(export_obj, metric) for metric in COVERAGE_METRICS}


def _covered_hashes(export_obj: dict[str, Any], metric: str) -> list[int]:
    hashes: set[int] = set()
    for data_item in export_obj.get('data') or []:
        if not isinstance(data_item, dict):
            continue
        for file_item in data_item.get('files') or []:
            _collect_file_hashes(hashes, file_item, metric)
        if metric == 'functions':
            for ordinal, function in enumerate(data_item.get('functions') or []):
                if _function_covered(function):
                    hashes.add(_stable_hash(_function_key('', function, ordinal)))
    return sorted(hashes)


def _collect_file_hashes(hashes: set[int], file_item: Any, metric: str) -> None:
    if not isinstance(file_item, dict):
        return
    filename = str(file_item.get('filename') or '')
    if not filename:
        return
    if metric in {'lines', 'regions'}:
        for segment in file_item.get('segments') or []:
            if _covered_tuple(segment, 2):
                hashes.add(_stable_hash(_safe_text(filename, segment[0], None if metric == 'lines' else segment[1])))
        return
    entries = file_item.get('branches') if metric == 'branches' else file_item.get('functions') if metric == 'functions' else []
    for ordinal, entry in enumerate(entries or []):
        if metric == 'branches' and _covered_tuple(entry, 4, 6):
            hashes.add(_stable_hash(_safe_text(filename, *list(entry)[:4], ordinal)))
        elif metric == 'functions' and _function_covered(entry):
            hashes.add(_stable_hash(_function_key(filename, entry, ordinal)))


def _function_covered(function: Any) -> bool:
    if not isinstance(function, dict):
        return False
    return _positive(function.get('count')) or any(_covered_tuple(region, 4) for region in function.get('regions') or [])


def _function_key(default_filename: str, function: Any, ordinal: int) -> str:
    regions = function.get('regions') if isinstance(function, dict) else None
    region_parts = list(regions[0][:4]) if isinstance(regions, list) and regions and _tuple_like(regions[0]) else []
    name = function.get('name') or function.get('demangled') or ordinal
    return _safe_text(_function_filename(default_filename, function), name, *region_parts)


def _function_filename(default_filename: str, function: dict[str, Any]) -> str:
    filenames = function.get('filenames')
    if isinstance(filenames, list) and filenames:
        return str(filenames[0])
    return str(function.get('filename') or default_filename)


def _safe_text(*parts: Any) -> str:
    return ':'.join(str(part).strip() for part in parts if part is not None and str(part).strip())


def _covered_tuple(values: Any, start: int, end: int | None = None) -> bool:
    return _tuple_like(values) and len(values) > start and any(_positive(value) for value in list(values)[start:end])


def _tuple_like(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def _positive(value: Any) -> bool:
    try:
        return float(value) > 0
    except Exception:
        return False


def _stable_hash(value: str) -> int:
    digest = hashlib.blake2b(value.encode('utf-8', errors='replace'), digest_size=8).digest()
    return int.from_bytes(digest, byteorder='big', signed=False)


def _nested_int(data: dict[str, Any], metric: str, key: str) -> int | None:
    try:
        return int((data.get(metric) or {}).get(key))
    except Exception:
        return None


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


def _encode_uvarint(value: int) -> bytes:
    out = bytearray()
    current = int(value)
    while current >= 0x80:
        out.append((current & 0x7F) | 0x80)
        current >>= 7
    out.append(current)
    return bytes(out)


def _encode_delta_varints(values: Iterable[int]) -> bytes:
    payload = bytearray()
    prev = 0
    first = True
    for value in values:
        current = int(value)
        delta = current if first else (current - prev)
        payload.extend(_encode_uvarint(delta))
        prev = current
        first = False
    return bytes(payload)


if __name__ == '__main__':
    main()
