# ruff: noqa: E501
"""A returned Payment used on a closed Lease after closure (V1-056 sub-slice 10e-4).

BR-SETTLE-013, BR-SETTLE-016, BR-PAY-042; DB-PAY-009, DB-SETTLE-005; owner answer (c) to
Q-2026-10-11-81 point 3 and the owner answer to Q-2026-10-11-82:

- A Payment that no closed Final Settlement relied on, but that names a closed Settlement's Lease
  or whose money is used on it (an active allocation, or an active application of one of its
  Credits, is on an Invoice of that Lease, or a Refund paid from its value is charged back on that
  Lease; since that Settlement did not rely on them, such uses came after closure), is returned
  through the RETURNED_PAYMENT correction of that Settlement. The way in through the named Lease
  has no time or use condition. The correction reverses the Payment's records as linked records,
  so the debt comes back on its obligations and stays with their Customers (BR-SETTLE-016), and
  recovers each Refund paid from its value by a charge to the person who received it, by the
  unchanged sub-slice 10e-1c rules (an EXTRA_CHARGE on that Lease when the Refund's charge goes on
  it, for a Payment Refund when the Payment names it, and that person is its signed Customer;
  otherwise an ordinary or no-Lease charge). With nothing refunded no charge is written: the
  reversed allocation puts the debt back on the Customer whose debt the Payment paid.
- The PAYMENT_RETURN draft keeps refusing a Payment whose Refund would be charged on a closed
  Settlement's Lease; its message now names the correction.
- A Payment whose records another closed Final Settlement relied on stays refused (the
  Q-2026-10-10-72 point 3 known limit).

Relaxing changes: the correction source gains `used_on_lease`; the correction's "did not rely on"
refusal lets such a Payment through. One refusal message changes. Fail closed (review round 1): in
that branch a source without a reliance list is refused, and only a JSON true flag counts.
"""

from alembic import op
from sqlalchemy import text

revision = "20261201_127"
down_revision = "20261130_126"
branch_labels = None
depends_on = None

SOURCE = "app.settlement_returned_payment_source(uuid,uuid,uuid,uuid)"
SOURCE_REPLACEMENTS = (
    (
        """                    WHERE reversal.deposit_disposition_id=disposition.id)),'[]'::jsonb))
""",
        """                    WHERE reversal.deposit_disposition_id=disposition.id)),'[]'::jsonb),
            -- Sub-slice 10e-4 (owner answer (c) to Q-2026-10-11-81): the Payment's money is used
            -- on this Settlement's Lease: the Payment names the Lease, or an active allocation of
            -- the Payment, or an active application of one of its Credits that is not reversed,
            -- is on an Invoice of the Lease or a Late-payment Charge of such an Invoice.
            'used_on_lease',COALESCE((SELECT COALESCE(payment.lease_id=settlement.lease_id,false)
                    OR EXISTS(SELECT 1 FROM app.payment_allocations allocation
                        LEFT JOIN app.late_payment_charges charge
                            ON charge.id=allocation.late_payment_charge_id
                        JOIN app.invoices invoice
                            ON invoice.id=COALESCE(allocation.invoice_id,charge.source_invoice_id)
                        WHERE allocation.payment_id=payment.id
                          AND invoice.lease_id=settlement.lease_id
                          AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                              WHERE reversal.payment_allocation_id=allocation.id))
                    OR EXISTS(SELECT 1 FROM app.customer_credits credit
                        JOIN app.customer_credit_applications application
                            ON application.customer_credit_id=credit.id
                        LEFT JOIN app.late_payment_charges charge
                            ON charge.id=application.late_payment_charge_id
                        JOIN app.invoices invoice
                            ON invoice.id=COALESCE(application.invoice_id,charge.source_invoice_id)
                        WHERE credit.source_payment_id=payment.id
                          AND invoice.lease_id=settlement.lease_id
                          AND NOT EXISTS(SELECT 1 FROM app.customer_credit_reversals reversal
                              WHERE reversal.customer_credit_id=credit.id)
                          AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal
                              WHERE reversal.credit_application_id=application.id))
                FROM app.payments payment
                JOIN app.final_settlements settlement
                    ON settlement.id=p_settlement AND settlement.property_id=p_property
                WHERE payment.id=p_payment AND payment.property_id=p_property),false))
""",
    ),
)

ASSERT = "app.assert_settlement_returned_payment_allowed(uuid,uuid,jsonb)"
ASSERT_REPLACEMENTS = (
    (
        """            RAISE EXCEPTION 'This Final Settlement did not rely on this Payment''s records; return it with a Payment return draft'
                USING ERRCODE='55000';
        END IF;
""",
        """            -- Sub-slice 10e-4 (owner answer (c) to Q-2026-10-11-81): a Payment whose money is used
            -- on this Settlement's Lease (the Payment names it, or an active record of its money
            -- is on it), or a Refund of whose value is charged back on that Lease, is returned
            -- through this correction. Fail closed (review round 1): the reliance list must be a
            -- list, and only a JSON true flag counts.
            IF jsonb_typeof(p_source->'relied_on') IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'The returned-Payment correction source is incomplete'
                    USING ERRCODE='55000'; END IF;
            IF p_source->'used_on_lease' IS DISTINCT FROM 'true'::jsonb
                AND NOT EXISTS(SELECT 1
                    FROM jsonb_array_elements(COALESCE(p_source->'recoveries','[]'::jsonb)) recovery
                    WHERE recovery->>'closed_final_settlement_id'=p_settlement::text)
            THEN
                RAISE EXCEPTION 'This Final Settlement did not rely on this Payment''s records; return it with a Payment return draft'
                    USING ERRCODE='55000';
            END IF;
        END IF;
""",
    ),
)

RECOVERIES = "app.assert_payment_return_recoveries_allowed(jsonb,uuid)"
RECOVERIES_REPLACEMENTS = (
    (
        """        -- A charge on a Lease with a closed Final Settlement is written only by a correction of that
        -- Settlement (the Q-2026-10-10-72 point 3 known limit; plan choice for the owner).
""",
        """        -- Sub-slice 10e-4 (owner answer (c) to Q-2026-10-11-81): the PAYMENT_RETURN draft (no
        -- Settlement) names the correction that returns such a Payment.
        IF p_settlement IS NULL AND EXISTS(SELECT 1
            FROM jsonb_array_elements(COALESCE(p_recoveries,'[]'::jsonb)) recovery
            WHERE recovery->>'closed_final_settlement_id' IS NOT NULL)
        THEN RAISE EXCEPTION 'A Refund paid from this Payment''s value would be charged on a Lease whose Final Settlement is closed; return the Payment through a returned-Payment correction of that Final Settlement'
            USING ERRCODE='55000'; END IF;
        -- A charge on a Lease with a closed Final Settlement is written only by a correction of that
        -- Settlement (the Q-2026-10-10-72 point 3 known limit; plan choice for the owner).
""",
    ),
)

PATCHES = (
    (SOURCE, SOURCE_REPLACEMENTS),
    (ASSERT, ASSERT_REPLACEMENTS),
    (RECOVERIES, RECOVERIES_REPLACEMENTS),
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
            raise RuntimeError(f"Returned Payment after closure contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Returned Payment after closure migration is forward-only")
