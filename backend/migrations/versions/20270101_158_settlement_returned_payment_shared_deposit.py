# ruff: noqa: E501
"""A returned-Payment correction gives back only a shared Deposit's shortfall (V1-056 sub-slice 10e-2b-4e-2a).

BR-SETTLE-013, BR-SETTLE-016, BR-REFUND-015, DL-032, DL-053; DB-SETTLE-005, DB-DEP-007,
DB-REFUND-002, DB-PAY-009; owner answer (a) to Q-2026-10-18-127 and owner answers (a) to
Q-2026-10-18-134 points 1 and 2 (newest first): after closure, when one of two or more Payments
that funded a Deposit bounces, the RETURNED_PAYMENT correction gives back only the Deposit's
shortfall (the returned Payment's active receipt less what the Deposit holds, never below 0) from
the Deposit's uses that are still in force, newest first: a Refund that is not fully returned by
the existing recovery charge to its recipient, a Deposit application by its reversal (the debt
comes back on the obligation's Customer, BR-SETTLE-016) and a forfeiture by its reversal (the
Property keeps less; nobody is charged); the kept part of the use given back in part is written
again, linked to the correction. The Deposit then ends holding only the other Payments' money. When
the unreturned Refunds went to two people the newest Refund's recipient pays first, before and
after closure. The receipt correction of a shared Deposit and the end of option (d) are sub-slice
10e-2b-4e-2b.

- Newest first is by time (a Refund's processed_at, an application's or a forfeiture's
  occurred_at), then a Refund before an application before a forfeiture at the same moment (DL-032
  writes applications before Refunds), then the later application order, then id.
- An application's kept part is a new Deposit application of the same Deposit, stage and target,
  numbered after the Settlement's last application; a forfeiture's kept part is a new forfeiture
  under the same ground. The closed records stay as they are.
- A kept application part beside a forfeiture of that Deposit that stays active is refused (a kept
  Deposit is never applied; a known limit).

New internal functions (no grant): app.settlement_returned_payment_shared,
app.write_settlement_shared_deposit_undo, app.settlement_shared_deposit_kept_application_allowed.
Exact-text patches (each replacement checked to match once): app.settlement_returned_payment_source,
app.assert_settlement_returned_payment_allowed, app.post_settlement_returned_payment,
app.settlement_returned_payment_result, app.assert_payment_return_recoveries_allowed,
app.write_payment_return_recoveries, app.payment_return_shortfall_recovery_amount,
app.payment_return_shared_receipt_reversal_allowed, app.validate_deposit_receipt_reversal,
app.validate_deposit_application, app.write_correction_deposit_forfeiture and
app.payment_return_shared_deposit_recoveries. No table, column, trigger, constraint or grant
changes.
"""

from alembic import op
from sqlalchemy import text

revision = "20270101_158"
down_revision = "20261231_157"
branch_labels = None
depends_on = None

