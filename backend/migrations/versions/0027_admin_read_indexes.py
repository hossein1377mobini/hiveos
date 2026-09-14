"""Indexes for the admin panel's hot read paths (PO request: performance).

Measured before writing this, on a synthetic 500k-row table with a correlated
per-parent count: 200 parents took 3,650 / 3,668 / 3,654 ms without an index on
the correlated column and 99 / 105 ms with one - a 37x difference at that size,
and the ratio grows with row count because the unindexed plan is a sequential
scan per parent.

Three of the queries in admin.py have exactly that shape:

  1. organization_members.user_id. The table has UNIQUE(organization_id,
     user_id), which cannot serve a lookup by user_id alone, yet admin.py asks
     "how many organizations does this user belong to" and the owner-orphan
     check filters m2.user_id = u.id per user.
  2. audit_logs.actor_user_id and (entity_type, entity_id). The log view filters
     by actor and the detail drawer pivots by entity; the only indexes present
     are (organization_id, created_at) and (event).
  3. agent_executions.status and knowledge_assets.status. /admin/system-status
     runs nineteen scalar counts every fifteen seconds and five of them filter
     on status over these tables.

All of these are additive and partial where the predicate is static, so the
index stays small. Nothing here changes a query result, only its plan.

Revision ID: 0027
Revises: 0026
"""

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_members_user_id "
        "ON hiveos.organization_members (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_user_id "
        "ON hiveos.audit_logs (actor_user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_entity "
        "ON hiveos.audit_logs (entity_type, entity_id)"
    )
    # Partial: the dashboard counts active work, and finished rows are the
    # overwhelming majority of both tables, so excluding them keeps each index
    # proportional to the live set rather than to history.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_executions_active "
        "ON hiveos.agent_executions (status) "
        "WHERE status IN ('PENDING', 'STARTING', 'RUNNING', 'CANCELLING')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_assets_live_status "
        "ON hiveos.knowledge_assets (status) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    for name in (
        "ix_organization_members_user_id",
        "ix_audit_logs_actor_user_id",
        "ix_audit_logs_entity",
        "ix_agent_executions_active",
        "ix_knowledge_assets_live_status",
    ):
        op.execute(f"DROP INDEX IF EXISTS hiveos.{name}")
