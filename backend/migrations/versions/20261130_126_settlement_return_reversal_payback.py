# ruff: noqa: E501
"""Who pays back, and how much, in a return reversal (V1-056 sub-slice 10e-3b).

BR-SETTLE-013, BR-SETTLE-016, BR-REFUND-015, DL-032; DB-REFUND-002, DB-SETTLE-005; owner answers
(a) to Q-2026-10-12-94 and (a) to Q-2026-10-12-95:

- Q-94: the person who received a Refund pays it back, also an agreed second Signer who is not the
  Deposit's own Customer (the Q-2026-10-11-78 rule). The `RETURN_REVERSAL` refusal of such a
  Refund is removed; the sub-slice 10e-1c writer charges that person (an `EXTRA_CHARGE` on the
  Lease when that person is its signed Customer, else a no-Lease charge).
- Q-95: only the mistaken amount is charged back. When the uses of the returned value are more
  than the returned amount, the Refunds paid out the returned money first (the owner answer to
  Q-2026-10-10-76), the oldest first: each is charged back only for its share of the returned
  amount, the rest of it stays paid, and every Deposit or Credit application stays. When the
  Refunds paid out less than the returned amount, the rest of it paid debt; that case is refused
  until the owner answers Q-2026-10-12-96.

Relaxing changes only: the source state shares the returned amount over the Refunds; the refusal
of an agreed-Signer recipient is removed and the refusal of uses beyond the return narrowed (on
the shared path a Refund of the uses with its own return is still refused); the recovery scope
check accepts the Refund's own recipient as recorded; the recovery writer may recover a recorded
share of a Refund inside a `RETURN_REVERSAL` only; the general Refund correction check accepts a
recovery of exactly the share a `RETURN_REVERSAL` draft recorded (every other recovery is still
the whole net); a later recovery of a partly recovered Refund gets its own charge reference, so its
rest can be charged back too (review round 1).
"""

from alembic import op
from sqlalchemy import text

revision = "20261130_126"
down_revision = "20261129_125"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- Sub-slice 10e-3b (owner answer (a) to Q-2026-10-12-95): the amount that the RETURN_REVERSAL
    -- draft whose correction links a recovery row recorded for that row's Refund, when that draft
    -- was confirmed in this transaction by the correction's approver, who is the row's actor
    -- (review rounds 1 and 2); NULL for a row that no such draft names. 0 (so the row is
    -- refused) when the draft names the Refund more than once, or when the same correction
    -- already links a recovery of that Refund (review round 2: one share, once).
    CREATE FUNCTION app.settlement_return_reversal_recovery_amount(p_correction app.refund_corrections)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT CASE WHEN found.items=0 THEN NULL
            WHEN found.items=1 AND NOT found.repeated THEN found.amount ELSE 0 END
        FROM (SELECT count(item) AS items,min((item->>'amount_usd_cents')::bigint) AS amount,
                COALESCE(bool_or(EXISTS(SELECT 1 FROM app.settlement_correction_effects other
                    JOIN app.refund_corrections earlier_row ON earlier_row.id=other.refund_correction_id
                    WHERE other.settlement_correction_id=correction.id
                      AND earlier_row.refund_id=(p_correction).refund_id
                      AND earlier_row.correction_kind='RECOVERED_BY_CHARGE'
                      AND earlier_row.id<>(p_correction).id)),false) AS repeated
            FROM app.settlement_correction_effects effect
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            JOIN app.financial_drafts draft ON draft.id=correction.correlation_id
                AND draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='RETURN_REVERSAL'
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
                AND decision.decision='CONFIRMED' AND decision.decided_by=correction.actor_id
            CROSS JOIN LATERAL jsonb_array_elements(draft.payload->'source'->'recoveries') item
            WHERE effect.refund_correction_id=(p_correction).id
              AND correction.actor_id=(p_correction).actor_id
              AND decision.result->>'transaction_id'=pg_current_xact_id()::text
              AND decision.decided_at>=transaction_timestamp()
              AND item->>'refund_id'=(p_correction).refund_id::text) found
    $$;

    -- Sub-slice 10e-3b (review round 1): the source reference of the next recovery charge of a
    -- Refund. The first keeps 'refund-recovery:<Refund>'; a later one (the rest of a Refund that
    -- a RETURN_REVERSAL charged back only in part) adds its number, because the obligation key
    -- is unique per Customer, category and reference. It counts the Refund's recoveries dated
    -- before p_before (every one when NULL, as the writer asks before its row exists), so the
    -- recovery check of a row gives the same answer before and after the row is written (review
    -- round 2).
    CREATE FUNCTION app.refund_recovery_source_reference(p_refund uuid, p_before timestamptz)
    RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT 'refund-recovery:' || p_refund::text
            || CASE WHEN count(*)>0 THEN ':' || (count(*)+1)::text ELSE '' END
        FROM app.refund_corrections correction
        WHERE correction.refund_id=p_refund AND correction.correction_kind='RECOVERED_BY_CHARGE'
          AND (p_before IS NULL OR correction.occurred_at<p_before)
    $$;
