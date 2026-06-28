# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        autoconf \
        cmake \
        libtool \
        pkg-config \
        make \
        ninja-build \
        python3-pip && \
    python3 -m pip install meson ninja requests && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p "${SRC}/font-corpus"
ADD https://github.com/adobe-fonts/adobe-variable-font-prototype/releases/download/1.001/AdobeVFPrototype.otf ${SRC}/font-corpus/
RUN git clone --depth 1 https://github.com/unicode-org/text-rendering-tests.git "${SRC}/text-rendering-tests" && \
    cp "${SRC}/text-rendering-tests/fonts/"* "${SRC}/font-corpus/"
RUN git clone --depth 1 https://github.com/freetype/freetype2-testing.git "${SRC}/freetype2-testing"

WORKDIR ${SRC}/freetype2-testing

COPY build.sh "${SRC}/"
COPY benchmark.yaml /benchmark.yaml
