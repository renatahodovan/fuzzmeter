# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import importlib.util
import sys

from pathlib import Path
from types import ModuleType
from typing import Callable, Sequence

from ..plugin_api import ExtraSection, ReportingContext, ReportingPlugin


class NullReportingPlugin:
    '''Represent the absence of a fuzzer reporting plugin.'''

    def build_extra_sections(self, ctx: ReportingContext) -> list[ExtraSection]:
        '''Return no extra sections.'''

        return []


class FunctionReportingPlugin:
    '''Adapt a build_extra_sections function to the plugin protocol.'''

    def __init__(self, fn: Callable[[ReportingContext], list[ExtraSection]]) -> None:
        self._fn = fn

    def build_extra_sections(self, ctx: ReportingContext) -> list[ExtraSection]:
        '''Return extra sections built by the wrapped function.'''

        sections = self._fn(ctx)
        return sections if isinstance(sections, list) else []


class ReportingPluginLoader:
    '''Load fuzzer-specific reporting plugins from the repository.'''

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root)

    def load(self, fuzzer_name: str) -> ReportingPlugin:
        '''Load a reporting plugin for one fuzzer.'''

        plugin, _ = self.load_first([fuzzer_name])
        return plugin

    def load_first(self, fuzzer_names: Sequence[str]) -> tuple[ReportingPlugin, str | None]:
        '''Load the first available reporting plugin from the candidate fuzzer names.'''

        for fuzzer_name in fuzzer_names:
            if not fuzzer_name:
                continue
            path = self.repo_root / 'fuzzers' / fuzzer_name / 'run' / 'reporting.py'
            if not path.is_file():
                continue
            module = self._load_module(path=path, module_name=f'fuzzers.{fuzzer_name}.run.reporting')
            getter = getattr(module, 'get_reporting_plugin', None)
            if callable(getter):
                plugin = getter()
                if hasattr(plugin, 'build_extra_sections'):
                    return plugin, fuzzer_name
            fn = getattr(module, 'build_extra_sections', None)
            if callable(fn):
                return FunctionReportingPlugin(fn), fuzzer_name
        return NullReportingPlugin(), None

    def _load_module(self, *, path: Path, module_name: str) -> ModuleType:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f'Cannot load module: {path}')
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        return module
