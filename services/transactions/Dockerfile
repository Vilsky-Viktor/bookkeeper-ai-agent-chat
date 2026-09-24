FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir poetry==1.8.4
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --with dev
COPY app ./app
CMD ["poetry", "run", "poe", "start"]
