#!/usr/bin/env bash
set -euo pipefail

CXXFLAGS="${CXXFLAGS} -O2"

cd /src/abseil-cpp
mkdir build && cd build
cmake -DCMAKE_POSITION_INDEPENDENT_CODE=ON ..
make -j"${FM_BUILD_JOBS:-$(nproc)}"
make install
ldconfig

cd /src/re2
make -j"${FM_BUILD_JOBS:-$(nproc)}" obj/libre2.a
make common-install

${CXX} ${CXXFLAGS} -I. \
    re2/fuzzing/re2_fuzzer.cc -o "${OUT}/re2_fuzzer" \
    ${LIB_FUZZING_ENGINE} obj/libre2.a \
    $(pkg-config re2 --libs | sed -e 's/-lre2//')
