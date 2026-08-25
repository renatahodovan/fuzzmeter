# syntax=docker/dockerfile:1.7
FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN git clone --depth 1 https://github.com/curl/curl.git "${SRC}/curl"
RUN git clone --depth 1 https://github.com/curl/curl-fuzzer.git "${SRC}/curl_fuzzer"

# Use curl-fuzzer's scripts to install and refresh its dependency stack.
RUN "${SRC}/curl_fuzzer/scripts/ossfuzzdeps.sh"

WORKDIR ${SRC}/curl_fuzzer

COPY build.sh "${SRC}/"
COPY benchmark.yaml /benchmark.yaml
