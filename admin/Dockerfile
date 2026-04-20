FROM python:3.12-slim

# System deps for Docker SDK (needs gcc for some deps) and general utils
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        wget \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml .

# Install dependencies
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy application code
COPY app/ app/

# Non-root user. UID/GID are pinned so the compose init container can chown
# /config and /state to match — keep these in sync with docker-compose.yml.
RUN useradd -m -u 1001 -U appuser
USER appuser

EXPOSE 8080

# Shell form so ADMIN_BIND_HOST / ADMIN_PORT from the env are honored. `exec`
# replaces the shell so uvicorn receives SIGTERM directly.
CMD ["sh", "-c", "exec uvicorn app.main:app --host ${ADMIN_BIND_HOST:-127.0.0.1} --port ${ADMIN_PORT:-8080}"]
