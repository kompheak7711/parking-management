# ruff: noqa: E501
"""The right receipt inside a Deposit receipt correction (V1-056 sub-slice 10e-2b-1).

BR-SETTLE-013, BR-SETTLE-008, BR-SETTLE-016, DL-032, BR-AUTH-010; DB-DEP-002, DB-SETTLE-005; owner
answer 2 to Q-2026-10-11-83, answer (a) to Q-2026-10-11-86, answers (a), (a), (a) to
Q-2026-10-12-87 and the instruction of 2026-10-12 with the answers to Q-2026-10-12-88:

- After the wrong receipt's reversal, a `DEPOSIT_RECEIPT_CORRECTION` may write the right receipt
  of the same Payment's freed value: into the right Deposit or for the right amount (one or two
  receipts, distinct Deposits of the Settlement's Lease, together at most the corrected receipt).
  Each is linked to the correction (DB-SETTLE-005 `deposit_receipt_id`) before it is written. The
  draft's DL-032 plan names the new money; the correction's shared DL-032 step applies it in the
  DL-032 order and refunds the rest. The money the receipts do not take stays unallocated with the
  Payment (BR-CREDIT-002).
- Rule 1: a Deposit holds at most one active receipt from each Payment; the key
  `UNIQUE (deposit_id, payment_id)` is replaced by that check, so a reversed receipt stays in the
  history and no longer blocks a new one. Rule 2: inside a correction of the Lease's closed Final
  Settlement that links it, a Security Deposit's first active receipt may differ from the accepted
  amount (never above the required amount, which does not change). Rule 3: the first Pet Deposit
  receipt writer, inside a correction only, refused while the Pet Deposit is kept.
- Refused until later sub-slices: a new receipt into a Deposit with a forfeiture ground
  (Q-2026-10-12-88, sub-slice 10e-2c), and a new receipt in a correction that also charges a
  recovered Refund on this Lease (its placeholder lines, sub-slice 10e-2b-2).

Relaxing changes only: the key becomes a check with the same error class; the receipt check, the
plan check, the correction lock function, the receipt correction's recorder, write helper and
result gain their 10e-2b parts by exact-text patches; the input accepts the optional receipts and
plan (both or neither; neither is sub-slice 10e-2 as built).
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from sqlalchemy import text

revision = "20261126_122"
down_revision = "20261125_121"
branch_labels = None
depends_on = None

TABLE_SQL = r"""
    -- Owner rule 1 of Q-2026-10-12-87: the receipt check below replaces this key.
    ALTER TABLE app.deposit_receipts DROP CONSTRAINT deposit_receipts_deposit_payment_unique;
