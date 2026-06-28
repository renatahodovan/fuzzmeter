# syntax=docker/dockerfile:1.7
FROM runtime_tools

ENV DEBIAN_FRONTEND=noninteractive
ENV CC=clang
ENV CXX=clang++
ENV FUZZER_LIB=/opt/fuzzmeter/tools/lib/libFuzzer.a

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      automake \
      bison \
      build-essential \
      cargo \
      clang-18 \
      cmake \
      curl \
      file \
      flex \
      gawk \
      git \
      libclang-rt-18-dev \
      libc++-dev \
      libc++abi-dev \
      libfuzzer-18-dev \
      libglib2.0-dev \
      libgtk-3-dev \
      libpixman-1-dev \
      libstdc++-12-dev \
      lld-18 \
      llvm-18 \
      llvm-18-dev \
      make \
      ninja-build \
      pkg-config \
      python3-dev \
      python3-setuptools \
      unzip \
      wget \
      xz-utils \
      zip \
      zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/clang-18 /usr/local/bin/clang && \
    ln -sf /usr/bin/clang++-18 /usr/local/bin/clang++ && \
    ln -sf /usr/bin/llvm-profdata-18 /usr/local/bin/llvm-profdata && \
    ln -sf /usr/bin/llvm-cov-18 /usr/local/bin/llvm-cov && \
    ln -sf /usr/bin/llvm-symbolizer-18 /usr/local/bin/llvm-symbolizer && \
    ln -sf /usr/bin/llvm-ar-18 /usr/local/bin/llvm-ar && \
    ln -sf /usr/bin/llvm-ranlib-18 /usr/local/bin/llvm-ranlib && \
    ln -sf /usr/bin/lld-18 /usr/local/bin/lld

RUN mkdir -p /opt/fuzzmeter/tools/lib /opt/fuzzmeter/meta && \
    cp -a /usr/lib/llvm-18/lib/libFuzzer.a /opt/fuzzmeter/tools/lib/libFuzzer.a

RUN clang --version > /opt/fuzzmeter/meta/clang-version.txt && \
    clang --print-resource-dir > /opt/fuzzmeter/meta/clang-resource-dir.txt && \
    test -f /opt/fuzzmeter/tools/lib/libFuzzer.a && \
    test -f "$(clang --print-resource-dir)/lib/linux/libclang_rt.asan-x86_64.a" && \
    test -f "$(clang --print-resource-dir)/lib/linux/libclang_rt.asan_static-x86_64.a" && \
    test -f "$(clang --print-resource-dir)/lib/linux/libclang_rt.profile-x86_64.a"
