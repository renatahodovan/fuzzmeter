# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Define normalized campaign configuration models."""

from __future__ import annotations

import json
import os

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from .benchmark_dockerfile import benchmark_workdir

RUN_CONFIG_FILE = 'benchmark_config.json'
RUN_CONFIG_VERSION = 1


@dataclass
class Fuzzer:
    id: str
    name: str
    src_dir: Path

    parent: Fuzzer | None = None
    allowed_fuzz_targets: tuple[str, ...] | None = None
    source_dependencies: list[Fuzzer] = field(default_factory=list)
    reporting_parents: list[Fuzzer] = field(default_factory=list)
    local_repo_env: str | None = None

    build_config: dict[str, Any] = field(default_factory=dict)
    run_config: dict[str, Any] = field(default_factory=dict)

    @cached_property
    def runner_image(self) -> str | None:
        """Return this fuzzer's own runner image target, when it defines a run Dockerfile."""
        return f'fuzzer_runner_{self.name}' if (self.src_dir / 'run' / 'Dockerfile').is_file() else None

    @cached_property
    def reporting_candidates(self) -> tuple[str, ...]:
        """Return the fuzzer names a report should look for reporting plugins in."""
        names: list[str] = []

        def add(name: str, fuzzer: Fuzzer) -> None:
            if name in names:
                return
            names.append(name)
            for reporting_parent in fuzzer.reporting_parents:
                add(reporting_parent.name, reporting_parent)
            if fuzzer.parent:
                add(fuzzer.parent.name, fuzzer.parent)

        add(self.id, self)
        return tuple(names)

    @cached_property
    def local_repo(self) -> Path | None:
        """Return the host-side source checkout this fuzzer is configured to build from."""
        raw_path = os.environ.get(self.local_repo_env, '').strip() if self.local_repo_env else ''
        if not raw_path:
            return None
        path = Path(raw_path).expanduser().resolve()
        if not path.is_dir():
            raise NotADirectoryError(
                f'Local fuzzer repository from {self.local_repo_env} is not a directory: {path}'
            )
        return path

    @property
    def parents(self) -> list[Fuzzer]:
        parent_list = []
        p = self.parent
        while p:
            parent_list.append(p)
            p = p.parent
        return parent_list

    @property
    def dependencies(self) -> list[Fuzzer]:
        """Return the ordered fuzzer closure needed to build this fuzzer."""
        return self._closure(reporting=False)

    @property
    def resources(self) -> list[Fuzzer]:
        """Return the fuzzer closure whose directories a run must be able to read."""
        return self._closure(reporting=True)

    def _closure(self, *, reporting: bool) -> list[Fuzzer]:
        result: list[Fuzzer] = []
        seen: set[str] = set()

        def add(item: Fuzzer) -> None:
            if item.parent:
                add(item.parent)
            if item.name in seen:
                return
            seen.add(item.name)
            result.append(item)
            for dependency in (*item.source_dependencies, *(item.reporting_parents if reporting else ())):
                add(dependency)

        add(self)
        return result


@dataclass(frozen=True)
class Benchmark:
    """Describe one benchmark project shared by all of its fuzz targets."""

    name: str
    src_dir: Path
    config_path: Path

    @cached_property
    def workdir(self) -> str:
        """Return the working directory the benchmark Dockerfile ends in."""
        return benchmark_workdir(self.src_dir)


@dataclass
class FuzzTarget:
    """Describe one fuzz target of a benchmark."""

    benchmark: Benchmark
    fuzz_target: str
    input_mode: str
    fuzzer_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    target_timeout_s: float = 1.0
    build_compile_jobs: int | None = None

    @property
    def ident(self) -> str:
        return f'{self.benchmark.name}-{self.fuzz_target}'

    @property
    def spec(self) -> str:
        """Return the user-facing campaign configuration identifier."""
        return f'{self.benchmark.name}:{self.fuzz_target}'


