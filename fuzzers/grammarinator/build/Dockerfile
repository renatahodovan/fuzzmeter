# syntax=docker/dockerfile:1.7
FROM parent_image

ENV DEBIAN_FRONTEND=noninteractive
ENV GRAMMARINATOR_DIR=/grammarinator

WORKDIR /work

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless \
        git \
        python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/renatahodovan/grammarinator.git "${GRAMMARINATOR_DIR}"
RUN python3 -m pip install --break-system-packages "${GRAMMARINATOR_DIR}" && \
    python3 -m pip install --break-system-packages -r ${GRAMMARINATOR_DIR}/grammarinator-cxx/dev/requirements.txt && \
    conan profile detect && echo "OK"