SQL = r"""
    -- The shared Deposits of a returned-Payment correction (each Deposit the Payment funded that
    -- also holds another Payment's active receipt) and what each gives back: its shortfall (the
    -- Payment's active receipt less what the Deposit holds, never below 0) from its uses still in
    -- force, newest first, each at most its amount (owner answers (a) to Q-2026-10-18-127 and
    -- Q-2026-10-18-134). The result overrides three keys of the return source: the recoveries
    -- (each shared Deposit's Refund entry replaced by its share, a share of 0 left out), the
    -- deposits (with the shared flag and the shortfall) and the plan (shared_deposits). A shared
    -- Deposit with a Reservation outcome Refund is not plain and keeps its entries, so its
    -- refusals stay.
    CREATE FUNCTION app.settlement_returned_payment_shared(p_property uuid, p_payment uuid, p_source jsonb)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
        WITH listed AS (
            SELECT recovery.value AS entry,recovery.position
            FROM jsonb_array_elements(COALESCE(p_source->'recoveries','[]'::jsonb))
                WITH ORDINALITY recovery(value,position)
        ), shared AS (
            SELECT returned.deposit_id,returned.receipt_amount,
                app.deposit_held_value_at(returned.deposit_id,'infinity') AS held,
                GREATEST(returned.receipt_amount
                    -app.deposit_held_value_at(returned.deposit_id,'infinity'),0) AS shortfall,
                NOT EXISTS(SELECT 1 FROM listed
                    WHERE listed.entry->>'source_kind'='DEPOSIT'
                      AND listed.entry->>'source_id'=returned.deposit_id::text
                      AND COALESCE((listed.entry->>'reservation_outcome')::boolean,false)) AS plain
            FROM (SELECT receipt.deposit_id,sum(receipt.amount_usd_cents)::bigint AS receipt_amount
                FROM app.deposit_receipts receipt
                JOIN app.payments payment ON payment.id=receipt.payment_id
                    AND payment.property_id=p_property
                WHERE receipt.payment_id=p_payment
                  AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                      WHERE reversal.deposit_receipt_id=receipt.id)
                  AND EXISTS(SELECT 1 FROM app.deposit_receipts other
                      WHERE other.deposit_id=receipt.deposit_id AND other.payment_id<>p_payment
                        AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                            WHERE reversal.deposit_receipt_id=other.id))
                GROUP BY receipt.deposit_id) returned
        ), uses AS (
            -- A Refund that is not fully returned, at its net (the listed recovery).
            SELECT shared.deposit_id,'REFUND'::text AS kind,1 AS kind_rank,refund.id,
                refund.processed_at AS at,0 AS application_order,
                (listed.entry->>'amount_usd_cents')::bigint AS amount,NULL::jsonb AS detail
            FROM shared
            JOIN listed ON listed.entry->>'source_kind'='DEPOSIT'
                AND listed.entry->>'source_id'=shared.deposit_id::text
            JOIN app.refunds refund ON refund.id=(listed.entry->>'refund_id')::uuid
            WHERE shared.plain
            UNION ALL
            SELECT application.deposit_id,'APPLICATION',2,application.id,application.occurred_at,
                application.application_order,application.amount_usd_cents,
                jsonb_build_object('final_settlement_id',application.final_settlement_id,
                    'application_stage',application.application_stage,
                    'target_kind',application.target_kind,'invoice_id',application.invoice_id,
                    'invoice_line_id',application.invoice_line_id,
                    'late_payment_charge_id',application.late_payment_charge_id,
                    'application_order',application.application_order)
            FROM app.deposit_applications application
            JOIN shared ON shared.deposit_id=application.deposit_id
            WHERE shared.plain AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                WHERE reversal.deposit_application_id=application.id)
            UNION ALL
            SELECT disposition.deposit_id,'FORFEITURE',3,disposition.id,disposition.occurred_at,0,
                disposition.amount_usd_cents,NULL
            FROM app.deposit_dispositions disposition
            JOIN shared ON shared.deposit_id=disposition.deposit_id
            WHERE shared.plain AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal
                WHERE reversal.deposit_disposition_id=disposition.id)
        ), ordered AS (
            SELECT uses.*,row_number() OVER newest AS position,
                LEAST(uses.amount,GREATEST(shared.shortfall-COALESCE((sum(uses.amount) OVER (newest
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING))::bigint,0),0)) AS undo
            FROM uses JOIN shared ON shared.deposit_id=uses.deposit_id
            WINDOW newest AS (PARTITION BY uses.deposit_id
                ORDER BY uses.at DESC,uses.kind_rank,uses.application_order DESC,uses.id DESC)
        )
        SELECT jsonb_build_object(
            'recoveries',COALESCE((SELECT jsonb_agg(CASE WHEN ordered.id IS NULL THEN listed.entry
                    ELSE listed.entry||jsonb_build_object('amount_usd_cents',ordered.undo,
                        'net_usd_cents',ordered.amount,'shortfall_share',true) END
                    ORDER BY listed.position)
                FROM listed
                LEFT JOIN ordered ON ordered.kind='REFUND'
                    AND listed.entry->>'source_kind'='DEPOSIT'
                    AND ordered.deposit_id::text=listed.entry->>'source_id'
                    AND ordered.id::text=listed.entry->>'refund_id'
                WHERE ordered.id IS NULL OR ordered.undo>0),'[]'::jsonb),
            'deposits',COALESCE((SELECT jsonb_agg(deposit.value||jsonb_build_object(
                    'shared',shared.deposit_id IS NOT NULL,
                    'shortfall_usd_cents',COALESCE(shared.shortfall,0))
                    ORDER BY deposit.position)
                FROM jsonb_array_elements(COALESCE(p_source->'deposits','[]'::jsonb))
                    WITH ORDINALITY deposit(value,position)
                LEFT JOIN shared ON shared.deposit_id::text=deposit.value->>'id'),'[]'::jsonb),
            'shared_deposits',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'deposit_id',shared.deposit_id,'receipt_usd_cents',shared.receipt_amount,
                    'held_usd_cents',shared.held,'shortfall_usd_cents',shared.shortfall,
                    'plain',shared.plain,
                    'uses',COALESCE((SELECT jsonb_agg(COALESCE(ordered.detail,'{}'::jsonb)
                            ||jsonb_build_object('kind',ordered.kind,'id',ordered.id,'at',ordered.at,
                                'amount_usd_cents',ordered.amount,'undo_usd_cents',ordered.undo,
                                'kept_usd_cents',ordered.amount-ordered.undo)
                            ORDER BY ordered.position)
                        FROM ordered WHERE ordered.deposit_id=shared.deposit_id AND ordered.undo>0),
                        '[]'::jsonb))
                    ORDER BY shared.deposit_id)
                FROM shared),'[]'::jsonb))
    $$;

    -- The applications and forfeitures a shared Deposit's plan gives back, in the returned-Payment
    -- correction's confirm, each linked before it is written: each listed application reversed,
    -- newest first (the shared writer's timing); each application's kept part written again as a
    -- new Deposit application of the same Deposit, stage and target (the DL-032 stage order,
    -- numbered after the Settlement's last application); each forfeiture's kept part forfeited
    -- again. The listed forfeitures were reversed before, by the correction's forfeiture loop.
    CREATE FUNCTION app.write_settlement_shared_deposit_undo(p_property uuid, p_approver uuid,
        p_correction uuid, p_settlement uuid, p_reason text, p_shared jsonb, p_at timestamptz)
    RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
    DECLARE v_at timestamptz; v_deposit uuid; v_use jsonb; v_new uuid; v_order integer;
    BEGIN
        v_at:=p_at;
        FOR v_deposit,v_use IN SELECT (shared.value->>'deposit_id')::uuid,used.value
            FROM jsonb_array_elements(COALESCE(p_shared,'[]'::jsonb)) WITH ORDINALITY shared(value,position)
            CROSS JOIN LATERAL jsonb_array_elements(shared.value->'uses') WITH ORDINALITY used(value,position)
            WHERE used.value->>'kind'='APPLICATION'
            ORDER BY shared.position,used.position
        LOOP
            v_at:=GREATEST(v_at+interval '1 microsecond',CASE v_use->>'target_kind'
                    WHEN 'INVOICE_LINE' THEN app.credit_excess_instant((v_use->>'invoice_id')::uuid,NULL)
                    ELSE app.settlement_late_charge_instant((v_use->>'late_payment_charge_id')::uuid,NULL) END,
                COALESCE(app.deposit_balance_latest_at(v_deposit),'-infinity')+interval '1 microsecond');
            v_new:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(p_correction,'deposit_application_reversal_id',v_new);
            INSERT INTO app.deposit_application_reversals(id,deposit_application_id,reason,occurred_at,
                actor_id,authorization_reference)
            VALUES (v_new,(v_use->>'id')::uuid,p_reason,v_at,p_approver,'financial.approve');
        END LOOP;
        FOR v_deposit,v_use IN SELECT (shared.value->>'deposit_id')::uuid,used.value
            FROM jsonb_array_elements(COALESCE(p_shared,'[]'::jsonb)) WITH ORDINALITY shared(value,position)
            CROSS JOIN LATERAL jsonb_array_elements(shared.value->'uses') WITH ORDINALITY used(value,position)
            WHERE used.value->>'kind'='APPLICATION' AND (used.value->>'kept_usd_cents')::bigint>0
            ORDER BY CASE used.value->>'application_stage' WHEN 'PET_RELATED_FIRST' THEN 1
                    WHEN 'SECURITY_EXPLICIT' THEN 2 ELSE 3 END,
                (used.value->>'application_order')::integer,shared.position
        LOOP
            SELECT COALESCE(max(application.application_order),0)+1 INTO v_order
            FROM app.deposit_applications application WHERE application.final_settlement_id=p_settlement;
            v_new:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(p_correction,'deposit_application_id',v_new);
            v_at:=GREATEST(v_at,(app.post_deposit_application(p_property,p_approver,p_settlement,v_new,
                v_deposit,v_use->>'application_stage',v_use->>'target_kind',
                COALESCE(v_use->>'invoice_line_id',v_use->>'late_payment_charge_id')::uuid,
                (v_use->>'kept_usd_cents')::bigint,v_order,p_reason)->>'occurred_at')::timestamptz);
        END LOOP;
        FOR v_deposit,v_use IN SELECT (shared.value->>'deposit_id')::uuid,used.value
            FROM jsonb_array_elements(COALESCE(p_shared,'[]'::jsonb)) WITH ORDINALITY shared(value,position)
            CROSS JOIN LATERAL jsonb_array_elements(shared.value->'uses') WITH ORDINALITY used(value,position)
            WHERE used.value->>'kind'='FORFEITURE' AND (used.value->>'kept_usd_cents')::bigint>0
            ORDER BY shared.position,used.position
        LOOP
            v_at:=app.write_correction_deposit_forfeiture(p_property,p_correction,p_approver,v_deposit,
                (v_use->>'kept_usd_cents')::bigint,p_reason,v_at);
        END LOOP;
        RETURN v_at;
    END $$;

    -- A post-settlement correction's own Deposit application that is the kept part of an
    -- application the same RETURNED_PAYMENT correction gave back in part: its draft's stored
    -- source lists it (the same Deposit, stage, target and kept amount), the listed application
    -- is reversed by a reversal linked to this correction, and the correction writes it once.
    -- Never NULL.
    CREATE FUNCTION app.settlement_shared_deposit_kept_application_allowed(p_correction uuid,
        p_application app.deposit_applications)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT EXISTS(SELECT 1
            FROM app.settlement_corrections correction
            JOIN app.financial_drafts draft ON draft.id=correction.correlation_id
            CROSS JOIN LATERAL jsonb_array_elements(CASE
                WHEN jsonb_typeof(draft.payload->'source'->'shared_deposits')='array'
                THEN draft.payload->'source'->'shared_deposits' ELSE '[]'::jsonb END) shared
            CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(shared->'uses')='array'
                THEN shared->'uses' ELSE '[]'::jsonb END) used
            WHERE correction.id=p_correction
              AND correction.final_settlement_id=(p_application).final_settlement_id
              AND draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='RETURNED_PAYMENT'
              AND shared->>'deposit_id'=(p_application).deposit_id::text
              AND used->>'kind'='APPLICATION'
              AND used->>'application_stage'=(p_application).application_stage
              AND used->>'target_kind'=(p_application).target_kind
              AND COALESCE(used->>'invoice_line_id',used->>'late_payment_charge_id')
                  =COALESCE((p_application).invoice_line_id,(p_application).late_payment_charge_id)::text
              AND (used->>'kept_usd_cents')::bigint=(p_application).amount_usd_cents
              AND EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                  JOIN app.settlement_correction_effects effect
                      ON effect.deposit_application_reversal_id=reversal.id
                  WHERE reversal.deposit_application_id=(used->>'id')::uuid
                    AND effect.settlement_correction_id=correction.id)
              AND NOT EXISTS(SELECT 1 FROM app.deposit_applications written
                  JOIN app.settlement_correction_effects effect ON effect.deposit_application_id=written.id
                  WHERE effect.settlement_correction_id=correction.id
                    AND written.id<>(p_application).id
                    AND written.deposit_id=(p_application).deposit_id
                    AND written.application_stage=(p_application).application_stage
                    AND written.target_kind=(p_application).target_kind
                    AND COALESCE(written.invoice_line_id,written.late_payment_charge_id)
                        =COALESCE((p_application).invoice_line_id,(p_application).late_payment_charge_id)
                    AND written.amount_usd_cents=(p_application).amount_usd_cents))),false)
    $$;
"""

