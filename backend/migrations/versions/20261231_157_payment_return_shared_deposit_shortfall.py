# ruff: noqa: E501
"""A returned Payment of a shared Deposit charges back only the shortfall (V1-056 sub-slice 10e-2b-4e-1).

BR-SETTLE-013, BR-SETTLE-016, BR-REFUND-015, DL-032, DL-053; DB-REFUND-002, DB-DEP-007, DB-PAY-009;
owner answer (a) to Q-2026-10-18-127: when one of two or more Payments that funded a Deposit
bounces, its return reverses its receipt when the Deposit still holds at least its amount, and
otherwise first charges back only the shortfall (its amount less what the Deposit holds) to the
person who received the Refund, with the same recovery charge as today. This sub-slice builds the
return before closure (the PAYMENT_RETURN draft); the RETURNED_PAYMENT correction and the receipt
correction after closure are sub-slice 10e-2b-4e-2 (Q-2026-10-18-134 point 1). Option (d), the
interim refusal of a receipt into a Deposit whose Refund is out, stays until 10e-2b-4e-2 (review
round 2: the owner's "(d) until (a) is built", and (a) includes the corrections after closure).

- A shared Deposit is one the returned Payment funded that also holds another Payment's active
  receipt. Its shortfall is the returned Payment's active receipt amount less what the Deposit
  holds, never below 0. A shortfall of 0 charges nothing. A shortfall above 0 is spread over the
  Deposit's Refunds that are not fully returned, newest first, each at most its net; while those
  Refunds went to more than one person the existing shared-Deposit refusal stays
  (Q-2026-10-18-134 point 2). The receipt is then reversed by the shared writer, dated after the
  recoveries, and the Deposit's held history stays at 0 or more. A Deposit only the returned
  Payment funded is unchanged: its shortfall is the nets of its Refunds, each recovered whole.
- The recovery insert check accepts a share only inside a confirmed PAYMENT_RETURN of this
  transaction whose Payment still has an active receipt in the Refund's shared Deposit, and only
  up to that Deposit's shortfall at the row; a smaller sum is refused by the held-history check at
  the receipt reversal. The receipt reversal check lets that same return reverse its Payment's
  receipt of a shared Deposit whose Refund stays out; its other refusals stay.
- The PAYMENT_RETURN recorder and confirm read a new source, app.payment_return_draft_source (the
  return source with these recoveries and each funded Deposit's shared flag and shortfall).
  app.payment_return_source and app.payment_return_recoveries, which the RETURNED_PAYMENT
  correction, the receipt correction and the return reversal read, are not changed, so those
  paths keep refusing a shared Deposit (review of targeted run T2: the correction's source extends
  app.payment_return_source).

New internal functions (no grant): app.payment_return_shared_deposit_recoveries,
app.payment_return_draft_source, app.payment_return_shortfall_recovery_amount,
app.payment_return_shared_receipt_reversal_allowed. Exact-text patches (each replacement checked
to match once): app.record_payment_return_draft, app.assert_payment_return_recoveries_allowed, app.assert_payment_return_recoveries_planned,
app.write_payment_return_recoveries, app.validate_general_refund_correction,
app.validate_deposit_receipt_reversal and app.confirm_payment_return. No table, column,
trigger, constraint or grant changes.
"""

from alembic import op
from sqlalchemy import text

revision = "20261231_157"
down_revision = "20261230_156"
branch_labels = None
depends_on = None

