# syntax=docker/dockerfile:1.7
FROM parent_image

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /opt/fuzzmeter/runtime

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      bash \
      clang llvm lld \
      libclang-rt-dev \
      python3 \
      coreutils findutils \
      tar zstd \
    && true

COPY fuzz.py /opt/fuzzmeter/runtime/fuzz.py

RUN chmod 0755 /opt/fuzzmeter/runtime/fuzz.py

CMD ["bash", "-lc", "true"]
