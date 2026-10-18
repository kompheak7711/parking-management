# ruff: noqa: E501
"""A shared Deposit with pay-back money gives back from its forfeiture first (V1-056 sub-slice 10e-2b-4e-2b-1).

BR-SETTLE-013, BR-DEP-022, DL-032, DL-053; DB-DEP-007, DB-SETTLE-005; owner answer (a) to
Q-2026-10-18-135: when the RETURNED_PAYMENT correction gives back a shared Deposit's shortfall and
the Deposit holds the Customer's pay-back money beside an active forfeiture, the forfeitures give
back first (the Property keeps less; nobody is charged), and only the rest of the shortfall comes
newest first from the Deposit's Refunds and applications. No part of the pay-back money stays
forfeited: the forfeitures give back the least of what they keep and the returned receipt less
the held value plus the pay-back count with payouts, so a forfeiture that stays active keeps at
most what the Deposit's other money holds beyond the pay-back money. The plan's total is the
greater of that part and the shortfall. Every other shared Deposit is unchanged.

- "A Deposit with pay-back money" is the condition the 10e-2b-4e-2a refusal used: an active
  forfeiture and a pay-back count without payouts above 0.
- The 10e-2b-4e-2a refusal (B1) stays as defence in depth; no plan of this planner for a plain
  Deposit reaches it.
- Review round 1: the record check takes one plan entry per shared Deposit and recomputes its
  total from the live state (the held value, the active forfeitures and the pay-back counts), so
  a hand-built plan that gives back anything else is refused (fail closed).

Exact-text patches (each replacement checked to match once):
app.settlement_returned_payment_shared and app.assert_settlement_returned_payment_allowed. No new
function, table, column, trigger, constraint or grant.
"""

from alembic import op
from sqlalchemy import text

revision = "20270102_159"
down_revision = "20270101_158"
branch_labels = None
depends_on = None

PLANNER = "app.settlement_returned_payment_shared(uuid,uuid,jsonb)"
PLANNER_REPLACEMENTS = (
    (
        "        ), shared AS (\n"
        "            SELECT returned.deposit_id,returned.receipt_amount,\n",
        "        ), measured AS (\n"
        "            SELECT returned.deposit_id,returned.receipt_amount,\n",
    ),
    (
        "        ), uses AS (\n",
        "        ), shared AS (\n"
        "            -- Sub-slice 10e-2b-4e-2b-1 (owner answer (a) to Q-2026-10-18-135): a Deposit with\n"
        "            -- the Customer's pay-back money beside an active forfeiture gives back from its\n"
        "            -- forfeitures first, enough that none keeps the pay-back money (the count with\n"
        "            -- payouts), then the rest of its shortfall newest first.\n"
        "            SELECT measured.*,payback_rule.forfeited,payback_rule.payback,\n"
        "                payback_rule.payback_first,\n"
        "                CASE WHEN payback_rule.payback_first THEN GREATEST(measured.shortfall,\n"
        "                    LEAST(payback_rule.forfeited,\n"
        "                        GREATEST(measured.receipt_amount-measured.held+payback_rule.payback,0)))\n"
        "                    ELSE measured.shortfall END AS give_back\n"
        "            FROM measured\n"
        "            CROSS JOIN LATERAL (SELECT kept.forfeited,\n"
        "                    app.lease_deposit_payback_count_as(measured.deposit_id,NULL,0,false) AS payback,\n"
        "                    measured.plain AND kept.forfeited>0\n"
        "                        AND app.lease_deposit_payback_count_as(measured.deposit_id,NULL,0,true)>0\n"
        "                        AS payback_first\n"
        "                FROM (SELECT COALESCE(sum(disposition.amount_usd_cents),0)::bigint AS forfeited\n"
        "                    FROM app.deposit_dispositions disposition\n"
        "                    WHERE disposition.deposit_id=measured.deposit_id\n"
        "                      AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal\n"
        "                          WHERE reversal.deposit_disposition_id=disposition.id)) kept) payback_rule\n"
        "        ), uses AS (\n",
    ),
    (
        "                LEAST(uses.amount,GREATEST(shared.shortfall-COALESCE((sum(uses.amount) OVER (newest\n",
        "                LEAST(uses.amount,GREATEST(shared.give_back-COALESCE((sum(uses.amount) OVER (newest\n",
    ),
    (
        "            WINDOW newest AS (PARTITION BY uses.deposit_id\n"
        "                ORDER BY uses.at DESC,uses.kind_rank,uses.application_order DESC,uses.id DESC)\n",
        "            WINDOW newest AS (PARTITION BY uses.deposit_id\n"
        "                -- Sub-slice 10e-2b-4e-2b-1: a payback_first Deposit's forfeitures first.\n"
        "                ORDER BY (shared.payback_first AND uses.kind='FORFEITURE') DESC,\n"
        "                    uses.at DESC,uses.kind_rank,uses.application_order DESC,uses.id DESC)\n",
    ),
    (
        "                    'plain',shared.plain,\n",
        "                    'plain',shared.plain,\n"
        "                    -- Sub-slice 10e-2b-4e-2b-1: what the plan gives back in all.\n"
        "                    'give_back_usd_cents',shared.give_back,'payback_first',shared.payback_first,\n"
        "                    'payback_usd_cents',shared.payback,\n",
    ),
)

