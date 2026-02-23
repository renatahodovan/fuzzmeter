# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Collect and mutate run-level metadata for the web UI.'''

from __future__ import annotations

import shutil

from pathlib import Path
from typing import Any

import yaml

from ...db.report_views import ReportingDB

from .file_service import FileService


class RunsService:
    '''Provide run listing and deletion helpers for the web UI.'''

    @staticmethod
    def _parse_suite_config(suite_yaml_text: str | None) -> dict[str, Any]:
        if not suite_yaml_text:
            return {}
        try:
            data = yaml.safe_load(str(suite_yaml_text)) or {}
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}

        def fuzzer_name(item: Any) -> str | None:
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                return str(item.get("fuzzer") or item.get("name") or item.get("parent") or "").strip() or None
            return None

        fuzzers = [name for name in (fuzzer_name(item) for item in data.get("fuzzers", [])) if name]
        targets = [str(item) for item in data.get("targets", []) if str(item).strip()]
        run_cfg = data.get("run") or {}
        snapshot_cfg = run_cfg.get("snapshot") or {}
        return {
            "fuzzers": fuzzers,
            "targets": targets,
            "policy": {
                "time_seconds": int(run_cfg.get("time_seconds", 0) or 0),
                "repetitions": int(run_cfg.get("repetitions", 0) or 0),
                "parallel_jobs": int(run_cfg.get("parallel_jobs", 0) or 0),
                "snapshot_every_seconds": int(snapshot_cfg.get("every_seconds", 0) or 0),
            },
        }

    @staticmethod
    def _status_summary(db: ReportingDB, run_id: str) -> dict[str, int]:
        if not db.table_exists("trials") or not db.col_exists("trials", "status"):
            return {}
        where = "WHERE run_id=?" if db.col_exists("trials", "run_id") else ""
        params: tuple[Any, ...] = (run_id,) if where else ()
        rows = db.rows(
            f"SELECT status, COUNT(*) AS c FROM trials {where} GROUP BY status",
            params,
        )
        return {
            str(row.get("status") or "unknown"): int(row.get("c") or 0)
            for row in rows
        }

    @staticmethod
    def _run_summary(db: ReportingDB, run_id: str) -> dict[str, Any]:
        overview = db.run_overview(run_id)
        config = RunsService._parse_suite_config(overview.get("suite_yaml"))
        where = "WHERE run_id=?" if db.col_exists("trials", "run_id") else ""
        params: tuple[Any, ...] = (run_id,) if where else ()

        if db.table_exists("trials"):
            benchmark_count = int(db.scalar(f"SELECT COUNT(DISTINCT benchmark) FROM trials {where}", params) or 0)
            target_count = int(
                db.scalar(f"SELECT COUNT(DISTINCT benchmark || '::' || fuzz_target) FROM trials {where}", params) or 0
            )
            fuzzer_count = int(db.scalar(f"SELECT COUNT(DISTINCT fuzzer) FROM trials {where}", params) or 0)
        else:
            benchmark_count = 0
            target_count = 0
            fuzzer_count = 0

        return {
            "created_ts": int(overview.get("created_ts") or 0) or None,
            "trials": int(overview.get("trials") or 0),
            "snapshots": int(overview.get("snapshots") or 0),
            "bugs": int(overview.get("bugs") or 0),
            "benchmark_count": benchmark_count,
            "target_count": target_count,
            "fuzzer_count": fuzzer_count or len(config.get("fuzzers") or []),
            "status_counts": RunsService._status_summary(db, run_id),
            "config": config,
        }

    @staticmethod
    def _updated_ts(run_dir: Path) -> int | None:
        candidates = [
            run_dir,
            run_dir / "fuzzmeter.db",
            run_dir / "suite.yaml",
            run_dir / "report" / "report.html",
            run_dir / "report" / "data.json",
        ]
        mtimes: list[int] = []
        for path in candidates:
            try:
                if path.exists():
                    mtimes.append(int(path.stat().st_mtime))
            except Exception:
                continue
        return max(mtimes) if mtimes else None

    @classmethod
    def _list_run_entry(cls, run_dir: Path) -> dict[str, Any]:
        run_dir = Path(run_dir).resolve()
        run_id = run_dir.name
        has_static_report = (run_dir / "report" / "report.html").is_file()
        db_path = run_dir / "fuzzmeter.db"
        suite_yaml_path = run_dir / "suite.yaml"
        summary: dict[str, Any] = {
            "created_ts": None,
            "trials": 0,
            "snapshots": 0,
            "bugs": 0,
            "benchmark_count": 0,
            "target_count": 0,
            "fuzzer_count": 0,
            "status_counts": {},
            "config": {},
        }
        error: str | None = None

        if suite_yaml_path.is_file():
            try:
                summary["config"] = cls._parse_suite_config(suite_yaml_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        if db_path.is_file():
            try:
                with ReportingDB(db_path) as db:
                    inferred_run_id = db.infer_run_id(run_id)
                    summary = cls._run_summary(db, inferred_run_id)
                    run_id = inferred_run_id or run_id
            except Exception as exc:
                error = str(exc)
        return {
            "run_id": run_id,
            "path": str(run_dir),
            "has_static_report": has_static_report,
            "updated_ts": cls._updated_ts(run_dir),
            "summary": summary,
            "error": error,
        }

    @staticmethod
    def list_runs(runs_root: Path) -> list[dict[str, Any]]:
        '''List all discovered runs sorted by most recent activity.'''
        root = Path(runs_root).resolve()
        if not root.is_dir():
            return []
        runs = [
            RunsService._list_run_entry(path)
            for path in root.iterdir()
            if path.is_dir()
        ]
        runs.sort(
            key=lambda item: (
                int(item.get("updated_ts") or 0),
                int((item.get("summary") or {}).get("created_ts") or 0),
                str(item.get("run_id") or ""),
            ),
            reverse=True,
        )
        return runs

    @staticmethod
    def delete_run(runs_root: Path, run_id: str) -> None:
        '''Delete one run directory after validating its path.'''
        run_dir = FileService.resolve_run_dir(runs_root, run_id)
        if not run_dir.is_dir():
            raise FileNotFoundError(str(run_dir))
        shutil.rmtree(run_dir, ignore_errors=False)

    @classmethod
    def delete_runs(cls, runs_root: Path, run_ids: list[Any]) -> dict[str, Any]:
        '''Delete multiple runs and return a structured outcome summary.'''
        deleted: list[str] = []
        missing: list[str] = []
        failed: list[dict[str, str]] = []

        for run_id in [str(run_id) for run_id in run_ids if str(run_id).strip()]:
            try:
                cls.delete_run(runs_root, run_id)
                deleted.append(run_id)
            except FileNotFoundError:
                missing.append(run_id)
            except ValueError as exc:
                failed.append({"run_id": run_id, "error": str(exc)})
            except Exception as exc:
                failed.append({"run_id": run_id, "error": str(exc)})

        return {
            "ok": not failed,
            "deleted": deleted,
            "missing": missing,
            "failed": failed,
        }
