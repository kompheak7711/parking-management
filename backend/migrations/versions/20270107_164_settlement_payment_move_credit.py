# ruff: noqa: E501
"""The narrow Credit and Refund refusal inside the PAYMENT_MOVE correction (V1-056 sub-slice 10g-2).

BR-PAY-042, BR-SETTLE-013, BR-SETTLE-016, DL-030, DL-068; DB-PAY-008, DB-SETTLE-005; owner answer
(a) to Q-2026-10-17-121: inside the PAYMENT_MOVE correction of a closed Final Settlement only, the
blanket refusal of a Payment with Customer Credit not reversed or a Refund not fully returned
becomes a narrow one. The correction moves only the wrong allocation, which is still active, so its
value never became Credit or a Refund; the Payment's Credit and Refunds come from its other value,
stay where they are and do not change, nor does the Settlement's use of them. Still refused: such a
Payment where a credit Adjustment (one-call, or written by a correction) released any part of an
allocation of this Payment on the wrong Invoice (that Credit came from the wrong money), and every
other slice 7 and 10g refusal. The slice 7 move draft keeps the blanket rule (owner answer 4 to
Q-2026-10-05-16); a NULL fourth argument also reads as the blanket rule.

New internal app.wrong_unit_move_source(property, allocation, target invoice, settlement
correction) (no grant), built from the current definition of app.payment_move_source by two
exact-text replacements (each checked to match once): its name and fourth argument, and the Credit
and Refund refusal, which keeps the blanket condition and, for a settlement correction, also needs
the release. app.payment_move_source keeps its signature and settings and calls it with false
(whole-body replacement), so slice 7 keeps one body and its refusals in their order;
app.settlement_payment_move_source (one exact-text replacement) calls it with true. The source keeps
its keys, so a waiting correction draft's digest does not change. No table, column, trigger,
constraint or grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20270107_164"
down_revision = "20270106_163"
branch_labels = None
depends_on = None

SOURCE = "app.payment_move_source(uuid,uuid,uuid)"
INTERNAL = ("app.wrong_unit_move_source(uuid,uuid,uuid,boolean)",)
SETTLEMENT_SOURCE = "app.settlement_payment_move_source(uuid,uuid,uuid,uuid)"

NEW_SOURCE_REPLACEMENTS = (
    (
        "CREATE OR REPLACE FUNCTION app.payment_move_source(p_property uuid, p_allocation uuid, p_target_invoice uuid)",
        "CREATE FUNCTION app.wrong_unit_move_source(p_property uuid, p_allocation uuid, p_target_invoice uuid, p_settlement_correction boolean)",
    ),
    (
        "            -- Answer 4: Credit and Refunds are recorded per Payment, so any Credit not reversed or\n"
        "            -- any Refund not fully returned blocks the move.\n"
        "            IF app.payment_credit_value_at(v_payment.id,'infinity'::timestamptz)>0\n"
        "                OR app.payment_refunded_value_at(v_payment.id,'infinity'::timestamptz)>0\n"
        "            THEN RAISE EXCEPTION",
        "            -- Answer 4: Credit and Refunds are recorded per Payment, so any Credit not reversed or\n"
        "            -- any Refund not fully returned blocks the move. Owner answer (a) to Q-2026-10-17-121:\n"
        "            -- a PAYMENT_MOVE correction of a closed Final Settlement moves only the wrong\n"
        "            -- allocation's own value, still on that active allocation, so they block it only\n"
        "            -- when a credit Adjustment released any part of an allocation of this Payment on\n"
        "            -- the wrong Invoice (that Credit came from the wrong money).\n"
        "            IF (app.payment_credit_value_at(v_payment.id,'infinity'::timestamptz)>0\n"
        "                OR app.payment_refunded_value_at(v_payment.id,'infinity'::timestamptz)>0)\n"
        "                AND (NOT COALESCE(p_settlement_correction,false) OR EXISTS (\n"
        "                    SELECT 1 FROM app.invoice_credit_excess_releases release\n"
        "                    JOIN app.payment_allocations released\n"
        "                        ON released.id=release.reversed_payment_allocation_id\n"
        "                    WHERE released.payment_id=v_payment.id\n"
        "                      AND released.invoice_id=v_source_invoice.id))\n"
        "            THEN RAISE EXCEPTION",
    ),
)

SLICE_7_SOURCE_SQL = """
    -- Sub-slice 10g-2: the slice 7 move draft keeps the blanket Credit and Refund refusal (owner
    -- answer 4 to Q-2026-10-05-16); the one body is app.wrong_unit_move_source.
    CREATE OR REPLACE FUNCTION app.payment_move_source(p_property uuid,p_allocation uuid,p_target_invoice uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    BEGIN
        RETURN app.wrong_unit_move_source(p_property,p_allocation,p_target_invoice,false);
    END $$;
"""

SETTLEMENT_SOURCE_REPLACEMENTS = (
    (
        "        RETURN app.payment_move_source(p_property,p_allocation,p_target_invoice)\n",
        "        -- Sub-slice 10g-2 (owner answer (a) to Q-2026-10-17-121): the narrow Credit and\n"
        "        -- Refund refusal of the correction.\n"
        "        RETURN app.wrong_unit_move_source(p_property,p_allocation,p_target_invoice,true)\n",
    ),
)


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _replaced(signature: str, replacements: tuple[tuple[str, str], ...]) -> str:
    definition = _definition(signature)
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Settlement Payment move Credit contract changed: {signature}")
        definition = definition.replace(before, after)
    return definition


def upgrade() -> None:
    # The new function is built from the slice 7 body before that body is replaced.
    op.execute(_replaced(SOURCE, NEW_SOURCE_REPLACEMENTS))
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    # CREATE OR REPLACE keeps each function's identity, owner and privileges.
    op.execute(SLICE_7_SOURCE_SQL)
    op.execute(_replaced(SETTLEMENT_SOURCE, SETTLEMENT_SOURCE_REPLACEMENTS))


def downgrade() -> None:
    raise RuntimeError("Settlement Payment move Credit migration is forward-only")
