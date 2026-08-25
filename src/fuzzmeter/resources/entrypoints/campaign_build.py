# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Campaign build entrypoint with shared environment initialization.'''

import importlib
import os

from fuzzmeter.resources.instrumentation import utils


def initialize_env(env: dict[str, str] | None = None) -> None:
    '''Set initial build flags before fuzzer build hooks run.'''
    if env is None:
        env = os.environ

    env['FUZZ_TARGET'] = utils.get_active_fuzz_target_name(env)
    env['CFLAGS'] = ''
    env['CXXFLAGS'] = ''
    utils.append_flags(
        'CFLAGS',
        utils.FUZZING_CFLAGS + utils.NO_SANITIZER_COMPAT_CFLAGS + [utils.DEFAULT_OPTIMIZATION_LEVEL],
        env=env,
    )
    utils.append_flags(
        'CXXFLAGS',
        utils.FUZZING_CFLAGS
        + utils.NO_SANITIZER_COMPAT_CFLAGS
        + [utils.DEFAULT_OPTIMIZATION_LEVEL],
        env=env,
    )

    for env_var in ('FUZZ_TARGET', 'CFLAGS', 'CXXFLAGS'):
        print(f'{env_var} = {env.get(env_var)}')


def main() -> None:
    '''Dispatch the fuzzer-specific build with benchmark metadata loaded.'''
    fuzzer = os.environ['FUZZER']
    initialize_env()
    mod = importlib.import_module(f'fuzzers.{fuzzer}.build.build')
    mod.build()


if __name__ == '__main__':
    main()