"""

INTERNAL = (
    "app.settlement_return_reversal_recovery_amount(app.refund_corrections)",
    "app.refund_recovery_source_reference(uuid,timestamp with time zone)",
)

SOURCE = "app.settlement_return_reversal_source_state(uuid,uuid)"
SOURCE_REPLACEMENTS = (
    (
        """               OR refund.source_deposit_id=earlier.deposit_id
        )
        SELECT jsonb_build_object(""",
        """               OR refund.source_deposit_id=earlier.deposit_id
        -- Sub-slice 10e-3b (owner answer (a) to Q-2026-10-12-95): the totals of the uses. When
        -- they are more than the returned amount, the Refunds paid out the returned money first,
        -- the oldest first (the owner answer to Q-2026-10-10-76), so each is charged back only for
        -- its share of the returned amount; when they also paid out the whole returned amount,
        -- every application stays. When they paid out less, the rest of the returned money paid
        -- debt, which waits for the owner (Q-2026-10-12-96, refused).
        ), totals AS (
            SELECT (SELECT earlier.amount FROM earlier) AS returned,
                ((SELECT COALESCE(sum(credit_use.amount_usd_cents),0) FROM credit_applications credit_use)
                    +(SELECT COALESCE(sum(deposit_use.amount_usd_cents),0)
                        FROM deposit_applications deposit_use))::bigint AS applied,
                (SELECT COALESCE(sum(refund_use.net),0) FROM paid refund_use
                    WHERE refund_use.net>0)::bigint AS refunded,
                -- Review round 1: the Refunds of the uses with their own return, also one
                -- returned in full (on the shared path its share would move to another Refund).
                (SELECT count(*) FROM paid refund_back WHERE refund_back.returns>0) AS returned_refunds
        ), shares AS (
            SELECT paid.id,CASE WHEN totals.applied+totals.refunded>totals.returned
                    THEN LEAST(paid.net,GREATEST(0,totals.returned-COALESCE(sum(paid.net) OVER (
                        ORDER BY paid.processed_at,paid.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)))
                    ELSE paid.net END::bigint AS amount
            FROM paid CROSS JOIN totals WHERE paid.net>0
        ), covered AS (
            SELECT COALESCE(totals.applied+totals.refunded>totals.returned
                AND totals.refunded>=totals.returned,false) AS refunds_only FROM totals
        )
        SELECT jsonb_build_object(""",
    ),
    (
        """                FROM credit_applications application),""",
        """                FROM credit_applications application
                -- Sub-slice 10e-3b: the Refunds took the whole returned amount.
                WHERE NOT (SELECT covered.refunds_only FROM covered)),""",
    ),
    (
        """                FROM deposit_applications application),""",
        """                FROM deposit_applications application
                WHERE NOT (SELECT covered.refunds_only FROM covered)),""",
    ),
    (
        """                    'amount_usd_cents',paid.net,'lease_id',paid.lease_id,""",
        """                    'amount_usd_cents',shares.amount,'net_usd_cents',paid.net,
                    'lease_id',paid.lease_id,""",
    ),
    (
        """                FROM paid WHERE paid.net>0),""",
        """                FROM paid JOIN shares ON shares.id=paid.id WHERE shares.amount>0),
            'uses',(SELECT jsonb_build_object('applied_usd_cents',totals.applied,
                    'refunded_usd_cents',totals.refunded,'returned_refunds',totals.returned_refunds)
                FROM totals),""",
    ),
)

ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
ASSERT_REPLACEMENTS = (
    (
        """        -- Q-2026-10-12-94: who pays back a Deposit Refund paid to an agreed Signer waits for the
        -- owner.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'recoveries') recovery
            WHERE NOT (recovery->>'deposit_customer')::boolean)
        THEN RAISE EXCEPTION 'Who pays back a Deposit Refund paid to an agreed Signer is not decided yet'
            USING ERRCODE='55000'; END IF;
