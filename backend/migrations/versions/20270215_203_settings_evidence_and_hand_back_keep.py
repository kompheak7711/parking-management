"""Two slice 12 fixes with no change to money (V1-056 slice 12a).

1. Settings writers name the capability they are authorized under. Since login sub-slice L5
   (Q-2026-10-24-186) the Service rate, Utility Rate and one-time charge Due Date days routes
   check `settings.manage`, but the database functions still wrote the old capability in their
   audit evidence (`service_rates.manage`, `utility_rates.manage`, `property.manage`), an
   exception to the migration `20261009_74` rule. They now write `settings.manage`. Earlier
   audit events keep what they recorded.
2. The hand-back assessment (`app.hand_back_rent_invoice_basis`, migration `20261017_82`) said
   `VOID` for an Invoice with nothing applied and nothing outstanding (a credit Adjustment took
   it to zero), because it tested "nothing applied" first. It now tests "nothing outstanding"
   first and says `KEEP`. The command refused that case before (the assessment said 0
   outstanding, which no resolution may expect, so it answered "assessment changed") and still
   refuses it ("kept as issued"), so no record changes; only the refusal changes.

Each function is patched by exact text; CREATE OR REPLACE keeps its owner, settings and grants.
"""

from alembic import op
from sqlalchemy import text

revision = "20270215_203"
down_revision = "20270214_202"
branch_labels = None
depends_on = None

PATCHES: tuple[tuple[str, str, str], ...] = (
    (
        "app.execute_service_rate(uuid,uuid,text,uuid,uuid,bigint,date,text,uuid)",
        "'service_rates.manage', p_property_id,",
        "'settings.manage', p_property_id,",
    ),
    (
        "app.set_one_time_charge_due_days(uuid,uuid,integer,integer,text,uuid)",
        "p_reason,'property.manage',",
        "p_reason,'settings.manage',",
    ),
    (
        "app.set_one_time_charge_due_days(uuid,uuid,integer,integer,text,uuid)",
        "jsonb_build_object('capability','property.manage')",
        "jsonb_build_object('capability','settings.manage')",
    ),
    (
        "app.hand_back_rent_invoice_basis(uuid,uuid,uuid)",
        "v_action:=CASE WHEN v_applied=0 THEN 'VOID' WHEN v_outstanding=0 THEN 'KEEP'",
        "v_action:=CASE WHEN v_outstanding=0 THEN 'KEEP' WHEN v_applied=0 THEN 'VOID'",
    ),
)


def _utility_signature() -> str:
    return str(
        op.get_bind()
        .execute(
            text(
                "SELECT oid::regprocedure::text FROM pg_catalog.pg_proc "
                "WHERE proname='execute_utility_rate' "
                "AND pronamespace='app'::regnamespace"
            )
        )
        .scalar_one()
    )


def _patch(signature: str, before: str, after: str) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    if definition.count(before) != 1:
        raise RuntimeError(f"Function contract changed: {signature}")
    op.execute(definition.replace(before, after))


def upgrade() -> None:
    for signature, before, after in PATCHES:
        _patch(signature, before, after)
    _patch(
        _utility_signature(),
        "'utility_rates.manage', p_property_id,",
        "'settings.manage', p_property_id,",
    )


def downgrade() -> None:
    raise RuntimeError("Settings evidence and hand-back KEEP migration is forward-only")
