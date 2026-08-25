# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        make \
        autoconf \
        automake \
        libtool \
        python3 \
        ruby \
        ninja-build \
        bison \
        flex \
        gperf \
        wget && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/WebKit/WebKit.git "${SRC}/WebKit"
RUN wget https://github.com/unicode-org/icu/releases/download/release-74-1/icu4c-74_1-src.tgz && \
    tar xzvf icu4c-74_1-src.tgz -C "${SRC}"

WORKDIR ${SRC}/WebKit

COPY build.sh "${SRC}/"
COPY benchmark.yaml /benchmark.yaml
