# ruff: noqa: E501
"""The mistaken part of returned money that paid debt (V1-056 sub-slice 10e-3c).

BR-SETTLE-013, BR-SETTLE-016, DL-032; DB-SETTLE-005; owner answer (a) to Q-2026-10-12-96:

- A `RETURN_REVERSAL` whose uses of the returned value are more than the returned amount, while
  the Refunds of those uses paid out less than it, is no longer refused. Each Refund is charged
  back whole (its share is its whole net, sub-slice 10e-3b), so the rest of the returned amount
  paid debt. The newest applications of the uses are reversed whole until that rest is reached,
  and the part of the last of them that was not returned money is applied again to the same
  obligation from the same Credit or Deposit, in the same correction, linked before it is written
  (a new application). Only the mistaken amount comes back: the Refunds charged back and the
  debt owed again add up to the returned amount.
- The re-applied part is written right after the return is reversed (the source then holds that
  part): a Credit through the Settlement Credit writer reading a one-step plan the recorder stores
  in the draft, a Deposit through the Deposit application writer with the reversed application's
  stage and target, its check reading the same plan.

Relaxing changes: the refusal "The returned money also paid debt beyond what its Refunds paid out;
reversing it waits for the owner" is removed. Fail closed: the source must name the re-applied
part as a list of at most one entry (an entry only in that case), from a listed application of the
returned Refund's own Credit or Deposit, with the same obligation kind (and target for a
Late-payment Charge or a Deposit line), above 0 and below that application's amount; the reversal never brings back more than the returned amount (exactly that
amount when the uses are more than it); the confirm accepts only a draft whose payload has exactly
the recorder's keys and whose plan is the one built from its source. A RETURN_REVERSAL draft
recorded before this migration is stale at its confirm (P5S02, its source gained `reapply`); staff
reject it and record it again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261202_128"
down_revision = "20261201_127"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- Sub-slice 10e-3c: the one-step plan of the part a RETURN_REVERSAL applies again (no step
    -- when nothing is applied again), in the step format of the shared DL-032 step (sub-slice
    -- 10c-2a-2), read by the Settlement Credit application writer and the Deposit application
    -- check. An entry of an unknown source or stage gives no valid step (fail closed).
    CREATE FUNCTION app.settlement_return_reversal_reapply_steps(p_source jsonb)
    RETURNS jsonb LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE(jsonb_agg(CASE item->>'source_kind'
                WHEN 'CREDIT' THEN jsonb_build_object('kind','CUSTOMER_CREDIT',
                        'customer_credit_id',item->'customer_credit_id',
                        'target_kind',item->'target_kind','target_id',item->'target_id',
                        'amount_usd_cents',item->'amount_usd_cents')
                    ||CASE WHEN jsonb_typeof(item->'customer_designation')='string'
                        THEN jsonb_build_object('customer_designation',item->'customer_designation')
                        ELSE '{}'::jsonb END
                WHEN 'DEPOSIT' THEN jsonb_build_object('kind',CASE item->>'application_stage'
                            WHEN 'PET_RELATED_FIRST' THEN 'PET_DEPOSIT_PET_DAMAGE'
                            WHEN 'SECURITY_EXPLICIT' THEN 'SECURITY_DEPOSIT'
                            WHEN 'PET_REMAINDER_EXPLICIT' THEN 'PET_DEPOSIT_REMAINDER' END,
                        'deposit_id',item->'deposit_id',
                        'target_kind',item->'target_kind','target_id',item->'target_id',
                        'amount_usd_cents',item->'amount_usd_cents') END
                ORDER BY entry.position),'[]'::jsonb)
        FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_source->'reapply')='array'
            THEN p_source->'reapply' ELSE '[]'::jsonb END) WITH ORDINALITY entry(item,position)
    $$;
"""

INTERNAL = ("app.settlement_return_reversal_reapply_steps(jsonb)",)

