# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------- Build stage
# Dependencies are built in a stage that is thrown away, so no compiler and no
# build headers survive into the image that actually runs in production.
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copied alone so the dependency layer is only rebuilt when dependencies change,
# not on every source edit. A stub `app` package satisfies setuptools so the
# real dependencies install from pyproject, the single source of truth shared
# with CI, rather than a hand-maintained list that silently drifts from it.
COPY apps/api/pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip setuptools wheel \
    && pip install .

# ----------------------------------------------------------------- Run stage
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# libpq for psycopg, curl for the container healthcheck. No compiler.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# The application never needs to write to its own filesystem, and never needs
# root. Running as an unprivileged user limits what a code-execution bug reaches.
RUN groupadd --system --gid 1001 agoreum \
    && useradd --system --uid 1001 --gid agoreum --no-create-home agoreum

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv/app

COPY --chown=agoreum:agoreum apps/api/app ./app
COPY --chown=agoreum:agoreum apps/api/alembic.ini ./alembic.ini
# The contract ABI is read at runtime; the path mirrors the repository layout so
# app/chain/escrow.py resolves it identically in the container and locally.
COPY --chown=agoreum:agoreum packages/contracts /srv/packages/contracts

USER agoreum

EXPOSE 8000

# Checks readiness, not just liveness: a container that cannot reach its
# database should not be routed traffic.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health/ready || exit 1

# Workers are set by the compose file: the droplet has 2 vCPUs, and oversubscribing
# a small box costs more in context switching than it gains in concurrency.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--no-server-header"]
