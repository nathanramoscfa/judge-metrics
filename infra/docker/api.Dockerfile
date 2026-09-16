# infra/docker/api.Dockerfile
# The JudgeMetrics API image: multi-stage build on the official slim Python
# base with uv, locked runtime dependencies only (no dev or planning group),
# a non-root user, no `.env` (configuration comes from the environment), a
# HEALTHCHECK on /api/v1/health, and `judgemetrics serve` as the command.
#
#   docker build -f infra/docker/api.Dockerfile -t judgemetrics-api .
#   docker compose --profile app up

# --- build stage -------------------------------------------------------------
FROM python:3.13-slim AS builder

# uv pinned to the version the lockfile was produced with.
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first (cache-friendly): only the files uv needs to resolve.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-group planning --no-install-project

# Then the application (editable, so alembic/ next to src/ is found).
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-group planning

# --- runtime stage -----------------------------------------------------------
FROM python:3.13-slim AS runtime

ARG GIT_SHA=unknown

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JUDGEMETRICS_ENV=production \
    JUDGEMETRICS_LOG_FORMAT=json \
    JUDGEMETRICS_GIT_SHA=$GIT_SHA

# Apply Debian security updates, drop pip (uv built the environment; pip's
# vendored packages are what image scanners flag), and add the runtime user.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip* /usr/local/bin/pip* \
    && groupadd --system --gid 10001 judgemetrics \
    && useradd --system --uid 10001 --gid judgemetrics --create-home judgemetrics

WORKDIR /app
COPY --from=builder --chown=judgemetrics:judgemetrics /app /app

USER judgemetrics
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"]

CMD ["judgemetrics", "serve", "--host", "0.0.0.0"]
