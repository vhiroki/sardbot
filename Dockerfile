# Cloud Run Job container for sardbot paper-trade.
#
# We use uv inside the container too — it's just as fast there as locally.
# Multi-stage to keep the runtime image small.

FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1

# Install dependencies (cached layer)
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-install-project --no-dev

# Install the project itself
COPY . /app
RUN uv sync --frozen --no-dev

# Runtime
FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Cloud Run Job entrypoint: one paper-trade iteration, then exit.
CMD ["sardbot", "paper-trade"]
