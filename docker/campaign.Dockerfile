# syntax=docker/dockerfile:1.7

ARG BUILDER_IMAGE=builder
ARG BENCHMARK_IMAGE=benchmark
ARG BUILD_BASE_IMAGE=build_base
ARG RUNTIME_BASE_IMAGE=runtime_base
ARG RUNNER_BASE_IMAGE=runtime_base
ARG CLANG_BASE_IMAGE=clang_base

FROM ${BUILDER_IMAGE} AS builder
FROM ${BENCHMARK_IMAGE} AS benchmark
FROM ${BUILD_BASE_IMAGE} AS build_base

FROM builder AS campaign_builder
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG FUZZER
ARG FUZZER_BUILD_CONFIG_JSON="{}"
ARG FUZZER_SOURCE_DIRS=""
ARG BENCHMARK
ARG BENCHMARK_WORKDIR=/src
ARG TARGET_NAME
ARG FM_LOG_LEVEL=INFO

ENV FUZZER=${FUZZER}
ENV FM_FUZZER_BUILD_CONFIG_JSON=${FUZZER_BUILD_CONFIG_JSON}
ENV BENCHMARK=${BENCHMARK}
ENV BENCHMARK_WORKDIR=${BENCHMARK_WORKDIR}
ENV TARGET_NAME=${TARGET_NAME}
ENV FM_LOG_LEVEL=${FM_LOG_LEVEL}
ENV FUZZMETER_LOG_LEVEL=${FM_LOG_LEVEL}
ENV FM_BENCHMARK_YAML=/benchmark.yaml
ENV FM_FUZZER_BUILD_CACHE_DIR=/var/cache/fuzzmeter/fuzzer-build
ENV PYTHONPATH=/opt/fuzzmeter
ENV SRC=/src
ENV WORK=/work
ENV OUT=/out

WORKDIR $SRC

# Merge the full benchmark image filesystem into the fuzzer builder stage so
# target-specific packages and tools installed by benchmark Dockerfiles are
# available during campaign_build.
# COPY --from=benchmark / /

COPY --from=benchmark /usr /usr
COPY --from=benchmark /lib /lib
COPY --from=benchmark /lib64 /lib64
COPY --from=benchmark /etc /etc
COPY --from=benchmark /bin /bin
COPY --from=benchmark /sbin /sbin
COPY --from=benchmark /src /src
COPY --from=benchmark /out /out

COPY --from=build_base /opt/fuzzmeter/campaign_build.py /opt/fuzzmeter/campaign_build.py

