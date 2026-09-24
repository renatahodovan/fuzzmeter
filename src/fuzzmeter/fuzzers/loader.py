# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Load and normalize external fuzzer adapter modules."""

from __future__ import annotations

import importlib.util
import io
import sys
import threading

from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar, Mapping

from .models import OutputPaths


def install_fuzzer_namespace(fuzzer_dirs: Mapping[str, Path]) -> None:
    '''Expose configured fuzzer roots through the synthetic ``fuzzers`` package.'''

    roots = [str(Path(path).parent) for path in fuzzer_dirs.values()]
    package = sys.modules.get('fuzzers')
    if package is None:
        package = ModuleType('fuzzers')
        package.__path__ = roots  # type: ignore[attr-defined]
        sys.modules['fuzzers'] = package
        return

    if set(getattr(package, '__path__', [])) != set(roots):
        for module_name in [name for name in sys.modules if name.startswith('fuzzers.')]:
            del sys.modules[module_name]
    package.__path__ = roots  # type: ignore[attr-defined]


class FuzzerModule:
    def __init__(self, *, fuzzer_dir: Path, module: ModuleType) -> None:
        self.fuzzer_dir = Path(fuzzer_dir)
        self._module = module

    def output_paths(self, live_out: Path) -> OutputPaths:
        getter = getattr(self._module, 'get_output_paths', None)
        if not callable(getter):
            return self._default_output_paths(live_out)
        return self._normalize_output_paths(live_out, getter(live_out))

    def output_paths_relative(self) -> OutputPaths:
        live_out = Path('/__fuzzmeter_live_out__')
        resolved = self.output_paths(live_out)
        return OutputPaths(
            corpus_root=self._to_relative_under_root(live_out, resolved.corpus_root),
            crashes_root=self._to_relative_under_root(live_out, resolved.crashes_root),
            hangs_root=(
                None
                if resolved.hangs_root is None
                else self._to_relative_under_root(live_out, resolved.hangs_root)
            ),
        )

    def stats(self, trial_root: Path, *, cutoff_elapsed_s: int | None = None) -> dict[str, Any]:
        getter_until = getattr(self._module, 'get_stats_until', None)
        if callable(getter_until) and cutoff_elapsed_s is not None:
            with io.StringIO() as captured_stdout, redirect_stdout(captured_stdout):
                out = getter_until(trial_root, cutoff_elapsed_s=cutoff_elapsed_s)
            return out if isinstance(out, dict) else {}

        getter = getattr(self._module, 'get_stats', None)
        if not callable(getter):
            return {}
        with io.StringIO() as captured_stdout, redirect_stdout(captured_stdout):
            out = getter(trial_root)
        return out if isinstance(out, dict) else {}

    def custom_metrics(
        self,
        trial_root: Path,
        *,
        snapshot_dir: Path,
        cutoff_elapsed_s: int | None = None,
    ) -> list[dict[str, Any]]:
        '''Return snapshot-time custom metrics provided by the fuzzer adapter.'''

        getter = getattr(self._module, 'get_custom_metrics', None)
        if not callable(getter):
            return []
        with io.StringIO() as captured_stdout, redirect_stdout(captured_stdout):
            out = getter(trial_root, snapshot_dir=snapshot_dir, cutoff_elapsed_s=cutoff_elapsed_s)
        if isinstance(out, list):
            return [item for item in out if isinstance(item, dict)]
        if isinstance(out, dict):
            return [out]
        return []

    def snapshot_preprocess_script(self) -> Path | None:
        getter = getattr(self._module, 'snapshot_preprocess_script', None)
        if callable(getter):
            configured = getter()
            if configured is None:
                return None
            path = Path(configured)
            return path if path.is_absolute() else self.fuzzer_dir / path

        script = self.fuzzer_dir / 'run' / 'snapshot_preprocess.py'
        return script if script.is_file() else None

    @staticmethod
    def _default_output_paths(live_out: Path) -> OutputPaths:
        return OutputPaths(
            corpus_root=live_out / 'corpus',
            crashes_root=live_out / 'crashes',
            hangs_root=live_out / 'hangs',
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
                corpus_root=resolve(out.get('corpus_root')) or (live_out / 'corpus'),
                crashes_root=resolve(out.get('crashes_root')) or (live_out / 'crashes'),
                hangs_root=resolve(out.get('hangs_root')),
            )

        if isinstance(out, (tuple, list)) and len(out) in (2, 3):
            return OutputPaths(
                corpus_root=resolve(out[0]) or (live_out / 'corpus'),
                crashes_root=resolve(out[1]) or (live_out / 'crashes'),
                hangs_root=resolve(out[2]) if len(out) == 3 else None,
            )

        return cls._default_output_paths(live_out)

    @staticmethod
    def _to_relative_under_root(root: Path, path: Path) -> Path:
        try:
            return path.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f'Fuzzer output path must stay under {root}: {path}') from exc


class FuzzerLoader:
    _module_cache: ClassVar[dict[str, ModuleType]] = {}
    _module_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, fuzzer_dirs: Mapping[str, Path]) -> None:
        self.fuzzer_dirs = {name: Path(path) for name, path in fuzzer_dirs.items()}

    def load(self, fuzzer_name: str) -> FuzzerModule:
        try:
            fuzzer_dir = self.fuzzer_dirs[fuzzer_name]
        except KeyError as exc:
            raise RuntimeError(f'Fuzzer is not configured: {fuzzer_name}') from exc
        path = fuzzer_dir / 'run' / 'fuzz.py'
        if not path.exists():
            raise RuntimeError(f'fuzzer run entrypoint not found: {path}')
        module = self._load_module(path=path, module_name=f'fuzzmeter_user_fuzzers.{fuzzer_name}.run.fuzz')
        return FuzzerModule(fuzzer_dir=fuzzer_dir, module=module)

    def _load_module(self, *, path: Path, module_name: str) -> ModuleType:
        with self._module_lock:
            cache_key = f'{module_name}:{path.resolve()}'
            cached = self._module_cache.get(cache_key)
            if cached is not None:
                return cached

            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f'Cannot load module: {path}')

            try:
                install_fuzzer_namespace(self.fuzzer_dirs)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as exc:
                raise RuntimeError(f'Cannot load module: {path}') from exc

            self._module_cache[cache_key] = module
            return module
