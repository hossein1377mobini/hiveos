# HiveOS backend image (v0.1) - uv-based, Python 3.11
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# OCR engine for the image pipeline (US-205). The six image formats are part of
# the supported set, but classify.py refuses to run without the binary and
# raises OCR_UNAVAILABLE - so without this every image asset stayed queued
# forever and never became searchable. The Persian pack is required: extracted
# text is almost entirely Persian here, and eng alone returns nothing usable.
# Installed before the unprivileged user is created, as apt needs root.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-fas \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Review round 2: run as unprivileged user, not root (uid 10001).
RUN useradd --system --uid 10001 --no-create-home hiveos

WORKDIR /srv/backend
RUN chown hiveos:hiveos /srv/backend

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_CACHE_DIR=/tmp/uv-cache

COPY --chown=hiveos:hiveos backend/pyproject.toml backend/uv.lock ./
USER hiveos
# --extra local-ml pulls onnxruntime + transformers: embeddings and reranking
# run on this host so document text never leaves it (PO decision 2026-09-12).
# The int8 graphs themselves are bind-mounted at /opt/models, not baked in.
RUN uv sync --frozen --no-dev --extra local-ml --no-install-project

COPY --chown=hiveos:hiveos backend/ .
RUN uv sync --frozen --no-dev --extra local-ml

EXPOSE 8100
CMD ["uv", "run", "--no-sync", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8100"]
