"""add missing model CheckConstraints + idempotent vector extension (S1-17)

Revision ID: 74b5daa3f137
Revises: 4f1b2c9e7a3d
Create Date: 2026-08-20 22:00:00.000000

S1-17 corrective migration: the baseline (``2a44bc6adf74``) omitted the
CheckConstraints declared on the models for ``documents`` (format/status) and
``processing_jobs`` (type/status/attempts). They exist only on the
dev/``create_all`` path, so ``alembic check`` reported drift and the prod-path
migration produced a weaker schema. This migration adds them idempotently so
the prod-path schema matches the models (``alembic check`` clean).

It also re-asserts ``CREATE EXTENSION IF NOT EXISTS vector`` so a fresh volume
never depends solely on the ``initdb`` hook (``01-enable-vector.sql``) — safe
no-op when the extension already exists. ``ck_otp_codes_attempts`` is already
handled by ``f9398b06c0f5``, so it is intentionally not repeated here.

Each constraint is guarded by an inspector lookup so the migration is a no-op
on a database that already carries it (idempotent, re-run / stamp safe).
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '74b5daa3f137'
down_revision: str | Sequence[str] | None = '4f1b2c9e7a3d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK_CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    # (table, name, condition)
    ("documents", "ck_documents_format", "format IN ('pdf','docx','txt','md')"),
    (
        "documents",
        "ck_documents_status",
        "status IN ('detected','processing','ready','failed')",
    ),
    ("processing_jobs", "ck_processing_jobs_type", "job_type IN ('ingest')"),
    (
        "processing_jobs",
        "ck_processing_jobs_status",
        "status IN ('pending','running','succeeded','failed')",
    ),
    ("processing_jobs", "ck_processing_jobs_attempts", "attempts >= 0"),
)


def _existing_constraints() -> dict[str, set[str]]:
    """Map table -> set of existing CHECK constraint names."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {
        table: {c["name"] for c in inspector.get_check_constraints(table)}
        for table in {t for t, _, _ in _CHECK_CONSTRAINTS}
    }


def upgrade() -> None:
    """Install the missing model CheckConstraints + vector extension (idempotent)."""
    # (a) idempotent vector extension — never rely solely on the initdb hook.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # (b) add each model CHECK constraint that is not already present.
    existing = _existing_constraints()
    for table, name, condition in _CHECK_CONSTRAINTS:
        if name not in existing.get(table, set()):
            op.create_check_constraint(name, table, condition)


def downgrade() -> None:
    """Drop the five constraints this migration adds (leave vector extension)."""
    existing = _existing_constraints()
    for table, name, _ in reversed(_CHECK_CONSTRAINTS):
        if name in existing.get(table, set()):
            op.drop_constraint(name, table, type_="check")
