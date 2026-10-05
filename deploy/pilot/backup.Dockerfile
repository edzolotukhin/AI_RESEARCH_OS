FROM postgres:16-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 restic ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY tools/pilot_recovery.py /app/tools/pilot_recovery.py
COPY application/structured_output/json_validator.py /app/tools/structured_json_validator.py
RUN useradd --create-home --uid 1000 recovery \
    && mkdir -p /work /var/lib/ai_research_os/quantitative-protected /var/lib/ai_research_os/projects \
    && chown -R recovery:recovery /work /var/lib/ai_research_os
USER recovery
ENTRYPOINT ["python3", "/app/tools/pilot_recovery.py"]
