# ── Stage 1: dependency installation ─────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools needed for some C extensions (e.g. psycopg2, argon2)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only the package manifest first for layer-caching
COPY pyproject.toml ./
# Minimal stub so pip can install the package in editable-like form
COPY app/__init__.py app/__init__.py

# Install all runtime dependencies (no dev extras) into a prefix directory
RUN pip install --no-cache-dir --prefix=/install .


# ── Stage 2: final runtime image ──────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="EVE Healthcare Engineering" \
      description="EVE Healthcare Diagnostic Service API"

# Runtime OS dependencies only (libpq for psycopg2, no gcc needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root system user for the application
RUN groupadd --system appgroup && useradd --system --gid appgroup --no-create-home appuser

WORKDIR /app

# Pull installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini
COPY app/ ./app/
COPY pyproject.toml ./pyproject.toml

# Install the package itself (editable-style, no deps re-downloaded)
RUN pip install --no-cache-dir --no-deps -e .

# Hand ownership to the non-root user
RUN chown -R appuser:appgroup /app

USER appuser

# Uvicorn listens on 8000 inside the container
EXPOSE 8000

# Default command — overridden by docker-compose to run migrations first
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
