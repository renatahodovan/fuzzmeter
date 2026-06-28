#!/usr/bin/env bash
set -euo pipefail

: "${OUT:?OUT must be set}"
: "${TARGET_NAME:?TARGET_NAME must be set}"

cd /src/quickjs

# Makefile should not override externally provided compiler flags.
sed -i -e 's/CFLAGS=/CFLAGS+=/' Makefile
sed -i -e 's/#define USE_WORKER/\\/\\/#define USE_WORKER/' quickjs-libc.c
CONFIG_CLANG=y make libquickjs.fuzz.a .obj/fuzz_common.o .obj/libregexp.fuzz.o .obj/cutils.fuzz.o .obj/libunicode.fuzz.o

zip -r "${OUT}/fuzz_eval_seed_corpus.zip" /src/quickjs-corpus/js/*.js
zip -r "${OUT}/fuzz_compile_seed_corpus.zip" /src/quickjs-corpus/js/*.js

build_fuzz_target() {
    local target="$1"
    shift
    $CC $CFLAGS -I. -c "fuzz/${target}.c" -o "${target}.o"
    $CXX $CXXFLAGS "${target}.o" -o "${OUT}/${target}" "$@" "${LIB_FUZZING_ENGINE}"
}

case "${TARGET_NAME}" in
    fuzz_eval)
        build_fuzz_target fuzz_eval .obj/fuzz_common.o libquickjs.fuzz.a
        cp fuzz/fuzz.dict "${OUT}/fuzz_eval.dict"
        ;;
    fuzz_compile)
        build_fuzz_target fuzz_compile .obj/fuzz_common.o libquickjs.fuzz.a
        cp fuzz/fuzz.dict "${OUT}/fuzz_compile.dict"
        ;;
    fuzz_regexp)
        build_fuzz_target fuzz_regexp .obj/libregexp.fuzz.o .obj/cutils.fuzz.o .obj/libunicode.fuzz.o
        ;;
    *)
        printf 'Unsupported QuickJS fuzz target: %s\n' "${TARGET_NAME}" >&2
        exit 1
        ;;
esac
