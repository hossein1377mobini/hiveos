"""AvalAI cost basis on the wallet transaction (PO requirement 2026-09).

"میزان مصرف هر کاربر باید دقیقا برمبنای نحوه محاسبه میزان مصرف توی مستندات
aval ai باشه. هر طور که اون انجام میده ما هم باید."

Deductions used to be an unexplained integer: cost = ceil(tokens_out * rate /
1000), output tokens only, one flat admin rate, no record of what it was
computed from. That cannot be reconciled against anything the provider reports.

From this revision a DEDUCTION carries the provider's own USD figure
(cost_usd, from AvalAI's public /public/models price list applied to the three
token classes in the response usage object) and the full basis it came from
(cost_basis: model, prompt/cached/completion/reasoning tokens, the three rates
used, the USD->credit rate, and which source produced the number).

Both columns are nullable: every CHARGE row predates them and genuinely has no
cost basis, and a DEDUCTION that fell back to the admin rate has no USD figure.
An absent basis is the same absence as a NULL one, so no backfill is invented.

Revision ID: 0032
Revises: 0031
"""

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hiveos.wallet_transactions"
        " ADD COLUMN IF NOT EXISTS cost_usd numeric(18, 8)"
    )
    op.execute(
        "ALTER TABLE hiveos.wallet_transactions"
        " ADD COLUMN IF NOT EXISTS cost_basis jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE hiveos.wallet_transactions DROP COLUMN IF EXISTS cost_usd")
    op.execute("ALTER TABLE hiveos.wallet_transactions DROP COLUMN IF EXISTS cost_basis")