SQL = r"""
    -- The recoveries a PAYMENT_RETURN writes: the full list, with each entry of a shared Deposit
    -- (another Payment's active receipt is also in it) replaced by its share of the Deposit's
    -- shortfall, newest Refund first, each at most its net (owner answer (a) to
    -- Q-2026-10-18-127). An entry with a share of 0 is left out. A shared Deposit with a
    -- shortfall whose Refunds went to more than one person keeps its entries as they are, so the
    -- shared-Deposit refusal still applies (Q-2026-10-18-134 point 2); so does a shared Deposit
    -- with a Reservation outcome Refund or a charge on a closed Settlement's Lease, which keeps
    -- those refusals (review round 1).
    CREATE FUNCTION app.payment_return_shared_deposit_recoveries(p_property uuid, p_payment uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
        WITH listed AS (
            SELECT recovery.value AS entry,recovery.position
            FROM jsonb_array_elements(app.payment_return_recoveries(p_property,p_payment))
                WITH ORDINALITY recovery(value,position)
        ), shared AS (
            SELECT returned.deposit_id,
                GREATEST(returned.receipt_amount
                    -app.deposit_held_value_at(returned.deposit_id,'infinity'),0) AS shortfall,
                (SELECT count(DISTINCT listed.entry->>'recipient_customer_id') FROM listed
                    WHERE listed.entry->>'source_kind'='DEPOSIT'
                      AND listed.entry->>'source_id'=returned.deposit_id::text) AS recipients,
                NOT EXISTS(SELECT 1 FROM listed
                    WHERE listed.entry->>'source_kind'='DEPOSIT'
                      AND listed.entry->>'source_id'=returned.deposit_id::text
                      AND (COALESCE((listed.entry->>'reservation_outcome')::boolean,false)
                          OR listed.entry->>'closed_final_settlement_id' IS NOT NULL)) AS plain
            FROM (SELECT receipt.deposit_id,sum(receipt.amount_usd_cents) AS receipt_amount
                FROM app.deposit_receipts receipt
                WHERE receipt.payment_id=p_payment
                  AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                      WHERE reversal.deposit_receipt_id=receipt.id)
                  AND EXISTS(SELECT 1 FROM app.deposit_receipts other
                      WHERE other.deposit_id=receipt.deposit_id AND other.payment_id<>p_payment
                        AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                            WHERE reversal.deposit_receipt_id=other.id))
                GROUP BY receipt.deposit_id) returned
        ), planned AS (
            SELECT listed.position,listed.entry,
                CASE WHEN shared.deposit_id IS NULL THEN NULL
                    WHEN shared.shortfall>0 AND shared.recipients>1 THEN NULL
                    WHEN NOT shared.plain THEN NULL
                    ELSE LEAST((listed.entry->>'amount_usd_cents')::bigint,
                        GREATEST(shared.shortfall-COALESCE(sum((listed.entry->>'amount_usd_cents')::bigint)
                            OVER (PARTITION BY listed.entry->>'source_kind',listed.entry->>'source_id'
                                ORDER BY listed.position DESC
                                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0),0)) END AS share
            FROM listed
            LEFT JOIN shared ON listed.entry->>'source_kind'='DEPOSIT'
                AND listed.entry->>'source_id'=shared.deposit_id::text
        )
        SELECT COALESCE(jsonb_agg(CASE WHEN planned.share IS NULL THEN planned.entry
                ELSE planned.entry || jsonb_build_object('amount_usd_cents',planned.share,
                    'net_usd_cents',(planned.entry->>'amount_usd_cents')::bigint,
                    'shortfall_share',true) END
                ORDER BY planned.position) FILTER (WHERE planned.share IS NULL OR planned.share>0),'[]'::jsonb)
        FROM planned
    $$;

    -- The PAYMENT_RETURN draft's source (its recorder and its confirm): the return source with the
    -- recoveries above and each funded Deposit's shared flag and shortfall (its active receipt from
    -- the returned Payment less what it holds, never below 0). The RETURNED_PAYMENT correction keeps
    -- reading app.payment_return_source, so a shared Deposit stays refused there.
    CREATE FUNCTION app.payment_return_draft_source(p_property uuid, p_payment uuid, p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
        SELECT source||jsonb_build_object(
            'recoveries',app.payment_return_shared_deposit_recoveries(p_property,p_payment),
            'deposits',COALESCE((SELECT jsonb_agg(deposit.value||jsonb_build_object(
                    'shared',EXISTS(SELECT 1 FROM app.deposit_receipts other
                        WHERE other.deposit_id=(deposit.value->>'id')::uuid
                          AND other.payment_id<>p_payment
                          AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                              WHERE reversal.deposit_receipt_id=other.id)),
                    'shortfall_usd_cents',GREATEST(COALESCE((SELECT sum(receipt.amount_usd_cents)
                            FROM app.deposit_receipts receipt
                            WHERE receipt.deposit_id=(deposit.value->>'id')::uuid
                              AND receipt.payment_id=p_payment
                              AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                                  WHERE reversal.deposit_receipt_id=receipt.id)),0)
                        -(deposit.value->>'held_usd_cents')::bigint,0))
                    ORDER BY deposit.position)
                FROM jsonb_array_elements(source->'deposits') WITH ORDINALITY deposit(value,position)),
                '[]'::jsonb))
        FROM app.payment_return_source(p_property,p_payment,p_draft) source
    $$;

    -- The amount a recovery of a shared Deposit's Refund may take inside a confirmed
    -- PAYMENT_RETURN of this transaction whose Payment still has an active receipt in that
    -- Deposit: the row's amount when it is at most the Deposit's shortfall before the row (that
    -- receipt less the held value), otherwise the shortfall, so a larger row is refused. NULL for
    -- every other row, which keeps the whole-net rule. It bounds only the amount: the same check
    -- of app.validate_general_refund_correction still requires app.refund_recovery_allowed (the
    -- confirmed return, its approver under financial.approve, the charge of the same amount).
    CREATE FUNCTION app.payment_return_shortfall_recovery_amount(p_correction app.refund_corrections)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT LEAST((p_correction).source_balance_effect_usd_cents,
            returned.receipt_amount-app.deposit_held_value_at(refund.source_deposit_id,'infinity'))
        FROM app.refunds refund
        CROSS JOIN LATERAL (
            SELECT sum(receipt.amount_usd_cents) AS receipt_amount
            FROM app.payment_returns payment_return
            JOIN app.financial_draft_decisions decision
                ON decision.draft_id=payment_return.draft_id AND decision.decision='CONFIRMED'
                AND decision.decided_by=payment_return.actor_id
            JOIN app.deposit_receipts receipt ON receipt.payment_id=payment_return.payment_id
                AND receipt.deposit_id=refund.source_deposit_id
            WHERE payment_return.settlement_correction_id IS NULL
              AND decision.result->>'transaction_id'=pg_current_xact_id()::text
              AND decision.decided_at>=transaction_timestamp()
              AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                  WHERE reversal.deposit_receipt_id=receipt.id)
              AND EXISTS(SELECT 1 FROM app.deposit_receipts other
                  WHERE other.deposit_id=receipt.deposit_id AND other.payment_id<>receipt.payment_id
                    AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                        WHERE reversal.deposit_receipt_id=other.id))) returned
        WHERE refund.id=(p_correction).refund_id AND refund.source_deposit_id IS NOT NULL
          AND returned.receipt_amount IS NOT NULL
    $$;

    -- A confirmed PAYMENT_RETURN of this transaction reverses its Payment's receipt of a shared
    -- Deposit (another Payment's active receipt is also in it), also while a Refund of that
    -- Deposit stays out.
    CREATE FUNCTION app.payment_return_shared_receipt_reversal_allowed(p_reversal app.deposit_receipt_reversals)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT EXISTS(SELECT 1 FROM app.payment_returns payment_return
                    JOIN app.financial_draft_decisions decision
                        ON decision.draft_id=payment_return.draft_id AND decision.decision='CONFIRMED'
                        AND decision.decided_by=payment_return.actor_id
                    WHERE payment_return.payment_id=receipt.payment_id
                      AND payment_return.settlement_correction_id IS NULL
                      AND decision.result->>'transaction_id'=pg_current_xact_id()::text
                      AND decision.decided_at>=transaction_timestamp())
                AND EXISTS(SELECT 1 FROM app.deposit_receipts other
                    WHERE other.deposit_id=receipt.deposit_id AND other.payment_id<>receipt.payment_id
                      AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                          WHERE reversal.deposit_receipt_id=other.id))
            FROM app.deposit_receipts receipt WHERE receipt.id=(p_reversal).deposit_receipt_id),false)
    $$;
"""

