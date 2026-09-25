# Production image (built/pushed/deployed by .github/workflows/agent.yml) — for
# local dev via docker-compose.yml, see Dockerfile.dev instead. Differences from
# that one: multi-stage (final image doesn't carry uv, pip caches, or
# pyproject.toml/uv.lock), skips the `dev` dependency-group (black/isort/mypy/
# pytest/poethepoet — nothing this image runs needs them), runs as a non-root user,
# and listens on Cloud Run's injected $PORT (default 8080) instead of a hardcoded
# port — Dockerfile.dev can hardcode 8000 because docker-compose's internal
# networking (Caddyfile, TRANSACTIONS_URL) hardcodes that same port; Cloud Run picks
# its own port and health-checks exactly that.

FROM python:3.12-slim AS builder
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv==0.12.18
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app /app/app
RUN useradd --system --create-home appuser
USER appuser
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
