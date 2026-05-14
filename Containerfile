# WARNING: This Dockerfile is designed for the demonstration relay worker.
# Fully compliant with non-root security execution standards.

FROM ghcr.io/astral-sh/uv:latest AS uv_bin

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    libc6-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

RUN groupadd -r appgroup && useradd -r -g appgroup -m -s /bin/bash appuser

COPY --from=uv_bin /uv /uvx /bin/

COPY pyproject.toml README.md ./

COPY faktory_outbox/ ./faktory_outbox/
COPY examples/django_example/ ./examples/django_example/

RUN uv pip install --system ".[postgres,oracle]" && \
    uv pip install --system -e . && \
    uv pip install --system psycopg2-binary oracledb

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown appuser:appgroup /entrypoint.sh

RUN chown -R appuser:appgroup /app

USER appuser

ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]

CMD ["python", "-m", "faktory_outbox.relay"]
