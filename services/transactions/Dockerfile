FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv==0.12.18
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY app ./app
CMD ["uv", "run", "poe", "start"]