INTERNAL = (
    "app.payment_return_shared_deposit_recoveries(uuid,uuid)",
    "app.payment_return_draft_source(uuid,uuid,uuid)",
    "app.payment_return_shortfall_recovery_amount(app.refund_corrections)",
    "app.payment_return_shared_receipt_reversal_allowed(app.deposit_receipt_reversals)",
)

RECORDER = "app.record_payment_return_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
RECORDER_REPLACEMENTS = (
    (
        "        v_source:=app.payment_return_source(p_property,p_payment,p_draft);\n",
        "        -- Sub-slice 10e-2b-4e-1: the PAYMENT_RETURN draft's own source.\n"
        "        v_source:=app.payment_return_draft_source(p_property,p_payment,p_draft);\n",
    ),
)

ALLOWED = "app.assert_payment_return_recoveries_allowed(jsonb,uuid)"
ALLOWED_REPLACEMENTS = (
    (
        "            WHERE (recovery->>'shared_deposit')::boolean)\n",
        "            WHERE (recovery->>'shared_deposit')::boolean\n"
        "              -- Sub-slice 10e-2b-4e-1 (owner answer (a) to Q-2026-10-18-127): the\n"
        "              -- PAYMENT_RETURN path charges back a shared Deposit's shortfall share.\n"
        "              AND NOT (p_settlement IS NULL\n"
        "                  AND COALESCE((recovery->>'shortfall_share')::boolean,false)))\n",
    ),
)

