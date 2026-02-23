# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

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
) -> None:
    if total <= 0:
        return
    progress_enabled = LOG.level >= 20 and not getattr(sys.stderr, 'closed', True)
    progress_context = (
        tqdm(total=total, desc=desc, unit='job', position=position, leave=leave, dynamic_ncols=True)
        if progress_enabled
        else nullcontext()
    )
    with progress_context as progress:
        with cf.ThreadPoolExecutor(max_workers=jobs) as executor:
            for future in cf.as_completed(submit_jobs(executor)):
                future.result()
                if progress is not None:
                    try:
                        progress.update(1)
                    except (OSError, ValueError):
                        progress = None