SOURCE = "app.settlement_return_reversal_source_state(uuid,uuid)"
SOURCE_REPLACEMENTS = (
    (
        """        -- debt, which waits for the owner (Q-2026-10-12-96, refused).
""",
        """        -- debt (Q-2026-10-12-96; sub-slice 10e-3c below).
""",
    ),
    (
        """        ), covered AS (
            SELECT COALESCE(totals.applied+totals.refunded>totals.returned
                AND totals.refunded>=totals.returned,false) AS refunds_only FROM totals
        )
        SELECT jsonb_build_object(""",
        """        ), covered AS (
            SELECT COALESCE(totals.applied+totals.refunded>totals.returned
                AND totals.refunded>=totals.returned,false) AS refunds_only FROM totals
        -- Sub-slice 10e-3c (owner answer (a) to Q-2026-10-12-96): when the uses are more than the
        -- returned amount and the Refunds paid out less than it, each Refund is charged back whole
        -- (its share is its whole net) and the rest of the returned amount paid debt. The newest
        -- applications are then reversed whole until that rest is reached, and the part of the
        -- last of them that was not returned money is applied again to the same obligation from
        -- the same Credit or Deposit, so only the mistaken amount comes back. In every other case
        -- each listed application is reversed and nothing is applied again.
        ), partial AS (
            SELECT COALESCE(totals.applied+totals.refunded>totals.returned
                AND totals.refunded<totals.returned,false) AS debt_paid,
                totals.returned-totals.refunded AS rest FROM totals
        ), newer AS (
            SELECT 'CREDIT' AS kind,application.id,application.amount_usd_cents,
                COALESCE(sum(application.amount_usd_cents) OVER (
                    ORDER BY application.occurred_at DESC,application.id DESC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) AS before_it
            FROM credit_applications application
            UNION ALL
            SELECT 'DEPOSIT',application.id,application.amount_usd_cents,
                COALESCE(sum(application.amount_usd_cents) OVER (
                    ORDER BY application.occurred_at DESC,application.application_order DESC,
                        application.id DESC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)
            FROM deposit_applications application
        ), undone AS (
            SELECT newer.* FROM newer CROSS JOIN partial
            WHERE NOT partial.debt_paid OR newer.before_it<partial.rest
        ), restored AS (
            SELECT undone.kind,undone.id,undone.amount_usd_cents AS reversed_usd_cents,
                (undone.before_it+undone.amount_usd_cents-partial.rest)::bigint AS amount
            FROM undone CROSS JOIN partial
            WHERE partial.debt_paid AND undone.before_it+undone.amount_usd_cents>partial.rest
        )
        SELECT jsonb_build_object(""",
    ),
    (
        """                FROM credit_applications application
                -- Sub-slice 10e-3b: the Refunds took the whole returned amount.
                WHERE NOT (SELECT covered.refunds_only FROM covered)),""",
        """                FROM credit_applications application
                -- Sub-slice 10e-3b: the Refunds took the whole returned amount.
                WHERE NOT (SELECT covered.refunds_only FROM covered)
                  -- Sub-slice 10e-3c: the newest, up to the rest the debt took.
                  AND application.id IN (SELECT undone.id FROM undone)),""",
    ),
    (
        """                FROM deposit_applications application
                WHERE NOT (SELECT covered.refunds_only FROM covered)),""",
        """                FROM deposit_applications application
                WHERE NOT (SELECT covered.refunds_only FROM covered)
                  AND application.id IN (SELECT undone.id FROM undone)),""",
    ),
    (
        """            'uses',(SELECT jsonb_build_object('applied_usd_cents',totals.applied,
                    'refunded_usd_cents',totals.refunded,'returned_refunds',totals.returned_refunds)
                FROM totals),""",
        """            'uses',(SELECT jsonb_build_object('applied_usd_cents',totals.applied,
                    'refunded_usd_cents',totals.refunded,'returned_refunds',totals.returned_refunds)
                FROM totals),
            -- Sub-slice 10e-3c: the part applied again (at most one entry): the reversed
            -- application, its source, its obligation (a Credit application's one detail names
            -- its line), its stage or Customer designation, and the amount that was not returned
            -- money.
            'reapply',(SELECT COALESCE(jsonb_agg(jsonb_build_object('source_kind',restored.kind,
                    'application_id',restored.id,'reversed_usd_cents',restored.reversed_usd_cents,
                    'amount_usd_cents',restored.amount,
                    'customer_credit_id',credit_use.customer_credit_id,
                    'deposit_id',deposit_use.deposit_id,
                    'application_stage',deposit_use.application_stage,
                    'target_kind',CASE WHEN COALESCE(credit_use.late_payment_charge_id,
                            deposit_use.late_payment_charge_id) IS NOT NULL
                        THEN 'LATE_PAYMENT_CHARGE' ELSE 'INVOICE_LINE' END,
                    'target_id',COALESCE(credit_use.late_payment_charge_id,
                        deposit_use.late_payment_charge_id,detail.invoice_line_id,
                        deposit_use.invoice_line_id),
                    'customer_designation',credit_use.customer_designation_reference)
                    ORDER BY restored.id,detail.id),'[]'::jsonb)
                FROM restored
                LEFT JOIN app.customer_credit_applications credit_use
                    ON restored.kind='CREDIT' AND credit_use.id=restored.id
                LEFT JOIN app.customer_credit_application_details detail
                    ON detail.customer_credit_application_id=credit_use.id
                LEFT JOIN app.deposit_applications deposit_use
                    ON restored.kind='DEPOSIT' AND deposit_use.id=restored.id),""",
    ),
)

ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
ASSERT_REPLACEMENTS = (
    (
        """        -- returned amount, the rest of it paid debt, and which part of an application comes back
        -- waits for the owner (Q-2026-10-12-96). On the shared path a Refund of the uses with its
        -- own return, also one returned in full, is refused as above (review round 1). Both
        -- checks fail closed when the totals are missing; missing totals have their own message
""",
        """        -- returned amount, the rest of it paid debt, and only the part of the applications that
        -- was returned money comes back (Q-2026-10-12-96, sub-slice 10e-3c, below). On the shared
        -- path a Refund of the uses with its own return, also one returned in full, is refused as
        -- above (review round 1). The check fails closed when the totals are missing; missing
        -- totals have their own message
""",
    ),
    (
        """        IF COALESCE((p_source->'uses'->>'applied_usd_cents')::bigint
                +(p_source->'uses'->>'refunded_usd_cents')::bigint
                >(p_source->'earlier'->>'amount_usd_cents')::bigint
            AND (p_source->'uses'->>'refunded_usd_cents')::bigint
                <(p_source->'earlier'->>'amount_usd_cents')::bigint,true)
        THEN RAISE EXCEPTION 'The returned money also paid debt beyond what its Refunds paid out; reversing it waits for the owner'
            USING ERRCODE='55000'; END IF;
""",
        """        -- Sub-slice 10e-3c (owner answer (a) to Q-2026-10-12-96): Refunds that paid out less than
        -- the returned amount no longer wait for the owner; the source lists only the newest
        -- applications up to the rest of the returned amount and names at most one part to apply
        -- again. Fail closed: that part is a list, with an entry only in that case and at most
        -- one, from a listed application of the returned Refund's own Credit or Deposit and of the
        -- same obligation (review round 1), above 0 and below that application's amount; and the
        -- reversal never brings back more than the returned amount, and exactly that amount when
        -- the uses are more than it (review round 1).
        IF jsonb_typeof(p_source->'reapply') IS DISTINCT FROM 'array'
            -- In parentheses: PL/pgSQL ends an IF condition at the first THEN outside them.
            OR (CASE WHEN jsonb_typeof(p_source->'reapply')='array'
                THEN jsonb_array_length(p_source->'reapply')>1
                    OR (jsonb_array_length(p_source->'reapply')>0
                        AND NOT COALESCE((p_source->'uses'->>'applied_usd_cents')::bigint
                            +(p_source->'uses'->>'refunded_usd_cents')::bigint
                            >(p_source->'earlier'->>'amount_usd_cents')::bigint
                            AND (p_source->'uses'->>'refunded_usd_cents')::bigint
                                <(p_source->'earlier'->>'amount_usd_cents')::bigint,false))
                ELSE true END)
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_source->'reapply')='array'
                    THEN p_source->'reapply' ELSE '[]'::jsonb END) item
                WHERE NOT COALESCE((item->>'amount_usd_cents')::bigint>0
                    AND EXISTS(SELECT 1 FROM jsonb_array_elements(CASE item->>'source_kind'
                            WHEN 'CREDIT' THEN p_source->'credit_applications'
                            WHEN 'DEPOSIT' THEN p_source->'deposit_applications' END) application
                        WHERE application->>'id'=item->>'application_id'
                          AND (item->>'amount_usd_cents')::bigint
                              <(application->>'amount_usd_cents')::bigint
                          AND COALESCE(item->>'customer_credit_id','')
                              =COALESCE(application->>'customer_credit_id','')
                          AND COALESCE(item->>'deposit_id','')=COALESCE(application->>'deposit_id','')
                          AND COALESCE(item->>'customer_credit_id',item->>'deposit_id')
                              IN (p_source->'earlier'->>'customer_credit_id',
                                  p_source->'earlier'->>'deposit_id')
                          AND (item->>'target_kind'='LATE_PAYMENT_CHARGE')
                              =(application->>'late_payment_charge_id' IS NOT NULL)
                          AND (application->>'late_payment_charge_id' IS NULL
                              OR item->>'target_id'=application->>'late_payment_charge_id')
                          AND (item->>'source_kind'='CREDIT'
                              OR application->>'late_payment_charge_id' IS NOT NULL
                              OR item->>'target_id'=application->>'invoice_line_id')),false))
        THEN RAISE EXCEPTION 'The part of a return reversal applied again is invalid'
            USING ERRCODE='55000'; END IF;
        IF NOT COALESCE((SELECT back.amount<=returned.amount
                AND (back.uses<=returned.amount OR back.amount=returned.amount)
            FROM (SELECT (SELECT COALESCE(sum((application->>'amount_usd_cents')::bigint),0)
                        FROM jsonb_array_elements((p_source->'credit_applications')
                            ||(p_source->'deposit_applications')) application)
                    -(SELECT COALESCE(sum((item->>'amount_usd_cents')::bigint),0)
                        FROM jsonb_array_elements(p_source->'reapply') item)
                    +(SELECT COALESCE(sum((recovery->>'amount_usd_cents')::bigint),0)
                        FROM jsonb_array_elements(p_source->'recoveries') recovery) AS amount,
                    (p_source->'uses'->>'applied_usd_cents')::bigint
                        +(p_source->'uses'->>'refunded_usd_cents')::bigint AS uses) back
            CROSS JOIN (SELECT (p_source->'earlier'->>'amount_usd_cents')::bigint AS amount) returned),false)
        THEN RAISE EXCEPTION 'A return reversal brings back only the returned amount'
            USING ERRCODE='55000'; END IF;
""",
    ),
    (
        """            +(SELECT COALESCE(sum((recovery->>'amount_usd_cents')::bigint),0)
                FROM jsonb_array_elements(p_source->'recoveries') recovery)
            >=(p_source->'earlier'->>'amount_usd_cents')::bigint,false)""",
        """            +(SELECT COALESCE(sum((recovery->>'amount_usd_cents')::bigint),0)
                FROM jsonb_array_elements(p_source->'recoveries') recovery)
            -- Sub-slice 10e-3c: the source must still hold the part applied again after the
            -- return is reversed.
            -(SELECT COALESCE(sum((item->>'amount_usd_cents')::bigint),0)
                FROM jsonb_array_elements(p_source->'reapply') item)
            >=(p_source->'earlier'->>'amount_usd_cents')::bigint,false)""",
    ),
)

