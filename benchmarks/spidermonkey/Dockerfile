# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        autoconf2.13 \
        libc++1 \
        libc++abi1 \
        m4 \
        yasm \
        python3 \
        patchelf \
        libxml2 \
        llvm-dev \
        curl && \
    rm -rf /var/lib/apt/lists/*

RUN rm -f /usr/local/bin/cargo

ENV CARGO_HOME="${SRC}/.cargo"
ENV RUSTUP_HOME="${SRC}/.rustup"
ENV PATH="${SRC}/.cargo/bin:${PATH}"

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs > "${SRC}/rustbuild.sh" && \
    chmod +x "${SRC}/rustbuild.sh" && \
    "${SRC}/rustbuild.sh" -y

RUN git clone --depth=1 https://github.com/mozilla/gecko-dev "${SRC}/mozilla-central"

WORKDIR ${SRC}/mozilla-central

COPY build.sh "${SRC}/"
COPY benchmark.yaml /benchmark.yaml
