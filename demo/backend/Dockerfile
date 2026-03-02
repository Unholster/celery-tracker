FROM python:3.11.10-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/usr/local

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (without the project itself, since source isn't copied yet)
RUN uv sync --frozen --no-install-project

# Copy the full project source
COPY . .

# Install the project itself
RUN uv sync --frozen

RUN printf '#!/bin/sh\nexec python -m demo.backend "$@"\n' > /usr/local/bin/run && chmod +x /usr/local/bin/run

CMD ["celery", "-A", "demoproject.celery", "worker", "--loglevel=DEBUG"]