RUN --mount=type=bind,from=fuzzer_build_sources,source=.,target=/tmp/fuzzers,readonly \
    set -euxo pipefail; \
    mkdir -p /opt/fuzzmeter/fuzzers; \
    cp /tmp/fuzzers/__init__.py /opt/fuzzmeter/fuzzers/__init__.py; \
    cp /tmp/fuzzers/utils.py /opt/fuzzmeter/fuzzers/utils.py; \
    cp -a /tmp/fuzzers/_common /opt/fuzzmeter/fuzzers/_common; \
    for fuzzer_dir in ${FUZZER_SOURCE_DIRS}; do \
      mkdir -p "/opt/fuzzmeter/fuzzers/${fuzzer_dir}"; \
      if compgen -G "/tmp/fuzzers/${fuzzer_dir}/*.py" > /dev/null; then \
        cp /tmp/fuzzers/${fuzzer_dir}/*.py "/opt/fuzzmeter/fuzzers/${fuzzer_dir}/"; \
      fi; \
      if [ -d "/tmp/fuzzers/${fuzzer_dir}/build" ]; then \
        mkdir -p "/opt/fuzzmeter/fuzzers/${fuzzer_dir}/build"; \
        cp -a "/tmp/fuzzers/${fuzzer_dir}/build/." "/opt/fuzzmeter/fuzzers/${fuzzer_dir}/build/"; \
      fi; \
    done

RUN --mount=type=cache,target=/root/.cache \
    --mount=type=cache,target=/var/cache/fuzzmeter/fuzzer-build \
    set -euxo pipefail; \
    mkdir -p "${OUT}" /opt/fuzzmeter/fuzz/seeds; \
    if [ ! -s /benchmark.yaml ] && [ -s "${SRC}/benchmark.yaml" ]; then \
      cp "${SRC}/benchmark.yaml" /benchmark.yaml; \
    fi; \
    if [ ! -s /benchmark.yaml ]; then \
      printf "project: %s\n" "${BENCHMARK}" > /benchmark.yaml; \
      printf "fuzz_target: %s\n" "${TARGET_NAME}" >> /benchmark.yaml; \
      printf "target: %s:%s\n" "${BENCHMARK}" "${TARGET_NAME}" >> /benchmark.yaml; \
    fi; \
    printf "\nfuzz_target: %s\ntarget: %s:%s\n" "${TARGET_NAME}" "${BENCHMARK}" "${TARGET_NAME}" >> /benchmark.yaml; \
    PYTHONPATH=/opt/fuzzmeter python3 /opt/fuzzmeter/campaign_build.py; \
    test -f "/out/${TARGET_NAME}"; \
    if [ "${FUZZER}" = "grammarinator" ] || [ "${FUZZER}" = "afl_grammarinator" ] || [ "${FUZZER}" = "libfuzzer_grammarinator" ]; then \
      test -f "/out/grammarinator-decode-${TARGET_NAME}"; \
      chmod 0755 "/out/grammarinator-decode-${TARGET_NAME}"; \
    fi; \
    chmod 0755 "/out/${TARGET_NAME}"

FROM ${RUNTIME_BASE_IMAGE} AS runtime_base
FROM ${RUNNER_BASE_IMAGE} AS runner_base

FROM runner_base AS runner
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG TARGET_NAME
ARG FUZZER_SOURCE_DIRS=""
COPY --from=campaign_builder /src /src
COPY --from=campaign_builder /work /work
COPY --from=campaign_builder /out /out
COPY --from=campaign_builder /benchmark.yaml /benchmark.yaml
RUN --mount=type=bind,from=fuzzer_run_sources,source=.,target=/tmp/fuzzers,readonly \
    set -euxo pipefail; \
    mkdir -p /opt/fuzzmeter/fuzzers; \
    cp /tmp/fuzzers/__init__.py /opt/fuzzmeter/fuzzers/__init__.py; \
    cp /tmp/fuzzers/utils.py /opt/fuzzmeter/fuzzers/utils.py; \
    cp -a /tmp/fuzzers/_common /opt/fuzzmeter/fuzzers/_common; \
    for fuzzer_dir in ${FUZZER_SOURCE_DIRS}; do \
      mkdir -p "/opt/fuzzmeter/fuzzers/${fuzzer_dir}"; \
      if compgen -G "/tmp/fuzzers/${fuzzer_dir}/*.py" > /dev/null; then \
        cp /tmp/fuzzers/${fuzzer_dir}/*.py "/opt/fuzzmeter/fuzzers/${fuzzer_dir}/"; \
      fi; \
      if [ -d "/tmp/fuzzers/${fuzzer_dir}/run" ]; then \
        mkdir -p "/opt/fuzzmeter/fuzzers/${fuzzer_dir}/run"; \
        cp -a "/tmp/fuzzers/${fuzzer_dir}/run/." "/opt/fuzzmeter/fuzzers/${fuzzer_dir}/run/"; \
      fi; \
    done
ENV FM_TARGET_NAME=${TARGET_NAME}

FROM ${CLANG_BASE_IMAGE} AS clang_base

FROM clang_base AS coverage_runner
ARG TARGET_NAME
COPY --from=campaign_builder /src /src
COPY --from=campaign_builder /work /work
COPY --from=campaign_builder /out /out
COPY --from=campaign_builder /benchmark.yaml /benchmark.yaml
COPY --from=runtime_base /opt/fuzzmeter/coverage_repro_worker.py /opt/fuzzmeter/coverage_repro_worker.py
ENV PYTHONPATH=/opt/fuzzmeter
ENV FM_TARGET_NAME=${TARGET_NAME}

FROM clang_base AS crash_runner
ARG TARGET_NAME
COPY --from=campaign_builder /src /src
COPY --from=campaign_builder /work /work
COPY --from=campaign_builder /out /out
COPY --from=campaign_builder /benchmark.yaml /benchmark.yaml
COPY --from=runtime_base /opt/fuzzmeter/crash_repro_worker.py /opt/fuzzmeter/crash_repro_worker.py
ENV PYTHONPATH=/opt/fuzzmeter
ENV FM_TARGET_NAME=${TARGET_NAME}