def seed_dir_name(fuzzer: str, benchmark: str, fuzz_target: str) -> str:
    '''Return the shared seed corpus directory name of a fuzzer/fuzz-target pair.'''
    return f'{fuzzer}__{benchmark}__{fuzz_target}'


class TrialImages:
    '''Build docker image names for one fuzzer and target pair.'''

    def __init__(self, *, fuzzer_name: str, target_key: str) -> None:
        self.runner = f'fuzzmeter/runner-{fuzzer_name}-{target_key}:dev'
        self.coverage = f'fuzzmeter/coverage-runner-{target_key}:dev'
        self.asan = f'fuzzmeter/asan-runner-{target_key}:dev'


@dataclass(frozen=True)
class CampaignCase:
    '''Describe one fuzzer/fuzz-target combination in a campaign.'''
    fuzzer: Fuzzer
    fuzz_target: FuzzTarget

    build_config: dict[str, Any] = field(default_factory=dict)
    run_config: dict[str, Any] = field(default_factory=dict)

    replay_trials: tuple[Path, ...] = ()

    @cached_property
    def images(self) -> TrialImages:
        '''Return the docker image names built and run for this case.'''
        return TrialImages(fuzzer_name=self.fuzzer.id, target_key=self.fuzz_target.ident)

    @property
    def seed_dir_name(self) -> str:
        '''Return the shared seed corpus directory name of this case.'''
        return seed_dir_name(self.fuzzer.id, self.fuzz_target.benchmark.name, self.fuzz_target.fuzz_target)


@dataclass(frozen=True)
class CampaignSettings:
    '''Describe campaign-level runtime settings.'''

    time_seconds: int = 3600
    repetitions: int = 1
    build_jobs: int = 1
    build_compile_jobs: int = 1
    parallel_jobs: int = os.cpu_count() or 2
    snapshot_jobs: int = 1
    snapshot_every_seconds: int = 900
    snapshot_export_every_ticks: int = 1
    memory: str | None = None
    memory_swap: str | None = None


@dataclass(frozen=True)
class CampaignConfig:
    '''Describe the full fuzzing campaign loaded from YAML.'''

    settings: CampaignSettings
    cases: list[CampaignCase]

    @property
    def fuzzer_dirs(self) -> dict[str, Path]:
        dir_list: dict[str, Path] = {}
        for case in self.cases:
            for fuzzer in case.fuzzer.resources:
                dir_list[fuzzer.name] = fuzzer.src_dir
        return dir_list

    def write_run_config(self, run_dir: Path) -> None:
        """Store what a later, standalone report run cannot resolve on its own."""
        fuzzers = {
            case.fuzzer.id: {
                'base': case.fuzzer.parent.name if case.fuzzer.parent else case.fuzzer.id,
                'reporting_candidates': list(case.fuzzer.reporting_candidates),
            }
            for case in self.cases
        }
        (Path(run_dir) / RUN_CONFIG_FILE).write_text(
            json.dumps({'version': RUN_CONFIG_VERSION, 'fuzzers': fuzzers}, indent=2, sort_keys=True),
            encoding='utf-8',
        )


def read_run_config(run_dir: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Return the reporting plugin candidates and base fuzzer of each measured fuzzer."""
    try:
        data = json.loads((Path(run_dir) / RUN_CONFIG_FILE).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, {}
    if not isinstance(data, dict) or data.get('version') != RUN_CONFIG_VERSION:
        return {}, {}
    candidates: dict[str, list[str]] = {}
    bases: dict[str, str] = {}
    for fuzzer, entry in (data.get('fuzzers') or {}).items():
        if not isinstance(entry, dict):
            continue
        candidates[str(fuzzer)] = [str(name) for name in entry.get('reporting_candidates') or []]
        if entry.get('base'):
            bases[str(fuzzer)] = str(entry['base'])
    return candidates, bases
