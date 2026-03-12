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

# Non-root user (note: needs docker socket access, so add to docker group at runtime or use socket proxy)
RUN useradd -m -r appuser
USER appuser

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
