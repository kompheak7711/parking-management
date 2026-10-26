"""The Home page reads a Refund draft it does not understand as no amount (V1-060 B2).

Found by the V1-060 full PostgreSQL run: the Waiting for approval read (V1-058 R7a) gives a draft
payload it does not understand no amount and no error, but `app.home_page` cast the Refund
draft's `amount_usd_cents` straight to bigint, so one such draft stopped the whole Home page with
22P02. The Home page now counts only a JSON number as the amount, as the Waiting for approval
read does; the draft still counts as waiting. Drafts made by the app always hold a whole number
of cents, so no total changes for them. One exact-text replacement (checked to match once); same
signature, settings and privileges. Decided by Claude under the owner's 2026-10-23 22:30 rule
(a read, no rule or amount changes).
"""

from alembic import op
from sqlalchemy import text

revision = "20270323_242"
down_revision = "20270322_241"
branch_labels = None
depends_on = None

HOME = "app.home_page(uuid,uuid,uuid[],text[])"

REFUND_BEFORE = "WHEN 'REFUND' THEN (draft.payload->>'amount_usd_cents')::bigint\n"
REFUND_AFTER = (
    "WHEN 'REFUND' THEN CASE WHEN jsonb_typeof(draft.payload->'amount_usd_cents')='number'\n"
    "                        THEN (draft.payload->>'amount_usd_cents')::numeric END\n"
)


def upgrade() -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": HOME},
        )
        .scalar_one()
    )
    if definition.count(REFUND_BEFORE) != 1:
        raise RuntimeError(f"V1-060 Home page contract changed: {HOME}")
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition.replace(REFUND_BEFORE, REFUND_AFTER))


def downgrade() -> None:
    raise RuntimeError("V1-060 Home page migration is forward-only")
