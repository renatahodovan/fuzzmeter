# syntax=docker/dockerfile:1.7
FROM parent_image

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /work

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends git binutils-dev libunwind-dev libbfd-dev libblocksruntime-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/google/honggfuzz.git /honggfuzz
RUN make -C /honggfuzz -j"$(nproc)" && \
    install -D -m755 /honggfuzz/honggfuzz /honggfuzz/bin/honggfuzz && \
    touch empty_lib.c && \
    cc -c -o /honggfuzz/empty_lib.o empty_lib.c
  