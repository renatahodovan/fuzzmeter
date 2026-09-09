#!/usr/bin/env bash
set -euo pipefail

export SANITIZER="${SANITIZER:-}"
if [[ "${LIB_FUZZING_ENGINE}" == "/opt/fuzzmeter/tools/lib/libFuzzer.a" ]]; then
    export CMAKE_FUZZING_ENGINE="${LIB_FUZZING_ENGINE} -lstdc++"
else
    export CMAKE_FUZZING_ENGINE="${LIB_FUZZING_ENGINE}"
fi

cd /src/freetype2-testing

# libc++abi's compiler-flag probe fails through the AFL++ wrapper although
# its underlying Clang supports this flag.  Enable it only for libc++abi
# targets, avoiding libstdc++ wrapper headers without affecting LLVM setup.
sed -i 's/-DLIBCXXABI_ENABLE_SHARED=OFF/& -DLIBCXXABI_HAS_NOSTDINCXX_FLAG=ON/' fuzzing/scripts/build/libcxx.sh
# The initialized submodule is clean; preserve the libc++ adjustment below
# across the upstream script's otherwise redundant checkout reset.
sed -i '/^[[:space:]]*git reset --hard$/d' fuzzing/scripts/build/libcxx.sh
for submodule in external/zlib external/bzip2 external/libarchive external/brotli \
                 external/libpng external/freetype2 external/llvm-project; do
    for attempt in {1..5}; do
        if git submodule update --init --depth 1 "${submodule}"; then
            break
        fi
        if [[ "${attempt}" == 5 ]]; then
            exit 1
        fi
        sleep $((attempt * 2))
    done
done

# libc++ has a separate capability probe that fails for the same wrapper.
# Clang supports the flag, so add it directly to the libc++ target instead.
sed -i 's/target_add_compile_flags_if_supported(${target} PUBLIC -nostdinc++)/target_compile_options(${target} PUBLIC -nostdinc++)/' external/llvm-project/libcxx/CMakeLists.txt

bash "fuzzing/scripts/build-fuzzers.sh"
bash "fuzzing/scripts/prepare-oss-fuzz.sh"

for f in "${OUT}/legacy"*; do
    mv "${f}" "${f/legacy/ftfuzzer}"
done

zip -ju "${OUT}/ftfuzzer_seed_corpus.zip" "/src/font-corpus/"*
