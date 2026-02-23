# syntax=docker/dockerfile:1.7
FROM runtime_tools

COPY docker/campaign_build.py /opt/fuzzmeter/campaign_build.py
RUN chmod 0755 /opt/fuzzmeter/campaign_build.py
