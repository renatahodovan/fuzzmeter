# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends make autoconf automake libtool && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 -b develop https://github.com/madler/zlib.git "${SRC}/zlib"

WORKDIR ${SRC}/zlib

COPY build.sh "${SRC}/"
COPY zlib_uncompress_fuzzer.cc "${SRC}/"
COPY benchmark.yaml /benchmark.yaml
