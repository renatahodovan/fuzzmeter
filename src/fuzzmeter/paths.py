# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Access packaged engine resources.'''

from __future__ import annotations

from importlib import resources
from typing import Any


def docker_resources() -> Any:
    '''Return the packaged Docker resource directory.'''

    return resources.files('fuzzmeter').joinpath('resources', 'docker')


def entrypoint_resources() -> Any:
    '''Return the packaged container entrypoint resource directory.'''

    return resources.files('fuzzmeter').joinpath('resources', 'entrypoints')


def instrumentation_resources() -> Any:
    '''Return the packaged instrumentation resource directory.'''

    return resources.files('fuzzmeter').joinpath('resources', 'instrumentation')
