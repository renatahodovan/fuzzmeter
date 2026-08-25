#!/usr/bin/env bash
set -euo pipefail

: "${OUT:?OUT must be set}"

cd /src/jerryscript
rm -rf build

python3 tools/build.py \
  --builddir=build \
  --clean \
  --debug \
  --strip=off \
  --logging=on \
  --lto=off \
  --compile-flag="${CFLAGS}" \
  --linker-flag="${CFLAGS}"

EXTRA_FLAGS=""
if [ $FUZZER == "libfuzzer_grammarinator" ]; then
  EXTRA_FLAGS=$LIBFUZZER_FLAGS
fi

$CC $CFLAGS \
  -I/src/jerryscript/jerry-core/include \
  -c /src/jerryscript/jerry-main/main-libfuzzer.c \
  $EXTRA_FLAGS \
  -o /tmp/main-libfuzzer.o

$CXX $CFLAGS \
  /tmp/main-libfuzzer.o \
  build/lib/libjerry-core.a \
  build/lib/libjerry-ext.a \
  build/lib/libjerry-port.a \
  $FUZZER_LIB \
  -lm \
  -o "$OUT/$TARGET_NAME"