PLANNED = "app.assert_payment_return_recoveries_planned(jsonb)"
PLANNED_REPLACEMENTS = (
    (
        "                WHERE (deposit->>'unresolved_refund')::boolean AND NOT EXISTS(\n"
        "                    SELECT 1 FROM jsonb_array_elements(COALESCE(p_source->'recoveries','[]'::jsonb)) recovery\n"
        "                    WHERE recovery->>'source_kind'='DEPOSIT' AND recovery->>'source_id'=deposit->>'id'))\n",
        "                WHERE NOT COALESCE((deposit->>'shared')::boolean,false)\n"
        "                  AND (deposit->>'unresolved_refund')::boolean AND NOT EXISTS(\n"
        "                    SELECT 1 FROM jsonb_array_elements(COALESCE(p_source->'recoveries','[]'::jsonb)) recovery\n"
        "                    WHERE recovery->>'source_kind'='DEPOSIT' AND recovery->>'source_id'=deposit->>'id'))\n"
        "            -- Sub-slice 10e-2b-4e-1 (owner answer (a) to Q-2026-10-18-127): a shared\n"
        "            -- Deposit's planned recoveries are exactly its shortfall (none when it is 0).\n"
        "            -- An active forfeiture or application is refused right after this check\n"
        "            -- (review round 1), so it is not compared here.\n"
        "            OR EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_source->'deposits','[]'::jsonb)) deposit\n"
        "                WHERE COALESCE((deposit->>'shared')::boolean,false)\n"
        "                  AND NOT COALESCE((deposit->>'active_forfeiture')::boolean,false)\n"
        "                  AND NOT COALESCE((deposit->>'active_application')::boolean,false)\n"
        "                  AND COALESCE((deposit->>'shortfall_usd_cents')::bigint,0)\n"
        "                    <>COALESCE((SELECT sum((recovery->>'amount_usd_cents')::bigint)\n"
        "                        FROM jsonb_array_elements(COALESCE(p_source->'recoveries','[]'::jsonb)) recovery\n"
        "                        WHERE recovery->>'source_kind'='DEPOSIT'\n"
        "                          AND recovery->>'source_id'=deposit->>'id'),0))\n",
    ),
)