INTERNAL = (
    "app.settlement_returned_payment_shared(uuid,uuid,jsonb)",
    "app.write_settlement_shared_deposit_undo(uuid,uuid,uuid,uuid,text,jsonb,timestamp with time zone)",
    "app.settlement_shared_deposit_kept_application_allowed(uuid,app.deposit_applications)",
)

SOURCE = "app.settlement_returned_payment_source(uuid,uuid,uuid,uuid)"
SOURCE_REPLACEMENTS = (
    (
        "        SELECT app.payment_return_source(p_property,p_payment,p_draft)||jsonb_build_object(\n",
        "        SELECT source||jsonb_build_object(\n",
    ),
    (
        "                WHERE payment.id=p_payment AND payment.property_id=p_property),false))\n",
        "                WHERE payment.id=p_payment AND payment.property_id=p_property),false))\n"
        "            -- Sub-slice 10e-2b-4e-2a (owner answers (a) to Q-2026-10-18-134): a shared\n"
        "            -- Deposit's plan, its recoveries and its deposits' shared flags.\n"
        "            ||app.settlement_returned_payment_shared(p_property,p_payment,source)\n"
        "        FROM app.payment_return_source(p_property,p_payment,p_draft) source\n",
    ),
)

ALLOWED_CHECK = "app.assert_settlement_returned_payment_allowed(uuid,uuid,jsonb)"
ALLOWED_CHECK_REPLACEMENTS = (
    (
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'deposits') deposit\n"
        "            WHERE (deposit->>'held_usd_cents')::bigint\n",
        "        -- Sub-slice 10e-2b-4e-2a: a shared Deposit is checked below.\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'deposits') deposit\n"
        "            WHERE NOT COALESCE((deposit->>'shared')::boolean,false)\n"
        "              AND (deposit->>'held_usd_cents')::bigint\n",
    ),
    (
        "        THEN RAISE EXCEPTION 'A Deposit this Payment funded would still hold money after the return'\n"
        "            USING ERRCODE='55000'; END IF;\n",
        "        THEN RAISE EXCEPTION 'A Deposit this Payment funded would still hold money after the return'\n"
        "            USING ERRCODE='55000'; END IF;\n"
        "        -- Sub-slice 10e-2b-4e-2a (owner answers (a) to Q-2026-10-18-127 and Q-2026-10-18-134):\n"
        "        -- a shared Deposit gives back exactly its shortfall, newest use first, so it then\n"
        "        -- holds only the other Payments' money.\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'deposits') deposit\n"
        "            WHERE COALESCE((deposit->>'shared')::boolean,false)\n"
        "              AND COALESCE((deposit->>'shortfall_usd_cents')::bigint,-1)\n"
        "                IS DISTINCT FROM COALESCE((SELECT sum((used->>'undo_usd_cents')::bigint)\n"
        "                    FROM jsonb_array_elements(COALESCE(p_source->'shared_deposits','[]'::jsonb)) shared\n"
        "                    CROSS JOIN LATERAL jsonb_array_elements(shared->'uses') used\n"
        "                    WHERE shared->>'deposit_id'=deposit->>'id'),0))\n"
        "        THEN RAISE EXCEPTION 'A Deposit this Payment funded would still hold money after the return'\n"
        "            USING ERRCODE='55000'; END IF;\n"
        "        -- A kept Deposit is never applied (app.validate_deposit_application), so an\n"
        "        -- application's kept part is not written beside a forfeiture that stays active.\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_source->'shared_deposits','[]'::jsonb)) shared\n"
        "            CROSS JOIN LATERAL jsonb_array_elements(shared->'uses') used\n"
        "            WHERE used->>'kind'='APPLICATION' AND (used->>'kept_usd_cents')::bigint>0\n"
        "              AND EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'forfeitures') forfeiture\n"
        "                  WHERE forfeiture->>'deposit_id'=shared->>'deposit_id'\n"
        "                    AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(shared->'uses') undone\n"
        "                        WHERE undone->>'kind'='FORFEITURE' AND undone->>'id'=forfeiture->>'id'\n"
        "                          AND (undone->>'kept_usd_cents')::bigint=0)))\n"
        "        THEN RAISE EXCEPTION 'A Deposit this Payment funded also holds another Payment''s money and keeps a forfeiture beside a Deposit application; this correction cannot return the Payment'\n"
        "            USING ERRCODE='55000'; END IF;\n"
        "        -- Review round 1 (security B1; Q-2026-10-18-135): no Refund or application of a\n"
        "        -- Deposit with the Customer's pay-back money is charged back or reversed while a\n"
        "        -- forfeiture of that Deposit stays active (it could keep the pay-back money).\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_source->'shared_deposits','[]'::jsonb)) shared\n"
        "            WHERE EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'forfeitures') forfeiture\n"
        "                  WHERE forfeiture->>'deposit_id'=shared->>'deposit_id'\n"
        "                    AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(shared->'uses') undone\n"
        "                        WHERE undone->>'kind'='FORFEITURE' AND undone->>'id'=forfeiture->>'id'\n"
        "                          AND (undone->>'kept_usd_cents')::bigint=0))\n"
        "              AND ((EXISTS(SELECT 1 FROM jsonb_array_elements(shared->'uses') used\n"
        "                        WHERE used->>'kind' IN ('REFUND','APPLICATION'))\n"
        "                    AND app.lease_deposit_payback_count_as((shared->>'deposit_id')::uuid,NULL,0,true)>0)\n"
        "                -- Review round 2 (security note 1): also the end state the check after the\n"
        "                -- writes reads (a plan that gives back only from the forfeiture).\n"
        "                OR app.lease_deposit_payback_count_as((shared->>'deposit_id')::uuid,NULL,0,false)\n"
        "                    >GREATEST((shared->>'held_usd_cents')::bigint\n"
        "                        -(shared->>'receipt_usd_cents')::bigint,0)))\n"
        "        THEN RAISE EXCEPTION 'A Deposit this Payment funded holds the Customer''s pay-back money beside a forfeiture; this correction cannot return the Payment'\n"
        "            USING ERRCODE='55000'; END IF;\n",
    ),
)

