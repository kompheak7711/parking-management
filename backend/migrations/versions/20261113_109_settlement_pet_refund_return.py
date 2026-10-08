# ruff: noqa: E501
"""Post-settlement correction: a returned Pet Refund-review Refund (V1-056 sub-slice 10c-2b-2b).

BR-SETTLE-013, BR-REFUND-014, DL-053, DL-032, BR-DEP-022, BR-AUTH-010; owner answer 6 to Q-2026-10-08-55, the
owner answer to Q-2026-10-08-60 and the owner instruction of 2026-10-09 on the gap named in review
round 3 of sub-slice 10c-2b-2a:

- Approved tightening (owner answer 6 to Q-2026-10-08-55): once the Lease's Final Settlement is
  closed, a Pet Refund-review Refund (DL-053, paid while the Lease was signed) is no longer
  returned with one call, and no return of it is reversed with one call (P5S01, a conflict). The
  Refund correction check refuses every other row for such a Refund (P5S01), except the verified
  return of its own REFUND_RETURN correction. So an older one-call return of such a Refund cannot
  be reversed against Pet Deposit money that a return-only correction left held (the 2026-10-09
  owner instruction).
- The REFUND_RETURN correction of sub-slices 10c-2b-1 and 10c-2b-2a also returns a Pet
  Refund-review Refund of the Settlement's Lease: the returned amount goes back to the Pet Deposit
  (DB-DER-004). A return-only correction leaves it held; with a new Refund the shared DL-032 step
  runs, only on the DL-032 path (sub-slice 10c-2b-2a).
- Approved tightening (owner answer to Q-2026-10-08-60, as the answers to Q-2026-10-08-51 and
  Q-2026-10-08-59): a Lease Deposit forfeiture draft is recorded only at READ COMMITTED (55000).

One function is replaced in place (CREATE OR REPLACE keeps owner and privileges); three functions
are patched in place: the one-call Refund correction source check, the Refund correction check and
the Lease forfeiture recorder.
"""

from alembic import op
from sqlalchemy import text

revision = "20261113_109"
down_revision = "20261112_108"
branch_labels = None
depends_on = None

CORRECTABLE = "app.require_correctable_usd_refund(uuid,uuid)"
CORRECTABLE_REPLACEMENTS = (
    (
        "            IF v_refund.pet_refund_review_id IS NOT NULL THEN\n"
        "                PERFORM app.serialize_deposit_state(v_refund.source_deposit_id);\n"
        "            ELSE\n",
        "            IF v_refund.pet_refund_review_id IS NOT NULL THEN\n"
        "                PERFORM app.serialize_deposit_state(v_refund.source_deposit_id);\n"
        "                -- Sub-slice 10c-2b-2b (owner answer 6 to Q-2026-10-08-55, approved tightening):\n"
        "                -- once the Lease's Final Settlement is closed, a Pet Refund-review Refund is\n"
        "                -- returned only through a post-settlement correction and no return of it is\n"
        "                -- reversed. Read after the Deposit lock: at READ COMMITTED a closure committed\n"
        "                -- meanwhile is seen; a REPEATABLE READ snapshot older than the closure already\n"
        "                -- failed above on the Deposit guard the closure updated (40001).\n"
        "                IF EXISTS(SELECT 1 FROM app.final_settlements settlement\n"
        "                    JOIN app.deposits deposit ON deposit.lease_id=settlement.lease_id\n"
        "                    WHERE deposit.id=v_refund.source_deposit_id AND settlement.closed_at IS NOT NULL)\n"
        "                THEN RAISE EXCEPTION 'A closed Final Settlement''s Pet Deposit Refund is corrected only through a post-settlement correction'\n"
        "                    USING ERRCODE='P5S01'; END IF;\n"
        "            ELSE\n",
    ),
)

