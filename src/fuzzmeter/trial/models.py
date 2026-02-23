# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from ..fuzzers import OutputPaths


@dataclass(frozen=True)
class TrialImages:
    runner: str
    coverage: str
    asan: str

    @staticmethod
    def for_trial(*, fuzzer_name: str, target_id: str) -> "TrialImages":
        return TrialImages(
            runner=f"fuzzmeter/runner-{fuzzer_name}-{target_id}:dev",
            coverage=TrialImages.coverage_for_target(target_id),
            asan=TrialImages.asan_for_target(target_id),
        )

    @staticmethod
    def coverage_for_target(target_id: str) -> str:
        return f"fuzzmeter/coverage-runner-{target_id}:dev"

    @staticmethod
    def asan_for_target(target_id: str) -> str:
        return f"fuzzmeter/asan-runner-{target_id}:dev"


@dataclass(frozen=True)
class TrialPathConfig:
    live_out_root: Path
    snapshots_root: Path
    logs_root: Path
    fuzzer_log: Path
    output_paths: OutputPaths


@dataclass(frozen=True)
class TrialConfig:
    fuzzer: str
    fuzzer_base: str
    benchmark: str
    fuzz_target: str
    input_mode: str
    rep: int
    trial_key: str
    paths: TrialPathConfig
    time_seconds: int
    snapshot_every_seconds: int
    snapshot_preprocess_script: Optional[Path]
    runner_image: str
    coverage_image: str
    asan_image: str
    replay_trial_path: Optional[Path] = None
    build_config: Dict[str, Any] = field(default_factory=dict)
    runtime_config: Dict[str, Any] = field(default_factory=dict)
    target_timeout_s: float | None = None


@dataclass
class TrialPaths:
    trial_dir: Path
    fuzzer_log: Path
    live_out_root: Path
    corpus_root: Path
    logs_root: Path
    snapshots_root: Path
    target_bin: Path
    crashes_root: Path
    hangs_root: Optional[Path] = None


def resolve_trial_paths(*, trial_dir: Path, cfg: TrialConfig, target_bin: Path) -> TrialPaths:
    live_out_root = trial_dir / cfg.paths.live_out_root
    corpus_root = live_out_root / cfg.paths.output_paths.corpus_root
    crashes_root = live_out_root / cfg.paths.output_paths.crashes_root
    hangs_root = None
    if cfg.paths.output_paths.hangs_root is not None:
        hangs_root = live_out_root / cfg.paths.output_paths.hangs_root

    return TrialPaths(
        trial_dir=trial_dir,
        fuzzer_log=trial_dir / cfg.paths.fuzzer_log,
        live_out_root=live_out_root,
        corpus_root=corpus_root,
        logs_root=trial_dir / cfg.paths.logs_root,
        snapshots_root=trial_dir / cfg.paths.snapshots_root,
        target_bin=target_bin,
        crashes_root=crashes_root,
        hangs_root=hangs_root,
    )


@dataclass(frozen=True)
class ActiveTrial:
    trial_row_id: int
    trial_id: str
    container_name: str
    fuzzer: str
    fuzzer_base: str
    benchmark: str
    fuzz_target: str
    input_mode: str
    rep: int
    runner_image: str
    coverage_image: str
    asan_image: str
    snapshot_preprocess_script: Optional[Path]
    trial_root: Path
    live_out: Path
    fuzzer_log: Path
    corpus_root: Path
    crashes_root: Path
    snapshots_root: Path
    seed_root: Optional[Path]
    repo_root: Path
    started_ts: Optional[int] = None
    replay_start_ts: Optional[int] = None
    replay_end_ts: Optional[int] = None
    target_timeout_s: float | None = None