POST = "app.post_settlement_returned_payment(uuid,uuid,uuid,uuid,uuid,text)"
POST_REPLACEMENTS = (
    (
        "              AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal\n"
        "                  WHERE reversal.deposit_disposition_id=disposition.id)\n"
        "            ORDER BY disposition.occurred_at DESC,disposition.id DESC\n",
        "              AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal\n"
        "                  WHERE reversal.deposit_disposition_id=disposition.id)\n"
        "              -- Sub-slice 10e-2b-4e-2a: a shared Deposit's forfeiture only when its plan\n"
        "              -- gives it back.\n"
        "              AND (NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v_source->'shared_deposits') shared\n"
        "                      WHERE shared->>'deposit_id'=disposition.deposit_id::text)\n"
        "                  OR EXISTS(SELECT 1 FROM jsonb_array_elements(v_source->'shared_deposits') shared\n"
        "                      CROSS JOIN LATERAL jsonb_array_elements(shared->'uses') used\n"
        "                      WHERE used->>'kind'='FORFEITURE' AND used->>'id'=disposition.id::text))\n"
        "            ORDER BY disposition.occurred_at DESC,disposition.id DESC\n",
    ),
    (
        "                  AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal\n"
        "                      WHERE reversal.deposit_receipt_id=receipt.id)),v_at);\n",
        "                  AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal\n"
        "                      WHERE reversal.deposit_receipt_id=receipt.id)\n"
        "                  -- Sub-slice 10e-2b-4e-2a: a shared Deposit gives back only its plan.\n"
        "                  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v_source->'shared_deposits') shared\n"
        "                      WHERE shared->>'deposit_id'=receipt.deposit_id::text)),v_at);\n"
        "        v_at:=app.write_settlement_shared_deposit_undo(p_property,p_approver,p_correction,\n"
        "            v_settlement,v_reason,v_source->'shared_deposits',v_at);\n",
    ),
    (
        "        -- The Payment last (DB-PAY-006: every use reversed first; dated after every one).\n",
        "        -- Review round 1 (security B1): a shared Deposit whose forfeiture stays active still\n"
        "        -- holds at least the Customer's pay-back money after the return.\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(v_source->'shared_deposits','[]'::jsonb)) shared\n"
        "            WHERE EXISTS(SELECT 1 FROM app.deposit_dispositions disposition\n"
        "                    WHERE disposition.deposit_id=(shared->>'deposit_id')::uuid\n"
        "                      AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal\n"
        "                          WHERE reversal.deposit_disposition_id=disposition.id))\n"
        "              AND app.lease_deposit_payback_count_as((shared->>'deposit_id')::uuid,NULL,0,false)\n"
        "                  >app.deposit_held_value_at((shared->>'deposit_id')::uuid,'infinity'))\n"
        "        THEN RAISE EXCEPTION 'A Deposit this Payment funded holds the Customer''s pay-back money beside a forfeiture; this correction cannot return the Payment'\n"
        "            USING ERRCODE='55000'; END IF;\n"
        "        -- The Payment last (DB-PAY-006: every use reversed first; dated after every one).\n",
    ),
)

