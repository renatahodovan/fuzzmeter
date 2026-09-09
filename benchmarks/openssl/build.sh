#!/usr/bin/env bash
set -euo pipefail

export SANITIZER="${SANITIZER:-}"
export FUZZ_INTROSPECTOR_CONFIG=/src/openssl/fuzz/fuzz_introspector_exclusion.config

FUZZER_LIBRARY="${LIB_FUZZING_ENGINE%.a}"
CONFIGURE_FLAGS="--debug enable-fuzz-libfuzzer -DPEDANTIC -DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION no-shared enable-tls1_3 enable-rc5 enable-md2 enable-nextprotoneg enable-weak-ssl-ciphers --with-fuzzer-lib=${FUZZER_LIBRARY} ${CFLAGS} -fno-sanitize=alignment enable-unit-test no-tests"
if [[ "${CFLAGS}" == *sanitize=memory* ]]; then
    CONFIGURE_FLAGS="${CONFIGURE_FLAGS} no-asm"
fi
if [[ "${CFLAGS}" != *-m32* ]]; then
    CONFIGURE_FLAGS="${CONFIGURE_FLAGS} enable-ec_nistp_64_gcc_128"
fi
if [[ "${CFLAGS}" == *-m32* ]]; then
    CONFIGURE_FLAGS="${CONFIGURE_FLAGS} no-threads"
fi

if [[ "${CFLAGS}" == *-m32* ]]; then
    setarch i386 ./config ${CONFIGURE_FLAGS} no-apps no-docs
else
    ./config ${CONFIGURE_FLAGS} no-apps no-docs
fi

# Linking OpenSSL's fuzz targets in parallel exceeds the 4 GiB image-build
# limit when coverage instrumentation is enabled.
make -j1 LDCMD="${CXX} ${CXXFLAGS}"

fuzzers=$(find fuzz -executable -type f '!' -name '*.py' '!' -name '*-test' '!' -name '*.pl' '!' -name '*.sh')
for f in ${fuzzers}; do
    fuzzer=$(basename "${f}")
    cp "${f}" "${OUT}/${fuzzer}"
    zip -j "${OUT}/${fuzzer}_seed_corpus.zip" "fuzz/corpora/${fuzzer}"/*
done

cp fuzz/oids.txt "${OUT}/asn1.dict"
cp fuzz/oids.txt "${OUT}/x509.dict"
