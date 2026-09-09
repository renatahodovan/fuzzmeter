#!/usr/bin/env bash
set -euo pipefail

export SANITIZER="${SANITIZER:-address}"
export ARCHITECTURE="${ARCHITECTURE:-$(uname -m)}"

cd /src/libxml2
./fuzz/oss-fuzz-build.sh