RESULT = "app.settlement_returned_payment_result(uuid)"
RESULT_REPLACEMENTS = (
    (
        "            'payment_reversal_id',(SELECT payment_reversal_id FROM effects\n",
        "            -- Sub-slice 10e-2b-4e-2a: the kept parts a shared Deposit's plan writes again.\n"
        "            'deposit_application_ids',COALESCE((SELECT jsonb_agg(deposit_application_id\n"
        "                    ORDER BY effect_sequence) FROM effects\n"
        "                WHERE deposit_application_id IS NOT NULL),'[]'::jsonb),\n"
        "            'forfeiture_ids',COALESCE((SELECT jsonb_agg(deposit_disposition_id\n"
        "                    ORDER BY effect_sequence) FROM effects\n"
        "                WHERE deposit_disposition_id IS NOT NULL),'[]'::jsonb),\n"
        "            'payment_reversal_id',(SELECT payment_reversal_id FROM effects\n",
    ),
)

RECOVERIES_ALLOWED = "app.assert_payment_return_recoveries_allowed(jsonb,uuid)"
RECOVERIES_ALLOWED_REPLACEMENTS = (
    (
        "              -- Sub-slice 10e-2b-4e-1 (owner answer (a) to Q-2026-10-18-127): the\n"
        "              -- PAYMENT_RETURN path charges back a shared Deposit's shortfall share.\n"
        "              AND NOT (p_settlement IS NULL\n"
        "                  AND COALESCE((recovery->>'shortfall_share')::boolean,false)))\n",
        "              -- Sub-slices 10e-2b-4e-1 and 10e-2b-4e-2a (owner answers (a) to\n"
        "              -- Q-2026-10-18-127 and Q-2026-10-18-134): the PAYMENT_RETURN draft and the\n"
        "              -- RETURNED_PAYMENT correction charge back a shared Deposit's share; only their\n"
        "              -- two planners set the flag (review round 2, security note 3).\n"
        "              AND NOT COALESCE((recovery->>'shortfall_share')::boolean,false))\n",
    ),
)

