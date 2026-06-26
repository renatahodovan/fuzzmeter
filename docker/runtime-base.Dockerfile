# syntax=docker/dockerfile:1.7
FROM build_base

COPY fuzzers/_common/run_fuzzer.py /opt/fuzzmeter/run_fuzzer.py
COPY src/fuzzmeter/repro/coverage_sets.py /opt/fuzzmeter/coverage_sets.py
COPY src/fuzzmeter/repro/coverage_worker.py /opt/fuzzmeter/coverage_worker.py
COPY src/fuzzmeter/repro/crash_worker.py /opt/fuzzmeter/crash_worker.py

RUN chmod 0755 \
      /opt/fuzzmeter/run_fuzzer.py \
      /opt/fuzzmeter/campaign_build.py \
      /opt/fuzzmeter/coverage_worker.py \
      /opt/fuzzmeter/crash_worker.py
