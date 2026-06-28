#!/usr/bin/env bash
set -euo pipefail

export CMAKE_FUZZING_ENGINE="${LIB_FUZZING_ENGINE}"

cd /src/freetype2-testing

bash "fuzzing/scripts/build-fuzzers.sh"
bash "fuzzing/scripts/prepare-oss-fuzz.sh"

for f in "${OUT}/legacy"*; do
    mv "${f}" "${f/legacy/ftfuzzer}"
done

zip -ju "${OUT}/ftfuzzer_seed_corpus.zip" "/src/font-corpus/"*
