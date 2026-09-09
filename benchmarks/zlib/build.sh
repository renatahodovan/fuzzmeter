#!/usr/bin/env bash
set -euo pipefail

export SANITIZER="${SANITIZER:-}"

cd /src/zlib

if ! ./configure; then
    cat configure.log
    exit 1
fi

make -j"${FM_BUILD_JOBS:-$(nproc)}" clean
make -j"${FM_BUILD_JOBS:-$(nproc)}" all

if [[ "${SANITIZER}" != "memory" ]]; then
    make -j"${FM_BUILD_JOBS:-$(nproc)}" check
fi

${CXX} ${CXXFLAGS} -std=c++11 -I. \
    /src/zlib_uncompress_fuzzer.cc -o "${OUT}/${TARGET_NAME}" \
    ${LIB_FUZZING_ENGINE} ./libz.a

zip "${OUT}/${TARGET_NAME}_seed_corpus.zip" *.*
