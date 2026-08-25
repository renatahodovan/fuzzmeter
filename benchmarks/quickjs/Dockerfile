# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends make zip && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/bellard/quickjs "${SRC}/quickjs"
RUN git clone --depth 1 https://github.com/renatahodovan/quickjs-corpus "${SRC}/quickjs-corpus"

WORKDIR ${SRC}/quickjs

COPY build.sh "${SRC}/"
COPY benchmark.yaml /benchmark.yaml

RUN sed -i -e '/qjs\$(EXE) tests\/test_worker.js/d' Makefile
