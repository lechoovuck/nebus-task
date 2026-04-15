FROM python:3.14-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_SYSTEM_PYTHON=1

COPY pyproject.toml .
RUN uv sync --no-dev

COPY . .

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python"]
