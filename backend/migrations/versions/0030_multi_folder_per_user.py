"""Multiple folders per user (PO request 2026-09).

The PO changed the folder model:

    "کاربر باید بتونه چندتا پوشه تعریف کنه. یعنی هر پوشه ای که تعریف کرد میره
     و دکمه اضافه کردن پوشه جدید میزنه و یکی دیگه اضافه میکنه. اینجوری دیگه
     یکی مثل مدیرها به تمام دانش دسترسی دارن. درواقع ما تمام دانش سازمان رو
     جمع آوری میکنیم ولی هر کسی به اندازه سطح دسترسش به اون اطلاعات دسترسی داره"

A user registers MANY folders. Every folder's content still lands in the
organization's knowledge; a folder is PROVENANCE (who contributed it, where it
came from), not an access boundary. Reading is decided by the asset's
owner_id (per-user files vs org-wide files) plus the organization-admin bypass
added in the same change, never by "which folder is mine".

Migration 0029 enforced the older "one folder per user" reading with two partial
UNIQUE indexes:

    uq_knowledge_sources_per_user  (organization_id, user_id) WHERE user_id IS NOT NULL
    uq_knowledge_sources_per_org   (organization_id)          WHERE user_id IS NULL

Both make the PO's request impossible - a second folder for the same user (or a
second org-wide folder) violates them. They are replaced here by ONE ordinary
NON-unique index over (organization_id, user_id), which is all the read paths
need to list "the folders visible to this caller". Uniqueness is now enforced
per PATH inside service.register_folder_source, which is where "the exact same
path is already registered for this user" is actually known. It cannot be a
database constraint: the same path may legitimately be registered by two
different users (a shared network drive), and path spelling differs between the
client's Windows path and the server's own.

ix_knowledge_sources_user_id is left in place: it belongs to the lookup by the
folders a person owns and remains useful.

Revision ID: 0030
Revises: 0029
"""

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The two partial unique indexes are what blocked a second folder. Drop
    # both, then index the pair the list query filters on.
    op.execute("DROP INDEX IF EXISTS hiveos.uq_knowledge_sources_per_user")
    op.execute("DROP INDEX IF EXISTS hiveos.uq_knowledge_sources_per_org")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_knowledge_sources_org_user
        ON hiveos.knowledge_sources (organization_id, user_id)
        """
    )
    # ix_knowledge_sources_user_id (created by 0029) is intentionally kept: it
    # is the index for "every folder this person owns".


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS hiveos.ix_knowledge_sources_org_user")
    # Restoring UNIQUE here can fail if a user registered more than one folder
    # (or an organization gained a second org-wide folder) while 0030 was
    # applied - the data genuinely does not fit the one-folder-per-user model,
    # and silently deleting the extra folders to make the downgrade succeed
    # would destroy the user's data. That failure is correct.
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
