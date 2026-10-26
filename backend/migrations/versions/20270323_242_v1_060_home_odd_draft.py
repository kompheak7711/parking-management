"""The Home page reads a Refund draft it does not understand as no amount (V1-060 B2).

Found by the V1-060 full PostgreSQL run: the Waiting for approval read (V1-058 R7a) gives a draft
payload it does not understand no amount and no error, but `app.home_page` cast the Refund
draft's `amount_usd_cents` straight to bigint (and a Payment return draft's `payment_id` straight
to uuid), so one such draft stopped the whole Home page with 22P02. The Home page now uses the
same checks as the Waiting for approval read (`20270314_233`): the amount counts only when it is
a JSON number of whole cents from 0 to 9,000,000,000,000,000, and the Payment id is read with
`app.draft_uuid` (NULL when it is not a uuid). The draft still counts as waiting. Drafts made by
the app always pass these checks, so no total changes for them. Exact-text replacements (each
checked to match once); same signature, settings and privileges. Decided by Claude under the
owner's 2026-10-23 22:30 rule (a read, no rule or amount changes).
"""

from alembic import op
from sqlalchemy import text

revision = "20270323_242"
down_revision = "20270322_241"
branch_labels = None
depends_on = None

HOME = "app.home_page(uuid,uuid,uuid[],text[])"

REFUND_BEFORE = "WHEN 'REFUND' THEN (draft.payload->>'amount_usd_cents')::bigint\n"
# Nested CASE: only a JSON number is cast (AND does not promise an order of evaluation).
REFUND_AFTER = (
    "WHEN 'REFUND' THEN CASE WHEN jsonb_typeof(draft.payload->'amount_usd_cents')='number'\n"
    "                        THEN CASE WHEN (draft.payload->>'amount_usd_cents')::numeric\n"
    "                                BETWEEN 0 AND 9000000000000000\n"
    "                            AND (draft.payload->>'amount_usd_cents')::numeric\n"
    "                                =trunc((draft.payload->>'amount_usd_cents')::numeric)\n"
    "                            THEN (draft.payload->>'amount_usd_cents')::numeric::bigint\n"
    "                        END END\n"
)
PAYMENT_BEFORE = "AND payment.id=(draft.payload->>'payment_id')::uuid\n"
PAYMENT_AFTER = "AND payment.id=app.draft_uuid(draft.payload->>'payment_id')\n"
REPLACEMENTS = ((REFUND_BEFORE, REFUND_AFTER), (PAYMENT_BEFORE, PAYMENT_AFTER))


def upgrade() -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": HOME},
        )
        .scalar_one()
    )
    for before, after in REPLACEMENTS:
        if definition.count(before) != 1:
            raise RuntimeError(f"V1-060 Home page contract changed: {HOME}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def downgrade() -> None:
    raise RuntimeError("V1-060 Home page migration is forward-only")
