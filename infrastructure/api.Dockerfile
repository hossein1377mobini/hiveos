# HiveOS backend image (v0.1) - uv-based, Python 3.11
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# Review round 2: run as unprivileged user, not root (uid 10001).
RUN useradd --system --uid 10001 --no-create-home hiveos

WORKDIR /srv/backend
RUN chown hiveos:hiveos /srv/backend

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_CACHE_DIR=/tmp/uv-cache

COPY --chown=hiveos:hiveos backend/pyproject.toml backend/uv.lock ./
USER hiveos
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=hiveos:hiveos backend/ .
RUN uv sync --frozen --no-dev

EXPOSE 8100
CMD ["uv", "run", "--no-sync", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8100"]