RECORD = "app.record_settlement_return_reversal_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
RECORD_REPLACEMENTS = (
    (
        """            'return_reversal',v_input,'source',v_source);""",
        """            'return_reversal',v_input,'source',v_source,
            -- Sub-slice 10e-3c: the one-step plan of the part applied again (no step otherwise),
            -- read by the Credit application writer and the Deposit application check.
            'plan',jsonb_build_object('steps',app.settlement_return_reversal_reapply_steps(v_source)));""",
    ),
)

CONFIRM = "app.confirm_settlement_return_reversal(uuid,uuid,uuid,text)"
CONFIRM_REPLACEMENTS = (
    (
        """        v_return app.refund_corrections%ROWTYPE; v_refund app.refunds%ROWTYPE; v_net bigint;
    BEGIN""",
        """        v_return app.refund_corrections%ROWTYPE; v_refund app.refunds%ROWTYPE; v_net bigint;
        v_reapply jsonb; v_reapplied uuid; v_order integer;
    BEGIN""",
    ),
    (
        """            OR v_draft.payload->'returned_amount_usd_cents'
                IS DISTINCT FROM v_source->'earlier'->'amount_usd_cents'
""",
        """            OR v_draft.payload->'returned_amount_usd_cents'
                IS DISTINCT FROM v_source->'earlier'->'amount_usd_cents'
            -- Sub-slice 10e-3c: the stored plan is the one-step plan of the part applied again,
            -- and the payload has exactly the recorder's keys (review round 1: no plan overlay
            -- can map the step's target to another line).
            OR v_draft.payload->'plan' IS DISTINCT FROM jsonb_build_object('steps',
                app.settlement_return_reversal_reapply_steps(v_source))
            OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(v_draft.payload) key)
                IS DISTINCT FROM ARRAY['customer_credit_id','deposit_id','final_settlement_id',
                    'held_from_settlement_correction_id','lease_id','plan','refund_id',
                    'return_reversal','returned_amount_usd_cents','source','variant']
            -- Review round 2: the stored Lease is the Settlement's, as the other confirms check.
            OR v_draft.payload->'lease_id' IS DISTINCT FROM to_jsonb(v_settlement.lease_id)
""",
    ),
    (
        """            v_draft.reason,v_input->>'evidence_reference',v_at,p_actor,'refunds.corrections.reverse');
""",
        """            v_draft.reason,v_input->>'evidence_reference',v_at,p_actor,'refunds.corrections.reverse');
        -- Sub-slice 10e-3c (owner answer (a) to Q-2026-10-12-96): the part of the last reversed
        -- application that was not returned money is applied again to the same obligation from
        -- the same Credit or Deposit, after the return is reversed (the source then holds that
        -- part), linked to the correction before it is written: a Credit through the Settlement
        -- Credit writer, which reads the draft's one-step plan; a Deposit through the Deposit
        -- application writer with the reversed application's stage and target, numbered after
        -- the Settlement's last application, its check reading the same plan. The audit event
        -- is dated at the latest record (review round 1).
        v_reapply:=v_source->'reapply'->0;
        IF v_reapply->>'source_kind'='CREDIT' THEN
            v_at:=GREATEST(v_at,(app.post_final_settlement_credit_application(p_property,p_actor,
                v_settlement.id,p_draft,1)->>'occurred_at')::timestamptz);
        ELSIF v_reapply->>'source_kind'='DEPOSIT' THEN
            SELECT COALESCE(max(application.application_order),0)+1 INTO v_order
            FROM app.deposit_applications application
            WHERE application.final_settlement_id=v_settlement.id;
            v_reapplied:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(v_correction,'deposit_application_id',v_reapplied);
            v_at:=GREATEST(v_at,(app.post_deposit_application(p_property,p_actor,v_settlement.id,
                v_reapplied,(v_reapply->>'deposit_id')::uuid,v_reapply->>'application_stage',
                v_reapply->>'target_kind',(v_reapply->>'target_id')::uuid,
                (v_reapply->>'amount_usd_cents')::bigint,v_order,v_draft.reason)->>'occurred_at')::timestamptz);
        END IF;
""",
    ),
    (
        """                'recoveries',v_result->'recoveries'),""",
        """                'recoveries',v_result->'recoveries',
                -- Sub-slice 10e-3c: the part applied again.
                'reapplied',v_result->'reapplied'),""",
    ),
)

