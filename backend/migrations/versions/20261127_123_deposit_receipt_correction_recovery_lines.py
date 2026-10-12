# ruff: noqa: E501
"""Recovery charges as placeholder lines in a Deposit receipt correction's plan (V1-056
sub-slice 10e-2b-2).

BR-SETTLE-013, BR-SETTLE-008, BR-SETTLE-016, DL-032, BR-AUTH-010, BR-CREDIT-008; DB-SETTLE-005,
DB-DEP-002;
the owner instruction of 2026-10-12 with the answers to Q-2026-10-12-88 and owner answer 1 to
Q-2026-10-12-89:

- A `DEPOSIT_RECEIPT_CORRECTION` with right receipts may also charge back a Refund paid from the
  corrected receipt's Deposit on this Lease (the sub-slice 10e-1c rule: the person who received it
  pays it back). The draft names each such recovery charge as a placeholder line
  (`md5('deposit-receipt-recovery:' || draft || ':' || refund)`) with its Refund, Customer, Lease
  and exact amount in the plan overlay's `new_obligations`, so the DL-032 plan may pay it and the
  approver confirms real numbers. At the confirm the shared step first checks that each real
  recovery charge equals its placeholder exactly (Customer, Lease, amount; stale P5S02 otherwise),
  then every step on a placeholder pays the real charge line (also in the Credit step writer, which
  reads its step from the draft). The 10e-2b-1 refusal of such a correction is lifted.
- Owner answer 1 to Q-2026-10-12-89 (an approved tightening): a receipt correction must change the
  Deposit or the amount; the same receipt again into the same Deposit is refused (55000).
- The right-receipt writer also requires its correction's decision confirmed in this transaction
  by this approver (10e-2b-1 review round 2).

Exact-text patches of the receipt correction's recorder and target check, the receipt writer, the
shared plan check, the shared DL-032 step, the Credit step writer and the three checks that match a
correction's Credit or Deposit application with its plan step; three new internal functions.
"""

from alembic import op
from sqlalchemy import text

