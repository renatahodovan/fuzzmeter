#!/usr/bin/env bash
set -euo pipefail

cd /src/curl_fuzzer

if [[ -n "${REPLAY_ENABLED:-}" ]]; then
    rm -f /src/curl_fuzzer/build/curl-install/lib/libcurl.a
    pushd /src/curl >/dev/null
    make install
    popd >/dev/null
fi

./ossfuzz.sh
