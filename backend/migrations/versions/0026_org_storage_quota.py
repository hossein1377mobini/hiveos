"""Per-organization storage quota (FR-011, PO request 2026-09-13).

Every tenant writes into one shared volume, so without a cap the first
organization to upload heavily fills the disk and takes the others down with
it - and the failure only shows up when the volume is full. The column is
nullable: NULL means unlimited, which is what existing rows get, so this
migration cannot lock anyone out of their own data.

Revision ID: 0026
Revises: 0025
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE hiveos.organizations ADD COLUMN IF NOT EXISTS storage_quota_mb integer")
    # A non-positive quota would block every upload; only NULL or a positive
    # cap is meaningful.
    op.execute(
        "ALTER TABLE hiveos.organizations ADD CONSTRAINT storage_quota_mb_positive "
        "CHECK (storage_quota_mb IS NULL OR storage_quota_mb > 0)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE hiveos.organizations DROP CONSTRAINT IF EXISTS storage_quota_mb_positive")
    op.execute("ALTER TABLE hiveos.organizations DROP COLUMN IF EXISTS storage_quota_mb")
