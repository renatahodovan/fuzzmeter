#!/usr/bin/env bash
set -euo pipefail

source /src/.cargo/env
rustup default nightly

cat > ./mozconfig <<'EOF'
ac_add_options --enable-application=js
mk_add_options MOZ_OBJDIR=@TOPSRCDIR@/obj-shell

ac_add_options --enable-debug
ac_add_options --enable-optimize="-O2 -gline-tables-only"

ac_add_options --disable-jemalloc
ac_add_options --disable-tests
ac_add_options --enable-address-sanitizer

CFLAGS="-fsanitize=address"
CXXFLAGS="-fsanitize=address"
LDFLAGS="-fsanitize=address"
EOF
export MOZCONFIG=./mozconfig

./mach --no-interactive bootstrap --application-choice js

build_jobs="$(nproc)"
if [ "${build_jobs}" -gt 2 ]; then
    build_jobs=2
fi

./mach build "-j${build_jobs}"

cp obj-shell/dist/bin/js "${OUT}/${TARGET_NAME}"

mkdir -p "${OUT}/lib"
cp -L /usr/lib/x86_64-linux-gnu/libc++.so.1 "${OUT}/lib"
cp -L /usr/lib/x86_64-linux-gnu/libc++abi.so.1 "${OUT}/lib"

patchelf --set-rpath '$ORIGIN/lib' "${OUT}/${TARGET_NAME}"
