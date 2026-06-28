# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Resolve user-provided resource roots and packaged engine resources.'''

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExternalRoots:
    '''Hold validated user-provided fuzzer and target resource roots.'''

    fuzzers_root: Path
    targets_root: Path

    @classmethod
    def from_paths(cls, *, fuzzers_root: Path, targets_root: Path) -> 'ExternalRoots':
        '''Create roots from explicit paths without checking their contents.'''

        return cls(
            fuzzers_root=Path(fuzzers_root).expanduser().resolve(),
            targets_root=Path(targets_root).expanduser().resolve(),
        )

    @classmethod
    def from_checkout(cls, checkout_root: Path) -> 'ExternalRoots':
        '''Create roots from a development checkout layout.'''

        root = Path(checkout_root).expanduser().resolve()
        return cls.from_paths(fuzzers_root=root / 'fuzzers', targets_root=root / 'targets')


def docker_resources() -> Any:
    '''Return the packaged Docker resource directory.'''

    return resources.files('fuzzmeter').joinpath('resources', 'docker')


def entrypoint_resources() -> Any:
    '''Return the packaged container entrypoint resource directory.'''

    return resources.files('fuzzmeter').joinpath('resources', 'entrypoints')


def instrumentation_resources() -> Any:
    '''Return the packaged instrumentation resource directory.'''

    return resources.files('fuzzmeter').joinpath('resources', 'instrumentation')
