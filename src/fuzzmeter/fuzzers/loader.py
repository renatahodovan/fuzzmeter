# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import importlib
import io
import sys
import threading
import types

from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any

from .models import OutputPaths


class FuzzerModule:
    def __init__(self, *, repo_root: Path, fuzzer_name: str, module: ModuleType) -> None:
        self.repo_root = Path(repo_root)
        self.fuzzer_name = str(fuzzer_name)
        self._module = module

    def output_paths(self, live_out: Path) -> OutputPaths:
        getter = getattr(self._module, "get_output_paths", None)
        if not callable(getter):
            return self._default_output_paths(live_out)
        return self._normalize_output_paths(live_out, getter(live_out))

    def output_paths_relative(self) -> OutputPaths:
        live_out = Path("/__fuzzmeter_live_out__")
        resolved = self.output_paths(live_out)
        return OutputPaths(
            corpus_root=self._to_relative_under_root(live_out, resolved.corpus_root),
            crashes_root=self._to_relative_under_root(live_out, resolved.crashes_root),
            hangs_root=None if resolved.hangs_root is None else self._to_relative_under_root(live_out, resolved.hangs_root),
        )

    def stats(self, trial_root: Path, *, cutoff_elapsed_s: int | None = None) -> dict[str, Any]:
        getter_until = getattr(self._module, "get_stats_until", None)
        if callable(getter_until) and cutoff_elapsed_s is not None:
            with io.StringIO() as captured_stdout, redirect_stdout(captured_stdout):
                out = getter_until(trial_root, cutoff_elapsed_s=cutoff_elapsed_s)
            return out if isinstance(out, dict) else {}

        getter = getattr(self._module, "get_stats", None)
        if not callable(getter):
            return {}
        with io.StringIO() as captured_stdout, redirect_stdout(captured_stdout):
            out = getter(trial_root)
        return out if isinstance(out, dict) else {}

    def snapshot_preprocess_script(self) -> Path | None:
        getter = getattr(self._module, 'snapshot_preprocess_script', None)
        if callable(getter):
            # with io.StringIO() as captured_stdout, redirect_stdout(captured_stdout):
            configured = getter()
            if configured is None:
                return None
            configured_path = Path(configured)
            return configured_path if configured_path.is_absolute() else configured_path

        script = self.repo_root / "fuzzers" / self.fuzzer_name / "run" / "snapshot_preprocess.py"
        return script.relative_to(self.repo_root) if script.is_file() else None

    @staticmethod
    def _default_output_paths(live_out: Path) -> OutputPaths:
        return OutputPaths(
            corpus_root=live_out / "corpus",
            crashes_root=live_out / "crashes",
            hangs_root=live_out / "hangs",
        )

    @classmethod
    def _normalize_output_paths(cls, live_out: Path, out: Any) -> OutputPaths:
        def resolve(value: str | Path | None) -> Path | None:
            if value is None:
                return None
            path = Path(value)
            return path if path.is_absolute() else (live_out / path)

        if isinstance(out, OutputPaths):
            return out

        if isinstance(out, dict):
            return OutputPaths(
                corpus_root=resolve(out.get("corpus_root")) or (live_out / "corpus"),
                crashes_root=resolve(out.get("crashes_root")) or (live_out / "crashes"),
                hangs_root=resolve(out.get("hangs_root")),
            )

        if isinstance(out, (tuple, list)) and len(out) in (2, 3):
            return OutputPaths(
                corpus_root=resolve(out[0]) or (live_out / "corpus"),
                crashes_root=resolve(out[1]) or (live_out / "crashes"),
                hangs_root=resolve(out[2]) if len(out) == 3 else None,
            )

        return cls._default_output_paths(live_out)

    @staticmethod
    def _to_relative_under_root(root: Path, path: Path) -> Path:
        try:
            return path.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"Fuzzer output path must stay under {root}: {path}") from exc


class FuzzerLoader:
    _module_cache: dict[str, ModuleType] = {}
    _module_lock = threading.RLock()

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root)

    def load(self, fuzzer_name: str) -> FuzzerModule:
        path = self.repo_root / "fuzzers" / fuzzer_name / "run" / "fuzz.py"
        if not path.exists():
            raise RuntimeError(f"fuzzer run entrypoint not found: {path}")
        module = self._load_module(path=path, module_name=f"fuzzers.{fuzzer_name}.run.fuzz")
        return FuzzerModule(repo_root=self.repo_root, fuzzer_name=fuzzer_name, module=module)

    def _load_module(self, *, path: Path, module_name: str) -> ModuleType:
        with self._module_lock:
            cached = self._module_cache.get(module_name)
            if cached is not None:
                return cached

            repo_root_str = str(self.repo_root)
            if repo_root_str not in sys.path:
                sys.path.insert(0, repo_root_str)
            self._install_fuzzers_utils_stub()

            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                raise RuntimeError(f"Cannot load module: {path}") from exc

            self._module_cache[module_name] = module
            return module

    def _install_fuzzers_utils_stub(self) -> None:
        fuzzers_root = self.repo_root / "fuzzers"
        fuzzers_pkg = sys.modules.get("fuzzers")
        if fuzzers_pkg is None:
            fuzzers_pkg = types.ModuleType("fuzzers")
            sys.modules["fuzzers"] = fuzzers_pkg
        if not hasattr(fuzzers_pkg, "__path__"):
            setattr(fuzzers_pkg, "__path__", [str(fuzzers_root)])

        utils_mod = sys.modules.get("fuzzers.utils")
        if utils_mod is None:
            try:
                utils_mod = importlib.import_module("fuzzers.utils")
            except Exception:
                utils_mod = types.ModuleType("fuzzers.utils")
                utils_mod.append_flags = lambda *args, **kwargs: None
                utils_mod.build_benchmark = lambda *args, **kwargs: None
                utils_mod.initialize_env = lambda *args, **kwargs: None
                utils_mod.get_stats = lambda *args, **kwargs: {}
                sys.modules["fuzzers.utils"] = utils_mod
            setattr(fuzzers_pkg, "utils", utils_mod)