WRITER = "app.write_payment_return_recoveries(uuid,uuid,uuid,uuid,uuid,jsonb,text,text,timestamp with time zone,jsonb)"
WRITER_REPLACEMENTS = (
    (
        "            v_planned:=CASE WHEN p_authorization_evidence->>'variant'='RETURN_REVERSAL'\n"
        "                THEN COALESCE((v_recovery->>'net_usd_cents')::bigint,v_amount) ELSE v_amount END;\n",
        "            v_planned:=CASE WHEN p_authorization_evidence->>'variant'='RETURN_REVERSAL'\n"
        "                    -- Sub-slice 10e-2b-4e-1 (owner answer (a) to Q-2026-10-18-127): with no\n"
        "                    -- correction, a shared Deposit's entry recovers its share of the shortfall.\n"
        "                    OR (p_correction IS NULL\n"
        "                        AND COALESCE((v_recovery->>'shortfall_share')::boolean,false))\n"
        "                THEN COALESCE((v_recovery->>'net_usd_cents')::bigint,v_amount) ELSE v_amount END;\n",
    ),
)

REFUND_CHECK = "app.validate_general_refund_correction()"
REFUND_CHECK_REPLACEMENTS = (
    (
        "                        COALESCE(app.settlement_return_reversal_recovery_amount(NEW),v_net)\n",
        "                        COALESCE(app.settlement_return_reversal_recovery_amount(NEW),\n"
        "                            -- Sub-slice 10e-2b-4e-1: a shared Deposit's shortfall share.\n"
        "                            app.payment_return_shortfall_recovery_amount(NEW),v_net)\n",
    ),
)

REVERSAL_CHECK = "app.validate_deposit_receipt_reversal()"
REVERSAL_CHECK_REPLACEMENTS = (
    (
        "            ) OR app.deposit_has_unresolved_refund(v_deposit_id)\n",
        "            ) OR (app.deposit_has_unresolved_refund(v_deposit_id)\n"
        "                  -- Sub-slice 10e-2b-4e-1 (owner answer (a) to Q-2026-10-18-127): a confirmed\n"
        "                  -- PAYMENT_RETURN of this transaction reverses its Payment's receipt of a\n"
        "                  -- shared Deposit whose Refund stays out; the held history stays at 0 or more.\n"
        "                  AND NOT app.payment_return_shared_receipt_reversal_allowed(NEW))\n",
    ),
)

CONFIRM = "app.confirm_payment_return(uuid,uuid,uuid,text)"
CONFIRM_REPLACEMENTS = (
    (
        "        v_source:=app.payment_return_source(p_property,v_payment.id,p_draft);\n",
        "        -- Sub-slice 10e-2b-4e-1: the PAYMENT_RETURN draft's own source.\n"
        "        v_source:=app.payment_return_draft_source(p_property,v_payment.id,p_draft);\n",
    ),
    (
        "            IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_source->'recoveries') recovery\n"
        "                WHERE recovery->>'source_kind'='DEPOSIT'\n"
        "                  AND recovery->>'source_id'=v_row.deposit_id::text)\n",
        "            IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_source->'recoveries') recovery\n"
        "                WHERE recovery->>'source_kind'='DEPOSIT'\n"
        "                  AND recovery->>'source_id'=v_row.deposit_id::text)\n"
        "                -- Sub-slice 10e-2b-4e-1: also a shared Deposit whose Refund stays out, when\n"
        "                -- its shortfall is 0 and nothing was charged back.\n"
        "                OR EXISTS(SELECT 1 FROM jsonb_array_elements(v_source->'deposits') deposit\n"
        "                    WHERE deposit->>'id'=v_row.deposit_id::text\n"
        "                      AND COALESCE((deposit->>'shared')::boolean,false)\n"
        "                      AND (deposit->>'unresolved_refund')::boolean)\n",
    ),
)

PATCHES = (
    (RECORDER, RECORDER_REPLACEMENTS),
    (ALLOWED, ALLOWED_REPLACEMENTS),
    (PLANNED, PLANNED_REPLACEMENTS),
    (WRITER, WRITER_REPLACEMENTS),
    (REFUND_CHECK, REFUND_CHECK_REPLACEMENTS),
    (REVERSAL_CHECK, REVERSAL_CHECK_REPLACEMENTS),
    (CONFIRM, CONFIRM_REPLACEMENTS),
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
            raise RuntimeError(f"Payment return shared Deposit contract changed: {signature}")
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
    raise RuntimeError("Payment return shared Deposit migration is forward-only")
