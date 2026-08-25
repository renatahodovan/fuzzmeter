# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends cmake make pkg-config && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/abseil/abseil-cpp "${SRC}/abseil-cpp"
RUN git clone --depth 1 https://github.com/google/re2 "${SRC}/re2"

WORKDIR ${SRC}/re2

COPY build.sh "${SRC}/"
COPY benchmark.yaml /benchmark.yaml