""",
        """        -- Owner answer (a) to Q-2026-10-12-94 (sub-slice 10e-3b): the person who received a
        -- Refund pays it back, also an agreed Signer who is not the Deposit's own Customer.
""",
    ),
    (
        """        -- Q-2026-10-12-95: the uses to undo are more than the returned amount (a REFUND_RETURN
        -- with a new Refund also applied or refunded money its source already held), so who pays
        -- back the part the return did not bring back waits for the owner (review round 1).
        IF (SELECT COALESCE(sum((application->>'amount_usd_cents')::bigint),0)
                FROM jsonb_array_elements((p_source->'credit_applications')
                    ||(p_source->'deposit_applications')) application)
            +(SELECT COALESCE(sum((recovery->>'amount_usd_cents')::bigint),0)
                FROM jsonb_array_elements(p_source->'recoveries') recovery)
            >(p_source->'earlier'->>'amount_usd_cents')::bigint
        THEN RAISE EXCEPTION 'The correction to reverse also used money its return did not bring back; reversing it waits for the owner'
            USING ERRCODE='55000'; END IF;
""",
        """        -- Owner answer (a) to Q-2026-10-12-95 (sub-slice 10e-3b): when the uses are more than the
        -- returned amount, the Refunds paid out the returned money first (the source state shares
        -- it over them and keeps every application). When the Refunds paid out less than the
        -- returned amount, the rest of it paid debt, and which part of an application comes back
        -- waits for the owner (Q-2026-10-12-96). On the shared path a Refund of the uses with its
        -- own return, also one returned in full, is refused as above (review round 1). Both
        -- checks fail closed when the totals are missing; missing totals have their own message
        -- (review round 2).
        IF jsonb_typeof(p_source->'uses') IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
        IF COALESCE((p_source->'uses'->>'applied_usd_cents')::bigint
                +(p_source->'uses'->>'refunded_usd_cents')::bigint
                >(p_source->'earlier'->>'amount_usd_cents')::bigint
            AND (p_source->'uses'->>'returned_refunds')::bigint>0,true)
        THEN RAISE EXCEPTION 'A Refund paid from the returned value has its own return; reverse that return first'
            USING ERRCODE='55000'; END IF;
        IF COALESCE((p_source->'uses'->>'applied_usd_cents')::bigint
                +(p_source->'uses'->>'refunded_usd_cents')::bigint
                >(p_source->'earlier'->>'amount_usd_cents')::bigint
            AND (p_source->'uses'->>'refunded_usd_cents')::bigint
                <(p_source->'earlier'->>'amount_usd_cents')::bigint,true)
        THEN RAISE EXCEPTION 'The returned money also paid debt beyond what its Refunds paid out; reversing it waits for the owner'
            USING ERRCODE='55000'; END IF;
""",
    ),
)

SCOPE = "app.settlement_return_reversal_refund(uuid,uuid)"
SCOPE_REPLACEMENTS = (
    (
        """                      WHERE item->>'refund_id'=p_refund::text
                        AND (item->>'deposit_customer')::boolean))""",
        """                      WHERE item->>'refund_id'=p_refund::text
                        -- Sub-slice 10e-3b (owner answer (a) to Q-2026-10-12-94): the recorded
                        -- recipient is the Refund's own, an agreed Signer too.
                        AND item->>'recipient_customer_id'=refund.recipient_customer_id::text))""",
    ),
)

GENERAL = "app.validate_general_refund_correction()"
GENERAL_REPLACEMENTS = (
    (
        """                    OR NEW.source_balance_effect_usd_cents<>v_net
