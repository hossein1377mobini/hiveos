"""Bounded knowledge access: one watched folder per user (PO 2026-09).

The PO stated the product's access model: each user is registered with a folder,
a user's access to knowledge is bounded by that folder, uploads land in it, and
anything the system writes on their behalf goes into a "برنامه" subfolder
("برنامه" = "program") inside it.

Two obstacles in the schema:

  1. knowledge_sources.organization_id was UNIQUE, so an organization could hold
     exactly ONE folder no matter how many members it had. There was no folder a
     person owned, so there was nothing for access to be bounded by.
  2. knowledge_assets had no owner. uploaded_by existed and was written by the
     upload and report paths, but no query ever read it - list_assets, the
     download endpoint and semantic_search all scoped by organization only. Every
     member of an organization could therefore list, download and retrieve in
     their answers every other member's files. That is a cross-user leak, not a
     missing feature.

What this migration does:

  - knowledge_sources.user_id: the person whose folder this is. NULL keeps the
    existing meaning - one folder for the whole organization - which the
    on-premises scanner still needs, since it walks a path on the server itself
    that belongs to no single person.
  - Replaces UNIQUE(organization_id) with two PARTIAL unique indexes: one per
    (organization_id, user_id) where user_id IS NOT NULL, one per
    (organization_id) where user_id IS NULL. Partial because Postgres treats
    every NULL as distinct, so a plain UNIQUE(organization_id, user_id) would
    allow unlimited org-level rows.
  - knowledge_assets.owner_id: the user an asset belongs to. NULL means visible
    to the whole organization (the org-level folder's files, and rows written
    before this migration). Backfilled from uploaded_by, which already held the
    right value on the upload and report paths.

owner_id and uploaded_by are kept separate on purpose. uploaded_by answers "who
performed the action" and is audit-facing; owner_id answers "who may read this"
and is enforcement-facing. A future admin-uploaded file should stay readable by
its uploader's organization without becoming readable by the admin alone.

Revision ID: 0029
Revises: 0028
"""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- one folder per user -------------------------------------------------
    op.execute(
        "ALTER TABLE hiveos.knowledge_sources ADD COLUMN IF NOT EXISTS user_id uuid"
    )
    op.execute(
        """
        ALTER TABLE hiveos.knowledge_sources
        ADD CONSTRAINT fk_knowledge_sources_user_id_users
        FOREIGN KEY (user_id) REFERENCES hiveos.users(id) ON DELETE CASCADE
        """
    )
    # The old constraint allowed one folder per organization; the new model
    # allows one per user plus one org-level, so it must go.
    op.execute(
        "ALTER TABLE hiveos.knowledge_sources "
        "DROP CONSTRAINT IF EXISTS uq_knowledge_sources_per_org"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_sources_per_user
        ON hiveos.knowledge_sources (organization_id, user_id)
        WHERE user_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_sources_per_org
        ON hiveos.knowledge_sources (organization_id)
        WHERE user_id IS NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_sources_user_id "
        "ON hiveos.knowledge_sources (user_id)"
    )

    # --- asset ownership -----------------------------------------------------
    op.execute(
        "ALTER TABLE hiveos.knowledge_assets ADD COLUMN IF NOT EXISTS owner_id uuid"
    )
    op.execute(
        """
        ALTER TABLE hiveos.knowledge_assets
        ADD CONSTRAINT fk_knowledge_assets_owner_id_users
        FOREIGN KEY (owner_id) REFERENCES hiveos.users(id) ON DELETE CASCADE
        """
    )
    # Pre-existing rows already recorded the uploader. Without this backfill the
    # rows would be org-visible (owner_id IS NULL) and the leak would persist for
    # every file already in the database.
    op.execute(
        "UPDATE hiveos.knowledge_assets SET owner_id = uploaded_by "
        "WHERE owner_id IS NULL AND uploaded_by IS NOT NULL"
    )
    # Files discovered by an org-level folder scan belong to the organization.
    # Files discovered by a per-user folder belong to that user. The scan paths
    # set owner_id from the source's user_id; this index serves the list and
    # search filters, which always constrain on organization_id first.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_assets_org_owner "
        "ON hiveos.knowledge_assets (organization_id, owner_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS hiveos.ix_knowledge_assets_org_owner")
    op.execute(
        "ALTER TABLE hiveos.knowledge_assets "
        "DROP CONSTRAINT IF EXISTS fk_knowledge_assets_owner_id_users"
    )
    op.execute("ALTER TABLE hiveos.knowledge_assets DROP COLUMN IF EXISTS owner_id")

    op.execute("DROP INDEX IF EXISTS hiveos.ix_knowledge_sources_user_id")
    op.execute("DROP INDEX IF EXISTS hiveos.uq_knowledge_sources_per_org")
    op.execute("DROP INDEX IF EXISTS hiveos.uq_knowledge_sources_per_user")
    op.execute(
        "ALTER TABLE hiveos.knowledge_sources "
        "DROP CONSTRAINT IF EXISTS fk_knowledge_sources_user_id_users"
    )
    op.execute("ALTER TABLE hiveos.knowledge_sources DROP COLUMN IF EXISTS user_id")
    # Restoring the constraint can fail if the downgrade runs after a second
    # member of an organization registered a folder. That is correct: the data
    # genuinely does not fit the old model, and silently deleting folders to make
    # a downgrade succeed would destroy user data.
    op.execute(
        "ALTER TABLE hiveos.knowledge_sources "
        "ADD CONSTRAINT uq_knowledge_sources_per_org UNIQUE (organization_id)"
    )
