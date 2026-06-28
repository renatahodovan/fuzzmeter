#!/usr/bin/env bash
set -euo pipefail

export CFLAGS="${CFLAGS} -fno-sanitize=vptr -DHB_NO_VISIBILITY"
export CXXFLAGS="${CXXFLAGS} -fno-sanitize=vptr -DHB_NO_VISIBILITY"

build="${WORK}/build"
rm -rf "${build}"
mkdir -p "${build}"

meson --default-library=static --prefer-static --wrap-mode=nodownload \
      -Dexperimental_api=true \
      -Dfuzzer_ldflags="$(echo "${LIB_FUZZING_ENGINE}")" \
      "${build}" \
  || (cat build/meson-logs/meson-log.txt && false)

ninja -v -j"$(nproc)" -C "${build}" test/fuzzing/hb-{shape,raster,vector,gpu,subset,repacker}-fuzzer
mv "${build}"/test/fuzzing/hb-{shape,raster,vector,gpu,subset,repacker}-fuzzer "${OUT}/"

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

zip "${OUT}/hb-shape-fuzzer_seed_corpus.zip" all-fonts/*
cp "${OUT}/hb-shape-fuzzer_seed_corpus.zip" "${OUT}/hb-raster-fuzzer_seed_corpus.zip"
cp "${OUT}/hb-shape-fuzzer_seed_corpus.zip" "${OUT}/hb-vector-fuzzer_seed_corpus.zip"
cp "${OUT}/hb-shape-fuzzer_seed_corpus.zip" "${OUT}/hb-gpu-fuzzer_seed_corpus.zip"
cp "${OUT}/hb-shape-fuzzer_seed_corpus.zip" "${OUT}/hb-subset-fuzzer_seed_corpus.zip"
zip "${OUT}/hb-repacker-fuzzer_seed_corpus.zip" ./test/fuzzing/graphs/*
