# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from pathlib import Path


class FileService:

    @staticmethod
    def resolve_run_dir(runs_root: Path, run_id: str) -> Path:
        root = Path(runs_root).resolve()
        run_dir = (root / run_id).resolve()
        try:
            run_dir.relative_to(root)
        except ValueError:
            raise ValueError("invalid run path")
        return run_dir

    @classmethod
    def resolve_run_file(cls, runs_root: Path, run_id: str, relpath: str) -> Path:
        run_dir = cls.resolve_run_dir(runs_root, run_id)
        rel = Path(relpath)
        if ".." in rel.parts:
            raise ValueError("invalid relative path")

        full = (run_dir / rel).resolve()
        try:
            full.relative_to(run_dir)
        except ValueError:
            raise ValueError("invalid file path")

        if full.is_dir():
            full = (full / "index.html").resolve()
        return full
