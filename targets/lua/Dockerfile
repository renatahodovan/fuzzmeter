# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        ninja-build \
        cmake \
        make \
        protobuf-compiler \
        libprotobuf-dev \
        zlib1g-dev \
        libreadline-dev \
        libunwind-dev && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/ligurio/lunapark $SRC/testdir
WORKDIR testdir
# RUN git clone --depth 1 --jobs $(nproc) https://github.com/ligurio/lunapark-corpus $SRC/corpus_dir
WORKDIR $SRC

COPY build.sh $SRC/testdir/
COPY build.sh $SRC/
COPY fuzz_lua.c $SRC/
COPY benchmark.yaml /benchmark.yaml
COPY fuzz_lua_seed_corpus.zip "${OUT}/fuzz_lua_seed_corpus.zip"
COPY grammarinator/ $SRC/grammarinator
