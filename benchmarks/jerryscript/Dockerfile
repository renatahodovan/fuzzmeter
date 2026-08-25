# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN git clone --depth 1 https://github.com/jerryscript-project/jerryscript "${SRC}/jerryscript"

COPY build.sh build.patch benchmark.yaml $SRC/
COPY benchmark.yaml /benchmark.yaml
COPY jerry_port_fatal_abort.c "${SRC}/jerryscript/jerry-main/"
COPY jerry_seed_corpus.zip "${OUT}/jerry_seed_corpus.zip"
COPY grammarinator/ $SRC/grammarinator
COPY jerry.dict $SRC/jerry.dict

WORKDIR ${SRC}/jerryscript

RUN git apply "${SRC}/build.patch"
