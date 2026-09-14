"""Per-user agent, memory and tool-invocation tables (PO 2026-09).

Three new tables, all additive - no existing table is altered and no existing
row is touched, so this migration is safe to run against a live database and
its downgrade is a clean drop.

  1. user_agents           - one agent per (organization_id, user_id).
                             UNIQUE(organization_id, user_id) is the whole
                             contract: it is what makes the agent per-user
                             rather than per-org, and it is enforced by the
                             database rather than by application code.
  2. agent_memories        - what one user's agent remembers. Embeds at
                             HALFVEC(1024) to match knowledge_chunks, which is
                             the same provider and width, so the two stores
                             stay comparable.
  3. agent_tool_invocations- the trace of every tool call.

Why HALFVEC(1024) and not a fresh vector column type: migration 0025 moved
knowledge_chunks to halfvec for the memory saving. Using the same type here
means one embedding provider config serves both, and a memory vector can be
compared against a chunk vector without a cast.

Indexes are chosen from the actual read paths, not speculatively:
  - the memory retrieval query is "active memories for (org, user), best first"
  - the tool trace is read per organization in time order
  - the invocation lookup is by execution when debugging a single run

Revision ID: 0028
Revises: 0027
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS hiveos.user_agents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES hiveos.organizations(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES hiveos.users(id) ON DELETE CASCADE,
            brain_id uuid REFERENCES hiveos.organization_brains(id) ON DELETE SET NULL,
            display_name varchar(120) NOT NULL DEFAULT '',
            persona text NOT NULL DEFAULT '',
            allowed_tools jsonb NOT NULL DEFAULT '[]'::jsonb,
            settings jsonb NOT NULL DEFAULT '{}'::jsonb,
            status varchar(10) NOT NULL DEFAULT 'active',
            version integer NOT NULL DEFAULT 1,
            last_active_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_agents_org_user UNIQUE (organization_id, user_id),
            CONSTRAINT ck_user_agents_status_allowed_values
                CHECK (status IN ('active', 'paused', 'archived'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_agents_org_status "
        "ON hiveos.user_agents (organization_id, status)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS hiveos.agent_memories (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES hiveos.organizations(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES hiveos.users(id) ON DELETE CASCADE,
            agent_id uuid NOT NULL REFERENCES hiveos.user_agents(id) ON DELETE CASCADE,
            kind varchar(12) NOT NULL DEFAULT 'fact',
            content text NOT NULL,
            weight double precision NOT NULL DEFAULT 1.0,
            active boolean NOT NULL DEFAULT true,
            hits integer NOT NULL DEFAULT 0,
            misses integer NOT NULL DEFAULT 0,
            source_execution_id uuid REFERENCES hiveos.agent_executions(id) ON DELETE SET NULL,
            source_message_id uuid REFERENCES hiveos.chat_messages(id) ON DELETE SET NULL,
            embedding halfvec(1024),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_agent_memories_kind_allowed_values
                CHECK (kind IN ('fact', 'preference', 'decision', 'summary')),
            CONSTRAINT ck_agent_memories_weight_positive CHECK (weight >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_memories_agent_kind "
        "ON hiveos.agent_memories (agent_id, kind)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_memories_org_user_active "
        "ON hiveos.agent_memories (organization_id, user_id, active)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS hiveos.agent_tool_invocations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES hiveos.organizations(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES hiveos.users(id) ON DELETE CASCADE,
            agent_id uuid REFERENCES hiveos.user_agents(id) ON DELETE SET NULL,
            execution_id uuid REFERENCES hiveos.agent_executions(id) ON DELETE SET NULL,
            tool_name varchar(80) NOT NULL,
            arguments jsonb NOT NULL DEFAULT '{}'::jsonb,
            ok boolean NOT NULL DEFAULT true,
            error_message text,
            result_preview text,
            asset_id uuid REFERENCES hiveos.knowledge_assets(id) ON DELETE SET NULL,
            duration_ms integer NOT NULL DEFAULT 0,
            round_index integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_tool_invocations_org_created "
        "ON hiveos.agent_tool_invocations (organization_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_tool_invocations_execution "
        "ON hiveos.agent_tool_invocations (execution_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_tool_invocations_agent "
        "ON hiveos.agent_tool_invocations (agent_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hiveos.agent_tool_invocations")
    op.execute("DROP TABLE IF EXISTS hiveos.agent_memories")
    op.execute("DROP TABLE IF EXISTS hiveos.user_agents")
