# HiveOS v0.1 backend image (staging/prod, zero-open deploy bundle)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/pyproject.toml ./backend/
COPY backend/alembic.ini ./backend/
COPY backend/migrations ./backend/migrations
COPY backend/backend ./backend/backend

RUN pip install --no-cache-dir ./backend

EXPOSE 8000
WORKDIR /app/backend

# migrations run at container start (idempotent), then the API.
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
