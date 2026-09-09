#!/usr/bin/env bash
set -euo pipefail

DEPS_PATH=/src/deps
mkdir -p "${DEPS_PATH}"

# Build ICU for linking statically.
cd /src/icu/source
./configure --disable-shared --enable-static --disable-layoutex \
  --disable-tests --disable-samples --with-data-packaging=static --prefix="${DEPS_PATH}"
make install -j"${FM_BUILD_JOBS:-$(nproc)}"

# Flatten ICU archives because WebKit's static link expects single archives.
cd "${DEPS_PATH}/lib"
ls *.a | xargs -n1 ar x
rm *.a
ar r libicu.a *.{ao,o}
ln -s libicu.a libicudata.a
ln -s libicu.a libicuuc.a
ln -s libicu.a libicui18n.a

export CFLAGS="${CFLAGS} -DU_STATIC_IMPLEMENTATION"
export CXXFLAGS="${CXXFLAGS} -DU_STATIC_IMPLEMENTATION"
export ICU_ROOT="${DEPS_PATH}"

cd /src/WebKit
Tools/Scripts/build-jsc \
  --debug \
  --jsc-only \
  --cmakeargs="-DENABLE_STATIC_JSC=ON -DUSE_THIN_ARCHIVES=OFF -DWEBKIT_LIBRARIES_DIR=${DEPS_PATH} -DWEBKIT_LIBRARIES_INCLUDE_DIR=${DEPS_PATH}/include -DWEBKIT_LIBRARIES_LINK_DIR=${DEPS_PATH}/lib" \
  --makeargs='-v'

cp WebKitBuild/JSCOnly/Debug/bin/jsc "${OUT}/${TARGET_NAME}"
