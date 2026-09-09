# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends python3-venv ragel pkg-config zlib1g-dev && \
    python3 -m venv /usr/local/harfbuzz-build-env && \
    /usr/local/harfbuzz-build-env/bin/pip install --upgrade pip && \
    /usr/local/harfbuzz-build-env/bin/pip install meson==1.2.0 ninja && \
    ln -s /usr/local/harfbuzz-build-env/bin/meson /usr/local/bin/meson && \
    ln -s /usr/local/harfbuzz-build-env/bin/ninja /usr/local/bin/ninja && \
    rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/local/harfbuzz-build-env/bin:${PATH}"

RUN git clone --depth 1 https://github.com/harfbuzz/harfbuzz.git "${SRC}/harfbuzz"

WORKDIR ${SRC}/harfbuzz

COPY build.sh "${SRC}/"
COPY benchmark.yaml /benchmark.yaml
