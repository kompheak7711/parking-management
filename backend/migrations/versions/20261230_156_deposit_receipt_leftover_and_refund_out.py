# ruff: noqa: E501
"""A Payment's leftover into a Deposit, no receipt while a Refund is out, and none after a termination that keeps the Deposit (V1-056 sub-slice 10e-2b-4d).

BR-PAY-024, BR-PAY-026, BR-CREDIT-004, BR-DEP-022, BR-DEP-023, DL-030; DB-DEP-002; owner answers
of 2026-10-18 to the 10e-2b-4b-2b report: answer 1, option (d) of Q-2026-10-18-127 until option (a)
is built (refuse a receipt into a Deposit whose Refund is out); answer 2, option (b) of
Q-2026-10-18-128 (once the Invoice a Payment names has nothing outstanding, what is left of that
Payment may go into the Deposit; one transfer that pays the Initial Rent and the Deposit together
is normal); answer 3, built as option (a) of Q-2026-10-18-131 (refuse a receipt into a Deposit
after a termination whose ground keeps that Deposit, also after a forfeiture reversal).

app.record_lease_deposit_receipt: the whole-Payment refusal of a Payment confirmed for an Invoice
or a Late-payment Charge (sub-slice 10e-2b-4b-2b) is replaced by three checks, all after the
Payment and Deposit locks and the active-forfeiture refusal:
- a receipt into a Deposit of a TERMINATED Lease whose termination ground keeps that Deposit type
  (app.lease_termination_forfeiture_rule, the rule the Final Settlement and the forfeiture drafts
  use) is refused (55000): staff record that money as a normal Payment, so it pays open Invoices or
  becomes Credit (DL-030); a forfeiture reversal does not change the ground;
- a receipt into a Deposit with a Refund that is not fully returned
  (app.deposit_has_unresolved_refund) is refused (55000); on a Lease's Deposit before closure such
  a Refund is a Pet Refund-review Refund, so later Security Deposit receipts stay allowed;
- for a Payment confirmed for an Invoice or a Late-payment Charge, app.assert_payment_excess_eligible,
  the check and locks the Credit path uses for leftover money (the obligation tables in SHARE MODE
  NOWAIT; 23514 while the named Invoice or Charge, or a Late-payment Charge of the named Invoice,
  has anything outstanding). It runs after the Payment and Deposit locks, as in the Credit path
  (review round 1): its NOWAIT table locks never wait, so the writer never holds them while it
  waits for a row lock. Once the named target has nothing outstanding, the Payment's value left
  after it may go into the Deposit; the receipt table's Payment availability bound limits the
  amount. A Payment that names nothing is unchanged (staff choose where it goes).

One exact-text patch of an existing function (one replacement, checked to match once); no other
function, table, trigger, constraint or grant changes.
"""

from alembic import op
from sqlalchemy import text

revision = "20261230_156"
down_revision = "20261229_155"
branch_labels = None
depends_on = None

WRITER = "app.record_lease_deposit_receipt(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,text,text)"
WRITER_REPLACEMENTS = (
    (
        "            -- Review round 1 (security): a Payment confirmed for an Invoice or a Late-payment\n"
        "            -- Charge is allocated only there (BR-PAY-024, BR-PAY-026; the allocation check refuses\n"
        "            -- any other target), and its rest becomes Credit or a Refund, never a Deposit receipt\n"
        "            -- (the whole Payment is refused; Q-2026-10-18-128).\n"
        "            IF EXISTS(SELECT 1 FROM app.payments payment WHERE payment.id=p_payment_id\n"
        "                AND (payment.identified_invoice_id IS NOT NULL\n"
        "                    OR payment.identified_late_payment_charge_id IS NOT NULL))\n"
        "            THEN RAISE EXCEPTION 'A Payment confirmed for an Invoice or a Late-payment Charge is not a Deposit receipt'\n"
        "                USING ERRCODE='55000'; END IF;\n",
        "            -- Sub-slice 10e-2b-4d (owner answer (a) to Q-2026-10-18-131): money paid after a\n"
        "            -- termination whose ground keeps this Deposit type is not forfeited at once; staff\n"
        "            -- record it as a normal Payment, so it pays open Invoices or becomes Credit (DL-030).\n"
        "            -- Also after a forfeiture reversal: the reversal does not change the ground.\n"
        "            -- (A nested IF: the rule refuses a Lease that is not terminated, so it is read only\n"
        "            -- for a TERMINATED Lease; review round 2, security note.)\n"
        "            IF v_deposit.lease_id IS NOT NULL AND v_status='TERMINATED' THEN\n"
        "                IF app.lease_termination_forfeiture_rule(p_property_id,v_deposit.lease_id,\n"
        "                    v_deposit.deposit_type) IS NOT NULL\n"
        "                THEN RAISE EXCEPTION 'The Lease''s termination ground keeps this Deposit; this receipt is not recorded here'\n"
        "                    USING ERRCODE='55000'; END IF;\n"
        "            END IF;\n"
        "            -- Sub-slice 10e-2b-4d (owner answer (d) to Q-2026-10-18-127, until option (a) is\n"
        "            -- built): no receipt into a Deposit whose Refund is not fully returned, so a bounced\n"
        "            -- Payment of a Deposit funded by two Payments cannot be put out of reach on purpose.\n"
        "            IF app.deposit_has_unresolved_refund(p_deposit_id) THEN\n"
        "                RAISE EXCEPTION 'The Deposit has a Refund that is not fully returned; this receipt is not recorded here'\n"
        "                    USING ERRCODE='55000'; END IF;\n"
        "            -- Sub-slice 10e-2b-4d (owner answer (b) to Q-2026-10-18-128): a Payment confirmed for\n"
        "            -- an Invoice or a Late-payment Charge goes first where the Customer named it\n"
        "            -- (BR-PAY-024, BR-PAY-026); only its value left after that target has nothing\n"
        "            -- outstanding may go into a Deposit, under the Credit path's check and locks. As in\n"
        "            -- the Credit path, they come after the Payment (and here the Deposit) locks: their\n"
        "            -- NOWAIT table locks never wait, and no row lock is waited for while they are held.\n"
        "            IF EXISTS(SELECT 1 FROM app.payments payment WHERE payment.id=p_payment_id\n"
        "                AND (payment.identified_invoice_id IS NOT NULL\n"
        "                    OR payment.identified_late_payment_charge_id IS NOT NULL))\n"
        "            THEN PERFORM app.assert_payment_excess_eligible(p_payment_id); END IF;\n",
    ),
)

PATCHES = ((WRITER, WRITER_REPLACEMENTS),)


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
            raise RuntimeError(f"Deposit receipt leftover contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Deposit receipt leftover migration is forward-only")