""",
        """                    -- Sub-slice 10e-3b (owner answer (a) to Q-2026-10-12-95): a RETURN_REVERSAL
                    -- recovers the amount its draft recorded, which can be only the share of the
                    -- Refund that paid out the returned money; every other recovery the whole net.
                    OR NEW.source_balance_effect_usd_cents>v_net
                    OR NEW.source_balance_effect_usd_cents IS DISTINCT FROM
                        COALESCE(app.settlement_return_reversal_recovery_amount(NEW),v_net)
""",
    ),
)

RECOVERY_WRITER = "app.write_payment_return_recoveries(uuid,uuid,uuid,uuid,uuid,jsonb,text,text,timestamp with time zone,jsonb)"
RECOVERY_WRITER_REPLACEMENTS = (
    (
        """        v_lease uuid; v_from text;
    BEGIN
""",
        """        v_lease uuid; v_from text; v_amount bigint; v_planned bigint;
    BEGIN
""",
    ),
    (
        """            IF v_net IS DISTINCT FROM (v_recovery->>'amount_usd_cents')::bigint OR v_net<=0
""",
        """            -- Sub-slice 10e-3b (owner answer (a) to Q-2026-10-12-95): inside a RETURN_REVERSAL an
            -- entry that names the Refund's net may recover only a share of it; any other entry,
            -- and every other caller, the whole net (review round 1).
            v_amount:=(v_recovery->>'amount_usd_cents')::bigint;
            v_planned:=CASE WHEN p_authorization_evidence->>'variant'='RETURN_REVERSAL'
                THEN COALESCE((v_recovery->>'net_usd_cents')::bigint,v_amount) ELSE v_amount END;
            IF v_net IS DISTINCT FROM v_planned
                OR v_net<=0 OR v_amount IS NULL OR v_amount<=0 OR v_amount>v_net
""",
    ),
    (
        """                p_evidence,'refund-recovery:' || v_refund.id::text,
""",
        """                -- Sub-slice 10e-3b (review round 1): a later recovery of a partly recovered
                -- Refund gets its own reference.
                p_evidence,app.refund_recovery_source_reference(v_refund.id,NULL),
""",
    ),
    (
        """                v_net,NULL,NULL,'A Refund paid from ' || v_from || ' is charged back to its recipient',
""",
        """                v_amount,NULL,NULL,'A Refund paid from ' || v_from || ' is charged back to its recipient',
""",
    ),
    (
        """            VALUES (v_row,v_refund.id,'RECOVERED_BY_CHARGE',NULL,v_net,v_net,v_net,0,p_reason,
""",
        """            VALUES (v_row,v_refund.id,'RECOVERED_BY_CHARGE',NULL,v_amount,v_amount,v_net,v_net-v_amount,p_reason,
""",
    ),
)

RECOVERY = "app.refund_recovery_allowed(app.refund_corrections)"
RECOVERY_REPLACEMENTS = (
    (
        """                      AND obligation.source_reference='refund-recovery:' || refund.id::text)""",
        """                      -- Sub-slice 10e-3b (review round 1): the reference of this recovery,
                      -- numbered after an earlier recovery of a part of the Refund.
                      AND obligation.source_reference=app.refund_recovery_source_reference(refund.id,
                          (p_correction).occurred_at))""",
    ),
)

PATCHES = (
    (SOURCE, SOURCE_REPLACEMENTS),
    (ASSERT, ASSERT_REPLACEMENTS),
    (SCOPE, SCOPE_REPLACEMENTS),
    (GENERAL, GENERAL_REPLACEMENTS),
    (RECOVERY_WRITER, RECOVERY_WRITER_REPLACEMENTS),
    (RECOVERY, RECOVERY_REPLACEMENTS),
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
            raise RuntimeError(f"Settlement return reversal payback contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(FUNCTION_SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Settlement return reversal payback migration is forward-only")