RESULT = "app.settlement_return_reversal_result(uuid)"
RESULT_REPLACEMENTS = (
    (
        """            'recoveries',(SELECT COALESCE(jsonb_agg(app.refund_recovery_json(recovery.id)""",
        """            -- Sub-slice 10e-3c: the part applied again (a Credit or Deposit application).
            'reapplied',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
                    'id',COALESCE(credit_use.id,deposit_use.id),
                    'source_kind',CASE WHEN credit_use.id IS NOT NULL THEN 'CREDIT' ELSE 'DEPOSIT' END,
                    'customer_credit_id',credit_use.customer_credit_id,
                    'deposit_id',deposit_use.deposit_id,
                    'application_stage',deposit_use.application_stage,
                    'invoice_id',COALESCE(credit_use.invoice_id,deposit_use.invoice_id),
                    'invoice_line_id',COALESCE(detail.invoice_line_id,deposit_use.invoice_line_id),
                    'late_payment_charge_id',COALESCE(credit_use.late_payment_charge_id,
                        deposit_use.late_payment_charge_id),
                    'amount_usd_cents',COALESCE(credit_use.amount_usd_cents,deposit_use.amount_usd_cents),
                    'occurred_at',COALESCE(credit_use.occurred_at,deposit_use.occurred_at))
                    ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                LEFT JOIN app.customer_credit_applications credit_use
                    ON credit_use.id=effect.customer_credit_application_id
                LEFT JOIN app.customer_credit_application_details detail
                    ON detail.customer_credit_application_id=credit_use.id
                LEFT JOIN app.deposit_applications deposit_use
                    ON deposit_use.id=effect.deposit_application_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)
                  AND (effect.customer_credit_application_id IS NOT NULL
                      OR effect.deposit_application_id IS NOT NULL)),
            'recoveries',(SELECT COALESCE(jsonb_agg(app.refund_recovery_json(recovery.id)""",
    ),
)

PATCHES = (
    (SOURCE, SOURCE_REPLACEMENTS),
    (ASSERT, ASSERT_REPLACEMENTS),
    (RECORD, RECORD_REPLACEMENTS),
    (CONFIRM, CONFIRM_REPLACEMENTS),
    (RESULT, RESULT_REPLACEMENTS),
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
            raise RuntimeError(f"Settlement return reversal reapply contract changed: {signature}")
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
    raise RuntimeError("Settlement return reversal reapply migration is forward-only")
