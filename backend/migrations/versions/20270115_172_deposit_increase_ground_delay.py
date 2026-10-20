# ruff: noqa: E501
"""An increase counts for the unpaid-Initial ground only five days after its record (V1-056 sub-slice 10i-2).

BR-LEASE-005, BR-DEP-004, DL-066; owner answer (b) to Q-2026-10-19-138: an increase of the required
Security Deposit total counts for the unpaid-Initial termination ground only from the later of Lease
Start plus five days and five days after the increase was recorded, so the Customer always gets five
days to pay it. A decrease counts from its record, as before.

New internal app.deposit_ground_required_total_at(deposit, as_of) (no grant): the first amount, each
DECREASE recorded at or before as_of, and each INCREASE recorded at or before as_of whose business date
(Asia/Phnom_Penh, the ground's own date rule) plus five days is before the business date of as_of;
NULL for an unknown Deposit or a NULL time. The ground already requires a termination date after
Lease Start plus five days.

Exact-text patch (checked to match once) of app.require_lease_termination_context: the Security
Deposit branch compares the held value with the new total. app.deposit_required_total_at and its
other reader (the old Reservation move-in) are unchanged. No table, column, trigger, constraint or
grant change; signatures, owners, settings and privileges are kept.
"""

from alembic import op
from sqlalchemy import text

revision = "20270115_172"
down_revision = "20270114_171"
branch_labels = None
depends_on = None

SQL = """
    -- Sub-slice 10i-2 (owner answer (b) to Q-2026-10-19-138): the required total the BR-LEASE-005
    -- ground reads; an increase counts only after its business date plus five days.
    CREATE FUNCTION app.deposit_ground_required_total_at(p_deposit uuid,p_as_of timestamptz)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT (deposit.required_usd_cents + COALESCE((
            SELECT sum(CASE adjustment.adjustment_type WHEN 'INCREASE'
                THEN adjustment.amount_usd_cents ELSE -adjustment.amount_usd_cents END)
            FROM app.deposit_required_amount_adjustments AS adjustment
            WHERE adjustment.deposit_id=deposit.id AND adjustment.occurred_at<=p_as_of
              AND (adjustment.adjustment_type='DECREASE'
                OR timezone('Asia/Phnom_Penh',adjustment.occurred_at)::date+5
                    <timezone('Asia/Phnom_Penh',p_as_of)::date)
        ),0))::bigint
        FROM app.deposits AS deposit
        WHERE deposit.id=p_deposit AND p_as_of IS NOT NULL
    $$;
"""

INTERNAL = ("app.deposit_ground_required_total_at(uuid,timestamp with time zone)",)

GROUND = "app.require_lease_termination_context(uuid,uuid,text,uuid,uuid,integer,date,timestamp with time zone,text,text,uuid)"
GROUND_REPLACEMENTS = (
    (
        "                          -- Sub-slice 10e-2b-4f (owner answer (a) to Q-2026-10-18-130): the\n"
        "                          -- required total recorded by the termination time.\n"
        "                          AND app.deposit_held_value_at(deposit.id,p_occurred)\n"
        "                              <app.deposit_required_total_at(deposit.id,p_occurred))))\n",
        "                          -- Sub-slice 10e-2b-4f (owner answer (a) to Q-2026-10-18-130): the\n"
        "                          -- required total recorded by the termination time; sub-slice 10i-2\n"
        "                          -- (owner answer (b) to Q-2026-10-19-138): an increase counts only\n"
        "                          -- after its business date plus five days.\n"
        "                          AND app.deposit_held_value_at(deposit.id,p_occurred)\n"
        "                              <app.deposit_ground_required_total_at(deposit.id,p_occurred))))\n",
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
            raise RuntimeError(f"Deposit increase ground delay contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SQL)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    _patch(GROUND, GROUND_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("Deposit increase ground delay migration is forward-only")
