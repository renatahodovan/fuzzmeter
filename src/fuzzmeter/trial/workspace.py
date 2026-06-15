# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Prepare host-side trial directories and seed corpora.'''

from __future__ import annotations

import logging
import os
import shutil
import zipfile

from pathlib import Path

from ..docker import DockerClient
from .models import TrialConfig, TrialLayout

LOG = logging.getLogger(__name__)


def prepare_live_workspace(*, run_dir: Path, cfg: TrialConfig) -> tuple[TrialLayout, Path]:
    '''Prepare live trial directories and resolve the seed corpus root.'''
    layout = TrialLayout.from_config(trial_dir=run_dir / 'trials' / cfg.trial_key, cfg=cfg)
    for path in (layout.trial_dir, layout.snapshots_dir, layout.logs_dir,
                 layout.fuzz_dir, layout.corpus_dir, layout.crashes_dir):
        path.mkdir(parents=True, exist_ok=True)
    if layout.hangs_dir is not None:
        layout.hangs_dir.mkdir(parents=True, exist_ok=True)

    layout.fuzzer_log.write_text('', encoding='utf-8')
    seed_root = _resolve_seed_root(run_dir=run_dir, cfg=cfg)
    return layout, seed_root or _prepare_empty_seed_root(run_dir=run_dir, cfg=cfg)


def prepare_replay_workspace(*, run_dir: Path, cfg: TrialConfig) -> TrialLayout:
    '''Prepare replay trial directories without creating live output paths.'''
    layout = TrialLayout.from_config(
        trial_dir=run_dir / 'trials' / cfg.trial_key,
        cfg=cfg,
    )
    for path in (layout.trial_dir, layout.snapshots_dir, layout.logs_dir):
        path.mkdir(parents=True, exist_ok=True)
    layout.fuzzer_log.write_text('', encoding='utf-8')
    return layout


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
    seed_root = out_dir / f'{fuzzer}__{benchmark}__{fuzz_target}'
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
            try:
                out_path.relative_to(tmp_extract_dir)
            except ValueError:
                LOG.warning('Skipping unsafe path: %s', info.filename)
                continue

            out_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(out_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)

    shutil.rmtree(seed_root, ignore_errors=True)
    seed_root.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp_root, seed_root)

    extract_dir = seed_root / 'corpus'
    if extract_dir.is_dir() and any(extract_dir.iterdir()):
        return extract_dir
    LOG.warning('Extracted seed corpus is empty in %s', extract_dir)
    return None


def _resolve_seed_root(*, run_dir: Path, cfg: TrialConfig) -> Path | None:
    extract_dir = run_dir / 'seed_corpora' / f'{cfg.fuzzer}__{cfg.benchmark}__{cfg.fuzz_target}' / 'corpus'
    if extract_dir.is_dir() and any(extract_dir.iterdir()):
        return extract_dir
    return None


def _prepare_empty_seed_root(*, run_dir: Path, cfg: TrialConfig) -> Path:
    empty_root = run_dir / 'seed_corpora' / '_empty' / cfg.trial_key / 'corpus'
    empty_root.mkdir(parents=True, exist_ok=True)
    return empty_root
