# HiveOS v0.1 backend image (staging/prod, zero-open deploy bundle).
# Dependencies are vendored as wheels by the deployer before building:
#   cd backend && py -3.11 -m pip download . -d ../deploy/_wheels
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_INDEX=1 \
    PIP_FIND_LINKS=/app/_wheels

WORKDIR /app

COPY deploy/_wheels ./_wheels
COPY backend/pyproject.toml ./backend/
COPY backend/alembic.ini ./backend/
COPY backend/migrations ./backend/migrations
COPY backend/backend ./backend/backend

# hatchling (build backend) is vendored too; --no-build-isolation avoids network.
# onnxruntime + transformers power the local embedding and rerank models
# (PO decision 2026-09-12). Vendored as wheels like everything else, so the
# build still needs no network. The int8 graphs themselves are mounted from
# /opt/models at run time and are not part of the image.
RUN pip install --no-cache-dir /app/_wheels/hatchling-*.whl && \
    pip install --no-cache-dir --no-build-isolation "./backend[local-ml]"

EXPOSE 8000
WORKDIR /app/backend

# migrations run at container start (idempotent), then the API.
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
