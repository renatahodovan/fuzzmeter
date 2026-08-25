#!/usr/bin/env bash
set -euo pipefail

cd /src/zlib

if ! ./configure; then
    cat configure.log
    exit 1
fi

make -j"$(nproc)" clean
make -j"$(nproc)" all

if [[ "${SANITIZER}" != "memory" ]]; then
    make -j"$(nproc)" check
fi

${CXX} ${CXXFLAGS} -std=c++11 -I. \
    /src/zlib_uncompress_fuzzer.cc -o "${OUT}/${TARGET_NAME}" \
    ${LIB_FUZZING_ENGINE} ./libz.a

zip "${OUT}/${TARGET_NAME}_seed_corpus.zip" *.*
