# syntax=docker/dockerfile:1.7
FROM build_base

COPY --from=entrypoints run_fuzzer.py /opt/fuzzmeter/run_fuzzer.py
COPY --from=entrypoints coverage_sets.py /opt/fuzzmeter/coverage_sets.py
COPY --from=entrypoints coverage_worker.py /opt/fuzzmeter/coverage_worker.py
COPY --from=entrypoints crash_worker.py /opt/fuzzmeter/crash_worker.py

RUN chmod 0755 \
      /opt/fuzzmeter/run_fuzzer.py \
      /opt/fuzzmeter/campaign_build.py \
      /opt/fuzzmeter/coverage_worker.py \
      /opt/fuzzmeter/crash_worker.py
