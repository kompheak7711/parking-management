"""The shared draft reads leave out the decision's transaction id (V1-056 slice 11b).

A confirmed draft's decision result may hold `transaction_id`, the database transaction that
applied it; the confirm commands use it only to recognise their own replay. The shared reads by
capability (`app.financial_draft_resource_by_capability`, `app.list_financial_drafts_by_capability`)
returned it for every kind. Since the slice 11b routes show these reads to staff, both now leave
it out for every kind (plan notes of sub-slices 10e-1a and 10f-2). The confirm commands keep
their own copies unchanged. No table or privilege changes.
"""

from alembic import op
from sqlalchemy import text

revision = "20270208_196"
down_revision = "20270207_195"
branch_labels = None
depends_on = None

STRIP = " #- '{decision,result,transaction_id}'"

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.financial_draft_resource_by_capability(uuid,uuid,uuid,text[])",
        (
            (
                "RETURN app.financial_draft_json(v_draft);",
                f"RETURN app.financial_draft_json(v_draft){STRIP};",
            ),
        ),
    ),
    (
        "app.list_financial_drafts_by_capability(uuid,uuid,text[],text,integer,timestamp with time zone,uuid)",
        (
            (
                "jsonb_agg(app.financial_draft_json(page.draft)",
                f"jsonb_agg(app.financial_draft_json(page.draft){STRIP}",
            ),
        ),
    ),
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Financial draft read contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("The draft read migration is forward-only")
