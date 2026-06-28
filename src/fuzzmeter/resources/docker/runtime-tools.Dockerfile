# syntax=docker/dockerfile:1.7
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONPATH=/opt/fuzzmeter
ENV SRC=/src
ENV WORK=/work
ENV OUT=/out

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /opt/fuzzmeter

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      bash \
      ca-certificates \
      coreutils \
      findutils \
      gdb \
      python3 \
      python3-yaml \
      python3-pip \
      python3-venv \
      tar \
      zstd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p "${SRC}" "${WORK}" "${OUT}" /opt/fuzzmeter