RECOVERY_WRITER = "app.write_payment_return_recoveries(uuid,uuid,uuid,uuid,uuid,jsonb,text,text,timestamp with time zone,jsonb)"
RECOVERY_WRITER_REPLACEMENTS = (
    (
        "                    -- Sub-slice 10e-2b-4e-1 (owner answer (a) to Q-2026-10-18-127): with no\n"
        "                    -- correction, a shared Deposit's entry recovers its share of the shortfall.\n"
        "                    OR (p_correction IS NULL\n"
        "                        AND COALESCE((v_recovery->>'shortfall_share')::boolean,false))\n",
        "                    -- Sub-slices 10e-2b-4e-1 and 10e-2b-4e-2a: a shared Deposit's entry\n"
        "                    -- recovers its share (a PAYMENT_RETURN or a RETURNED_PAYMENT correction).\n"
        "                    OR COALESCE((v_recovery->>'shortfall_share')::boolean,false)\n",
    ),
)

SHORTFALL_AMOUNT = "app.payment_return_shortfall_recovery_amount(app.refund_corrections)"
SHORTFALL_AMOUNT_REPLACEMENTS = (
    (
        "            WHERE payment_return.settlement_correction_id IS NULL\n"
        "              AND decision.result->>'transaction_id'=pg_current_xact_id()::text\n",
        "            -- Sub-slice 10e-2b-4e-2a (review round 1, security S1): the return of the\n"
        "            -- correction that links the recovery, or a PAYMENT_RETURN with no correction.\n"
        "            WHERE payment_return.settlement_correction_id IS NOT DISTINCT FROM (\n"
        "                    SELECT effect.settlement_correction_id FROM app.settlement_correction_effects effect\n"
        "                    WHERE effect.refund_correction_id=(p_correction).id)\n"
        "              AND decision.result->>'transaction_id'=pg_current_xact_id()::text\n",
    ),
)

