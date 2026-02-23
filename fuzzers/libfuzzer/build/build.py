import os
import re

from fuzzers import utils


def build():
    """Build benchmark."""
    # With LibFuzzer we use -fsanitize=fuzzer-no-link for build CFLAGS and then
    # /usr/lib/libFuzzer.a as the FUZZER_LIB for the main fuzzing binary. This
    # allows us to link against a version of LibFuzzer that we specify.
    cflags = ['-fsanitize=fuzzer-no-link']
    utils.append_flags('CFLAGS', cflags)
    utils.append_flags('CXXFLAGS', cflags)

    os.environ['CC'] = '/usr/bin/clang-18'
    os.environ['CXX'] = '/usr/bin/clang++-18'
    os.environ['FUZZER_LIB'] = '/opt/fuzzmeter/tools/lib/libFuzzer.a'
    utils.apply_configured_env(utils.get_build_env())

    utils.build_benchmark()


# #73348: cov: 44138 ft: 40833 corp: 1553 exec/s: 2237 oom/timeout/crash: 0/0/1 time: 52s job: 8 dft_time: 0
_LIBFUZZER_DONE = re.compile(
    r"^#(?P<execs_done>\d+):.*?exec/s:\s+(?P<execs_per_sec>[0-9.]+).*?time:\s+(?P<time_s>\d+)s",
    re.IGNORECASE | re.MULTILINE,
)
