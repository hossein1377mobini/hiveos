"""Files a reply produced, stored on the assistant message (PO request 2026-09).

The PO reported that a generated file is neither shown in the chat nor
findable afterwards:

    "فایل که می‌سازه اولاً توی چت نمایش نمیده و دوماً معلوم نیست اصن ساخته
     میشه یا نه یا ادرس ساختش چیه"

The agent's report/chart tools already write a real KnowledgeAsset row (see
backend/knowledge/reporting.save_report) and return its id in the tool result's
meta, and the execution already traced that id on agent_tool_invocations. What
was missing was the user-visible half: the id never reached the reply.

This column is the durable half of the fix, stored exactly the way citations
already are (a JSON list beside the message content) so history reload shows the
file just like it shows sources. The live half is execution.output["artifacts"],
written in the same turn.

Nullable with no default: every existing message predates the feature and
genuinely has no artifacts, and a NULL list is the same absence as an empty one.

Revision ID: 0031
Revises: 0030
"""

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hiveos.chat_messages ADD COLUMN IF NOT EXISTS artifacts jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE hiveos.chat_messages DROP COLUMN IF EXISTS artifacts")
