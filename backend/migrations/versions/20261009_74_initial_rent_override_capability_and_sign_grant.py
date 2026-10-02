# ruff: noqa: E501
"""Record the real capability of an Initial Rent Due Date override and retire the old sign grant.

Additive for records: a new overload of ``app.set_initial_rent_due_date`` takes the capability the
caller was authorized under (``billing.generate`` or ``invoices.issue``) and writes it into the audit
evidence. The six-argument function keeps recording ``billing.generate`` for the billing service
path. No earlier record is rewritten. The runtime role also loses direct EXECUTE on the old
``app.sign_lease``; signing runs through ``app.sign_lease_with_reservation``, a SECURITY DEFINER
function that still calls it.
"""

from alembic import op
from sqlalchemy import text

revision = "20261009_74"
down_revision = "20261008_73"
branch_labels = None
depends_on = None

OLD = "app.set_initial_rent_due_date(uuid,uuid,uuid,uuid,date,text)"
NEW = "app.set_initial_rent_due_date(uuid,uuid,uuid,uuid,date,text,text)"
SIGN = "app.sign_lease(uuid,uuid,text,uuid,uuid,integer,timestamptz,text,uuid)"
CHECK = """
        BEGIN
            IF p_capability IS NULL OR p_capability NOT IN ('billing.generate','invoices.issue') THEN
                RAISE EXCEPTION 'Initial Rent Due Date capability is invalid' USING ERRCODE='22023';
            END IF;
"""


def upgrade() -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": OLD},
        )
        .scalar_one()
    )
    for before, count in (
        ("p_reason text)\n", 1),
        ("'billing.generate'", 2),
        ("\n        BEGIN\n", 1),
    ):
        if definition.count(before) != count:
            raise RuntimeError("Initial Rent Due Date source contract changed")
    definition = definition.replace("p_reason text)\n", "p_reason text, p_capability text)\n")
    definition = definition.replace("'billing.generate'", "p_capability")
    definition = definition.replace("\n        BEGIN\n", CHECK, 1)
    op.execute(definition)
    op.execute(f"REVOKE ALL ON FUNCTION {NEW} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap")
    op.execute(f"GRANT EXECUTE ON FUNCTION {NEW} TO prm_financial")
    op.execute(f"REVOKE EXECUTE ON FUNCTION {SIGN} FROM prm_runtime")


def downgrade() -> None:
    raise RuntimeError("Initial Rent override capability and sign grant change is forward-only")