"""

FUNCTION_SQL = r"""
    -- The correction's input: the receipt and the evidence reference, and optionally (both or
    -- neither) the right receipts and the DL-032 plan for their money.
    CREATE OR REPLACE FUNCTION app.settlement_deposit_receipt_correction_input(p_input jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_receipt text; v_receipts jsonb:='[]'::jsonb; v_item jsonb; v_deposit text;
    BEGIN
        IF p_input IS NULL OR jsonb_typeof(p_input) IS DISTINCT FROM 'object'
            -- The byte order, whatever the database collation.
            OR ((SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(p_input) key)
                    IS DISTINCT FROM ARRAY['deposit_receipt_id','evidence_reference']
                AND (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(p_input) key)
                    IS DISTINCT FROM ARRAY['deposit_receipt_id','evidence_reference','plan','receipts'])
            OR jsonb_typeof(p_input->'evidence_reference') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_input->>'evidence_reference',500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Deposit receipt correction input is invalid' USING ERRCODE='22023'; END IF;
        v_receipt:=app.final_settlement_plan_id(p_input->'deposit_receipt_id');
        IF v_receipt IS NULL THEN
            RAISE EXCEPTION 'Deposit receipt correction input is invalid' USING ERRCODE='22023'; END IF;
        IF NOT p_input ? 'receipts' THEN
            RETURN jsonb_build_object('deposit_receipt_id',v_receipt,
                'evidence_reference',p_input->>'evidence_reference');
        END IF;
        -- Sub-slice 10e-2b: one or two right receipts, each into a distinct Deposit, each above 0;
        -- the plan's shape is checked by the shared DL-032 plan check.
        IF jsonb_typeof(p_input->'receipts') IS DISTINCT FROM 'array'
            OR jsonb_array_length(p_input->'receipts') NOT BETWEEN 1 AND 2
            OR jsonb_typeof(p_input->'plan') IS DISTINCT FROM 'object'
        THEN RAISE EXCEPTION 'Deposit receipt correction input is invalid' USING ERRCODE='22023'; END IF;
        FOR v_item IN SELECT item.value FROM jsonb_array_elements(p_input->'receipts') WITH ORDINALITY item(value,position)
            ORDER BY item.position
        LOOP
            IF jsonb_typeof(v_item) IS DISTINCT FROM 'object'
                OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(v_item) key)
                    IS DISTINCT FROM ARRAY['amount_usd_cents','deposit_id']
                OR jsonb_typeof(v_item->'amount_usd_cents') IS DISTINCT FROM 'number'
                OR (v_item->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
                OR (v_item->>'amount_usd_cents')::numeric>9000000000000000
            THEN RAISE EXCEPTION 'Deposit receipt correction input is invalid' USING ERRCODE='22023'; END IF;
            v_deposit:=app.final_settlement_plan_id(v_item->'deposit_id');
            IF v_deposit IS NULL OR EXISTS(SELECT 1 FROM jsonb_array_elements(v_receipts) earlier
                WHERE earlier->>'deposit_id'=v_deposit)
            THEN RAISE EXCEPTION 'Deposit receipt correction input is invalid' USING ERRCODE='22023'; END IF;
            v_receipts:=v_receipts||jsonb_build_array(jsonb_build_object('deposit_id',v_deposit,
                'amount_usd_cents',(v_item->>'amount_usd_cents')::bigint));
        END LOOP;
        RETURN jsonb_build_object('deposit_receipt_id',v_receipt,
            'evidence_reference',p_input->>'evidence_reference','receipts',v_receipts,
            'plan',p_input->'plan');
    END $$;

    -- Sub-slice 10e-2b: what each right receipt's Deposit allows now, read for the recorder, the
    -- confirm and the write helper (the corrected receipt is counted as reversed).
    CREATE FUNCTION app.settlement_deposit_receipt_correction_targets(p_property uuid, p_source jsonb,
        p_receipts jsonb)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
        SELECT COALESCE(jsonb_agg(jsonb_build_object('deposit_id',item.value->>'deposit_id',
                'amount_usd_cents',(item.value->>'amount_usd_cents')::bigint,
                'found',deposit.id IS NOT NULL,'lease_id',deposit.lease_id,
                'deposit_type',deposit.deposit_type,
                'path',CASE WHEN deposit.id IS NOT NULL
                    THEN app.lease_deposit_settlement_path(p_property,deposit.id) END,
                'held_usd_cents',CASE WHEN deposit.id IS NOT NULL
                    THEN app.deposit_held_value_at(deposit.id,'infinity') END,
                -- The existing Payment source rule of a receipt (app.validate_payment_deposit_source).
                'payment_funds',deposit.id IS NOT NULL AND payment.id IS NOT NULL AND NOT (
                    (payment.payment_scope_kind='NORMAL_CUSTOMER'
                        AND deposit.customer_id<>payment.payer_customer_id)
                    OR (payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                        AND (payment.lease_id IS NULL OR payment.lease_id IS DISTINCT FROM deposit.lease_id))),
                -- Owner rule 1: another active receipt of the same Payment in this Deposit.
                'payment_receipt_active',EXISTS(SELECT 1 FROM app.deposit_receipts other
                    WHERE other.deposit_id=deposit.id AND other.payment_id=payment.id
                      AND other.id IS DISTINCT FROM (p_source->'receipt'->>'id')::uuid
                      AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                          WHERE reversal.deposit_receipt_id=other.id)),
                -- What the required amount still takes (it does not change, owner rule 2).
                'room_usd_cents',CASE WHEN deposit.id IS NOT NULL THEN
                    (app.deposit_snapshot(deposit.id)->>'required_usd_cents')::bigint
                    -COALESCE((SELECT sum(other.amount_usd_cents) FROM app.deposit_receipts other
                        WHERE other.deposit_id=deposit.id
                          AND other.id IS DISTINCT FROM (p_source->'receipt'->>'id')::uuid
                          AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                              WHERE reversal.deposit_receipt_id=other.id)),0) END)
                ORDER BY item.position),'[]'::jsonb)
        FROM jsonb_array_elements(COALESCE(p_receipts,'[]'::jsonb)) WITH ORDINALITY item(value,position)
        LEFT JOIN app.deposits deposit ON deposit.id=(item.value->>'deposit_id')::uuid
            AND app.deposit_property_id(deposit.id)=p_property
        LEFT JOIN app.payments payment ON payment.id=(p_source->'receipt'->>'payment_id')::uuid
    $$;

    -- Sub-slice 10e-2b: the refusals of the right receipts (recorder, confirm and the write
    -- helper), after the sub-slice 10e-2 refusals of the corrected receipt.
    CREATE FUNCTION app.assert_settlement_deposit_receipt_targets_allowed(p_lease uuid, p_source jsonb,
        p_targets jsonb)
    RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target
            WHERE NOT (target->>'found')::boolean)
        THEN RAISE EXCEPTION 'The Deposit of a new receipt was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target
            WHERE target->>'lease_id' IS DISTINCT FROM p_lease::text)
        THEN RAISE EXCEPTION 'A new receipt goes only into a Deposit of this Final Settlement''s Lease'
            USING ERRCODE='55000'; END IF;
        -- Owner rule 3 of Q-2026-10-12-87 (a Pet Deposit) and answer (a) to Q-2026-10-11-83
        -- point 3 (a Security Deposit): no new money reaches a Deposit the Property keeps.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target
            WHERE target->'path'->>'forfeiture'='ACTIVE')
        THEN RAISE EXCEPTION 'A new receipt cannot go into a Deposit the Property keeps'
            USING ERRCODE='55000'; END IF;
        -- Q-2026-10-12-88 (answered 2026-10-12, built in sub-slice 10e-2c): until then a Deposit
        -- whose termination ground says the Property keeps it takes no new receipt.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target
            WHERE target->'path'->>'ground' IS NOT NULL)
        THEN RAISE EXCEPTION 'A new receipt into a Deposit with a forfeiture ground is not supported yet'
            USING ERRCODE='55000'; END IF;
        -- The Payment never gives more than the corrected receipt frees.
        IF (SELECT sum((target->>'amount_usd_cents')::bigint) FROM jsonb_array_elements(p_targets) target)
            >(p_source->'receipt'->>'amount_usd_cents')::bigint
        THEN RAISE EXCEPTION 'The new receipts take more than the corrected receipt frees'
            USING ERRCODE='55000'; END IF;
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target
            WHERE NOT (target->>'payment_funds')::boolean)
        THEN RAISE EXCEPTION 'The corrected receipt''s Payment cannot fund this Deposit'
            USING ERRCODE='55000'; END IF;
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target
            WHERE (target->>'payment_receipt_active')::boolean)
        THEN RAISE EXCEPTION 'The Deposit already holds an active receipt from this Payment'
            USING ERRCODE='55000'; END IF;
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target
            WHERE (target->>'amount_usd_cents')::bigint>(target->>'room_usd_cents')::bigint)
        THEN RAISE EXCEPTION 'A new receipt would exceed the Deposit''s required amount'
            USING ERRCODE='55000'; END IF;
        -- Sub-slice 10e-2b-2 names a recovery charge on this Lease in the plan; until then such a
        -- correction takes no new receipt.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'recoveries') recovery
            WHERE recovery->>'lease_id'=p_lease::text)
        THEN RAISE EXCEPTION 'A new receipt in a correction that charges a Refund back on this Lease is not supported yet'
            USING ERRCODE='55000'; END IF;
    END $$;

    -- Sub-slice 10e-2b: the plan check's overlay. Each obligation whose Deposit applications the
    -- correction reverses owes its open amount plus those applications; each named Deposit holds,
    -- after the correction, the right receipts' money (the corrected receipt's Deposit ends empty
    -- before them, sub-slice 10e-2).
    CREATE FUNCTION app.settlement_deposit_receipt_correction_overlay(p_source jsonb, p_receipts jsonb)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT jsonb_build_object('obligations',COALESCE((SELECT jsonb_object_agg(target.key,
                    CASE target.kind WHEN 'INVOICE_LINE' THEN app.invoice_line_outstanding(target.id)
                        ELSE COALESCE((SELECT position.remaining_balance_usd_cents
                            FROM app.late_payment_charge_financial_position position
                            WHERE position.late_payment_charge_id=target.id),0) END+target.applied)
                FROM (SELECT application->>'target_kind' AS kind,
                        COALESCE(application->>'invoice_line_id',application->>'late_payment_charge_id')::uuid AS id,
                        application->>'target_kind' || ':'
                            || COALESCE(application->>'invoice_line_id',application->>'late_payment_charge_id') AS key,
                        sum((application->>'amount_usd_cents')::bigint) AS applied
                    FROM jsonb_array_elements(p_source->'deposit_applications') application
                    GROUP BY 1,2,3) target),'{}'::jsonb),
            'credits','{}'::jsonb,'deposits','{}'::jsonb,
            'deposits_after',(SELECT jsonb_object_agg(deposit.id,
                    CASE WHEN deposit.id=p_source->'receipt'->>'deposit_id' THEN 0
                        ELSE app.deposit_held_value_at(deposit.id::uuid,'infinity') END
                    +COALESCE((SELECT sum((item->>'amount_usd_cents')::bigint)
                        FROM jsonb_array_elements(p_receipts) item WHERE item->>'deposit_id'=deposit.id),0))
                FROM (SELECT p_source->'receipt'->>'deposit_id' AS id
                    UNION SELECT item->>'deposit_id' FROM jsonb_array_elements(p_receipts) item) deposit))
    $$;

    -- Sub-slice 10e-2b (owner rules 1 to 3 of Q-2026-10-12-87): a right receipt of the corrected
    -- receipt's Payment, linked to the correction before it is written, dated after the latest
    -- event of its Deposit, with its own Deposit audit event (review round 1). The only Pet
    -- Deposit receipt writer; no grant. It writes only a receipt the correction's own
    -- DEPOSIT_RECEIPT_CORRECTION draft names, from that draft's Payment (review round 1).
    CREATE FUNCTION app.write_correction_deposit_receipt(p_correction uuid, p_approver uuid,
        p_deposit uuid, p_payment uuid, p_amount bigint, p_reason text, p_at timestamptz)
    RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
    DECLARE v_at timestamptz; v_new uuid;
    BEGIN
        IF NOT EXISTS(SELECT 1 FROM app.settlement_corrections correction
            JOIN app.financial_drafts draft ON draft.id=correction.correlation_id
            WHERE correction.id=p_correction AND correction.actor_id=p_approver
              AND draft.kind='SETTLEMENT_CORRECTION'
              AND draft.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION'
              AND draft.payload->>'payment_id'=p_payment::text
              AND EXISTS(SELECT 1 FROM jsonb_array_elements(
                      draft.payload->'deposit_receipt_correction'->'receipts') item
                  WHERE item->>'deposit_id'=p_deposit::text
                    AND (item->>'amount_usd_cents')::bigint=p_amount))
        THEN RAISE EXCEPTION 'The new receipt is not one the correction''s draft names'
            USING ERRCODE='55000'; END IF;
        v_at:=GREATEST(p_at+interval '1 microsecond',clock_timestamp(),
            COALESCE(app.deposit_balance_latest_at(p_deposit),'-infinity')+interval '1 microsecond');
        v_new:=gen_random_uuid();
        PERFORM app.link_settlement_correction_effect(p_correction,'deposit_receipt_id',v_new);
        INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,occurred_at,actor_id)
        VALUES (v_new,p_deposit,p_payment,p_amount,v_at,p_approver);
        PERFORM app.record_deposit_audit(v_new,'deposit.receipt.recorded','deposit_receipt',v_new,
            p_deposit,p_reason,'financial.approve',p_approver,p_correction,
            app.deposit_resource_snapshot(p_deposit));
        RETURN v_at;
    END $$;