SHARED_REVERSAL = "app.payment_return_shared_receipt_reversal_allowed(app.deposit_receipt_reversals)"
SHARED_REVERSAL_REPLACEMENTS = (
    (
        "                      AND payment_return.settlement_correction_id IS NULL\n",
        "                      -- Sub-slice 10e-2b-4e-2a (review round 1, security S1): the return of\n"
        "                      -- the correction that links the reversal, whose plan lists this\n"
        "                      -- Deposit, or a PAYMENT_RETURN with no correction.\n"
        "                      AND payment_return.settlement_correction_id IS NOT DISTINCT FROM (\n"
        "                          SELECT effect.settlement_correction_id\n"
        "                          FROM app.settlement_correction_effects effect\n"
        "                          WHERE effect.deposit_receipt_reversal_id=(p_reversal).id)\n"
        "                      AND (payment_return.settlement_correction_id IS NULL OR EXISTS(SELECT 1\n"
        "                          FROM app.financial_drafts draft\n"
        "                          CROSS JOIN LATERAL jsonb_array_elements(CASE\n"
        "                              WHEN jsonb_typeof(draft.payload->'source'->'shared_deposits')='array'\n"
        "                              THEN draft.payload->'source'->'shared_deposits' ELSE '[]'::jsonb END) shared\n"
        "                          WHERE draft.id=payment_return.draft_id\n"
        "                            AND shared->>'deposit_id'=receipt.deposit_id::text))\n",
    ),
)

REVERSAL_CHECK = "app.validate_deposit_receipt_reversal()"
REVERSAL_CHECK_REPLACEMENTS = (
    (
        "            IF EXISTS (\n"
        "                SELECT 1 FROM app.deposit_dispositions AS disposition\n",
        "            -- Sub-slice 10e-2b-4e-2a (owner answers (a) to Q-2026-10-18-134): the\n"
        "            -- RETURNED_PAYMENT correction of this transaction (linked above) reverses its\n"
        "            -- Payment's receipt of a shared Deposit whose kept forfeiture or application stays.\n"
        "            IF (EXISTS (\n"
        "                SELECT 1 FROM app.deposit_dispositions AS disposition\n",
    ),
    (
        "                    WHERE reversal.deposit_disposition_id=disposition.id)\n"
        "            ) OR (app.deposit_has_unresolved_refund(v_deposit_id)\n",
        "                    WHERE reversal.deposit_disposition_id=disposition.id)\n"
        "            ) AND NOT (v_settlement IS NOT NULL\n"
        "                AND app.payment_return_shared_receipt_reversal_allowed(NEW)))\n"
        "              OR (app.deposit_has_unresolved_refund(v_deposit_id)\n",
    ),
    (
        "              OR app.deposit_has_active_application(v_deposit_id)\n",
        "              OR (app.deposit_has_active_application(v_deposit_id)\n"
        "                  AND NOT (v_settlement IS NOT NULL\n"
        "                      AND app.payment_return_shared_receipt_reversal_allowed(NEW)))\n",
    ),
)

APPLICATION_CHECK = "app.validate_deposit_application()"
APPLICATION_CHECK_REPLACEMENTS = (
    (
        "                IF NOT EXISTS(SELECT 1 FROM app.financial_drafts draft\n",
        "                -- Sub-slice 10e-2b-4e-2a: or the kept part of a shared Deposit's application.\n"
        "                IF NOT app.settlement_shared_deposit_kept_application_allowed(v_correction.id,NEW)\n"
        "                    AND NOT EXISTS(SELECT 1 FROM app.financial_drafts draft\n",
    ),
)