revision = "20261127_123"
down_revision = "20261126_122"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- Sub-slice 10e-2b-2: each recovery charge the correction writes on this Lease, as a
    -- placeholder line id (from the draft and the Refund) with its Refund, Customer, Lease and
    -- exact amount. A recovery with no Lease is not debt of this Lease and has no placeholder.
    CREATE FUNCTION app.settlement_deposit_receipt_recovery_lines(p_draft uuid, p_lease uuid, p_source jsonb)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE(jsonb_object_agg(
                md5('deposit-receipt-recovery:' || p_draft::text || ':' || (recovery->>'refund_id'))::uuid::text,
                jsonb_build_object('refund_id',recovery->>'refund_id',
                    'customer_id',recovery->>'recipient_customer_id','lease_id',recovery->>'lease_id',
                    'amount_usd_cents',(recovery->>'amount_usd_cents')::bigint)),'{}'::jsonb)
        FROM jsonb_array_elements(COALESCE(p_source->'recoveries','[]'::jsonb)) recovery
        WHERE recovery->>'lease_id'=p_lease::text
    $$;

    -- Sub-slice 10e-2b-2: the real line of a placeholder line (the recovery charge line of the
    -- correction's linked RECOVERED_BY_CHARGE row of that Refund; NULL before it is written);
    -- any other target is returned unchanged.
    CREATE FUNCTION app.settlement_correction_line_id(p_correction uuid, p_lines jsonb, p_target uuid)
    RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT CASE WHEN jsonb_typeof(p_lines) IS DISTINCT FROM 'object'
                OR NOT p_lines ? p_target::text THEN p_target
            ELSE (SELECT line.id FROM app.settlement_correction_effects effect
                JOIN app.refund_corrections recovery ON recovery.id=effect.refund_correction_id
                JOIN app.invoice_lines line ON line.authorized_obligation_id=recovery.recovery_obligation_id
                WHERE effect.settlement_correction_id=p_correction
                  AND recovery.correction_kind='RECOVERED_BY_CHARGE'
                  AND recovery.refund_id::text=p_lines->p_target::text->>'refund_id') END
    $$;

    -- Sub-slice 10e-2b-2 (owner instruction of 2026-10-12): at the confirm each placeholder line
    -- is a real recovery charge of this correction, exactly as the draft showed it (its Invoice's
    -- Customer and Lease, its one line's amount), and every recovery charge the correction wrote on
    -- the Settlement's Lease has its placeholder.
    CREATE FUNCTION app.assert_settlement_correction_placeholder_lines(p_correction uuid, p_lines jsonb)
    RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_lines jsonb:=COALESCE(p_lines,'{}'::jsonb); v_lease uuid;
    BEGIN
        SELECT settlement.lease_id INTO v_lease FROM app.settlement_corrections correction
        JOIN app.final_settlements settlement ON settlement.id=correction.final_settlement_id
        WHERE correction.id=p_correction;
        IF jsonb_typeof(v_lines) IS DISTINCT FROM 'object'
            OR EXISTS(SELECT 1 FROM jsonb_each(v_lines) item
                WHERE NOT EXISTS(SELECT 1 FROM app.invoice_lines line
                    JOIN app.invoices invoice ON invoice.id=line.invoice_id
                    WHERE line.id=app.settlement_correction_line_id(p_correction,v_lines,item.key::uuid)
                      AND invoice.customer_id::text=item.value->>'customer_id'
                      AND invoice.lease_id::text=item.value->>'lease_id'
                      AND invoice.lease_id=v_lease
                      AND line.amount_usd_cents::text=item.value->>'amount_usd_cents'
                      AND invoice.original_total_usd_cents=line.amount_usd_cents))
            OR (SELECT count(*) FROM app.settlement_correction_effects effect
                    JOIN app.refund_corrections recovery ON recovery.id=effect.refund_correction_id
                    JOIN app.authorized_nonrecurring_obligations obligation
                        ON obligation.id=recovery.recovery_obligation_id
                    WHERE effect.settlement_correction_id=p_correction
                      AND recovery.correction_kind='RECOVERED_BY_CHARGE'
                      AND obligation.lease_id=v_lease)
                <>(SELECT count(*) FROM jsonb_object_keys(v_lines))
            -- Each placeholder names a distinct Refund, so the counts match one to one (review
            -- round 1).
            OR (SELECT count(DISTINCT item.value->>'refund_id') FROM jsonb_each(v_lines) item)
                <>(SELECT count(*) FROM jsonb_object_keys(v_lines))
        THEN RAISE EXCEPTION 'A recovery charge does not match its placeholder line in the draft'
            USING ERRCODE='P5S02'; END IF;
    END $$;
"""

INTERNAL = (
    "app.settlement_deposit_receipt_recovery_lines(uuid,uuid,jsonb)",
    "app.settlement_correction_line_id(uuid,jsonb,uuid)",
    "app.assert_settlement_correction_placeholder_lines(uuid,jsonb)",
)

TARGETS_CHECK = "app.assert_settlement_deposit_receipt_targets_allowed(uuid,jsonb,jsonb)"
TARGETS_CHECK_REPLACEMENTS = (
    (
        "        -- Sub-slice 10e-2b-2 names a recovery charge on this Lease in the plan; until then such a\n"
        "        -- correction takes no new receipt.\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'recoveries') recovery\n"
        "            WHERE recovery->>'lease_id'=p_lease::text)\n"
        "        THEN RAISE EXCEPTION 'A new receipt in a correction that charges a Refund back on this Lease is not supported yet'\n"
        "            USING ERRCODE='55000'; END IF;\n",
        "        -- Sub-slice 10e-2b-2: a recovery charge on this Lease is a placeholder line of the plan\n"
        "        -- (app.settlement_deposit_receipt_recovery_lines), so it no longer refuses a new receipt.\n"
        "        -- Owner answer 1 to Q-2026-10-12-89 (an approved tightening): a receipt correction must\n"
        "        -- change the Deposit or the amount; the same receipt again into the same Deposit (the\n"
        "        -- same Payment, the same amount) belongs to another correction kind.\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target\n"
        "            WHERE target->>'deposit_id'=p_source->'receipt'->>'deposit_id'\n"
        "              AND (target->>'amount_usd_cents')::bigint=(p_source->'receipt'->>'amount_usd_cents')::bigint)\n"
        "        THEN RAISE EXCEPTION 'A receipt correction must change the Deposit or the amount'\n"
        "            USING ERRCODE='55000'; END IF;\n",
    ),
)

WRITER = (
    "app.write_correction_deposit_receipt(uuid,uuid,uuid,uuid,bigint,text,timestamp with time zone)"
)
WRITER_REPLACEMENTS = (
    (
        "        THEN RAISE EXCEPTION 'The new receipt is not one the correction''s draft names'\n"
        "            USING ERRCODE='55000'; END IF;\n",
        "        THEN RAISE EXCEPTION 'The new receipt is not one the correction''s draft names'\n"
        "            USING ERRCODE='55000'; END IF;\n"
        "        -- Sub-slice 10e-2b-2 (10e-2b-1 review round 2): only inside that correction's confirm,\n"
        "        -- decided in this transaction by this approver.\n"
        "        IF NOT EXISTS(SELECT 1 FROM app.settlement_corrections correction\n"
        "            JOIN app.financial_draft_decisions decision ON decision.draft_id=correction.correlation_id\n"
        "            WHERE correction.id=p_correction AND decision.decision='CONFIRMED'\n"
        "              AND decision.decided_by=p_approver AND decision.authorization_reference='financial.approve'\n"
        "              AND decision.result->>'transaction_id'=pg_current_xact_id()::text\n"
        "              AND decision.decided_at>=transaction_timestamp())\n"
        "        THEN RAISE EXCEPTION 'A new receipt is written only inside its correction''s confirm'\n"
        "            USING ERRCODE='55000'; END IF;\n",
    ),
)

RECORDER = (
    "app.record_settlement_deposit_receipt_correction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
)
RECORDER_REPLACEMENTS = (
    (
        "        v_overlay jsonb; v_result jsonb;\n    BEGIN\n",
        "        v_overlay jsonb; v_result jsonb; v_lines jsonb;\n    BEGIN\n",
    ),
    (
        "            v_overlay:=app.settlement_deposit_receipt_correction_overlay(v_source,v_input->'receipts');\n",
        "            v_overlay:=app.settlement_deposit_receipt_correction_overlay(v_source,v_input->'receipts');\n"
        "            -- Sub-slice 10e-2b-2 (owner instruction of 2026-10-12): each recovery charge on this\n"
        "            -- Lease is a placeholder line with its Refund, Customer, Lease and exact amount, so the\n"
        "            -- plan may pay it and the draft shows it to the approver.\n"
        "            v_lines:=app.settlement_deposit_receipt_recovery_lines(p_draft,v_settlement.lease_id,v_source);\n"
        "            IF v_lines<>'{}'::jsonb THEN\n"
        "                v_overlay:=v_overlay||jsonb_build_object('new_obligations',v_lines); END IF;\n",
    ),
)

PLAN_RESULT = "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)"
PLAN_RESULT_REPLACEMENTS = (
    (
        "                    WHERE key NOT IN ('pet_damage','hold_deposits','held_left','deposits_after'))\n",
        "                    WHERE key NOT IN ('pet_damage','hold_deposits','held_left','deposits_after',\n"
        "                        'new_obligations'))\n",
    ),
    (
        "                WHERE app.final_settlement_plan_id(to_jsonb(item.key)) IS DISTINCT FROM item.key\n"
        "                   OR NOT app.settlement_correction_overlay_amount(item.value))\n"
        "        THEN RAISE EXCEPTION 'Post-settlement correction overlay is invalid' USING ERRCODE='22023'; END IF;\n",
        "                WHERE app.final_settlement_plan_id(to_jsonb(item.key)) IS DISTINCT FROM item.key\n"
        "                   OR NOT app.settlement_correction_overlay_amount(item.value))\n"
        "            -- Sub-slice 10e-2b-2: a receipt correction's placeholder lines (a line id to the\n"
        "            -- recovery charge's Refund, Customer, Lease and whole amount above 0).\n"
        "            OR jsonb_typeof(COALESCE(p_overlay->'new_obligations','{}'::jsonb)) IS DISTINCT FROM 'object'\n"
        "            OR EXISTS(SELECT 1 FROM jsonb_each(CASE WHEN jsonb_typeof(p_overlay->'new_obligations')='object'\n"
        "                    THEN p_overlay->'new_obligations' ELSE '{}'::jsonb END) item\n"
        "                WHERE app.final_settlement_plan_id(to_jsonb(item.key)) IS DISTINCT FROM item.key\n"
        "                   OR jsonb_typeof(item.value) IS DISTINCT FROM 'object'\n"
        '                   OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(item.value) key)\n'
        "                       IS DISTINCT FROM ARRAY['amount_usd_cents','customer_id','lease_id','refund_id']\n"
        "                   -- Each id a UUID string in its normal form, never JSON null (security review\n"
        "                   -- round 1); the amount above 0 and within the shared overlay limit.\n"
        "                   OR jsonb_typeof(item.value->'customer_id') IS DISTINCT FROM 'string'\n"
        "                   OR jsonb_typeof(item.value->'lease_id') IS DISTINCT FROM 'string'\n"
        "                   OR jsonb_typeof(item.value->'refund_id') IS DISTINCT FROM 'string'\n"
        "                   OR app.final_settlement_plan_id(item.value->'customer_id') IS DISTINCT FROM item.value->>'customer_id'\n"
        "                   OR app.final_settlement_plan_id(item.value->'lease_id') IS DISTINCT FROM item.value->>'lease_id'\n"
        "                   OR app.final_settlement_plan_id(item.value->'refund_id') IS DISTINCT FROM item.value->>'refund_id'\n"
        "                   OR NOT app.settlement_correction_overlay_amount(item.value->'amount_usd_cents')\n"
        "                   OR item.value->'amount_usd_cents'='0'::jsonb)\n"
        "        THEN RAISE EXCEPTION 'Post-settlement correction overlay is invalid' USING ERRCODE='22023'; END IF;\n",
    ),
    (
        "            v_open:=v_open||jsonb_build_object(v_entry.key,(v_entry.value#>>'{}')::bigint);\n"
        "        END LOOP;\n"
        "        v_open_start:=v_open;\n",
        "            v_open:=v_open||jsonb_build_object(v_entry.key,(v_entry.value#>>'{}')::bigint);\n"
        "        END LOOP;\n"
        "        -- Sub-slice 10e-2b-2: each placeholder line owes its whole amount, named on its Customer,\n"
        "        -- on this Lease; a recovery charge is never pet damage and has no Invoice yet, so no\n"
        "        -- Rent-first proposal applies (its real Invoice has one Miscellaneous line).\n"
        "        FOR v_entry IN SELECT item.key,item.value\n"
        "            FROM jsonb_each(COALESCE(p_overlay->'new_obligations','{}'::jsonb)) item\n"
        "        LOOP\n"
        "            IF v_owner ? ('INVOICE_LINE:'||v_entry.key) OR v_entry.value->>'lease_id' IS DISTINCT FROM v_lease::text THEN\n"
        "                RAISE EXCEPTION 'The overlay names an obligation outside this Final Settlement'\n"
        "                    USING ERRCODE='55000'; END IF;\n"
        "            v_open:=v_open||jsonb_build_object('INVOICE_LINE:'||v_entry.key,\n"
        "                (v_entry.value->>'amount_usd_cents')::bigint);\n"
        "            v_owner:=v_owner||jsonb_build_object('INVOICE_LINE:'||v_entry.key,v_entry.value->'customer_id');\n"
        "        END LOOP;\n"
        "        v_open_start:=v_open;\n",
    ),
    (
        "        INTO v_credit,v_credit_owner\n"
        "        FROM jsonb_array_elements(v_preview->'customers') person,jsonb_array_elements(person->'credits') credit;\n",
        "        INTO v_credit,v_credit_owner\n"
        "        FROM jsonb_array_elements(v_preview->'customers') person,jsonb_array_elements(person->'credits') credit;\n"
        "        -- Sub-slice 10e-2b-2: a placeholder line's Customer whom the preview does not name yet (a\n"
        "        -- signed Signer on no issued Invoice of the Lease) is named at the confirm by the recovery\n"
        "        -- charge's Invoice; that Customer's Credit counts now as the preview reads it then.\n"
        "        SELECT v_credit||COALESCE(jsonb_object_agg(available.id,available.amount),'{}'::jsonb),\n"
        "            v_credit_owner||COALESCE(jsonb_object_agg(available.id,available.customer),'{}'::jsonb)\n"
        "        INTO v_credit,v_credit_owner\n"
        "        FROM (SELECT credit.id::text AS id,app.credit_available_value(credit.id) AS amount,\n"
        "                to_jsonb(credit.customer_id::text) AS customer\n"
        "            FROM app.customer_credits credit JOIN app.payments payment ON payment.id=credit.source_payment_id\n"
        "            WHERE payment.property_id=p_property\n"
        "              AND credit.customer_id::text IN (SELECT item.value->>'customer_id'\n"
        "                  FROM jsonb_each(COALESCE(p_overlay->'new_obligations','{}'::jsonb)) item)\n"
        "              AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v_preview->'customers') person\n"
        "                  WHERE person->>'customer_id'=credit.customer_id::text)) available\n"
        "        WHERE available.amount>0;\n",
    ),
)

PLAN_STEP = "app.post_settlement_correction_plan(uuid,uuid,uuid)"
PLAN_STEP_REPLACEMENTS = (
    (
        "        PERFORM app.lock_settlement_correction_plan(p_draft);\n",
        "        PERFORM app.lock_settlement_correction_plan(p_draft);\n"
        "        -- Sub-slice 10e-2b-2 (owner instruction of 2026-10-12): each placeholder line of the draft\n"
        "        -- is now a real recovery charge of this correction, exactly as the draft showed it; the\n"
        "        -- steps on it pay the real line. (The lock pass above skips a placeholder: its line is\n"
        "        -- written in this transaction, so no other transaction sees it before the commit.)\n"
        "        PERFORM app.assert_settlement_correction_placeholder_lines(v_correction.id,\n"
        "            v_draft.payload->'plan_overlay'->'new_obligations');\n",
    ),
    (
        "        INTO v_steps FROM jsonb_array_elements(v_plan->'steps') WITH ORDINALITY AS item(step,ordinality);\n",
        "        INTO v_steps FROM jsonb_array_elements(v_plan->'steps') WITH ORDINALITY AS item(step,ordinality);\n"
        "        -- Sub-slice 10e-2b-2: a step on a placeholder line names its real recovery charge line.\n"
        "        SELECT COALESCE(jsonb_agg(CASE WHEN item.step ? 'target_id'\n"
        "                    AND v_draft.payload->'plan_overlay'->'new_obligations'\n"
        "                        ? app.final_settlement_plan_id(item.step->'target_id')\n"
        "                THEN jsonb_set(item.step,'{target_id}',to_jsonb(app.settlement_correction_line_id(\n"
        "                    v_correction.id,v_draft.payload->'plan_overlay'->'new_obligations',\n"
        "                    app.final_settlement_plan_id(item.step->'target_id')::uuid)::text))\n"
        "                ELSE item.step END ORDER BY item.ordinality),'[]'::jsonb)\n"
        "        INTO v_steps FROM jsonb_array_elements(v_steps) WITH ORDINALITY AS item(step,ordinality);\n",
    ),
    (
        "                v_item->>'target_kind',app.final_settlement_plan_id(v_item->'target_id')::uuid,\n",
        "                v_item->>'target_kind',app.settlement_correction_line_id(v_correction.id,\n"
        "                    v_draft.payload->'plan_overlay'->'new_obligations',\n"
        "                    app.final_settlement_plan_id(v_item->'target_id')::uuid),\n",
    ),
)

CREDIT_STEP = "app.post_final_settlement_credit_application(uuid,uuid,uuid,uuid,integer)"
CREDIT_STEP_REPLACEMENTS = (
    (
        "            v_target:=app.final_settlement_plan_id(v_step->'target_id')::uuid;\n",
        "            v_target:=app.final_settlement_plan_id(v_step->'target_id')::uuid;\n"
        "            -- Sub-slice 10e-2b-2: a correction's step on a placeholder line pays its real recovery\n"
        "            -- charge line (the shared step checked it against the placeholder first).\n"
        "            IF v_draft.kind='SETTLEMENT_CORRECTION' THEN\n"
        "                v_target:=app.settlement_correction_line_id(app.settlement_correction_id(p_draft),\n"
        "                    v_draft.payload->'plan_overlay'->'new_obligations',v_target); END IF;\n",
    ),
)

# The insert and deferred checks that match a correction's Credit or Deposit application with its
# plan step read the step's target through the placeholder mapping as well.
CREDIT_CHECK = (
    "app.assert_settlement_correction_credit_application(app.customer_credit_applications)"
)
CREDIT_CHECK_REPLACEMENTS = (
    (
        "                          WHERE line.id=app.final_settlement_plan_id(step->'target_id')::uuid\n",
        "                          -- Sub-slice 10e-2b-2: a placeholder line names its real recovery line.\n"
        "                          WHERE line.id=app.settlement_correction_line_id(v_correction.id,\n"
        "                              (SELECT draft.payload->'plan_overlay'->'new_obligations'\n"
        "                                  FROM app.financial_drafts draft WHERE draft.id=v_correction.correlation_id),\n"
        "                              app.final_settlement_plan_id(step->'target_id')::uuid)\n",
    ),
)

CREDIT_CONFIRMED = "app.assert_settlement_correction_credit_application_confirmed(app.customer_credit_applications)"
CREDIT_CONFIRMED_REPLACEMENTS = (
    (
        "            OR (v_step->>'target_kind'='INVOICE_LINE' AND v_detail.invoice_line_id::text\n"
        "                IS DISTINCT FROM app.final_settlement_plan_id(v_step->'target_id'))\n",
        "            -- Sub-slice 10e-2b-2: a placeholder line names its real recovery line.\n"
        "            OR (v_step->>'target_kind'='INVOICE_LINE' AND v_detail.invoice_line_id::text\n"
        "                IS DISTINCT FROM app.settlement_correction_line_id(v_correction.id,\n"
        "                    (SELECT draft.payload->'plan_overlay'->'new_obligations'\n"
        "                        FROM app.financial_drafts draft WHERE draft.id=v_correction.correlation_id),\n"
        "                    app.final_settlement_plan_id(v_step->'target_id')::uuid)::text)\n",
    ),
)

DEPOSIT_CHECK = "app.validate_deposit_application()"
DEPOSIT_CHECK_REPLACEMENTS = (
    (
        "                      AND app.final_settlement_plan_id(step->'target_id')\n"
        "                          =COALESCE(NEW.invoice_line_id,NEW.late_payment_charge_id)::text\n",
        "                      -- Sub-slice 10e-2b-2: a placeholder line names its real recovery line.\n"
        "                      AND app.settlement_correction_line_id(v_correction.id,\n"
        "                              draft.payload->'plan_overlay'->'new_obligations',\n"
        "                              app.final_settlement_plan_id(step->'target_id')::uuid)::text\n"
        "                          =COALESCE(NEW.invoice_line_id,NEW.late_payment_charge_id)::text\n",
    ),
)

PATCHES = (
    (TARGETS_CHECK, TARGETS_CHECK_REPLACEMENTS),
    (WRITER, WRITER_REPLACEMENTS),
    (RECORDER, RECORDER_REPLACEMENTS),
    (PLAN_RESULT, PLAN_RESULT_REPLACEMENTS),
    (PLAN_STEP, PLAN_STEP_REPLACEMENTS),
    (CREDIT_STEP, CREDIT_STEP_REPLACEMENTS),
    (CREDIT_CHECK, CREDIT_CHECK_REPLACEMENTS),
    (CREDIT_CONFIRMED, CREDIT_CONFIRMED_REPLACEMENTS),
    (DEPOSIT_CHECK, DEPOSIT_CHECK_REPLACEMENTS),
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
            raise RuntimeError(
                f"Deposit receipt correction recovery lines contract changed: {signature}"
            )
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
    raise RuntimeError("Deposit receipt correction recovery lines migration is forward-only")
