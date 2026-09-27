# Image for both Python services (build context: services/agent or
# services/transactions — they're laid out the same way).
#   target `dev`  — docker-compose.yml: every dependency, dev tools included; the
#                   source is bind-mounted over app/ and uvicorn reloads on change.
#   final stage   — production (Cloud Run, built by CI): no dev tools, no uv, runs
#                   as a non-root user, listens on Cloud Run's injected $PORT.

ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS base
# Also pinned in .github/workflows/python-service.yml (setup-uv).
ARG UV_VERSION=0.12.18
ENV PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/app/.venv UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv==${UV_VERSION}
WORKDIR /app
COPY pyproject.toml uv.lock ./

FROM base AS dev
RUN uv sync --frozen
COPY app ./app
# Port 8000 matches docker-compose's internal networking (Caddyfile, TRANSACTIONS_URL).
CMD ["uv", "run", "poe", "start"]

FROM base AS build
RUN uv sync --frozen --no-dev
COPY app ./app

FROM ${PYTHON_IMAGE}
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/app /app/app
RUN useradd --system --create-home appuser
USER appuser
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
