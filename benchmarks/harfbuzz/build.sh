#!/usr/bin/env bash
set -euo pipefail

export CFLAGS="${CFLAGS} -fno-sanitize=vptr -DHB_NO_VISIBILITY"
export CXXFLAGS="${CXXFLAGS} -fno-sanitize=vptr -DHB_NO_VISIBILITY"

build="${WORK}/build"
build_jobs="${FM_BUILD_JOBS:-$(nproc)}"
rm -rf "${build}"
mkdir -p "${build}"

meson --default-library=static --prefer-static --wrap-mode=nodownload \
      -Dexperimental_api=true \
      -Dfuzzer_ldflags="$(echo "${LIB_FUZZING_ENGINE}")" \
      "${build}" \
  || (cat build/meson-logs/meson-log.txt && false)

ninja -v -j"${build_jobs}" -C "${build}" "test/fuzzing/${TARGET_NAME:?TARGET_NAME must be set}"
mv "${build}/test/fuzzing/${TARGET_NAME}" "${OUT}/"

if [[ "${TARGET_NAME}" == hb-repacker-fuzzer ]]; then
    zip "${OUT}/${TARGET_NAME}_seed_corpus.zip" ./test/fuzzing/graphs/*
else
    mkdir -p all-fonts
    for d in \
        test/shape/data/in-house/fonts \
        test/shape/data/aots/fonts \
        test/shape/data/text-rendering-tests/fonts \
        test/api/fonts \
        test/fuzzing/fonts \
        perf/fonts
    do
        cp "${d}"/* all-fonts/
    done
    zip "${OUT}/${TARGET_NAME}_seed_corpus.zip" all-fonts/*
fi
