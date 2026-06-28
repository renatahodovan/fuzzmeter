# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends make && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/openssl/openssl.git "${SRC}/openssl"
RUN cd "${SRC}/openssl" && git submodule update --init fuzz/corpora

WORKDIR ${SRC}/openssl

COPY build.sh "${SRC}/"
COPY benchmark.yaml /benchmark.yaml
