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
        libtool \
        pkg-config \
        zlib1g-dev \
        liblzma-dev \
        curl && \
    curl -LO http://mirrors.kernel.org/ubuntu/pool/main/a/automake-1.16/automake_1.16.5-1.3_all.deb && \
    apt install -y ./automake_1.16.5-1.3_all.deb && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://gitlab.gnome.org/GNOME/libxml2.git "${SRC}/libxml2"

WORKDIR ${SRC}/libxml2

COPY build.sh "${SRC}/"
COPY benchmark.yaml /benchmark.yaml
