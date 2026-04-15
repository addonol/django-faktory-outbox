# WARNING: This Dockerfile is designed for the demonstration relay worker.
# In a production environment, use a multi-stage build and manage secrets
# through a secure orchestration tool like Ansible or Kubernetes.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1


RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    libc6-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app


RUN groupadd -r appgroup && useradd -r -g appgroup appuser

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml README.md ./

RUN uv pip install --system ".[postgres,oracle]"

COPY faktory_outbox/ ./faktory_outbox/
COPY examples/ ./examples/
COPY pyproject.toml ./

RUN uv pip install --system -e .

RUN chown -R appuser:appgroup /app

USER appuser

ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]

CMD ["python", "-m", "faktory_outbox.relay"]