FORFEITURE_WRITER = "app.write_correction_deposit_forfeiture(uuid,uuid,uuid,uuid,bigint,text,timestamp with time zone)"
FORFEITURE_WRITER_REPLACEMENTS = (
    (
        "    DECLARE v_draft uuid; v_lease app.leases%ROWTYPE;",
        "    DECLARE v_draft uuid; v_variant text; v_lease app.leases%ROWTYPE;",
    ),
    (
        "        SELECT draft.id INTO v_draft FROM app.settlement_corrections correction\n",
        "        SELECT draft.id,draft.payload->>'variant' INTO v_draft,v_variant\n"
        "        FROM app.settlement_corrections correction\n",
    ),
    (
        "          AND draft.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION'\n"
        "          AND EXISTS(SELECT 1 FROM jsonb_array_elements(draft.payload->'deposit_receipt_forfeitures') item\n"
        "              WHERE item->>'deposit_id'=p_deposit::text\n"
        "                AND (item->>'amount_usd_cents')::bigint=p_amount AND item->>'reason'=p_reason);\n",
        "          AND ((draft.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION'\n"
        "              AND EXISTS(SELECT 1 FROM jsonb_array_elements(draft.payload->'deposit_receipt_forfeitures') item\n"
        "                  WHERE item->>'deposit_id'=p_deposit::text\n"
        "                    AND (item->>'amount_usd_cents')::bigint=p_amount AND item->>'reason'=p_reason))\n"
        "            -- Sub-slice 10e-2b-4e-2a: the kept part of a shared Deposit's forfeiture that a\n"
        "            -- RETURNED_PAYMENT correction gives back in part, with the draft's reason.\n"
        "            OR (draft.payload->>'variant'='RETURNED_PAYMENT' AND draft.reason=p_reason\n"
        "              AND EXISTS(SELECT 1 FROM jsonb_array_elements(CASE\n"
        "                      WHEN jsonb_typeof(draft.payload->'source'->'shared_deposits')='array'\n"
        "                      THEN draft.payload->'source'->'shared_deposits' ELSE '[]'::jsonb END) shared\n"
        "                  CROSS JOIN LATERAL jsonb_array_elements(shared->'uses') used\n"
        "                  WHERE shared->>'deposit_id'=p_deposit::text AND used->>'kind'='FORFEITURE'\n"
        "                    AND (used->>'kept_usd_cents')::bigint=p_amount\n"
        "                    -- Review round 1 (security S2): the listed forfeiture was reversed by\n"
        "                    -- this correction.\n"
        "                    AND EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal\n"
        "                        JOIN app.settlement_correction_effects effect\n"
        "                            ON effect.deposit_disposition_reversal_id=reversal.id\n"
        "                        WHERE reversal.deposit_disposition_id=(used->>'id')::uuid\n"
        "                          AND effect.settlement_correction_id=p_correction))));\n",
    ),
    (
        "        IF v_rule IS NULL OR app.deposit_held_value_at(p_deposit,'infinity')\n"
        "                -app.lease_deposit_payback_value(p_deposit)<>p_amount\n",
        "        -- Sub-slice 10e-2b-4e-2a: a kept part is limited by the forfeiture table's checks.\n"
        "        IF v_rule IS NULL OR (v_variant='DEPOSIT_RECEIPT_CORRECTION'\n"
        "                AND app.deposit_held_value_at(p_deposit,'infinity')\n"
        "                -app.lease_deposit_payback_value(p_deposit)<>p_amount)\n",
    ),
)

SHARED_RECOVERIES = "app.payment_return_shared_deposit_recoveries(uuid,uuid)"
SHARED_RECOVERIES_REPLACEMENTS = (
    (
        "                (SELECT count(DISTINCT listed.entry->>'recipient_customer_id') FROM listed\n"
        "                    WHERE listed.entry->>'source_kind'='DEPOSIT'\n"
        "                      AND listed.entry->>'source_id'=returned.deposit_id::text) AS recipients,\n",
        "",
    ),
    (
        "                    WHEN shared.shortfall>0 AND shared.recipients>1 THEN NULL\n",
        "",
    ),
)

PATCHES = (
    (SOURCE, SOURCE_REPLACEMENTS),
    (ALLOWED_CHECK, ALLOWED_CHECK_REPLACEMENTS),
    (POST, POST_REPLACEMENTS),
    (RESULT, RESULT_REPLACEMENTS),
    (RECOVERIES_ALLOWED, RECOVERIES_ALLOWED_REPLACEMENTS),
    (RECOVERY_WRITER, RECOVERY_WRITER_REPLACEMENTS),
    (SHORTFALL_AMOUNT, SHORTFALL_AMOUNT_REPLACEMENTS),
    (SHARED_REVERSAL, SHARED_REVERSAL_REPLACEMENTS),
    (REVERSAL_CHECK, REVERSAL_CHECK_REPLACEMENTS),
    (APPLICATION_CHECK, APPLICATION_CHECK_REPLACEMENTS),
    (FORFEITURE_WRITER, FORFEITURE_WRITER_REPLACEMENTS),
    (SHARED_RECOVERIES, SHARED_RECOVERIES_REPLACEMENTS),
)


def upgrade() -> None:
    op.execute(SQL)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Returned-Payment shared Deposit migration is forward-only")


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
            raise RuntimeError(f"Returned-Payment shared Deposit contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)
