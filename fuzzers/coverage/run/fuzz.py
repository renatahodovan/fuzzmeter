# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from pathlib import Path
from typing import Any, Dict


def get_output_paths(live_out: Path) -> Dict[str, Any]:
    p = Path(live_out)
    return {
        'corpus_root': p,
        'crashes_root': p / 'crashes',
        'hangs_root': p / 'hangs',
    }