GENERAL_CORRECTION = "app.validate_general_refund_correction()"
GENERAL_CORRECTION_REPLACEMENTS = (
    (
        "            IF v_refund.source_deposit_id IS NOT NULL THEN\n"
        "                PERFORM app.serialize_deposit_state(v_refund.source_deposit_id);\n"
        "                v_property:=app.deposit_property_id(v_refund.source_deposit_id);\n",
        "            IF v_refund.source_deposit_id IS NOT NULL THEN\n"
        "                PERFORM app.serialize_deposit_state(v_refund.source_deposit_id);\n"
        "                -- Sub-slice 10c-2b-2b (owner answer 6 to Q-2026-10-08-55, approved tightening):\n"
        "                -- once the Lease's Final Settlement is closed, a Pet Refund-review Refund takes\n"
        "                -- only the verified return of its own REFUND_RETURN correction, never a one-call\n"
        "                -- row or a reversal; read after the Deposit lock (as the one-call check).\n"
        "                IF v_refund.pet_refund_review_id IS NOT NULL AND NOT v_linked AND EXISTS(\n"
        "                    SELECT 1 FROM app.final_settlements settlement\n"
        "                    JOIN app.deposits deposit ON deposit.lease_id=settlement.lease_id\n"
        "                    WHERE deposit.id=v_refund.source_deposit_id AND settlement.closed_at IS NOT NULL)\n"
        "                THEN RAISE EXCEPTION 'A closed Final Settlement''s Pet Deposit Refund is corrected only through a post-settlement correction'\n"
        "                    USING ERRCODE='P5S01'; END IF;\n"
        "                v_property:=app.deposit_property_id(v_refund.source_deposit_id);\n",
    ),
)

FORFEITURE_RECORDER = (
    "app.record_lease_deposit_forfeiture_draft(uuid,uuid,uuid,uuid,uuid,text,text)"
)
FORFEITURE_RECORDER_REPLACEMENTS = (
    (
        "            -- Sub-slice 10c-2b-2a (owner answer 1 to Q-2026-10-08-59, approved tightening): no\n",
        "            -- Sub-slice 10c-2b-2b (owner answer to Q-2026-10-08-60, approved tightening, as the\n"
        "            -- answers to Q-2026-10-08-51 and Q-2026-10-08-59): recorded only at READ COMMITTED,\n"
        "            -- so the closure read below sees every committed closure.\n"
        "            IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN\n"
        "                RAISE EXCEPTION 'A Lease Deposit forfeiture draft is recorded at READ COMMITTED'\n"
        "                    USING ERRCODE='55000'; END IF;\n"
        "            -- Sub-slice 10c-2b-2a (owner answer 1 to Q-2026-10-08-59, approved tightening): no\n",
    ),
)

SQL = r"""
    -- The closed Final Settlement a Refund that a REFUND_RETURN correction may return belongs to;
    -- NULL for every other Refund. Sub-slice 10c-2b-1: a correction's Credit Refund; sub-slice
    -- 10c-2b-2a: a correction's Deposit Refund and a Final Settlement Deposit Refund (8d); sub-slice
    -- 10c-2b-2b: a Pet Refund-review Refund (DL-053) of a Deposit of the Settlement's Lease.
    CREATE OR REPLACE FUNCTION app.settlement_refund_return_settlement(p_refund uuid)
    RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE(
            (SELECT correction.final_settlement_id FROM app.settlement_correction_refund_details detail
                JOIN app.settlement_corrections correction ON correction.id=detail.settlement_correction_id
                JOIN app.refunds refund ON refund.id=detail.refund_id
                WHERE detail.refund_id=p_refund
                  AND ((detail.deposit_id IS NULL AND refund.source_customer_credit_id IS NOT NULL)
                      OR (detail.deposit_id IS NOT NULL AND refund.source_deposit_id=detail.deposit_id))),
            (SELECT detail.final_settlement_id FROM app.final_settlement_refund_details detail
                JOIN app.final_settlements settlement ON settlement.id=detail.final_settlement_id
                JOIN app.refunds refund ON refund.id=detail.refund_id
                WHERE detail.refund_id=p_refund AND settlement.closed_at IS NOT NULL
                  AND refund.source_deposit_id=detail.deposit_id AND refund.pet_refund_review_id IS NULL),
            (SELECT settlement.id FROM app.refunds refund
                JOIN app.deposits deposit ON deposit.id=refund.source_deposit_id
                JOIN app.final_settlements settlement ON settlement.lease_id=deposit.lease_id
                WHERE refund.id=p_refund AND refund.pet_refund_review_id IS NOT NULL
                  AND settlement.closed_at IS NOT NULL))
    $$;
"""

REPLACED = ("app.settlement_refund_return_settlement(uuid)",)


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
            raise RuntimeError(
                f"Returned Pet Refund-review Refund correction source contract changed: {signature}"
            )
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    # CREATE OR REPLACE keeps the privileges migration 20261111_107 set on this function.
    op.execute(SQL)
    _patch(CORRECTABLE, CORRECTABLE_REPLACEMENTS)
    _patch(GENERAL_CORRECTION, GENERAL_CORRECTION_REPLACEMENTS)
    _patch(FORFEITURE_RECORDER, FORFEITURE_RECORDER_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("Returned Pet Refund-review Refund correction migration is forward-only")
