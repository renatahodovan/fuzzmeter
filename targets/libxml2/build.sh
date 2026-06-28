#!/usr/bin/env bash
set -euo pipefail

cd /src/libxml2
./fuzz/oss-fuzz-build.sh
