# ruff: noqa: E501
"""The Final Settlement preview's waiting drafts (V1-056 sub-slice 10h-3).

BR-SETTLE-002, BR-SETTLE-012, BR-SETTLE-013, BR-PAY-042, BR-AUTH-010, DL-032; owner answer (a) to
Q-2026-10-17-120 point 3: the preview's pending-draft check also lists three waiting draft kinds,
so a Lease does not close while one of them waits on its sources (each could then no longer be
confirmed outside a correction):

- a SETTLEMENT_CORRECTION draft of the variant PAYMENT_MOVE (sub-slice 10g, another Lease's
  correction) whose correct Invoice is an Invoice of the Lease;
- a PAYMENT_RETURN draft (sub-slice 10e-1a) whose Payment has an active allocation on an
  obligation of the Lease, an active Customer Credit held by a Lease person, an active
  application of one of its Credits on such an obligation, or an active receipt into a Deposit of
  the Lease; and, on the same sources, another Settlement's waiting RETURNED_PAYMENT correction
  draft (sub-slice 10e-1b; review round 2, security should-fix 1), whose confirm would otherwise
  be refused once this Settlement also relied on that Payment;
- an ADJUSTMENT_REVERSAL draft (sub-slice 10f-1) of an Adjustment on an Invoice of the Lease.

The Settlement record and the 8e-3 confirm refuse while the preview has a blocking issue, and
every correction plan refuses a step while it lists a waiting draft, so these refuse too. The
Deposit branch keeps its three earlier kinds. One exact-text replacement of the filter (each part
checked to match once); signature, settings and privileges are kept; the issue's shape and the
rule for who sees a draft's identity do not change. No table, column, trigger, constraint or
grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20270111_168"
down_revision = "20270110_167"
branch_labels = None
depends_on = None

PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"

PREVIEW_REPLACEMENTS = (
    (
        "            -- A pending forfeiture, reversal, Refund or Payment move draft on a Settlement source.\n",
        "            -- A pending forfeiture, reversal, Refund or Payment move draft on a Settlement source;\n"
        "            -- since sub-slice 10h-3 (owner answer (a) to Q-2026-10-17-120 point 3) also another\n"
        "            -- Lease's PAYMENT_MOVE correction draft, a Payment return draft (or another\n"
        "            -- Settlement's RETURNED_PAYMENT correction draft) and an Adjustment reversal\n"
        "            -- draft on the Lease's sources.\n",
    ),
    (
        "                WHERE draft.property_id=p_property AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE','PAYMENT_MOVE')\n"
        "                  AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision WHERE decision.draft_id=draft.id)\n"
        "                  AND (draft.payload->>'deposit_id' IN (SELECT deposit.id::text FROM app.deposits deposit\n"
        "                          WHERE deposit.lease_id=v_lease.id)\n",
        "                WHERE draft.property_id=p_property AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE','PAYMENT_MOVE',\n"
        "                      'SETTLEMENT_CORRECTION','PAYMENT_RETURN','ADJUSTMENT_REVERSAL')\n"
        "                  AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision WHERE decision.draft_id=draft.id)\n"
        "                  AND ((draft.kind IN ('REFUND','DEPOSIT_FORFEITURE','PAYMENT_MOVE')\n"
        "                      AND draft.payload->>'deposit_id' IN (SELECT deposit.id::text FROM app.deposits deposit\n"
        "                          WHERE deposit.lease_id=v_lease.id))\n",
    ),
    (
        "                              WHERE invoice.lease_id=v_lease.id))))),'[]'::jsonb);\n",
        "                              WHERE invoice.lease_id=v_lease.id)))\n"
        "                      OR (draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='PAYMENT_MOVE'\n"
        "                          AND draft.payload->>'target_invoice_id' IN (SELECT invoice.id::text\n"
        "                              FROM app.invoices invoice WHERE invoice.lease_id=v_lease.id))\n"
        "                      OR ((draft.kind='PAYMENT_RETURN'\n"
        "                          OR (draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='RETURNED_PAYMENT'\n"
        "                              AND draft.payload->>'final_settlement_id' IS DISTINCT FROM p_settlement::text))\n"
        "                          AND draft.payload->>'payment_id' IN (\n"
        "                          SELECT allocation.payment_id::text FROM app.payment_allocations allocation\n"
        "                          LEFT JOIN app.late_payment_charges charge ON charge.id=allocation.late_payment_charge_id\n"
        "                          JOIN app.invoices invoice ON invoice.id=COALESCE(allocation.invoice_id,charge.source_invoice_id)\n"
        "                          WHERE invoice.lease_id=v_lease.id AND NOT EXISTS(\n"
        "                              SELECT 1 FROM app.payment_allocation_reversals reversal\n"
        "                              WHERE reversal.payment_allocation_id=allocation.id)\n"
        "                          UNION SELECT credit.source_payment_id::text FROM app.customer_credits credit\n"
        "                          WHERE credit.source_payment_id IS NOT NULL AND NOT EXISTS(\n"
        "                                  SELECT 1 FROM app.customer_credit_reversals reversal\n"
        "                                  WHERE reversal.customer_credit_id=credit.id)\n"
        "                            AND (credit.customer_id=ANY(v_people) OR EXISTS(\n"
        "                                SELECT 1 FROM app.customer_credit_applications application\n"
        "                                LEFT JOIN app.late_payment_charges charge\n"
        "                                    ON charge.id=application.late_payment_charge_id\n"
        "                                JOIN app.invoices invoice\n"
        "                                    ON invoice.id=COALESCE(application.invoice_id,charge.source_invoice_id)\n"
        "                                WHERE application.customer_credit_id=credit.id AND invoice.lease_id=v_lease.id\n"
        "                                  AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal\n"
        "                                      WHERE reversal.credit_application_id=application.id)))\n"
        "                          UNION SELECT receipt.payment_id::text FROM app.deposit_receipts receipt\n"
        "                          JOIN app.deposits deposit ON deposit.id=receipt.deposit_id\n"
        "                          WHERE deposit.lease_id=v_lease.id AND NOT EXISTS(\n"
        "                              SELECT 1 FROM app.deposit_receipt_reversals reversal\n"
        "                              WHERE reversal.deposit_receipt_id=receipt.id)))\n"
        "                      OR (draft.kind='ADJUSTMENT_REVERSAL' AND draft.payload->>'invoice_adjustment_id' IN (\n"
        "                          SELECT adjustment.id::text FROM app.invoice_adjustments adjustment\n"
        "                          JOIN app.invoices invoice ON invoice.id=adjustment.invoice_id\n"
        "                          WHERE invoice.lease_id=v_lease.id)))),'[]'::jsonb);\n",
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
            raise RuntimeError(f"Settlement preview waiting drafts contract changed: {signature}")
        definition = definition.replace(before, after)
    return definition


def upgrade() -> None:
    # CREATE OR REPLACE keeps the function's identity, owner and privileges.
    op.execute(_replaced(PREVIEW, PREVIEW_REPLACEMENTS))


def downgrade() -> None:
    raise RuntimeError("Settlement preview waiting drafts migration is forward-only")
