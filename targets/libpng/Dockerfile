FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y make autoconf automake libtool zlib1g-dev

RUN git clone --depth 1 https://github.com/madler/zlib.git $SRC/zlip
RUN git clone -b master --depth 1 https://github.com/pnggroup/libpng.git $SRC/libpng
RUN cp $SRC/libpng/contrib/oss-fuzz/build.sh $SRC

COPY build.sh $SRC/

WORKDIR $SRC/libpng
