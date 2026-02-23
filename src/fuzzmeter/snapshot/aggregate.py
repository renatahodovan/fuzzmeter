# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Build campaign-level coverage artifacts from trial coverage profiles.'''

from __future__ import annotations

import json
import logging
import os
import shutil

from pathlib import Path

from ..db import DB
from ..db.snapshot import upsert_agg_snapshot, update_agg_snapshot_coverage
from ..docker import DockerClient, DockerRuntime
from .models import CoverageTask

LOG = logging.getLogger(__name__)


class SnapshotAggregateUpdater:
    '''Update aggregate coverage snapshots.'''

    def __init__(self, *, docker_runtime: DockerRuntime, export_every_ticks: int = 1) -> None:
        self.docker_runtime = docker_runtime
        self.docker = DockerClient(docker_runtime)
        self.export_every_ticks = int(export_every_ticks)

    def update(
        self,
        *,
        db: DB,
        run_dir,
        run_id: str,
        tick_idx: int,
        ts: int,
        coverage_tasks: list[CoverageTask],
    ) -> None:
        '''Update aggregate coverage for campaigns changed at the given tick.'''
        campaigns = sorted({
            (task.trial.fuzzer, task.trial.benchmark, task.trial.fuzz_target)
            for task in coverage_tasks
        })
        for fuzzer, benchmark, fuzz_target in campaigns:
            self._update_aggregate_coverage(
                db=db,
                run_dir=run_dir,
                run_id=run_id,
                fuzzer=fuzzer,
                benchmark=benchmark,
                fuzz_target=fuzz_target,
                idx=tick_idx,
                ts=ts,
                write_export=self._should_write_export(tick_idx, coverage_tasks),
            )

    def _update_aggregate_coverage(
        self,
        *,
        db: DB,
        run_dir: Path,
        run_id: str,
        fuzzer: str,
        benchmark: str,
        fuzz_target: str,
        idx: int,
        ts: int,
        write_export: bool,
    ) -> None:
        run_dir = Path(run_dir)

        profdata_inputs = [
            str(Path(self.docker.container_path(path)))
            for path in self._campaign_profdata_paths(
                db=db,
                run_dir=run_dir,
                run_id=run_id,
                fuzzer=fuzzer,
                benchmark=benchmark,
                fuzz_target=fuzz_target,
            )
            if path.is_file() and path.stat().st_size > 64
        ]
        if not profdata_inputs:
            return

        agg_id = upsert_agg_snapshot(
            db,
            run_id=run_id,
            fuzzer=fuzzer,
            benchmark=benchmark,
            fuzz_target=fuzz_target,
            idx=idx,
            ts=ts,
        )
        db.commit()

        target_key = f'{fuzzer}/{benchmark}/{fuzz_target}'
        agg_root = run_dir / 'coverage' / fuzzer / benchmark / fuzz_target / 'campaign'
        latest_root = agg_root
        tick_root = agg_root.parent / 'campaign_snapshots' / f'{idx:06d}'
        agg_root.mkdir(parents=True, exist_ok=True)
        tick_root.mkdir(parents=True, exist_ok=True)

        cov_tmp = agg_root.parent / f'.{agg_root.name}.tmp'
        shutil.rmtree(cov_tmp, ignore_errors=True)
        cov_tmp.mkdir(parents=True, exist_ok=True)
        work_root = cov_tmp / '_work'
        profdata_path = cov_tmp / 'merged.profdata'

        prof_list_path = cov_tmp / 'profdata_inputs.txt'
        prof_list_path.write_text('\n'.join(profdata_inputs) + '\n', encoding='utf-8')

        coverage_sets_tmp = cov_tmp / 'coverage-sets.json'
        coverage_sets_tick = tick_root / 'coverage-sets.json'
        src_root = run_dir / 'coverage_src' / f'{benchmark}/{fuzz_target}'

        env = {
            'FM_OUT_DIR': str(Path(self.docker.container_path(cov_tmp))),
            'FM_TARGET_NAME': fuzz_target,
            'FM_PROF_LIST': str(Path(self.docker.container_path(prof_list_path))),
            'FM_PROFDATA_PATH': str(Path(self.docker.container_path(profdata_path))),
            'FM_WORK_DIR': str(Path(self.docker.container_path(work_root))),
            'FM_LOG_LEVEL': str(os.environ.get('FM_LOG_LEVEL', 'INFO')).upper(),
        }
        if write_export:
            env['FM_COVERAGE_SETS_JSON'] = str(Path(self.docker.container_path(coverage_sets_tmp)))
        if src_root.is_dir():
            env['FM_PATH_EQ_FROM'] = '/src'
            env['FM_PATH_EQ_TO'] = str(Path(self.docker.container_path(src_root)))

        result = self.docker.run(
            image=self._cov_image_for(benchmark, fuzz_target),
            env=env,
            volumes=[self.docker.out_volume()],
            check=True,
            cmd=['python3', '/opt/fuzzmeter/coverage_repro_worker.py'],
        )
        if result.stderr:
            LOG.info('Aggregate coverage worker[%s]:\n%s', target_key, result.stderr.rstrip())
        if result.stdout:
            LOG.info('Aggregate coverage worker[%s] stdout:\n%s', target_key, result.stdout.rstrip())

        summary_path = cov_tmp / 'summary.json'
        summary = {}
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding='utf-8', errors='replace') or '{}')

        coverage_sets_json_rel = None
        if coverage_sets_tmp.exists():
            shutil.copy2(coverage_sets_tmp, coverage_sets_tick)
            coverage_sets_json_rel = str(coverage_sets_tick.relative_to(run_dir))
        else:
            previous_coverage_sets = latest_root / 'coverage-sets.json'
            if previous_coverage_sets.exists():
                shutil.copy2(previous_coverage_sets, coverage_sets_tmp)
                coverage_sets_json_rel = str((latest_root / 'coverage-sets.json').relative_to(run_dir))

        shutil.rmtree(latest_root, ignore_errors=True)
        shutil.move(str(cov_tmp), str(latest_root))

        html_index = latest_root / 'html' / 'index.html'
        rel_html = str(html_index.relative_to(run_dir)) if html_index.exists() else None

        update_agg_snapshot_coverage(
            db,
            agg_snapshot_id=agg_id,
            coverage_html_dir=rel_html,
            summary=summary,
            coverage_sets_json_rel=coverage_sets_json_rel,
        )
        db.commit()

    def _should_write_export(self, tick_idx: int, coverage_tasks: list[CoverageTask]) -> bool:
        if any(task.render_heavy for task in coverage_tasks):
            return True
        if self.export_every_ticks <= 0:
            return False
        return int(tick_idx) % int(self.export_every_ticks) == 0

    @staticmethod
    def _cov_image_for(benchmark: str, fuzz_target: str) -> str:
        target_id = f'{benchmark}-{fuzz_target}'.replace('/', '_')
        return f'fuzzmeter/coverage-runner-{target_id}:dev'

    @staticmethod
    def _campaign_profdata_paths(
        *,
        db: DB,
        run_dir: Path,
        run_id: str,
        fuzzer: str,
        benchmark: str,
        fuzz_target: str,
    ) -> list[Path]:
        rows = db.q(
            '''
            SELECT rep
              FROM trials
             WHERE run_id=?
               AND fuzzer=?
               AND benchmark=?
               AND fuzz_target=?
             ORDER BY rep
            ''',
            (str(run_id), str(fuzzer), str(benchmark), str(fuzz_target)),
        )
        profdata_paths: list[Path] = []
        for row in rows:
            trial_key = SnapshotAggregateUpdater._trial_key(fuzzer, benchmark, fuzz_target, int(row['rep']))
            profdata_paths.append(Path(run_dir) / 'trials' / trial_key / 'coverage_state' / 'merged.profdata')
        return profdata_paths

    @staticmethod
    def _trial_key(fuzzer: str, benchmark: str, fuzz_target: str, rep: int) -> str:
        target_id = f'{benchmark}-{fuzz_target}'.replace('/', '_')
        return f'{fuzzer}__{target_id}__rep{int(rep)}'
