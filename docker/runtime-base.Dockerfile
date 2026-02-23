# syntax=docker/dockerfile:1.7
FROM build_base

COPY fuzzers/_common/run_fuzzer.py /opt/fuzzmeter/run_fuzzer.py
COPY src/fuzzmeter/repro/coverage_repro_worker.py /opt/fuzzmeter/coverage_repro_worker.py
COPY src/fuzzmeter/repro/crash_repro_worker.py /opt/fuzzmeter/crash_repro_worker.py

RUN chmod 0755 \
      /opt/fuzzmeter/run_fuzzer.py \
      /opt/fuzzmeter/campaign_build.py \
      /opt/fuzzmeter/coverage_repro_worker.py \
      /opt/fuzzmeter/crash_repro_worker.py
