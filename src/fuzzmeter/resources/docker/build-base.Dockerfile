# syntax=docker/dockerfile:1.7
FROM runtime_tools

COPY --from=entrypoints campaign_build.py /opt/fuzzmeter/campaign_build.py
COPY --from=fuzzmeter_resources resources/__init__.py /opt/fuzzmeter/fuzzmeter/resources/__init__.py
COPY --from=fuzzmeter_resources resources/instrumentation /opt/fuzzmeter/fuzzmeter/resources/instrumentation
RUN touch /opt/fuzzmeter/fuzzmeter/__init__.py
RUN chmod 0755 /opt/fuzzmeter/campaign_build.py
