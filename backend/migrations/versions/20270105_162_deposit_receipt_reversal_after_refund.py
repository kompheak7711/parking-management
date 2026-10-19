# ruff: noqa: E501
"""The two-person reversal of a receipt recorded while a Refund is out (V1-056 sub-slice 10e-2b-4e-2b-3).

BR-DEP-002, BR-DEP-005, BR-AUTH-010, DL-053; DB-DEP-002; owner answer (a) to Q-2026-10-19-137,
with the narrowing of its review rounds 2 and 3: a wrong receipt must always be fixable by two
people. Since the end of option (d) (sub-slice 10e-2b-4e-2b-2b) one staff member can record a
Payment into a Pet Deposit whose Pet Refund-review Refund is not fully returned; the receipt
reversal (the 8r draft: deposits.correct records, financial.approve confirms) refused it until
the Refund was returned in full.

New internal app.deposit_receipt_reversal_after_refund_allowed(receipt, reversal, actor) (no
grant) is true only for the reversal written by a DEPOSIT_RECEIPT_REVERSAL draft confirmed in this
transaction by the reversal's actor, of a Deposit whose Lease has no closed Final Settlement,
when every Refund of that Deposit that is not fully returned was processed strictly before the
receipt and the Deposit held at least the receipt's amount at every balance time from the
receipt on (so no later return, correction or payout relied on the receipt's money).

Exact-text patches (one replacement each, checked to match once): app.reverse_deposit_receipt
(the check the 8r confirm reaches through app.reverse_deposit_receipt_v2) and the trigger
function app.validate_deposit_receipt_reversal let such a reversal pass the unresolved-Refund
refusal. Every other refusal stays: an active forfeiture, an active Deposit application, a
waiting draft, a closed Final Settlement and the held history at 0 or more. No table, column,
trigger, constraint or grant changes. A relaxing change.
"""

from alembic import op
from sqlalchemy import text

revision = "20270105_162"
down_revision = "20270104_161"
branch_labels = None
depends_on = None

SQL = """
    -- Sub-slice 10e-2b-4e-2b-3 (owner answer (a) to Q-2026-10-19-137, narrowed by its review
    -- rounds 2 and 3): the two-person reversal undoes a receipt recorded while a Refund of its
    -- Deposit is out, when nothing relied on the receipt's money.
    CREATE FUNCTION app.deposit_receipt_reversal_after_refund_allowed(p_receipt uuid,p_reversal uuid,p_actor uuid)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT
            -- (1) A DEPOSIT_RECEIPT_REVERSAL draft of this receipt's Property and Deposit,
            -- confirmed by this reversal's actor since this transaction began, names this
            -- receipt and this reversal. The time alone does not bind the decision to this
            -- transaction: the reversal id is the reversal table's key and a receipt is reversed
            -- once, so a decision naming both belongs to the 8r confirm that writes this row.
            EXISTS(SELECT 1 FROM app.financial_drafts draft
                JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
                    AND decision.decision='CONFIRMED' AND decision.decided_by=p_actor
                    AND decision.decided_at>=transaction_timestamp()
                WHERE draft.kind='DEPOSIT_FORFEITURE' AND draft.prepare_capability='deposits.correct'
                  AND draft.property_id=app.deposit_property_id(receipt.deposit_id)
                  AND draft.payload->>'variant'='DEPOSIT_RECEIPT_REVERSAL'
                  AND draft.payload->>'deposit_id'=receipt.deposit_id::text
                  AND draft.payload->>'receipt_id'=receipt.id::text
                  AND draft.payload->>'reversal_id'=p_reversal::text)
            -- (2) No closed Final Settlement of the Deposit's Lease.
            AND NOT EXISTS(SELECT 1 FROM app.final_settlements settlement
                JOIN app.deposits deposit ON deposit.lease_id=settlement.lease_id
                WHERE deposit.id=receipt.deposit_id AND settlement.closed_at IS NOT NULL)
            -- (3) Every Refund of the Deposit that is not fully returned was processed strictly
            -- before the receipt.
            AND NOT EXISTS(SELECT 1 FROM app.refunds refund
                WHERE refund.source_deposit_id=receipt.deposit_id
                  AND refund.usd_accounting_value_cents<>COALESCE((
                      SELECT sum(correction.source_balance_effect_usd_cents)
                      FROM app.refund_corrections correction WHERE correction.refund_id=refund.id),0)
                  AND (refund.processed_at<receipt.occurred_at) IS NOT TRUE)
            -- (4) From the receipt on, the Deposit held at least the receipt's amount at every
            -- balance time, so no later return, correction or payout relied on its money.
            AND NOT EXISTS(SELECT 1 FROM (
                SELECT event_at,sum(amount) OVER (ORDER BY event_at RANGE UNBOUNDED PRECEDING) AS held
                FROM app.deposit_balance_events(receipt.deposit_id)) positions
                WHERE (positions.event_at<receipt.occurred_at) IS NOT TRUE
                  AND (positions.held>=receipt.amount_usd_cents) IS NOT TRUE)
            FROM app.deposit_receipts receipt WHERE receipt.id=p_receipt),false)
    $$;
"""

INTERNAL = ("app.deposit_receipt_reversal_after_refund_allowed(uuid,uuid,uuid)",)

INNER = "app.reverse_deposit_receipt(uuid,uuid,uuid,text,uuid,uuid,text,text)"
INNER_REPLACEMENTS = (
    (
        "                OR app.deposit_has_unresolved_refund(v_deposit_id)\n"
        "            THEN RAISE EXCEPTION 'Deposit receipt has active dependent financial history' USING ERRCODE='55000'; END IF;\n",
        "                -- Sub-slice 10e-2b-4e-2b-3 (owner answer (a) to Q-2026-10-19-137): the\n"
        "                -- two-person reversal of a receipt recorded after every such Refund passes.\n"
        "                OR (app.deposit_has_unresolved_refund(v_deposit_id)\n"
        "                    AND NOT app.deposit_receipt_reversal_after_refund_allowed(\n"
        "                        p_receipt_id,p_reversal_id,p_actor_id))\n"
        "            THEN RAISE EXCEPTION 'Deposit receipt has active dependent financial history' USING ERRCODE='55000'; END IF;\n",
    ),
)

REVERSAL_CHECK = "app.validate_deposit_receipt_reversal()"
REVERSAL_CHECK_REPLACEMENTS = (
    (
        "                  -- shared Deposit whose Refund stays out; the held history stays at 0 or more.\n"
        "                  AND NOT app.payment_return_shared_receipt_reversal_allowed(NEW))\n",
        "                  -- shared Deposit whose Refund stays out; the held history stays at 0 or more.\n"
        "                  AND NOT app.payment_return_shared_receipt_reversal_allowed(NEW)\n"
        "                  -- Sub-slice 10e-2b-4e-2b-3 (owner answer (a) to Q-2026-10-19-137): or the\n"
        "                  -- two-person reversal of a receipt recorded after every such Refund, whose\n"
        "                  -- money no later balance event relied on.\n"
        "                  AND NOT (v_settlement IS NULL\n"
        "                      AND app.deposit_receipt_reversal_after_refund_allowed(\n"
        "                          NEW.deposit_receipt_id,NEW.id,NEW.actor_id)))\n",
    ),
)

PATCHES = ((INNER, INNER_REPLACEMENTS), (REVERSAL_CHECK, REVERSAL_CHECK_REPLACEMENTS))


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
            raise RuntimeError(f"Deposit receipt reversal after-Refund contract changed: {signature}")
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
    raise RuntimeError("Deposit receipt reversal after-Refund migration is forward-only")
