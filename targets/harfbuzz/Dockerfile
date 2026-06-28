# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends python3-pip ragel pkg-config zlib1g-dev && \
    pip3 install --upgrade pip && \
    pip3 install meson==1.2.0 ninja && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/harfbuzz/harfbuzz.git "${SRC}/harfbuzz"

WORKDIR ${SRC}/harfbuzz

COPY build.sh "${SRC}/"
COPY benchmark.yaml /benchmark.yaml
