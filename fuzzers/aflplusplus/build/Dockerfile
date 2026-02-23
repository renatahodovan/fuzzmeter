# syntax=docker/dockerfile:1.7
FROM parent_image

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /work

# Download afl++.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

RUN git clone -b v4.35c https://github.com/AFLplusplus/AFLplusplus /afl

# Build without Python support as we don't need it.
# Set AFL_NO_X86 to skip flaky tests.
RUN cd /afl && \
    unset CFLAGS CXXFLAGS && \
    export CC=clang CXX=clang++ && \
    PYTHON_INCLUDE=/ make PERFORMANCE=1 && \
    cp utils/aflpp_driver/libAFLDriver.a /
