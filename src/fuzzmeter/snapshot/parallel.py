# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Share small helpers across snapshot collection and processing steps.'''

from __future__ import annotations

import concurrent.futures as cf
import logging
import sys

from contextlib import nullcontext
from typing import Callable

from tqdm import tqdm

LOG = logging.getLogger(__name__)


def run_parallel_jobs(
    *,
    jobs: int,
    total: int,
    desc: str,
    position: int = 0,
    leave: bool = False,
    submit_jobs: Callable[[cf.ThreadPoolExecutor], list[cf.Future[None]]],
    progress_step: Callable[[], None] | None = None,
) -> None:
    '''Run submitted jobs in parallel and update a progress bar when available.'''
    if total <= 0:
        return
    progress_enabled = (
        progress_step is None
        and LOG.isEnabledFor(logging.INFO)
        and sys.stderr is not None
        and not getattr(sys.stderr, 'closed', True)
        and getattr(sys.stderr, 'isatty', lambda: False)()
    )
    progress_context = (
        tqdm(total=total, desc=desc, unit='job', position=position, leave=leave, dynamic_ncols=True)
        if progress_enabled
        else nullcontext()
    )
    with progress_context as progress:
        progress_bar = progress
        with cf.ThreadPoolExecutor(max_workers=jobs) as executor:
            for future in cf.as_completed(submit_jobs(executor)):
                future.result()
                if progress_step is not None:
                    progress_step()
                elif progress_bar is not None:
                    try:
                        progress_bar.update(1)
                    except (OSError, ValueError):
                        progress_bar = None
