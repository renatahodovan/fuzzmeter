#!/usr/bin/env bash
set -euo pipefail

cd /src/curl_fuzzer

build_jobs="${FM_BUILD_JOBS:-$(nproc)}"
export CMAKE_BUILD_PARALLEL_LEVEL="${build_jobs}"
# curl-fuzzer appends `nproc` to MAKEFLAGS for its nested dependency builds.
sed -i "s/\\\$(nproc)/${build_jobs}/g" scripts/compile_target.sh

if [[ -n "${REPLAY_ENABLED:-}" ]]; then
    rm -f /src/curl_fuzzer/build/curl-install/lib/libcurl.a
    pushd /src/curl >/dev/null
    make install
    popd >/dev/null
fi

./ossfuzz.sh
