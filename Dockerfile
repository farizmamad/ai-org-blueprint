# Dockerfile — main Python image for all services (brain, mock-llm, demo)
#
# Rebuild triggers:
#   - Changes to pyproject.toml (dependency bump)
#   - Changes to source files (anything under core/, agents/, tools/, scripts/)
#
# Layer ordering: install deps first so source-only changes don't re-run pip.

FROM python:3.12-slim

WORKDIR /app

# Install build tools for any C extensions (e.g. SQLite FTS5 on some platforms)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Dependencies (cached layer) ───────────────────────────────────────────────
COPY pyproject.toml .
# Stub minimal package structure so pip can resolve the package in editable mode
# before the full source is copied.
RUN mkdir -p core tools agents \
    && touch core/__init__.py tools/__init__.py agents/__init__.py \
    && pip install --no-cache-dir -e . 2>/dev/null || \
       pip install --no-cache-dir \
           "anthropic>=0.40.0" \
           "fastapi>=0.110.0" \
           "uvicorn>=0.27.0" \
           "httpx>=0.27.0" \
           "pydantic>=2.5.0" \
           "apscheduler>=3.10.0" \
           "python-dotenv>=1.0.0"

# ── Source ────────────────────────────────────────────────────────────────────
COPY . .
RUN pip install --no-cache-dir -e . --no-deps

# Data directory for brain.db (overridden by volume mount in docker-compose)
RUN mkdir -p data

ENV BRAIN_DB_PATH=/app/data/brain.db
ENV PYTHONUNBUFFERED=1
