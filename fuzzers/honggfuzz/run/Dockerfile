# syntax=docker/dockerfile:1.7
FROM parent_image

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends libbfd-dev libunwind-dev libatomic1 && \
    rm -rf /var/lib/apt/lists/*
