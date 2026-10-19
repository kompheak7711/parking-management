# ruff: noqa: E501
"""The adjusted required total in two readers of the first amount (V1-056 sub-slice 10e-2b-4f).

BR-DEP-004, BR-LEASE-005, DL-008, DL-066; DB-DEP-001, DB-DEP-003; owner answer (a) to
Q-2026-10-18-130: a Deposit's required total is its first amount plus the adjustments recorded by
then, and every reader uses it.

New internal app.deposit_required_total_at(deposit, as_of) (no grant): the first amount plus each
required-amount adjustment recorded at or before as_of (INCREASE adds, DECREASE subtracts); with
'infinity' it equals the snapshot's required_usd_cents; NULL for an unknown Deposit or a NULL time.

Exact-text patches (each replacement checked to match once): app.require_lease_termination_context
(the BR-LEASE-005 ground compares the Security Deposit's held value at the termination time with
the required total recorded by that time) and app.complete_reservation_move_in (the old move-in
of Leases signed before migration 69: the Security Deposit and each required Pet Deposit count
only receipts with no reversal, which must reach at least the current required total; the
active-receipt rule is an approved tightening of that old path, and a total lowered below what
was received no longer needs equality). The Reservation read API reads the snapshot's total
(application code). No table, column, trigger, constraint or grant changes.
"""

from alembic import op
from sqlalchemy import text

revision = "20270106_163"
down_revision = "20270105_162"
branch_labels = None
depends_on = None

SQL = """
    -- Sub-slice 10e-2b-4f (owner answer (a) to Q-2026-10-18-130): the required total recorded
    -- by a time, adjustments included (BR-DEP-004).
    CREATE FUNCTION app.deposit_required_total_at(p_deposit uuid,p_as_of timestamptz)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT (deposit.required_usd_cents + COALESCE((
            SELECT sum(CASE adjustment.adjustment_type WHEN 'INCREASE'
                THEN adjustment.amount_usd_cents ELSE -adjustment.amount_usd_cents END)
            FROM app.deposit_required_amount_adjustments AS adjustment
            WHERE adjustment.deposit_id=deposit.id AND adjustment.occurred_at<=p_as_of
        ),0))::bigint
        FROM app.deposits AS deposit
        WHERE deposit.id=p_deposit AND p_as_of IS NOT NULL
    $$;
"""

INTERNAL = ("app.deposit_required_total_at(uuid,timestamp with time zone)",)

GROUND = "app.require_lease_termination_context(uuid,uuid,text,uuid,uuid,integer,date,timestamp with time zone,text,text,uuid)"
GROUND_REPLACEMENTS = (
    (
        "                          AND app.deposit_held_value_at(deposit.id,p_occurred)<deposit.required_usd_cents)))\n",
        "                          -- Sub-slice 10e-2b-4f (owner answer (a) to Q-2026-10-18-130): the\n"
        "                          -- required total recorded by the termination time.\n"
        "                          AND app.deposit_held_value_at(deposit.id,p_occurred)\n"
        "                              <app.deposit_required_total_at(deposit.id,p_occurred))))\n",
    ),
)

MOVE_IN = "app.complete_reservation_move_in(uuid,uuid,text,uuid,uuid,uuid,integer,integer,integer,date,jsonb,text,text,uuid)"
MOVE_IN_REPLACEMENTS = (
    (
        "              AND timezone(v_timezone, receipt.occurred_at)::date <= p_actual_move_in_date;\n"
        "            IF v_deposit.lease_id IS NOT NULL\n"
        "                OR v_received <> v_deposit.required_usd_cents\n",
        "              AND timezone(v_timezone, receipt.occurred_at)::date <= p_actual_move_in_date\n"
        "              -- Sub-slice 10e-2b-4f (owner answer (a) to Q-2026-10-18-130): only active\n"
        "              -- receipts, at least the current required total with its adjustments (a\n"
        "              -- total lowered below what was received does not refuse; NULL refuses).\n"
        "              AND NOT EXISTS (SELECT 1 FROM app.deposit_receipt_reversals AS reversal\n"
        "                  WHERE reversal.deposit_receipt_id = receipt.id);\n"
        "            IF v_deposit.lease_id IS NOT NULL\n"
        "                OR NOT COALESCE(\n"
        "                    v_received >= app.deposit_required_total_at(v_deposit.id, 'infinity'), false)\n",
    ),
    (
        "                              AND timezone(v_timezone, receipt.occurred_at)::date\n"
        "                                  <= p_actual_move_in_date\n"
        "                        ) = pet_deposit.required_usd_cents\n",
        "                              AND timezone(v_timezone, receipt.occurred_at)::date\n"
        "                                  <= p_actual_move_in_date\n"
        "                              -- Sub-slice 10e-2b-4f: only active receipts, at least the\n"
        "                              -- current required total with its adjustments.\n"
        "                              AND NOT EXISTS (SELECT 1 FROM app.deposit_receipt_reversals AS reversal\n"
        "                                  WHERE reversal.deposit_receipt_id = receipt.id)\n"
        "                        ) >= app.deposit_required_total_at(pet_deposit.id, 'infinity')\n",
    ),
)

PATCHES = ((GROUND, GROUND_REPLACEMENTS), (MOVE_IN, MOVE_IN_REPLACEMENTS))


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
            raise RuntimeError(f"Deposit required total reader contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SQL)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Deposit required total reader migration is forward-only")
