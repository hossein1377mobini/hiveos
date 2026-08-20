"""rename otp_codes attempts check constraint to ck_otp_codes_attempts

Revision ID: f9398b06c0f5
Revises: 2a44bc6adf74
Create Date: 2026-08-20 13:52:15.469861

S1-05 corrective migration: ``OtpCode.attempts`` (models.py) previously reused
the copy-pasted constraint name ``ck_processing_jobs_attempts`` (owned by
``ProcessingJob.attempts``). Rename/repair it to ``ck_otp_codes_attempts`` so
the model and the migration-produced schema agree (``alembic check`` clean).

Handles all three real-world states idempotently:
  * the misnamed ``ck_processing_jobs_attempts`` exists on otp_codes -> drop it;
  * the correct ``ck_otp_codes_attempts`` is missing -> create it;
  * already correct -> no-op.

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f9398b06c0f5'
down_revision: str | Sequence[str] | None = '2a44bc6adf74'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "otp_codes"
_WRONG_NAME = "ck_processing_jobs_attempts"
_RIGHT_NAME = "ck_otp_codes_attempts"
_CONDITION = "attempts >= 0"


def upgrade() -> None:
    """Repair the otp_codes.attempts CheckConstraint name."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_check_constraints(_TABLE)}

    if _WRONG_NAME in existing:
        op.drop_constraint(_WRONG_NAME, _TABLE, type_="check")

    if _RIGHT_NAME not in existing:
        op.create_check_constraint(_RIGHT_NAME, _TABLE, _CONDITION)


def downgrade() -> None:
    """Revert to the baseline (no-constraint) state's corrected constraint."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_check_constraints(_TABLE)}

    if _RIGHT_NAME in existing:
        op.drop_constraint(_RIGHT_NAME, _TABLE, type_="check")
