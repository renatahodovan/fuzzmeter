'''Load flat container entrypoint modules from their shipped source directory.'''

from __future__ import annotations

import importlib
import sys

from pathlib import Path
from types import ModuleType


ENTRYPOINTS_DIR = (
    Path(__file__).resolve().parents[2]
    / 'src'
    / 'fuzzmeter'
    / 'resources'
    / 'entrypoints'
)


def load_entrypoint(module_name: str) -> ModuleType:
    '''Import a flat module with the same path semantics as the container.'''
    if str(ENTRYPOINTS_DIR) not in sys.path:
        sys.path.insert(0, str(ENTRYPOINTS_DIR))
    return importlib.import_module(module_name)