"""

TARGETS = "app.settlement_deposit_receipt_correction_targets(uuid,jsonb,jsonb)"
INTERNAL = (
    TARGETS,
    "app.assert_settlement_deposit_receipt_targets_allowed(uuid,jsonb,jsonb)",
    "app.settlement_deposit_receipt_correction_overlay(jsonb,jsonb)",
    "app.write_correction_deposit_receipt(uuid,uuid,uuid,uuid,bigint,text,timestamp with time zone)",
)
INPUT = "app.settlement_deposit_receipt_correction_input(jsonb)"

RECEIPT_CHECK = "app.validate_deposit_receipt()"
RECEIPT_CHECK_REPLACEMENTS = (
    (
        "            SELECT COALESCE(sum(receipt.amount_usd_cents),0) INTO v_received\n",
        "            -- Sub-slice 10e-2b (owner rule 1 of Q-2026-10-12-87): a Deposit holds at most one\n"
        "            -- active receipt from each Payment; a reversed receipt stays in the history and no\n"
        "            -- longer blocks a new one (this check replaces the key UNIQUE (deposit_id, payment_id)).\n"
        "            -- It relies on the Deposit row lock taken above and by the earlier balance trigger:\n"
        "            -- at READ COMMITTED it reads after the lock; a REPEATABLE READ writer fails on the\n"
        "            -- Deposit's serialization guard instead (both writers run at READ COMMITTED).\n"
        "            IF EXISTS(SELECT 1 FROM app.deposit_receipts AS receipt\n"
        "                WHERE receipt.deposit_id=NEW.deposit_id AND receipt.payment_id=NEW.payment_id\n"
        "                  AND NOT EXISTS (SELECT 1 FROM app.deposit_receipt_reversals AS reversal\n"
        "                      WHERE reversal.deposit_receipt_id=receipt.id))\n"
        "            THEN RAISE EXCEPTION 'A Deposit holds at most one active receipt from each Payment'\n"
        "                USING ERRCODE='23505'; END IF;\n"
        "            SELECT COALESCE(sum(receipt.amount_usd_cents),0) INTO v_received\n",
    ),
    (
        "                    OR (v_received=0 AND NEW.amount_usd_cents<>v_accepted)\n",
        "                    OR (v_received=0 AND NEW.amount_usd_cents<>v_accepted\n"
        "                        -- Sub-slice 10e-2b (owner rule 2 of Q-2026-10-12-87): a receipt that a\n"
        "                        -- correction of the Lease's closed Final Settlement links in this\n"
        "                        -- transaction may differ from the accepted amount (never above the\n"
        "                        -- required amount, checked next; the required amount does not change).\n"
        "                        AND app.settlement_correction_linked((SELECT settlement.id\n"
        "                            FROM app.final_settlements AS settlement\n"
        "                            WHERE settlement.lease_id=v_deposit.lease_id\n"
        "                              AND settlement.closed_at IS NOT NULL),'deposit_receipts',NEW.id)\n"
        "                            IS NOT TRUE)\n",
    ),
)

PLAN_RESULT = "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)"
PLAN_RESULT_REPLACEMENTS = (
    (
        "                    WHERE key NOT IN ('pet_damage','hold_deposits','held_left'))\n",
        "                    WHERE key NOT IN ('pet_damage','hold_deposits','held_left','deposits_after'))\n",
    ),
    (
        "            OR EXISTS(SELECT 1 FROM jsonb_each(p_overlay->'deposits') item\n"
        "                WHERE app.final_settlement_plan_id(to_jsonb(item.key)) IS DISTINCT FROM item.key\n"
        "                   OR NOT app.settlement_correction_overlay_amount(item.value))\n"
        "        THEN RAISE EXCEPTION 'Post-settlement correction overlay is invalid' USING ERRCODE='22023'; END IF;\n",
        "            OR EXISTS(SELECT 1 FROM jsonb_each(p_overlay->'deposits') item\n"
        "                WHERE app.final_settlement_plan_id(to_jsonb(item.key)) IS DISTINCT FROM item.key\n"
        "                   OR NOT app.settlement_correction_overlay_amount(item.value))\n"
        "            -- Sub-slice 10e-2b: a receipt correction's held value of each named Deposit after the\n"
        "            -- correction, absolute (a Deposit id to whole cents).\n"
        "            OR jsonb_typeof(COALESCE(p_overlay->'deposits_after','{}'::jsonb)) IS DISTINCT FROM 'object'\n"
        "            OR EXISTS(SELECT 1 FROM jsonb_each(CASE WHEN jsonb_typeof(p_overlay->'deposits_after')='object'\n"
        "                    THEN p_overlay->'deposits_after' ELSE '{}'::jsonb END) item\n"
        "                WHERE app.final_settlement_plan_id(to_jsonb(item.key)) IS DISTINCT FROM item.key\n"
        "                   OR NOT app.settlement_correction_overlay_amount(item.value))\n"
        "        THEN RAISE EXCEPTION 'Post-settlement correction overlay is invalid' USING ERRCODE='22023'; END IF;\n",
    ),
    (
        "            v_item:=NULL;\n"
        "        END LOOP;\n"
        "        SELECT COALESCE(jsonb_object_agg(item.key,item.value),'{}'::jsonb) INTO v_held\n",
        "            v_item:=NULL;\n"
        "        END LOOP;\n"
        "        -- Sub-slice 10e-2b: a receipt correction's Deposits hold, after the correction, exactly\n"
        "        -- what the overlay names (the corrected receipt's Deposit ends empty, then the right\n"
        "        -- receipts); at the step the receipts exist and the overlay has no such key.\n"
        "        FOR v_entry IN SELECT item.key,item.value\n"
        "            FROM jsonb_each(COALESCE(p_overlay->'deposits_after','{}'::jsonb)) item\n"
        "        LOOP\n"
        "            SELECT deposit INTO v_item FROM jsonb_array_elements(v_preview->'deposits') deposit\n"
        "            WHERE deposit->>'deposit_id'=v_entry.key;\n"
        "            IF v_item IS NULL THEN\n"
        "                RAISE EXCEPTION 'The overlay names a Deposit outside this Final Settlement' USING ERRCODE='55000';\n"
        "            END IF;\n"
        "            -- Only a Deposit that follows DL-032 may hold money the step applies or refunds\n"
        "            -- (review round 1; the recorder's refusals already keep every other Deposit out).\n"
        "            IF (v_entry.value#>>'{}')::bigint>0 AND v_item->>'path' IS DISTINCT FROM 'DL_032' THEN\n"
        "                RAISE EXCEPTION 'Only a Deposit that follows DL-032 and holds money may be applied'\n"
        "                    USING ERRCODE='55000'; END IF;\n"
        "            v_held:=v_held||jsonb_build_object(v_entry.key,(v_entry.value#>>'{}')::bigint);\n"
        "            v_type:=v_type||jsonb_build_object(v_entry.key,v_item->'deposit_type');\n"
        "            v_item:=NULL;\n"
        "        END LOOP;\n"
        "        SELECT COALESCE(jsonb_object_agg(item.key,item.value),'{}'::jsonb) INTO v_held\n",
    ),
)

LOCK = "app.lock_settlement_correction_plan(uuid)"
LOCK_REPLACEMENTS = (
    (
        "        IF v_draft.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION' THEN v_steps:='[]'::jsonb; END IF;\n",
        "        -- Sub-slice 10e-2b: unless it writes the right receipts; then its plan's targets are locked\n"
        "        -- as every plan's (the receipts' Deposits are the Lease's, in the Deposit pass).\n"
        "        IF v_draft.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION'\n"
        "            AND jsonb_typeof(v_draft.payload->'plan') IS DISTINCT FROM 'object'\n"
        "        THEN v_steps:='[]'::jsonb; END IF;\n",
    ),
)

RECORDER = (
    "app.record_settlement_deposit_receipt_correction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
)
RECORDER_REPLACEMENTS = (
    (
        "        v_input jsonb; v_receipt uuid; v_payment uuid; v_source jsonb; v_payload jsonb;\n"
        "    BEGIN\n",
        "        v_input jsonb; v_receipt uuid; v_payment uuid; v_source jsonb; v_payload jsonb;\n"
        "        v_overlay jsonb; v_result jsonb;\n"
        "    BEGIN\n",
    ),
    (
        "        PERFORM app.assert_settlement_deposit_receipt_correction_allowed(v_settlement.id,v_settlement.lease_id,v_source);\n"
        "        v_payload:=jsonb_build_object('variant','DEPOSIT_RECEIPT_CORRECTION',\n",
        "        PERFORM app.assert_settlement_deposit_receipt_correction_allowed(v_settlement.id,v_settlement.lease_id,v_source);\n"
        "        -- Sub-slice 10e-2b: the right receipts, then the shared step's check on the current state\n"
        "        -- with the correction's effect as the overlay: the reopened obligations, and each named\n"
        "        -- Deposit's money after the correction; the Customer's Credit first, the Deposits in the\n"
        "        -- DL-032 order, only the rest refunded, every new cent applied or refunded\n"
        "        -- (BR-SETTLE-008). The confirm-time step checks the same result on the real state.\n"
        "        IF v_input ? 'receipts' THEN\n"
        "            PERFORM app.assert_settlement_deposit_receipt_targets_allowed(v_settlement.lease_id,v_source,\n"
        "                app.settlement_deposit_receipt_correction_targets(p_property,v_source,v_input->'receipts'));\n"
        "            v_overlay:=app.settlement_deposit_receipt_correction_overlay(v_source,v_input->'receipts');\n"
        "            v_result:=app.settlement_correction_plan_result(p_property,p_actor,v_settlement.id,\n"
        "                v_input->'plan',v_overlay)-'source_revision';\n"
        "        END IF;\n"
        "        v_payload:=jsonb_build_object('variant','DEPOSIT_RECEIPT_CORRECTION',\n",
    ),
    (
        "            'payment_id',v_payment,'deposit_receipt_correction',v_input,'source',v_source);\n",
        "            'payment_id',v_payment,'deposit_receipt_correction',v_input,'source',v_source)\n"
        "            ||CASE WHEN v_input ? 'receipts' THEN jsonb_build_object('plan',v_input->'plan',\n"
        "                'plan_overlay',v_overlay,'plan_result',v_result) ELSE '{}'::jsonb END;\n",
    ),
)

HELPER = "app.post_settlement_deposit_receipt_correction(uuid,uuid,uuid,uuid,uuid,text)"
HELPER_REPLACEMENTS = (
    (
        "        v_key text;\n    BEGIN\n",
        "        v_key text; v_receipts jsonb; v_item jsonb;\n    BEGIN\n",
    ),
    (
        "        PERFORM app.assert_settlement_deposit_receipt_correction_allowed(v_settlement,v_lease,v_source);\n"
        "        v_at:=clock_timestamp();\n",
        "        PERFORM app.assert_settlement_deposit_receipt_correction_allowed(v_settlement,v_lease,v_source);\n"
        "        -- Sub-slice 10e-2b: the right receipts the draft names, checked again under the locks.\n"
        "        SELECT draft.payload->'deposit_receipt_correction'->'receipts' INTO v_receipts\n"
        "        FROM app.financial_drafts draft WHERE draft.id=p_draft;\n"
        "        IF v_receipts IS NOT NULL THEN\n"
        "            PERFORM app.assert_settlement_deposit_receipt_targets_allowed(v_lease,v_source,\n"
        "                app.settlement_deposit_receipt_correction_targets(p_property,v_source,v_receipts));\n"
        "        END IF;\n"
        "        v_at:=clock_timestamp();\n",
    ),
    (
        "            v_reason,md5(v_key)::uuid,encode(sha256(convert_to(v_key,'UTF8')),'hex'),v_at);\n"
        "        RETURN v_at;\n",
        "            v_reason,md5(v_key)::uuid,encode(sha256(convert_to(v_key,'UTF8')),'hex'),v_at);\n"
        "        -- Sub-slice 10e-2b (owner answers to Q-2026-10-12-87): the right receipts of the same\n"
        "        -- Payment's freed value, each linked before it is written, then the shared DL-032 step,\n"
        "        -- which checks the draft's recorded result on the real state, applies the new money in\n"
        "        -- the DL-032 order and refunds the rest. What the receipts do not take stays\n"
        "        -- unallocated with the Payment (owner answer 1 to Q-2026-10-11-83).\n"
        "        IF v_receipts IS NOT NULL THEN\n"
        "            FOR v_item IN SELECT receipt.value\n"
        "                FROM jsonb_array_elements(v_receipts) WITH ORDINALITY receipt(value,position)\n"
        "                ORDER BY receipt.position\n"
        "            LOOP\n"
        "                v_at:=app.write_correction_deposit_receipt(p_correction,p_approver,\n"
        "                    (v_item->>'deposit_id')::uuid,(v_source->'receipt'->>'payment_id')::uuid,\n"
        "                    (v_item->>'amount_usd_cents')::bigint,v_reason,v_at);\n"
        "            END LOOP;\n"
        "            PERFORM app.post_settlement_correction_plan(p_property,p_approver,p_draft);\n"
        "            -- The confirm's audit event is dated after the step's records (review round 1).\n"
        "            v_at:=GREATEST(v_at,clock_timestamp());\n"
        "        END IF;\n"
        "        RETURN v_at;\n",
    ),
)

RESULT = "app.settlement_deposit_receipt_correction_result(uuid)"
RESULT_REPLACEMENTS = (
    (
        "            'payment',(SELECT jsonb_build_object('id',payment.id,'status',payment.status,\n",
        "            -- Sub-slice 10e-2b: the right receipts and the records of the DL-032 step.\n"
        "            'new_deposit_receipts',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',written.id,\n"
        "                    'deposit_id',written.deposit_id,'amount_usd_cents',written.amount_usd_cents)\n"
        "                    ORDER BY effects.effect_sequence)\n"
        "                FROM effects JOIN app.deposit_receipts written ON written.id=effects.deposit_receipt_id),\n"
        "                '[]'::jsonb),\n"
        "            'credit_application_ids',COALESCE((SELECT jsonb_agg(customer_credit_application_id\n"
        "                    ORDER BY effect_sequence) FROM effects\n"
        "                WHERE customer_credit_application_id IS NOT NULL),'[]'::jsonb),\n"
        "            'deposit_application_ids',COALESCE((SELECT jsonb_agg(deposit_application_id\n"
        "                    ORDER BY effect_sequence) FROM effects\n"
        "                WHERE deposit_application_id IS NOT NULL),'[]'::jsonb),\n"
        "            'refund_ids',COALESCE((SELECT jsonb_agg(refund_id ORDER BY effect_sequence) FROM effects\n"
        "                WHERE refund_id IS NOT NULL),'[]'::jsonb),\n"
        "            'payment',(SELECT jsonb_build_object('id',payment.id,'status',payment.status,\n",
    ),
)

PATCHES = (
    (RECEIPT_CHECK, RECEIPT_CHECK_REPLACEMENTS),
    (PLAN_RESULT, PLAN_RESULT_REPLACEMENTS),
    (LOCK, LOCK_REPLACEMENTS),
    (RECORDER, RECORDER_REPLACEMENTS),
    (HELPER, HELPER_REPLACEMENTS),
    (RESULT, RESULT_REPLACEMENTS),
)


def _link_sql() -> str:
    """DB-SETTLE-005 gains deposit_receipt_id; the link functions are rebuilt (as sub-slice
    10c-2a-5 rebuilt them)."""
    links = (
        *_module("20261102_98_settlement_extra_charge.py", "settlement_extra_charge_98").LINKS,
        ("deposit_application_reversal_id", "app.deposit_application_reversals"),
        ("settlement_pet_classification_id", "app.settlement_pet_classifications"),
        ("deposit_receipt_id", "app.deposit_receipts"),
    )
    column, table = links[-1]
    link_names = ",".join(name for name, _ in links)
    link_match = "\n                OR ".join(
        f"(p_table='{linked.removeprefix('app.')}' AND effect.{name}=p_record)"
        for name, linked in links
    )
    link_allowed = ",".join(f"'{name}'" for name, _ in links)
    link_values = ",".join(f"CASE WHEN p_link='{name}' THEN p_record END" for name, _ in links)
    return f"""
        -- Sub-slice 10e-2b: the right receipt a Deposit receipt correction writes.
        ALTER TABLE app.settlement_correction_effects
            ADD COLUMN {column} uuid UNIQUE REFERENCES {table}(id) ON DELETE RESTRICT
                DEFERRABLE INITIALLY DEFERRED,
            DROP CONSTRAINT settlement_correction_effect_one_link,
            ADD CONSTRAINT settlement_correction_effect_one_link CHECK (num_nonnulls({link_names})=1);

        -- Whether a record is linked to a correction of this Settlement confirmed in this
        -- transaction (never NULL); rebuilt with the new link.
        CREATE OR REPLACE FUNCTION app.settlement_correction_linked(p_settlement uuid,p_table text,
            p_record uuid)
        RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                JOIN app.settlement_corrections correction
                    ON correction.id=effect.settlement_correction_id
                JOIN app.financial_draft_decisions decision
                    ON decision.draft_id=correction.correlation_id AND decision.decision='CONFIRMED'
                WHERE correction.final_settlement_id=p_settlement
                  AND decision.result->>'transaction_id'=pg_current_xact_id()::text
                  AND decision.decided_at>=transaction_timestamp()
                  AND ({link_match}))
        $$;

        -- Internal: links one record to the correction, before the writer writes that record;
        -- rebuilt with the new link.
        CREATE OR REPLACE FUNCTION app.link_settlement_correction_effect(p_correction uuid,p_link text,
            p_record uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_effect uuid:=gen_random_uuid(); v_sequence integer;
        BEGIN
            IF p_correction IS NULL OR p_record IS NULL OR p_link IS NULL
                OR p_link NOT IN ({link_allowed})
            THEN RAISE EXCEPTION 'Post-settlement correction effect is invalid' USING ERRCODE='22023'; END IF;
            SELECT COALESCE(max(effect.effect_sequence),0)+1 INTO v_sequence
            FROM app.settlement_correction_effects effect WHERE effect.settlement_correction_id=p_correction;
            INSERT INTO app.settlement_correction_effects(id,settlement_correction_id,effect_sequence,{link_names})
            SELECT v_effect,p_correction,v_sequence,{link_values};
            RETURN v_effect;
        END $$;
    """


def _module(file_name: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file_name))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Deposit receipt correction source is missing: {file_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
            raise RuntimeError(f"Deposit receipt correction receipts contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(TABLE_SQL)
    op.execute(_link_sql())
    op.execute(FUNCTION_SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Deposit receipt correction receipts migration is forward-only")
