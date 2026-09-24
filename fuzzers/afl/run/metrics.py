'''Collect AFL-specific metrics from snapshot corpus file names.'''

from __future__ import annotations

import re

from pathlib import Path

_MUTATOR_RE = re.compile(r'(?:^|,)execs:\d+,(?:op:)?([^,]+)')


def get_custom_metrics(
    trial_root: Path,
    *,
    snapshot_dir: Path,
    cutoff_elapsed_s: int | None = None,
) -> dict | None:
    '''Return AFL custom mutator counts encoded in snapshot corpus names.'''

    del trial_root, cutoff_elapsed_s
    counts: dict[str, int] = {}
    corpus_dir = Path(snapshot_dir) / 'corpus'
    if not corpus_dir.is_dir():
        return None
    for path in corpus_dir.rglob('*'):
        if not path.is_file():
            continue
        match = _MUTATOR_RE.search(path.name)
        if not match:
            continue
        mutator = match.group(1).strip()
        if not mutator or mutator.startswith('orig:'):
            continue
        counts[mutator] = counts.get(mutator, 0) + 1
    if not counts:
        return None
    return {
        'counts': counts,
    }
