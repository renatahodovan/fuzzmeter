# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import logging
import os
import shutil
import zipfile

from dataclasses import dataclass
from pathlib import Path

from ..docker import DockerClient
from .models import TrialConfig, TrialPaths, resolve_trial_paths

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedTrialWorkspace:
    '''Describe the host workspace prepared for a trial.'''

    paths: TrialPaths
    seed_root: Path | None
    input_seed_root: Path


class TrialWorkspacePreparer:
    '''Prepare host-side trial directories and seed corpora.'''

    def __init__(self, *, target_bin_host_path: Path) -> None:
        self.target_bin_host_path = Path(target_bin_host_path)

    def prepare(self, *, run_dir: Path, cfg: TrialConfig) -> PreparedTrialWorkspace:
        '''Prepare trial directories and resolve the seed corpus root.'''
        paths = self._prepare_paths(run_dir=run_dir, cfg=cfg)
        self._validate_target_bin()
        seed_root = self.resolve_seed_root(run_dir=run_dir, cfg=cfg)
        return PreparedTrialWorkspace(
            paths=paths,
            seed_root=seed_root,
            input_seed_root=seed_root or self._prepare_empty_seed_root(run_dir=run_dir, cfg=cfg),
        )

    def _prepare_paths(self, *, run_dir: Path, cfg: TrialConfig) -> TrialPaths:
        paths = resolve_trial_paths(
            trial_dir=run_dir / 'trials' / cfg.trial_key,
            cfg=cfg,
            target_bin=self.target_bin_host_path,
        )
        for path in [
            paths.trial_dir,
            paths.live_out_root,
            paths.corpus_root,
            paths.crashes_root,
            paths.snapshots_root,
            paths.logs_root,
        ]:
            path.mkdir(parents=True, exist_ok=True)
        if paths.hangs_root is not None:
            paths.hangs_root.mkdir(parents=True, exist_ok=True)
        paths.fuzzer_log.write_text('', encoding='utf-8')
        return paths

    def _validate_target_bin(self) -> None:
        if not self.target_bin_host_path.is_file():
            raise RuntimeError(f'Target binary path is not a file: {self.target_bin_host_path}')

    @staticmethod
    def resolve_seed_root(*, run_dir: Path, cfg: TrialConfig) -> Path | None:
        '''Return the prepared seed corpus root for a trial, if any.'''
        seeds_out = run_dir / 'seed_corpora'
        seed_key = f'{cfg.fuzzer}__{cfg.benchmark}__{cfg.fuzz_target}'.replace('/', '_').replace(':', '_')
        extract_dir = seeds_out / seed_key / 'corpus'
        if extract_dir.exists() and any(extract_dir.iterdir()):
            return extract_dir
        return None

    @staticmethod
    def _prepare_empty_seed_root(*, run_dir: Path, cfg: TrialConfig) -> Path:
        empty_root = run_dir / 'seed_corpora' / '_empty' / cfg.trial_key.replace('/', '_').replace(':', '_') / 'corpus'
        empty_root.mkdir(parents=True, exist_ok=True)
        return empty_root

    @staticmethod
    def extract_seed_corpus_from_image(
        *,
        image: str,
        fuzzer: str,
        benchmark: str,
        fuzz_target: str,
        out_dir: Path,
    ) -> Path | None:
        '''Extract a seed corpus zip from a runner image, if present.'''
        docker = DockerClient()
        seed_key = f'{fuzzer}__{benchmark}__{fuzz_target}'.replace('/', '_').replace(':', '_')
        seed_root = out_dir / seed_key
        zip_name = f'{fuzz_target}_seed_corpus.zip'
        tmp_root = seed_root.with_suffix('.tmp')
        tmp_extract_dir = tmp_root / 'corpus'
        tmp_extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            docker.copy_from_image(
                image=image,
                src_path=f'/out/{zip_name}',
                dst_path=tmp_root / zip_name,
            )
        except RuntimeError as exc:
            shutil.rmtree(tmp_root, ignore_errors=True)
            if 'is missing' in str(exc):
                LOG.info('No seed corpus zip found in %s for %s/%s/%s', image, fuzzer, benchmark, fuzz_target)
                return None
            raise

        with zipfile.ZipFile(tmp_root / zip_name, 'r') as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue

                out_path = (tmp_extract_dir / info.filename).resolve()
                if not str(out_path).startswith(str(tmp_extract_dir.resolve())):
                    LOG.warning('Skipping unsafe path: %s', info.filename)
                    continue

                out_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, open(out_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)

        shutil.rmtree(seed_root, ignore_errors=True)
        seed_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_root, seed_root)

        extract_dir = seed_root / 'corpus'
        if extract_dir.exists() and any(extract_dir.iterdir()):
            return extract_dir
        LOG.warning('Extracted seed corpus is empty in %s', extract_dir)
        return None
