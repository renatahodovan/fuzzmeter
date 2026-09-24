# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Load reporting plugin modules from fuzzer directories.'''

from __future__ import annotations

import importlib.util
import logging
import sys

from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Mapping, Sequence

from ...fuzzers.loader import install_fuzzer_namespace
from ..plugin_api import ExtraSection, ReportingContext, ReportingPlugin

LOG = logging.getLogger(__name__)


class NullReportingPlugin:
    '''Represent the absence of a fuzzer reporting plugin.'''

    def build_extra_sections(self, ctx: ReportingContext) -> list[ExtraSection]:
        '''Return no extra sections.'''

        return []


class FunctionReportingPlugin:
    '''Adapt a build_extra_sections function to the plugin protocol.'''

    def __init__(
        self,
        fn: Callable[[ReportingContext], list[ExtraSection]],
        debug_fn: Callable[[ReportingContext], dict[str, Any]] | None = None,
    ) -> None:
        self._fn = fn
        self._debug_fn = debug_fn

    def build_extra_sections(self, ctx: ReportingContext) -> list[ExtraSection]:
        '''Return extra sections built by the wrapped function.'''

        sections = self._fn(ctx)
        return sections if isinstance(sections, list) else []

    def build_debug_info(self, ctx: ReportingContext) -> dict[str, Any]:
        '''Return optional diagnostics supplied beside the function entry point.'''

        return self._debug_fn(ctx) if self._debug_fn is not None else {}


class ReportingPluginLoader:
    '''Load fuzzer-specific reporting plugins from a fuzzer resource root.'''

    def __init__(self, fuzzer_dirs: Mapping[str, Path]) -> None:
        self.fuzzer_dirs = {name: Path(path) for name, path in fuzzer_dirs.items()}
        self.load_errors: list[dict[str, str]] = []

    def load_first(self, fuzzer_names: Sequence[str]) -> tuple[ReportingPlugin, str | None]:
        '''Load the first available reporting plugin from the candidate fuzzer names.'''

        self.load_errors = []
        for fuzzer_name in fuzzer_names:
            if not _is_safe_fuzzer_name(fuzzer_name):
                continue
            path = self.fuzzer_dirs.get(fuzzer_name, Path()) / 'run' / 'reporting.py'
            if not path.is_file():
                continue
            try:
                module = self._load_module(path=path, module_name=f'fuzzers.{fuzzer_name}.run.reporting')
            except Exception as exc:
                LOG.exception('Could not load reporting plugin %s from %s: %s', fuzzer_name, path, exc)
                self.load_errors.append({'plugin': fuzzer_name, 'error': str(exc)})
                continue
            getter = getattr(module, 'get_reporting_plugin', None)
            if callable(getter):
                plugin = getter()
                if hasattr(plugin, 'build_extra_sections'):
                    return plugin, fuzzer_name
            fn = getattr(module, 'build_extra_sections', None)
            if callable(fn):
                debug_fn = getattr(module, 'build_debug_info', None)
                return FunctionReportingPlugin(fn, debug_fn if callable(debug_fn) else None), fuzzer_name
        return NullReportingPlugin(), None

    def _load_module(self, *, path: Path, module_name: str) -> ModuleType:
        install_fuzzer_namespace(self.fuzzer_dirs)
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f'Cannot load module: {path}')
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        return module


def _is_safe_fuzzer_name(fuzzer_name: str) -> bool:
    text = str(fuzzer_name or '').strip()
    if not text:
        return False
    path = Path(text)
    return not path.is_absolute() and len(path.parts) == 1 and path.parts[0] != '..'
