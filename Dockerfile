FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

# Empty named volumes inherit this directory's ownership on first mount, so
# both trusted runtime processes can use the shared protected-data root while
# continuing to run as the unprivileged application user.
RUN mkdir -p /var/lib/ai_research_os/quantitative-protected \
    && chown -R appuser:appuser /var/lib/ai_research_os

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