ALLOWED_CHECK = "app.assert_settlement_returned_payment_allowed(uuid,uuid,jsonb)"
ALLOWED_CHECK_REPLACEMENTS = (
    (
        "              AND COALESCE((deposit->>'shortfall_usd_cents')::bigint,-1)\n"
        "                IS DISTINCT FROM COALESCE((SELECT sum((used->>'undo_usd_cents')::bigint)\n"
        "                    FROM jsonb_array_elements(COALESCE(p_source->'shared_deposits','[]'::jsonb)) shared\n"
        "                    CROSS JOIN LATERAL jsonb_array_elements(shared->'uses') used\n"
        "                    WHERE shared->>'deposit_id'=deposit->>'id'),0))\n",
        "              -- Sub-slice 10e-2b-4e-2b-1 (owner answer (a) to Q-2026-10-18-135; review round 1):\n"
        "              -- one plan entry per shared Deposit, giving back exactly the total the rule\n"
        "              -- gives on the live state: its shortfall, or, for a plain Deposit with pay-back\n"
        "              -- money beside an active forfeiture, enough from the forfeitures that none\n"
        "              -- keeps the pay-back money (the count with payouts).\n"
        "              AND NOT COALESCE((SELECT count(*)=1 AND bool_and(COALESCE(\n"
        "                        (shared->>'give_back_usd_cents')::bigint\n"
        "                            =COALESCE((SELECT sum((used->>'undo_usd_cents')::bigint)\n"
        "                                FROM jsonb_array_elements(shared->'uses') used),0)\n"
        "                        -- Review round 2: the receipt and the held value are the live ones,\n"
        "                        -- and a Deposit that is not plain gives back nothing.\n"
        "                        AND live.receipt IS NOT NULL\n"
        "                        AND (shared->>'receipt_usd_cents')::bigint=live.receipt\n"
        "                        AND (shared->>'held_usd_cents')::bigint=live.held\n"
        "                        AND (COALESCE((shared->>'plain')::boolean,false)\n"
        "                            OR COALESCE(jsonb_array_length(shared->'uses'),0)=0)\n"
        "                        AND live.shortfall=GREATEST(live.receipt-live.held,0)\n"
        "                        AND (shared->>'give_back_usd_cents')::bigint=CASE\n"
        "                            WHEN COALESCE((shared->>'plain')::boolean,false) AND live.forfeited>0\n"
        "                                AND app.lease_deposit_payback_count_as(live.deposit_id,NULL,0,true)>0\n"
        "                            THEN GREATEST(live.shortfall,LEAST(live.forfeited,GREATEST(live.receipt\n"
        "                                -live.held+app.lease_deposit_payback_count_as(live.deposit_id,NULL,0,false),0)))\n"
        "                            ELSE live.shortfall END,false))\n"
        "                FROM jsonb_array_elements(COALESCE(p_source->'shared_deposits','[]'::jsonb)) shared\n"
        "                CROSS JOIN LATERAL (SELECT (deposit->>'id')::uuid AS deposit_id,\n"
        "                        (deposit->>'shortfall_usd_cents')::bigint AS shortfall,\n"
        "                        (SELECT sum(receipt.amount_usd_cents)::bigint FROM app.deposit_receipts receipt\n"
        "                            WHERE receipt.deposit_id=(deposit->>'id')::uuid\n"
        "                              AND receipt.payment_id=(p_source->'payment'->>'id')::uuid\n"
        "                              AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal\n"
        "                                  WHERE reversal.deposit_receipt_id=receipt.id)) AS receipt,\n"
        "                        app.deposit_held_value_at((deposit->>'id')::uuid,'infinity') AS held,\n"
        "                        (SELECT COALESCE(sum(disposition.amount_usd_cents),0)::bigint\n"
        "                            FROM app.deposit_dispositions disposition\n"
        "                            WHERE disposition.deposit_id=(deposit->>'id')::uuid\n"
        "                              AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal\n"
        "                                  WHERE reversal.deposit_disposition_id=disposition.id)) AS forfeited) live\n"
        "                WHERE shared->>'deposit_id'=deposit->>'id'),false))\n"
        "            -- Review round 2: every plan entry names a shared Deposit of the source.\n"
        "            OR EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_source->'shared_deposits','[]'::jsonb)) shared\n"
        "                WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'deposits') deposit\n"
        "                    WHERE deposit->>'id'=shared->>'deposit_id'\n"
        "                      AND COALESCE((deposit->>'shared')::boolean,false)))\n",
    ),
    (
        "                OR app.lease_deposit_payback_count_as((shared->>'deposit_id')::uuid,NULL,0,false)\n"
        "                    >GREATEST((shared->>'held_usd_cents')::bigint\n"
        "                        -(shared->>'receipt_usd_cents')::bigint,0)))\n",
        "                OR app.lease_deposit_payback_count_as((shared->>'deposit_id')::uuid,NULL,0,false)\n"
        "                    -- Sub-slice 10e-2b-4e-2b-1: the end held of the plan's give_back total.\n"
        "                    >GREATEST((shared->>'held_usd_cents')::bigint\n"
        "                        +COALESCE((shared->>'give_back_usd_cents')::bigint,0)\n"
        "                        -(shared->>'receipt_usd_cents')::bigint,0)))\n",
    ),
)

PATCHES = (
    (PLANNER, PLANNER_REPLACEMENTS),
    (ALLOWED_CHECK, ALLOWED_CHECK_REPLACEMENTS),
)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Returned-Payment pay-back-first migration is forward-only")


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
            raise RuntimeError(f"Returned-Payment pay-back-first contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)
