# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install --no-install-recommends -y \
        lsb-release \
        sudo \
        pkg-config \
        file \
        libc++-18-dev \
        libc++abi-18-dev && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git "${SRC}/depot_tools"
ENV PATH="${SRC}/depot_tools:${PATH}"

RUN fetch v8 && cd v8 && git checkout HEAD && gclient sync -D

WORKDIR /src/v8

RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections
RUN ./build/install-build-deps.sh --no-prompt

COPY build.sh "${SRC}/"
COPY benchmark.yaml /benchmark.yaml

ENV CLANG_TOOLCHAIN="${SRC}/v8/third_party/llvm-build/Release+Asserts"
