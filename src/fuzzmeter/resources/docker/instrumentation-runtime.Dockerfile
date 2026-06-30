# syntax=docker/dockerfile:1.7
FROM runtime_base

ENV DEBIAN_FRONTEND=noninteractive

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      libclang-rt-18-dev \
      libc++1-18 \
      libc++abi1-18 \
      llvm-18 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/llvm-profdata-18 /usr/local/bin/llvm-profdata && \
    ln -sf /usr/bin/llvm-cov-18 /usr/local/bin/llvm-cov && \
    ln -sf /usr/bin/llvm-symbolizer-18 /usr/local/bin/llvm-symbolizer
