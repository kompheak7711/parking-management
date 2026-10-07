# ruff: noqa: E501
"""Post-settlement correction: the shared DL-032 step after closure (V1-056 sub-slice 10c-2a-2).

DL-032, BR-SETTLE-004, BR-SETTLE-005, BR-SETTLE-006, BR-SETTLE-008, BR-SETTLE-013, BR-SETTLE-017,
BR-CREDIT-006, BR-CREDIT-008, BR-CREDIT-014, BR-DEP-027, BR-REFUND-014, BR-REFUND-015, BR-AUTH-010;
owner answers 1 and 3 to Q-2026-10-07-41 and answers 1 and 2 to Q-2026-10-07-42.

Value a post-settlement correction releases or a Deposit holds again after closure is used under
the Settlement rules before anything is refunded: each Customer's own Credit pays that Customer's
open debt on the Lease first, then the Deposits pay the Lease's open debt in the DL-032 order, and
only the rest is refunded. The correction variants (sub-slices 10c-2a-3, 10c-2b and 10d) reuse this
step; none exists yet, so no role can reach it and every earlier result is unchanged.

- app.settlement_correction_plan_result (internal) checks a correction's DL-032 plan (the Settlement
  plan format) against the closed Settlement as the Settlement preview reads it, with an overlay of
  what the correction itself changes before the step, under the Settlement plan rules plus the
  correction rules: Credit before Deposits when a Deposit holds money (Q-42 answer 1), released
  Credit pays its own Customer's open debt before any Refund (Q-42 answer 2), and one Refund
  method, note, recipient and agreement per correction (Q-41 answer 3).
- app.lock_settlement_correction_plan (internal) takes the step's locks in the order of the
  Settlement confirm, the Lease row FOR UPDATE included (review round 2: the move-out inspection
  command locks it too, so an inspection cannot be superseded while the step runs);
  app.post_settlement_correction_plan (internal) runs the step inside its
  correction: the check again on the real state, then the Credit applications (the 8e-2 writer
  with a correction link, Q-42 answer 1), the Deposit applications and the Deposit Refunds, each
  linked to the correction before it is written.
- Relaxing: the 8e-2 Credit application checks, the Deposit application check and the 8d Deposit
  Refund source check accept a correction's own record (linked to a correction of the Settlement
  confirmed in this transaction, by its approver); app.settlement_correction_refund_details gains
  deposit_id and signer_agreement (Q-41 answer 3). Every other record stays refused after closure.
"""

from alembic import op
from sqlalchemy import text

revision = "20261106_102"
down_revision = "20261105_101"
branch_labels = None
depends_on = None

INTERNAL = (
    "app.settlement_correction_overlay_amount(jsonb)",
    "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)",
    "app.settlement_correction_credit_id(uuid,uuid)",
    "app.lock_settlement_correction_plan(uuid)",
    "app.assert_settlement_correction_credit_application(app.customer_credit_applications)",
    "app.assert_settlement_correction_credit_application_confirmed(app.customer_credit_applications)",
    "app.assert_settlement_correction_deposit_refund_source(app.refunds)",
    "app.post_settlement_correction_deposit_refund(uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid,text,text,text)",
    "app.post_settlement_correction_plan(uuid,uuid,uuid)",
)

CREDIT_WRITER = "app.post_final_settlement_credit_application(uuid,uuid,uuid,uuid,integer)"
CREDIT_WRITER_REPLACEMENTS = (
    (
        "            WHERE id=p_draft AND property_id=p_property AND kind='FINAL_SETTLEMENT'\n"
        "              AND payload->>'final_settlement_id'=p_settlement::text;\n",
        "            WHERE id=p_draft AND property_id=p_property AND kind IN ('FINAL_SETTLEMENT','SETTLEMENT_CORRECTION')\n"
        "              AND payload->>'final_settlement_id'=p_settlement::text;\n",
    ),
    (
        "            v_step:=v_draft.payload->'steps'->(p_step-1);\n",
        "            -- A post-settlement correction keeps its DL-032 steps in its plan (sub-slice 10c-2a-2).\n"
        "            v_step:=(CASE WHEN v_draft.kind='FINAL_SETTLEMENT' THEN v_draft.payload->'steps'\n"
        "                ELSE v_draft.payload->'plan'->'steps' END)->(p_step-1);\n",
    ),
    (
        "            v_credit:=app.final_settlement_plan_id(v_step->'customer_credit_id')::uuid;\n",
        "            v_credit:=app.final_settlement_plan_id(v_step->'customer_credit_id')::uuid;\n"
        "            -- A correction's plan key may name the Credit that value released by the same correction\n"
        "            -- became (BR-CREDIT-014; sub-slice 10c-2a-2).\n"
        "            IF v_draft.kind='SETTLEMENT_CORRECTION' THEN\n"
        "                v_credit:=app.settlement_correction_credit_id(p_draft,v_credit); END IF;\n",
    ),
    (
        "            v_id:=app.final_settlement_credit_application_id(p_draft,p_step);\n",
        "            -- A Settlement step's id is derived from its draft; a correction's record gets a fresh id,\n"
        "            -- linked to the correction before it is written (sub-slices 10a and 10b).\n"
        "            IF v_draft.kind='FINAL_SETTLEMENT' THEN\n"
        "                v_id:=app.final_settlement_credit_application_id(p_draft,p_step);\n"
        "            ELSE\n"
        "                v_id:=gen_random_uuid();\n"
        "                PERFORM app.link_settlement_correction_effect(app.settlement_correction_id(p_draft),\n"
        "                    'customer_credit_application_id',v_id);\n"
        "            END IF;\n",
    ),
)

CREDIT_SOURCE = "app.assert_final_settlement_credit_application_source()"
CREDIT_SOURCE_REPLACEMENTS = (
    (
        "            SELECT * INTO v_settlement FROM app.final_settlements WHERE id=NEW.final_settlement_id FOR UPDATE;\n"
        "            IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='23503'; END IF;\n",
        "            SELECT * INTO v_settlement FROM app.final_settlements WHERE id=NEW.final_settlement_id FOR UPDATE;\n"
        "            IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='23503'; END IF;\n"
        "            -- A post-settlement correction's own Credit application (sub-slice 10c-2a-2; owner answer 1\n"
        "            -- to Q-2026-10-07-42): linked, before it is written, to a correction of this Settlement\n"
        "            -- confirmed in this transaction.\n"
        "            IF app.settlement_correction_linked(v_settlement.id,'customer_credit_applications',NEW.id) THEN\n"
        "                PERFORM app.assert_settlement_correction_credit_application(NEW);\n"
        "                RETURN NEW;\n"
        "            END IF;\n",
    ),
)

CREDIT_CONFIRMED = "app.assert_final_settlement_credit_application_confirmed()"
CREDIT_CONFIRMED_REPLACEMENTS = (
    (
        "        BEGIN\n"
        "            SELECT draft.id,step.value INTO v_draft,v_step\n"
        "            FROM app.final_settlements settlement\n",
        "        BEGIN\n"
        "            -- A post-settlement correction's own Credit application (sub-slice 10c-2a-2).\n"
        "            IF EXISTS(SELECT 1 FROM app.settlement_correction_effects effect\n"
        "                WHERE effect.customer_credit_application_id=NEW.id) THEN\n"
        "                PERFORM app.assert_settlement_correction_credit_application_confirmed(NEW);\n"
        "                RETURN NULL;\n"
        "            END IF;\n"
        "            SELECT draft.id,step.value INTO v_draft,v_step\n"
        "            FROM app.final_settlements settlement\n",
    ),
)

DEPOSIT_APPLICATION = "app.validate_deposit_application()"
DEPOSIT_APPLICATION_REPLACEMENTS = (
    (
        "            v_last_order integer; v_last_rank integer; v_rank integer;\n",
        "            v_last_order integer; v_last_rank integer; v_rank integer;\n"
        "            v_correction app.settlement_corrections%ROWTYPE;\n",
    ),
    (
        "            IF v_settlement.closed_at IS NOT NULL THEN\n"
        "                RAISE EXCEPTION 'A closed Final Settlement takes no new Deposit application' USING ERRCODE='55000'; END IF;\n"
        "            -- BR-SETTLE-008: every Deposit application is recorded before the remaining Deposit\n"
        "            -- balances are refunded (sub-slice 8d).\n"
        "            IF EXISTS(SELECT 1 FROM app.final_settlement_refund_details detail\n"
        "                WHERE detail.final_settlement_id=NEW.final_settlement_id) THEN\n"
        "                RAISE EXCEPTION 'Deposit applications are recorded before the Final Settlement Refunds'\n"
        "                    USING ERRCODE='55000'; END IF;\n",
        "            -- A post-settlement correction's own Deposit application (DL-032 after closure; sub-slice\n"
        "            -- 10c-2a-2, owner answer 1 to Q-2026-10-07-41): linked, before it is written, to a\n"
        "            -- correction of this Settlement confirmed in this transaction; written by its approver,\n"
        "            -- not before it, and before that correction's Refunds.\n"
        "            IF app.settlement_correction_linked(NEW.final_settlement_id,'deposit_applications',NEW.id) THEN\n"
        "                SELECT correction.* INTO v_correction FROM app.settlement_correction_effects effect\n"
        "                JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id\n"
        "                WHERE effect.deposit_application_id=NEW.id;\n"
        "                IF NEW.actor_id IS DISTINCT FROM v_correction.actor_id\n"
        "                    OR NEW.occurred_at IS NULL OR NEW.occurred_at<v_correction.occurred_at\n"
        "                THEN RAISE EXCEPTION 'A post-settlement correction Deposit application is written by the correction''s approver, after it'\n"
        "                    USING ERRCODE='23514'; END IF;\n"
        "                IF EXISTS(SELECT 1 FROM app.settlement_correction_effects effect\n"
        "                    WHERE effect.settlement_correction_id=v_correction.id AND effect.refund_id IS NOT NULL) THEN\n"
        "                    RAISE EXCEPTION 'Deposit applications are recorded before the correction''s Refunds'\n"
        "                        USING ERRCODE='55000'; END IF;\n"
        "                -- BR-AUTH-010: a Deposit step of that correction's plan, exactly as prepared, each\n"
        "                -- step at most once (review round 1).\n"
        "                IF NOT EXISTS(SELECT 1 FROM app.financial_drafts draft\n"
        "                    CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(draft.payload->'plan'->'steps')='array'\n"
        "                        THEN draft.payload->'plan'->'steps' ELSE '[]'::jsonb END) step\n"
        "                    WHERE draft.id=v_correction.correlation_id\n"
        "                      AND step->>'kind'=CASE NEW.application_stage WHEN 'PET_RELATED_FIRST' THEN 'PET_DEPOSIT_PET_DAMAGE'\n"
        "                          WHEN 'SECURITY_EXPLICIT' THEN 'SECURITY_DEPOSIT' ELSE 'PET_DEPOSIT_REMAINDER' END\n"
        "                      AND app.final_settlement_plan_id(step->'deposit_id')=NEW.deposit_id::text\n"
        "                      AND step->>'target_kind'=NEW.target_kind\n"
        "                      AND app.final_settlement_plan_id(step->'target_id')\n"
        "                          =COALESCE(NEW.invoice_line_id,NEW.late_payment_charge_id)::text\n"
        "                      AND step->>'amount_usd_cents'=NEW.amount_usd_cents::text\n"
        "                    HAVING count(*)>(SELECT count(*) FROM app.deposit_applications application\n"
        "                        JOIN app.settlement_correction_effects effect ON effect.deposit_application_id=application.id\n"
        "                        WHERE effect.settlement_correction_id=v_correction.id\n"
        "                          AND application.deposit_id=NEW.deposit_id\n"
        "                          AND application.application_stage=NEW.application_stage\n"
        "                          AND application.target_kind=NEW.target_kind\n"
        "                          AND COALESCE(application.invoice_line_id,application.late_payment_charge_id)\n"
        "                              =COALESCE(NEW.invoice_line_id,NEW.late_payment_charge_id)\n"
        "                          AND application.amount_usd_cents=NEW.amount_usd_cents))\n"
        "                THEN RAISE EXCEPTION 'A post-settlement correction Deposit application must be a Deposit step of its correction, once'\n"
        "                    USING ERRCODE='23514'; END IF;\n"
        "            ELSE\n"
        "            IF v_settlement.closed_at IS NOT NULL THEN\n"
        "                RAISE EXCEPTION 'A closed Final Settlement takes no new Deposit application' USING ERRCODE='55000'; END IF;\n"
        "            -- BR-SETTLE-008: every Deposit application is recorded before the remaining Deposit\n"
        "            -- balances are refunded (sub-slice 8d).\n"
        "            IF EXISTS(SELECT 1 FROM app.final_settlement_refund_details detail\n"
        "                WHERE detail.final_settlement_id=NEW.final_settlement_id) THEN\n"
        "                RAISE EXCEPTION 'Deposit applications are recorded before the Final Settlement Refunds'\n"
        "                    USING ERRCODE='55000'; END IF;\n"
        "            END IF;\n",
    ),
    (
        "            FROM app.deposit_applications application WHERE application.final_settlement_id=NEW.final_settlement_id;\n"
        "            IF NEW.application_order<=COALESCE(v_last_order,0) OR v_rank<COALESCE(v_last_rank,1) THEN\n",
        "            FROM app.deposit_applications application WHERE application.final_settlement_id=NEW.final_settlement_id;\n"
        "            -- In a correction the DL-032 stage order holds within that correction; the order numbers\n"
        "            -- still follow the Settlement's last (sub-slice 10c-2a-2).\n"
        "            IF v_correction.id IS NOT NULL THEN\n"
        "                SELECT max(CASE application.application_stage WHEN 'PET_RELATED_FIRST' THEN 1\n"
        "                        WHEN 'SECURITY_EXPLICIT' THEN 2 ELSE 3 END) INTO v_last_rank\n"
        "                FROM app.deposit_applications application\n"
        "                JOIN app.settlement_correction_effects effect ON effect.deposit_application_id=application.id\n"
        "                WHERE effect.settlement_correction_id=v_correction.id;\n"
        "            END IF;\n"
        "            IF NEW.application_order<=COALESCE(v_last_order,0) OR v_rank<COALESCE(v_last_rank,1) THEN\n",
    ),
)

REFUND_SOURCE = "app.assert_final_settlement_refund_source(app.refunds)"
REFUND_SOURCE_REPLACEMENTS = (
    (
        "            -- The Settlement link is recorded first (deferred key); without it a Deposit Refund has\n"
        "            -- no source context.\n",
        "            -- A post-settlement correction's own Deposit Refund (sub-slice 10c-2a-2; owner answer 3 to\n"
        "            -- Q-2026-10-07-41): its correction details row names the Deposit.\n"
        "            IF EXISTS(SELECT 1 FROM app.settlement_correction_refund_details correction_detail\n"
        "                WHERE correction_detail.refund_id=p_refund.id AND correction_detail.deposit_id IS NOT NULL) THEN\n"
        "                PERFORM app.assert_settlement_correction_deposit_refund_source(p_refund);\n"
        "                RETURN;\n"
        "            END IF;\n"
        "            -- The Settlement link is recorded first (deferred key); without it a Deposit Refund has\n"
        "            -- no source context.\n",
    ),
)

REFUND_DETAIL = "app.assert_settlement_correction_refund_detail()"
REFUND_DETAIL_REPLACEMENTS = (
    (
        "        THEN RAISE EXCEPTION 'A post-settlement correction Refund is processed by the correction''s approver'\n"
        "            USING ERRCODE='42501'; END IF;\n",
        "        THEN RAISE EXCEPTION 'A post-settlement correction Refund is processed by the correction''s approver'\n"
        "            USING ERRCODE='42501'; END IF;\n"
        "        -- The details name the Refund's own Deposit, and no Deposit for a Credit Refund (sub-slice\n"
        "        -- 10c-2a-2, review round 1).\n"
        "        IF NOT EXISTS(SELECT 1 FROM app.refunds refund\n"
        "            WHERE refund.id=NEW.refund_id AND refund.source_deposit_id IS NOT DISTINCT FROM NEW.deposit_id)\n"
        "        THEN RAISE EXCEPTION 'A post-settlement correction Refund detail names its Refund''s own Deposit'\n"
        "            USING ERRCODE='23514'; END IF;\n",
    ),
)

CREDIT_REFUND_ALLOWED = "app.settlement_correction_refund_allowed(app.refunds)"
CREDIT_REFUND_ALLOWED_REPLACEMENTS = (
    (
        "            WHERE detail.refund_id=(p_refund).id),false)\n",
        "            -- A Credit Refund's details name no Deposit (sub-slice 10c-2a-2).\n"
        "            WHERE detail.refund_id=(p_refund).id AND detail.deposit_id IS NULL),false)\n",
    ),
)

STEP_SQL = """
    -- Owner answer 3 to Q-2026-10-07-41: a correction's Deposit Refund keeps its Deposit and the
    -- written agreement of all Signers (BR-REFUND-015) in its details row, as sub-slice 8d does.
    ALTER TABLE app.settlement_correction_refund_details
        ADD COLUMN deposit_id uuid REFERENCES app.deposits(id) ON DELETE RESTRICT,
        ADD COLUMN signer_agreement text
            CHECK (signer_agreement IS NULL
                OR (signer_agreement=btrim(signer_agreement) AND length(signer_agreement) BETWEEN 1 AND 2000)),
        ADD CONSTRAINT settlement_correction_refund_details_agreement_deposit
            CHECK (signer_agreement IS NULL OR deposit_id IS NOT NULL),
        -- Each Deposit is refunded at most once per correction (as 8d's once per Settlement; review
        -- round 1). Credit Refunds name no Deposit.
        ADD CONSTRAINT settlement_correction_refund_details_once_per_deposit
            UNIQUE (settlement_correction_id,deposit_id);
    CREATE INDEX settlement_correction_refund_details_deposit_idx
        ON app.settlement_correction_refund_details(deposit_id) WHERE deposit_id IS NOT NULL;

    -- An overlay amount: a JSON integer from 0 to 9,000,000,000,000,000 cents.
    CREATE FUNCTION app.settlement_correction_overlay_amount(p_value jsonb)
    RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
        SELECT COALESCE(jsonb_typeof(p_value)='number' AND p_value::text ~ '^(0|[1-9][0-9]{0,15})$'
            AND p_value::text::numeric<=9000000000000000,false)
    $$;

    -- Checks a post-settlement correction's DL-032 plan and returns what its draft records. The plan
    -- has the Settlement plan format (sub-slice 8c). The state is the closed Settlement as the
    -- Settlement preview reads it, with the overlay of what the correction itself changes before the
    -- step (obligations: what each owes after the release; credits: the value each released Credit
    -- gains, keyed by the Credit, or by the released Payment allocation whose value becomes a new
    -- Credit, BR-CREDIT-014; deposits: the value each Deposit gets back). A Deposit in the overlay
    -- follows DL-032 (the variant's release guarantees it; the confirm checks the real state).
    -- The rules are the Settlement plan's (owner answer 1 to Q-2026-10-07-41), plus: when a Deposit
    -- holds money, each Customer's Credit pays that Customer's open debt before any Deposit (Q-42
    -- answer 1); a released Credit with value left needs its Customer to owe nothing on the Lease
    -- (Q-42 answer 2); one Refund method, note, recipient and agreement (Q-41 answer 3). Of the
    -- preview's blocking issues only a pending draft refuses: the others describe the closure, which
    -- the 8e-1 refusals keep. Malformed input 22023; a plan or state the correction does not allow
    -- 55000. Everything, the source revision included, is read in one STABLE call.
    CREATE FUNCTION app.settlement_correction_plan_result(p_property uuid,p_actor uuid,p_settlement uuid,
        p_plan jsonb,p_overlay jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_preview jsonb; v_open jsonb; v_open_start jsonb;
        v_owner jsonb; v_pet text[]; v_credit jsonb; v_credit_start jsonb; v_credit_owner jsonb;
        v_held jsonb:='{}'::jsonb; v_type jsonb:='{}'::jsonb; v_left jsonb; v_used_credit jsonb:='{}'::jsonb;
        v_invoice_of jsonb; v_first uuid; v_refund jsonb:='{}'::jsonb; v_step_five boolean:=false;
        v_chosen_by text; v_primary uuid; v_lease uuid; v_item jsonb; v_step integer; v_last integer:=0;
        v_amount bigint; v_key text; v_target_left bigint; v_credit_id text; v_deposit text;
        v_pet_after_three bigint; v_basis jsonb; v_closing bigint; v_keys text[]; v_expected text[];
        v_method text; v_recipient text; v_security_at_five bigint; v_released jsonb:='{}'::jsonb;
        v_entry record; v_customer uuid; v_invoice uuid; v_line uuid; v_may_use jsonb;
    BEGIN
        IF p_plan IS NULL OR jsonb_typeof(p_plan)<>'object'
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_plan) key WHERE key NOT IN ('steps','pet_remainder'))
            OR jsonb_typeof(p_plan->'steps') IS DISTINCT FROM 'array'
            OR jsonb_array_length(p_plan->'steps')>200
            OR COALESCE(jsonb_typeof(p_plan->'pet_remainder'),'null') NOT IN ('null','object')
        THEN RAISE EXCEPTION 'Post-settlement correction plan is invalid' USING ERRCODE='22023'; END IF;
        IF p_overlay IS NULL OR jsonb_typeof(p_overlay)<>'object'
            OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(p_overlay) key)
                IS DISTINCT FROM ARRAY['credits','deposits','obligations']
            OR jsonb_typeof(p_overlay->'obligations') IS DISTINCT FROM 'object'
            OR jsonb_typeof(p_overlay->'credits') IS DISTINCT FROM 'object'
            OR jsonb_typeof(p_overlay->'deposits') IS DISTINCT FROM 'object'
            OR EXISTS(SELECT 1 FROM jsonb_each(p_overlay->'obligations') item
                WHERE split_part(item.key,':',1) NOT IN ('INVOICE_LINE','LATE_PAYMENT_CHARGE')
                   OR app.final_settlement_plan_id(to_jsonb(substr(item.key,strpos(item.key,':')+1)))
                       IS DISTINCT FROM substr(item.key,strpos(item.key,':')+1)
                   OR NOT app.settlement_correction_overlay_amount(item.value))
            OR EXISTS(SELECT 1 FROM jsonb_each(p_overlay->'credits') item
                WHERE app.final_settlement_plan_id(to_jsonb(item.key)) IS DISTINCT FROM item.key
                   OR jsonb_typeof(item.value) IS DISTINCT FROM 'object'
                   OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(item.value) key)
                       IS DISTINCT FROM ARRAY['add_usd_cents','customer_id','released_payment_allocation_id']
                   OR app.final_settlement_plan_id(item.value->'customer_id') IS NULL
                   OR NOT app.settlement_correction_overlay_amount(item.value->'add_usd_cents')
                   OR (jsonb_typeof(item.value->'released_payment_allocation_id') IS DISTINCT FROM 'null'
                       AND app.final_settlement_plan_id(item.value->'released_payment_allocation_id')
                           IS DISTINCT FROM item.key))
            OR EXISTS(SELECT 1 FROM jsonb_each(p_overlay->'deposits') item
                WHERE app.final_settlement_plan_id(to_jsonb(item.key)) IS DISTINCT FROM item.key
                   OR NOT app.settlement_correction_overlay_amount(item.value))
        THEN RAISE EXCEPTION 'Post-settlement correction overlay is invalid' USING ERRCODE='22023'; END IF;
        SELECT * INTO v_settlement FROM app.final_settlements WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement' USING ERRCODE='55000'; END IF;
        v_preview:=app.final_settlement_preview(p_property,p_actor,p_settlement,ARRAY['final_settlements.prepare']);
        -- The owner's 8r rule and the Settlement's pending-draft rule: no step while a forfeiture,
        -- reversal, Refund or Payment move draft waits on a Settlement source.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_preview->'blocking_issues') issue
            WHERE issue->>'code'='PENDING_DRAFT')
        THEN RAISE EXCEPTION 'A draft on a source of this Final Settlement is waiting' USING ERRCODE='55000'; END IF;
        v_lease:=(v_preview->'lease'->>'lease_id')::uuid;
        v_primary:=(v_preview->'lease'->>'primary_tenant_id')::uuid;
        v_chosen_by:=v_preview->'steps'->4->>'chosen_by';
        -- What each obligation still owes, who is named on it, and which lines are pet damage.
        SELECT COALESCE(jsonb_object_agg(item.key,item.amount),'{}'::jsonb),
            COALESCE(jsonb_object_agg(item.key,item.customer),'{}'::jsonb),
            COALESCE(array_agg(item.key) FILTER (WHERE item.pet),'{}'::text[]),
            COALESCE(jsonb_object_agg(item.key,item.invoice) FILTER (WHERE item.invoice IS NOT NULL),
                '{}'::jsonb)
        INTO v_open,v_owner,v_pet,v_invoice_of
        FROM (SELECT 'INVOICE_LINE:'||(line->>'invoice_line_id') AS key,
                (line->>'outstanding_usd_cents')::bigint AS amount,line->>'customer_id' AS customer,
                (line->>'pet_damage')::boolean AS pet,line->>'invoice_id' AS invoice
            FROM jsonb_array_elements(v_preview->'customers') person,
                jsonb_array_elements(person->'invoice_lines') line
            UNION ALL
            SELECT 'LATE_PAYMENT_CHARGE:'||(charge->>'late_payment_charge_id'),
                (charge->>'remaining_usd_cents')::bigint,charge->>'customer_id',false,NULL
            FROM jsonb_array_elements(v_preview->'customers') person,
                jsonb_array_elements(person->'late_payment_charges') charge) item;
        -- The overlay's obligations: what each owes after the correction's own release.
        FOR v_entry IN SELECT item.key,item.value FROM jsonb_each(p_overlay->'obligations') item LOOP
            IF NOT v_owner ? v_entry.key THEN
                IF split_part(v_entry.key,':',1)='INVOICE_LINE' THEN
                    SELECT line.id,invoice.id,invoice.customer_id INTO v_line,v_invoice,v_customer
                    FROM app.invoice_lines line JOIN app.invoices invoice ON invoice.id=line.invoice_id
                    WHERE line.id=split_part(v_entry.key,':',2)::uuid AND invoice.lease_id=v_lease
                      AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID');
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'The overlay names an obligation outside this Final Settlement'
                            USING ERRCODE='55000'; END IF;
                    v_invoice_of:=v_invoice_of||jsonb_build_object(v_entry.key,v_invoice);
                    IF app.invoice_line_is_pet_damage(v_line,v_lease) THEN v_pet:=v_pet||v_entry.key; END IF;
                ELSE
                    SELECT charge.customer_id INTO v_customer FROM app.late_payment_charges charge
                    JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                    WHERE charge.id=split_part(v_entry.key,':',2)::uuid AND invoice.lease_id=v_lease;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'The overlay names an obligation outside this Final Settlement'
                            USING ERRCODE='55000'; END IF;
                END IF;
                v_owner:=v_owner||jsonb_build_object(v_entry.key,v_customer);
            END IF;
            v_open:=v_open||jsonb_build_object(v_entry.key,(v_entry.value#>>'{}')::bigint);
        END LOOP;
        v_open_start:=v_open;
        SELECT COALESCE(jsonb_object_agg(credit->>'customer_credit_id',credit->'available_usd_cents'),'{}'::jsonb),
            COALESCE(jsonb_object_agg(credit->>'customer_credit_id',person->'customer_id'),'{}'::jsonb)
        INTO v_credit,v_credit_owner
        FROM jsonb_array_elements(v_preview->'customers') person,jsonb_array_elements(person->'credits') credit;
        -- The overlay's Credits: an existing Credit of that Customer that gets value back, or the value a
        -- released Payment allocation on an Invoice of this Lease becomes, Credit of that Invoice's
        -- Customer (BR-CREDIT-014). Each pays only its own Customer's obligations (BR-CREDIT-008).
        FOR v_entry IN SELECT item.key,item.value FROM jsonb_each(p_overlay->'credits') item LOOP
            v_customer:=(v_entry.value->>'customer_id')::uuid;
            IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v_preview->'customers') person
                WHERE (person->>'customer_id')::uuid=v_customer)
                OR (jsonb_typeof(v_entry.value->'released_payment_allocation_id')='null' AND NOT EXISTS(
                    SELECT 1 FROM app.customer_credits credit JOIN app.payments payment ON payment.id=credit.source_payment_id
                    WHERE credit.id=v_entry.key::uuid AND credit.customer_id=v_customer
                      AND payment.property_id=p_property))
                OR (jsonb_typeof(v_entry.value->'released_payment_allocation_id')<>'null' AND (NOT EXISTS(
                    SELECT 1 FROM app.payment_allocations allocation
                    JOIN app.invoices invoice ON invoice.id=allocation.invoice_id
                    WHERE allocation.id=v_entry.key::uuid AND invoice.lease_id=v_lease
                      AND invoice.customer_id=v_customer)
                    OR EXISTS(SELECT 1 FROM app.customer_credits credit WHERE credit.id=v_entry.key::uuid)))
            THEN RAISE EXCEPTION 'The overlay names a Customer Credit outside this Final Settlement'
                USING ERRCODE='55000'; END IF;
            v_credit:=v_credit||jsonb_build_object(v_entry.key,
                COALESCE((v_credit->>v_entry.key)::bigint,0)+(v_entry.value->>'add_usd_cents')::bigint);
            v_credit_owner:=v_credit_owner||jsonb_build_object(v_entry.key,v_customer);
            v_released:=v_released||jsonb_build_object(v_entry.key,v_customer);
        END LOOP;
        v_credit_start:=v_credit;
        -- Only a Deposit that follows DL-032 and holds money (after the overlay) may be applied or
        -- refunded.
        SELECT COALESCE(jsonb_object_agg(deposit->>'deposit_id',deposit->'held_usd_cents'),'{}'::jsonb),
            COALESCE(jsonb_object_agg(deposit->>'deposit_id',deposit->'deposit_type'),'{}'::jsonb)
        INTO v_held,v_type
        FROM jsonb_array_elements(v_preview->'deposits') deposit
        WHERE deposit->>'path'='DL_032' AND (deposit->>'held_usd_cents')::bigint>0;
        FOR v_entry IN SELECT item.key,item.value FROM jsonb_each(p_overlay->'deposits') item LOOP
            SELECT deposit INTO v_item FROM jsonb_array_elements(v_preview->'deposits') deposit
            WHERE deposit->>'deposit_id'=v_entry.key;
            IF v_item IS NULL THEN
                RAISE EXCEPTION 'The overlay names a Deposit outside this Final Settlement' USING ERRCODE='55000';
            END IF;
            v_held:=v_held||jsonb_build_object(v_entry.key,
                (v_item->>'held_usd_cents')::bigint+(v_entry.value#>>'{}')::bigint);
            v_type:=v_type||jsonb_build_object(v_entry.key,v_item->'deposit_type');
            v_item:=NULL;
        END LOOP;
        SELECT COALESCE(jsonb_object_agg(item.key,item.value),'{}'::jsonb) INTO v_held
        FROM jsonb_each(v_held) item WHERE (item.value#>>'{}')::bigint>0;
        v_left:=v_held;

        -- The Settlement plan's step loop (sub-slice 8c, with the 8d rule for step 5).
        FOR v_item IN SELECT value FROM jsonb_array_elements(p_plan->'steps') LOOP
            v_step:=CASE WHEN jsonb_typeof(v_item)='object' THEN CASE v_item->>'kind'
                WHEN 'CUSTOMER_CREDIT' THEN 2 WHEN 'PET_DEPOSIT_PET_DAMAGE' THEN 3
                WHEN 'SECURITY_DEPOSIT' THEN 4 WHEN 'PET_DEPOSIT_REMAINDER' THEN 5
                WHEN 'DEPOSIT_REFUNDS' THEN 7 END END;
            IF v_step IS NULL THEN
                RAISE EXCEPTION 'Post-settlement correction step kind is invalid' USING ERRCODE='22023'; END IF;
            IF v_step<v_last THEN
                RAISE EXCEPTION 'Post-settlement correction steps must follow the DL-032 order' USING ERRCODE='22023'; END IF;
            IF v_step>3 AND v_pet_after_three IS NULL THEN
                SELECT COALESCE(sum((v_open->>key)::bigint),0) INTO v_pet_after_three FROM unnest(v_pet) key;
            END IF;
            v_last:=v_step;
            SELECT array_agg(key ORDER BY key) INTO v_keys FROM jsonb_object_keys(v_item) key;
            v_expected:=CASE WHEN v_step=2
                THEN ARRAY['amount_usd_cents','customer_credit_id','customer_designation','kind','target_id',
                    'target_kind']
                WHEN v_step<7 THEN ARRAY['amount_usd_cents','deposit_id','kind','target_id','target_kind']
                ELSE ARRAY['amount_usd_cents','deposit_id','kind','recipient_customer_id','reference_note',
                    'refund_method_id','signer_agreement'] END;
            IF v_keys IS DISTINCT FROM v_expected
                OR jsonb_typeof(v_item->'amount_usd_cents') IS DISTINCT FROM 'number'
                OR (v_item->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
            THEN RAISE EXCEPTION 'Post-settlement correction step is invalid' USING ERRCODE='22023'; END IF;
            v_amount:=(v_item->>'amount_usd_cents')::bigint;
            IF v_amount>9000000000000000 THEN
                RAISE EXCEPTION 'Post-settlement correction step is invalid' USING ERRCODE='22023'; END IF;
            IF v_step<7 THEN
                IF COALESCE(v_item->>'target_kind','') NOT IN ('INVOICE_LINE','LATE_PAYMENT_CHARGE')
                    OR app.final_settlement_plan_id(v_item->'target_id') IS NULL
                    OR app.final_settlement_plan_id(v_item->CASE WHEN v_step=2 THEN 'customer_credit_id'
                        ELSE 'deposit_id' END) IS NULL
                THEN RAISE EXCEPTION 'Post-settlement correction step is invalid' USING ERRCODE='22023'; END IF;
                v_key:=(v_item->>'target_kind')||':'||app.final_settlement_plan_id(v_item->'target_id');
                v_target_left:=(v_open->>v_key)::bigint;
                IF v_target_left IS NULL THEN
                    RAISE EXCEPTION 'The target is not an open obligation of this Final Settlement'
                        USING ERRCODE='55000'; END IF;
                IF v_amount>v_target_left THEN
                    RAISE EXCEPTION 'The amount exceeds what the obligation still owes' USING ERRCODE='55000';
                END IF;
                IF v_step=2 THEN
                    v_credit_id:=app.final_settlement_plan_id(v_item->'customer_credit_id');
                    IF NOT v_credit ? v_credit_id THEN
                        RAISE EXCEPTION 'The Customer Credit is not available to this Final Settlement'
                            USING ERRCODE='55000'; END IF;
                    -- BR-CREDIT-008: a Customer's Credit pays only that Customer's obligations.
                    IF v_owner->>v_key IS DISTINCT FROM v_credit_owner->>v_credit_id THEN
                        RAISE EXCEPTION 'A Customer Credit pays only its own Customer''s obligations'
                            USING ERRCODE='55000'; END IF;
                    IF v_amount>(v_credit->>v_credit_id)::bigint THEN
                        RAISE EXCEPTION 'The amount exceeds the available Customer Credit' USING ERRCODE='55000';
                    END IF;
                    -- BR-CREDIT-006: the Customer's designation as text, or on an Invoice with Rent or
                    -- Service lines the Rent-first proposal order.
                    IF jsonb_typeof(v_item->'customer_designation') NOT IN ('null','string')
                        OR (jsonb_typeof(v_item->'customer_designation')='string'
                            AND app.lease_notice_text_valid(v_item->>'customer_designation',500) IS NOT TRUE)
                    THEN RAISE EXCEPTION 'Post-settlement correction step is invalid' USING ERRCODE='22023'; END IF;
                    IF jsonb_typeof(v_item->'customer_designation')='null' AND v_invoice_of ? v_key THEN
                        v_first:=app.final_settlement_rent_first_line((v_invoice_of->>v_key)::uuid,v_open);
                        IF v_first IS NOT NULL AND 'INVOICE_LINE:'||v_first::text<>v_key THEN
                            RAISE EXCEPTION 'Credit on an Invoice with Rent or Service lines follows the Rent-first proposal unless the Customer designated the line'
                                USING ERRCODE='55000'; END IF;
                    END IF;
                    v_credit:=jsonb_set(v_credit,ARRAY[v_credit_id],
                        to_jsonb((v_credit->>v_credit_id)::bigint-v_amount));
                    v_used_credit:=jsonb_set(v_used_credit,ARRAY[v_owner->>v_key],
                        to_jsonb(COALESCE((v_used_credit->>(v_owner->>v_key))::bigint,0)+v_amount));
                ELSE
                    v_deposit:=app.final_settlement_plan_id(v_item->'deposit_id');
                    IF NOT v_left ? v_deposit THEN
                        RAISE EXCEPTION 'Only a Deposit that follows DL-032 and holds money may be applied'
                            USING ERRCODE='55000'; END IF;
                    IF v_type->>v_deposit IS DISTINCT FROM (CASE v_step WHEN 4 THEN 'SECURITY' ELSE 'PET' END) THEN
                        RAISE EXCEPTION 'The Deposit type does not match the DL-032 step' USING ERRCODE='55000';
                    END IF;
                    IF v_step=3 AND NOT v_key=ANY(v_pet) THEN
                        RAISE EXCEPTION 'The Pet Deposit first pays only valid pet damage' USING ERRCODE='55000';
                    END IF;
                    IF v_amount>(v_left->>v_deposit)::bigint THEN
                        RAISE EXCEPTION 'The amount exceeds what the Deposit holds' USING ERRCODE='55000'; END IF;
                    v_left:=jsonb_set(v_left,ARRAY[v_deposit],to_jsonb((v_left->>v_deposit)::bigint-v_amount));
                    v_step_five:=v_step_five OR v_step=5;
                    -- What the Security Deposit still holds when step 5 starts (8d).
                    IF v_step=5 AND v_security_at_five IS NULL THEN
                        SELECT COALESCE(sum(item.value::bigint),0) INTO v_security_at_five
                        FROM jsonb_each_text(v_left) item WHERE v_type->>item.key='SECURITY';
                    END IF;
                END IF;
                v_open:=jsonb_set(v_open,ARRAY[v_key],to_jsonb(v_target_left-v_amount));
            ELSE
                v_deposit:=app.final_settlement_plan_id(v_item->'deposit_id');
                v_method:=app.final_settlement_plan_id(v_item->'refund_method_id');
                v_recipient:=app.final_settlement_plan_id(v_item->'recipient_customer_id');
                IF v_deposit IS NULL OR v_method IS NULL OR v_recipient IS NULL
                    OR jsonb_typeof(v_item->'reference_note') IS DISTINCT FROM 'string'
                    OR app.lease_notice_text_valid(v_item->>'reference_note',500) IS NOT TRUE
                    OR jsonb_typeof(v_item->'signer_agreement') NOT IN ('null','string')
                    OR (jsonb_typeof(v_item->'signer_agreement')='string'
                        AND app.lease_notice_text_valid(v_item->>'signer_agreement',2000) IS NOT TRUE)
                THEN RAISE EXCEPTION 'Post-settlement correction Refund step is invalid' USING ERRCODE='22023'; END IF;
                IF v_refund ? v_deposit THEN
                    RAISE EXCEPTION 'A Deposit has at most one Refund in a post-settlement correction'
                        USING ERRCODE='22023'; END IF;
                IF NOT v_left ? v_deposit THEN
                    RAISE EXCEPTION 'Only a Deposit that follows DL-032 and holds money may be refunded'
                        USING ERRCODE='55000'; END IF;
                IF v_amount>(v_left->>v_deposit)::bigint THEN
                    RAISE EXCEPTION 'The amount exceeds what the Deposit holds' USING ERRCODE='55000'; END IF;
                -- BR-REFUND-014: an active Refund method.
                PERFORM 1 FROM app.refund_methods WHERE id=v_method::uuid AND active;
                IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
                -- BR-REFUND-015: the Primary Tenant, or another signed Signer with the written
                -- agreement of all Signers.
                IF v_recipient::uuid=v_primary THEN
                    IF jsonb_typeof(v_item->'signer_agreement')='string' THEN
                        RAISE EXCEPTION 'The Primary Tenant needs no Signer agreement' USING ERRCODE='22023';
                    END IF;
                ELSE
                    IF jsonb_typeof(v_item->'signer_agreement') IS DISTINCT FROM 'string' THEN
                        RAISE EXCEPTION 'A Refund to another Signer needs the written agreement of all Signers'
                            USING ERRCODE='22023'; END IF;
                    PERFORM 1 FROM app.lease_signers signer
                    WHERE signer.lease_id=v_lease AND signer.customer_id=v_recipient::uuid
                      AND signer.signed_at IS NOT NULL;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'The Refund recipient must be a Signer of the Lease' USING ERRCODE='55000';
                    END IF;
                END IF;
                v_left:=jsonb_set(v_left,ARRAY[v_deposit],to_jsonb((v_left->>v_deposit)::bigint-v_amount));
                v_refund:=jsonb_set(v_refund,ARRAY[v_deposit],to_jsonb(v_amount));
            END IF;
        END LOOP;

        -- Owner answer 3 to Q-2026-10-07-41: one Refund method, reference note, recipient and agreement
        -- per correction (as the method and note of sub-slice 10c-1b).
        IF (SELECT count(DISTINCT jsonb_build_array(app.final_settlement_plan_id(step->'recipient_customer_id'),
                app.final_settlement_plan_id(step->'refund_method_id'),step->'reference_note',
                step->'signer_agreement'))
            FROM jsonb_array_elements(p_plan->'steps') step WHERE step->>'kind'='DEPOSIT_REFUNDS')>1
        THEN RAISE EXCEPTION 'A post-settlement correction has one Refund method, reference note, recipient and agreement'
            USING ERRCODE='22023'; END IF;
        -- The remaining Pet Deposit (DL-032 step 5): the Customer's choice with the staff reason, or,
        -- outside the BR-DEP-027 terminations, the staff reason when the Customer will not pay.
        v_basis:=CASE WHEN jsonb_typeof(p_plan->'pet_remainder')='object' THEN p_plan->'pet_remainder' END;
        IF v_step_five THEN
            SELECT array_agg(key ORDER BY key) INTO v_keys FROM jsonb_object_keys(v_basis) key;
            IF v_basis IS NULL OR v_keys IS DISTINCT FROM ARRAY['basis','customer_choice','staff_reason']
                OR v_basis->>'basis' IS NULL OR v_basis->>'basis' NOT IN ('CUSTOMER_CHOICE','STAFF_REASON')
                OR jsonb_typeof(v_basis->'staff_reason') IS DISTINCT FROM 'string'
                OR app.lease_notice_text_valid(v_basis->>'staff_reason',1000) IS NOT TRUE
                OR (v_basis->>'basis'='CUSTOMER_CHOICE'
                    AND (jsonb_typeof(v_basis->'customer_choice') IS DISTINCT FROM 'string'
                        OR app.lease_notice_text_valid(v_basis->>'customer_choice',2000) IS NOT TRUE))
                OR (v_basis->>'basis'='STAFF_REASON'
                    AND jsonb_typeof(v_basis->'customer_choice') IS DISTINCT FROM 'null')
            THEN RAISE EXCEPTION 'The remaining Pet Deposit needs the Customer''s choice or the staff reason'
                USING ERRCODE='22023'; END IF;
            IF v_basis->>'basis'='STAFF_REASON' AND v_chosen_by IS DISTINCT FROM 'CUSTOMER_OR_STAFF_WITH_REASON' THEN
                RAISE EXCEPTION 'At this termination only the Customer may choose to use the remaining Pet Deposit'
                    USING ERRCODE='55000'; END IF;
        ELSIF v_basis IS NOT NULL THEN
            RAISE EXCEPTION 'A remaining Pet Deposit basis needs a remaining Pet Deposit step' USING ERRCODE='22023';
        END IF;
        IF v_pet_after_three IS NULL THEN
            SELECT COALESCE(sum((v_open->>key)::bigint),0) INTO v_pet_after_three FROM unnest(v_pet) key;
        END IF;
        -- BR-SETTLE-008: every remaining Deposit balance is applied or refunded.
        IF EXISTS(SELECT 1 FROM jsonb_each_text(v_left) item WHERE item.value::bigint<>0) THEN
            RAISE EXCEPTION 'Every remaining Deposit balance must be applied or refunded' USING ERRCODE='55000';
        END IF;
        -- Owner answer 1 to Q-2026-10-07-42 (Q-2026-10-05-29 after closure): when a Deposit holds money,
        -- each Customer's Credit pays that Customer's own open debt, up to what it can pay, before any
        -- Deposit pays; never another Customer's debt (checked above).
        IF v_held<>'{}'::jsonb THEN
            SELECT COALESCE(jsonb_object_agg(owed.customer,LEAST(owed.total,COALESCE(available.total,0))),'{}'::jsonb)
            INTO v_may_use
            FROM (SELECT v_owner->>item.key AS customer,sum(item.value::bigint) AS total
                    FROM jsonb_each_text(v_open_start) item GROUP BY 1) owed
            LEFT JOIN (SELECT v_credit_owner->>item.key AS customer,sum(item.value::bigint) AS total
                    FROM jsonb_each_text(v_credit_start) item GROUP BY 1) available
                ON available.customer=owed.customer;
            IF EXISTS(SELECT 1 FROM jsonb_each_text(v_may_use) item
                WHERE COALESCE((v_used_credit->>item.key)::bigint,0)<item.value::bigint)
            THEN RAISE EXCEPTION 'Each Customer''s Credit must pay that Customer''s open debt, up to what it can pay, before any Deposit pays'
                USING ERRCODE='55000'; END IF;
        END IF;
        -- Owner answer 2 to Q-2026-10-07-42: Credit the correction releases pays its own Customer's open
        -- debt on this Lease first; only the rest is refunded.
        IF EXISTS(SELECT 1 FROM jsonb_each_text(v_released) item
            WHERE (v_credit->>item.key)::bigint>0
              AND EXISTS(SELECT 1 FROM jsonb_each_text(v_open) owed
                  WHERE v_owner->>owed.key=item.value AND owed.value::bigint>0))
        THEN RAISE EXCEPTION 'Customer Credit the correction releases pays its own Customer''s open debt on this Lease before any Refund'
            USING ERRCODE='55000'; END IF;
        -- Owner answer 3 (ii) to Q-2026-10-05-20: the Pet Deposit pays open pet damage before any other
        -- use or Refund.
        IF v_pet_after_three>0 AND (v_step_five OR EXISTS(SELECT 1 FROM jsonb_object_keys(v_refund) deposit
            WHERE v_type->>deposit='PET'))
        THEN RAISE EXCEPTION 'The Pet Deposit pays open pet damage before any other use or Refund'
            USING ERRCODE='55000'; END IF;
        SELECT COALESCE(sum(item.value::bigint),0) INTO v_closing FROM jsonb_each_text(v_open) item;
        -- Owner answer 3 (iii) to Q-2026-10-05-20: no Deposit Refund while the Lease still has open debt
        -- that the Deposit could pay.
        IF v_closing>0 AND EXISTS(SELECT 1 FROM jsonb_object_keys(v_refund) deposit
            WHERE v_type->>deposit='SECURITY' OR v_chosen_by='CUSTOMER_OR_STAFF_WITH_REASON')
        THEN RAISE EXCEPTION 'No Deposit Refund while the Lease still has open debt that the Deposit could pay'
            USING ERRCODE='55000'; END IF;
        -- The owner answer to choice (4a) of sub-slice 8c: the remaining Pet Deposit pays only debt still
        -- open after the Security Deposit has been used.
        IF v_security_at_five>0 THEN
            RAISE EXCEPTION 'The remaining Pet Deposit pays only debt still open after the Security Deposit has been used'
                USING ERRCODE='55000'; END IF;

        RETURN jsonb_build_object('lease_id',v_lease,
            'termination_ground',v_preview->'lease'->'termination_ground',
            'pet_remainder_chosen_by',v_chosen_by,
            'deposit_ids',(SELECT COALESCE(jsonb_agg(key ORDER BY key),'[]'::jsonb) FROM jsonb_object_keys(v_held) key),
            'open_total_usd_cents',(SELECT COALESCE(sum(item.value::bigint),0) FROM jsonb_each_text(v_open_start) item),
            'closing_balance_usd_cents',v_closing,
            'closing_balances',(SELECT COALESCE(jsonb_agg(jsonb_build_object('customer_id',owed.customer,
                    'open_usd_cents',owed.total) ORDER BY owed.customer<>v_primary::text,owed.customer),'[]'::jsonb)
                FROM (SELECT v_owner->>item.key AS customer,sum(item.value::bigint) AS total
                    FROM jsonb_each_text(v_open) item GROUP BY 1 HAVING sum(item.value::bigint)>0) owed),
            'credit_left',(SELECT COALESCE(jsonb_object_agg(item.key,(v_credit->>item.key)::bigint),'{}'::jsonb)
                FROM jsonb_each_text(v_released) item),
            -- The digest of every Settlement source, read in this same call (same snapshot).
            'source_revision','settlement-correction-plan:' || encode(sha256(convert_to(
                app.final_settlement_source_state(p_property,p_settlement)::text,'UTF8')),'hex'));
    END $$;

    -- The Credit a plan key names inside a correction draft's correction: the Credit that a release of
    -- the correction's own credit Adjustment recognized from the overlay's released Payment allocation
    -- (BR-CREDIT-014), otherwise the key itself. NULL for an unknown draft or a release not written.
    CREATE FUNCTION app.settlement_correction_credit_id(p_draft uuid,p_key uuid)
    RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT CASE WHEN jsonb_typeof(draft.payload->'plan_overlay'->'credits'->(p_key::text)
                ->'released_payment_allocation_id') IS DISTINCT FROM 'string'
            THEN p_key
            ELSE (SELECT release.customer_credit_id FROM app.settlement_correction_effects effect
                JOIN app.invoice_credit_excess_releases release
                    ON release.invoice_adjustment_id=effect.invoice_adjustment_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(p_draft)
                  AND release.reversed_payment_allocation_id=p_key) END
        FROM app.financial_drafts draft WHERE draft.id=p_draft AND draft.kind='SETTLEMENT_CORRECTION'
    $$;

    -- The step's locks, in the Settlement confirm's order (sub-slice 8e-3). A variant takes the draft
    -- lock and the Settlement's draft lock first (as sub-slice 10c-1b), then the Lease row FOR UPDATE
    -- (10c-1b as committed takes no Lease lock; every later correction type, and 10c-1b once it uses
    -- this step in 10c-2a-3, takes it FOR UPDATE here in the 8e-3 order, never FOR SHARE first; all
    -- three are taken again here, which costs nothing when held in these modes), then its own sources
    -- (for example the Payment of an allocation it releases), then calls this before
    -- app.begin_settlement_correction, at READ COMMITTED; the step calls it again inside the
    -- correction. Order: the Lease row FOR UPDATE, as
    -- the Settlement confirm and the Lease-first writers (review round 2: the move-out inspection
    -- command locks it FOR UPDATE, so no inspection is superseded, and no line stops being pet damage,
    -- while a correction runs the step); the Payments and then the Credits of the existing
    -- Credits the Credit steps name (Payment before Invoice, as the one-call writers); the Lease's
    -- Late-payment Charges and then its Invoices in id order (FOR UPDATE where a step pays them, with
    -- a Credit step Invoice's lines; FOR NO KEY UPDATE otherwise); the Settlement row; then each Deposit
    -- of the Lease in id order, its draft lock and its row. A detected deadlock (40P01) is a conflict.
    CREATE FUNCTION app.lock_settlement_correction_plan(p_draft uuid)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_lease uuid; v_settlement uuid; v_steps jsonb; v_credits uuid[];
        v_target_charges uuid[]; v_target_invoices uuid[]; v_credit_invoices uuid[]; v_id uuid; v_flag boolean;
    BEGIN
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND kind='SETTLEMENT_CORRECTION';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        SELECT settlement.id,settlement.lease_id INTO v_settlement,v_lease FROM app.final_settlements settlement
        WHERE settlement.id=app.final_settlement_plan_id(v_draft.payload->'final_settlement_id')::uuid
          AND settlement.property_id=v_draft.property_id;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement::text,0));
        PERFORM 1 FROM app.leases WHERE id=v_lease FOR UPDATE;
        v_steps:=v_draft.payload->'plan'->'steps';
        IF jsonb_typeof(v_steps) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'Post-settlement correction plan is invalid' USING ERRCODE='22023'; END IF;
        SELECT COALESCE(array_agg(DISTINCT credit.id),'{}') INTO v_credits
        FROM jsonb_array_elements(v_steps) step
        JOIN app.customer_credits credit ON credit.id=app.final_settlement_plan_id(step->'customer_credit_id')::uuid
        WHERE step->>'kind'='CUSTOMER_CREDIT';
        SELECT COALESCE(array_agg(DISTINCT app.final_settlement_plan_id(step->'target_id')::uuid),'{}')
        INTO v_target_charges FROM jsonb_array_elements(v_steps) step
        WHERE step->>'kind'<>'DEPOSIT_REFUNDS' AND step->>'target_kind'='LATE_PAYMENT_CHARGE';
        SELECT COALESCE(array_agg(DISTINCT line.invoice_id),'{}') INTO v_target_invoices
        FROM jsonb_array_elements(v_steps) step
        JOIN app.invoice_lines line ON line.id=app.final_settlement_plan_id(step->'target_id')::uuid
        WHERE step->>'kind'<>'DEPOSIT_REFUNDS' AND step->>'target_kind'='INVOICE_LINE';
        SELECT COALESCE(array_agg(DISTINCT line.invoice_id),'{}') INTO v_credit_invoices
        FROM jsonb_array_elements(v_steps) step
        JOIN app.invoice_lines line ON line.id=app.final_settlement_plan_id(step->'target_id')::uuid
        WHERE step->>'kind'='CUSTOMER_CREDIT' AND step->>'target_kind'='INVOICE_LINE';
        v_target_invoices:=v_target_invoices||COALESCE((SELECT array_agg(charge.source_invoice_id)
            FROM app.late_payment_charges charge WHERE charge.id=ANY(v_target_charges)),'{}');
        FOR v_id IN SELECT DISTINCT credit.source_payment_id FROM app.customer_credits credit
            WHERE credit.id=ANY(v_credits) ORDER BY 1
        LOOP
            PERFORM app.serialize_payment_state(v_id);
            PERFORM 1 FROM app.payments WHERE id=v_id FOR UPDATE;
        END LOOP;
        PERFORM 1 FROM app.customer_credits WHERE id=ANY(v_credits) ORDER BY id FOR UPDATE;
        FOR v_id,v_flag IN SELECT charge.id,charge.id=ANY(v_target_charges) FROM app.late_payment_charges charge
            JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
            WHERE invoice.lease_id=v_lease ORDER BY charge.id
        LOOP
            IF v_flag THEN PERFORM 1 FROM app.late_payment_charges WHERE id=v_id FOR UPDATE;
            ELSE PERFORM 1 FROM app.late_payment_charges WHERE id=v_id FOR NO KEY UPDATE; END IF;
        END LOOP;
        FOR v_id,v_flag IN SELECT invoice.id,invoice.id=ANY(v_target_invoices) FROM app.invoices invoice
            WHERE invoice.lease_id=v_lease ORDER BY invoice.id
        LOOP
            IF v_flag THEN
                PERFORM 1 FROM app.invoices WHERE id=v_id FOR UPDATE;
                IF v_id=ANY(v_credit_invoices) THEN
                    PERFORM 1 FROM app.invoice_lines WHERE invoice_id=v_id ORDER BY id FOR UPDATE;
                END IF;
            ELSE PERFORM 1 FROM app.invoices WHERE id=v_id FOR NO KEY UPDATE; END IF;
        END LOOP;
        PERFORM 1 FROM app.final_settlements WHERE id=v_settlement FOR UPDATE;
        FOR v_id IN SELECT deposit.id FROM app.deposits deposit WHERE deposit.lease_id=v_lease ORDER BY deposit.id
        LOOP
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || v_id::text,0));
            PERFORM app.serialize_deposit_state(v_id);
        END LOOP;
    END $$;

    -- The source check of a correction's own Credit application (owner answer 1 to Q-2026-10-07-42),
    -- called by the 8e-2 source check for a row linked to a correction of its Settlement confirmed in
    -- this transaction: the correction's approver under financial.approve, not before the
    -- correction, a target of the Settlement Lease, before any Deposit application or Refund of the
    -- same correction (DL-032 step 2), and a Credit step of that correction's plan with the basis
    -- BR-CREDIT-006 gives. Every existing Credit check still runs on the row.
    CREATE FUNCTION app.assert_settlement_correction_credit_application(p_application app.customer_credit_applications)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_correction app.settlement_corrections%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_lease app.leases%ROWTYPE; v_target_lease uuid; v_steps jsonb;
    BEGIN
        SELECT correction.* INTO v_correction FROM app.settlement_correction_effects effect
        JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
        WHERE effect.customer_credit_application_id=p_application.id;
        SELECT * INTO STRICT v_settlement FROM app.final_settlements WHERE id=v_correction.final_settlement_id;
        IF p_application.actor_id IS DISTINCT FROM v_correction.actor_id
            OR p_application.authorization_reference IS DISTINCT FROM 'financial.approve'
            OR NOT EXISTS(SELECT 1 FROM app.actor_identities identity
                WHERE identity.actor_id=p_application.actor_id AND identity.identity_kind='HUMAN')
        THEN RAISE EXCEPTION 'A post-settlement correction Credit application is written by the correction''s approver under financial.approve'
            USING ERRCODE='42501'; END IF;
        PERFORM app.assert_active_financial_actor(p_application.actor_id,v_settlement.property_id);
        IF p_application.occurred_at IS NULL OR p_application.occurred_at<v_correction.occurred_at THEN
            RAISE EXCEPTION 'A post-settlement correction Credit application cannot precede its correction'
                USING ERRCODE='23514'; END IF;
        SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_settlement.lease_id;
        IF p_application.target_kind='INVOICE' THEN
            SELECT invoice.lease_id INTO v_target_lease FROM app.invoices invoice WHERE invoice.id=p_application.invoice_id;
        ELSE
            SELECT invoice.lease_id INTO v_target_lease FROM app.late_payment_charges charge
            JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
            WHERE charge.id=p_application.late_payment_charge_id;
        END IF;
        IF v_lease.status IS DISTINCT FROM 'TERMINATED' OR v_target_lease IS DISTINCT FROM v_lease.id THEN
            RAISE EXCEPTION 'The Credit target must be an obligation of the terminated Settlement Lease'
                USING ERRCODE='23514'; END IF;
        IF EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
            WHERE effect.settlement_correction_id=v_correction.id
              AND (effect.deposit_application_id IS NOT NULL OR effect.refund_id IS NOT NULL))
        THEN RAISE EXCEPTION 'Customer Credit is applied before the correction''s Deposit applications and Refunds'
            USING ERRCODE='55000'; END IF;
        SELECT CASE WHEN jsonb_typeof(draft.payload->'plan'->'steps')='array' THEN draft.payload->'plan'->'steps'
            ELSE '[]'::jsonb END INTO v_steps
        FROM app.financial_drafts draft WHERE draft.id=v_correction.correlation_id;
        IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v_steps) step
            WHERE step->>'kind'='CUSTOMER_CREDIT'
              AND app.settlement_correction_credit_id(v_correction.correlation_id,
                  app.final_settlement_plan_id(step->'customer_credit_id')::uuid)=p_application.customer_credit_id
              AND step->>'amount_usd_cents'=p_application.amount_usd_cents::text
              AND ((step->>'target_kind'='INVOICE_LINE' AND p_application.target_kind='INVOICE'
                      AND EXISTS(SELECT 1 FROM app.invoice_lines line
                          WHERE line.id=app.final_settlement_plan_id(step->'target_id')::uuid
                            AND line.invoice_id=p_application.invoice_id))
                  OR (step->>'target_kind'='LATE_PAYMENT_CHARGE' AND p_application.target_kind='LATE_PAYMENT_CHARGE'
                      AND p_application.late_payment_charge_id::text=app.final_settlement_plan_id(step->'target_id')))
              AND p_application.within_invoice_basis IS NOT DISTINCT FROM
                  (CASE WHEN jsonb_typeof(step->'customer_designation')='string' THEN 'CUSTOMER_DESIGNATED'
                      WHEN step->>'target_kind'='LATE_PAYMENT_CHARGE' THEN 'NOT_APPLICABLE'
                      WHEN EXISTS(SELECT 1 FROM app.invoice_lines line WHERE line.invoice_id=p_application.invoice_id
                          AND line.category IN ('RENT','SERVICE_CHARGES')) THEN 'RENT_THEN_RECURRING_SERVICES_PROPOSAL'
                      ELSE 'OTHER_APPLICABLE_OBLIGATION' END)
              AND p_application.customer_designation_reference IS NOT DISTINCT FROM
                  (CASE WHEN jsonb_typeof(step->'customer_designation')='string' THEN step->>'customer_designation' END))
        THEN RAISE EXCEPTION 'A post-settlement correction Credit application must be a Credit step of its correction'
            USING ERRCODE='23514'; END IF;
    END $$;

    -- At commit (BR-AUTH-010): a correction's own Credit application commits only with its
    -- correction's draft confirmed under financial.approve by the same approver, and it pays exactly
    -- the Credit step its detail names, once.
    CREATE FUNCTION app.assert_settlement_correction_credit_application_confirmed(
        p_application app.customer_credit_applications)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_correction app.settlement_corrections%ROWTYPE; v_detail app.customer_credit_application_details%ROWTYPE;
        v_count integer; v_step jsonb; v_sequence integer;
    BEGIN
        SELECT correction.* INTO v_correction FROM app.settlement_correction_effects effect
        JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
        WHERE effect.customer_credit_application_id=p_application.id;
        IF NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
            WHERE decision.draft_id=v_correction.correlation_id AND decision.decision='CONFIRMED'
              AND decision.authorization_reference='financial.approve'
              AND decision.decided_by=p_application.actor_id)
        THEN RAISE EXCEPTION 'A post-settlement correction Credit application needs its correction confirmed under financial.approve by the same approver'
            USING ERRCODE='42501'; END IF;
        SELECT count(*) INTO v_count FROM app.customer_credit_application_details
        WHERE customer_credit_application_id=p_application.id;
        SELECT * INTO v_detail FROM app.customer_credit_application_details
        WHERE customer_credit_application_id=p_application.id;
        v_sequence:=CASE WHEN v_detail.calculation_trace->>'step_sequence' ~ '^[1-9][0-9]{0,2}$'
            THEN (v_detail.calculation_trace->>'step_sequence')::integer END;
        SELECT draft.payload->'plan'->'steps'->(v_sequence-1) INTO v_step
        FROM app.financial_drafts draft WHERE draft.id=v_correction.correlation_id;
        IF v_count<>1 OR v_sequence IS NULL
            OR v_detail.calculation_trace->>'draft_id' IS DISTINCT FROM v_correction.correlation_id::text
            OR v_step->>'kind' IS DISTINCT FROM 'CUSTOMER_CREDIT'
            OR app.settlement_correction_credit_id(v_correction.correlation_id,
                app.final_settlement_plan_id(v_step->'customer_credit_id')::uuid)
                IS DISTINCT FROM p_application.customer_credit_id
            OR v_step->>'amount_usd_cents' IS DISTINCT FROM p_application.amount_usd_cents::text
            OR v_detail.applied_amount_usd_cents IS DISTINCT FROM p_application.amount_usd_cents
            OR (v_step->>'target_kind'='INVOICE_LINE' AND v_detail.invoice_line_id::text
                IS DISTINCT FROM app.final_settlement_plan_id(v_step->'target_id'))
            OR (v_step->>'target_kind'='LATE_PAYMENT_CHARGE' AND v_detail.late_payment_charge_id::text
                IS DISTINCT FROM app.final_settlement_plan_id(v_step->'target_id'))
            OR EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                JOIN app.customer_credit_application_details other
                    ON other.customer_credit_application_id=effect.customer_credit_application_id
                WHERE effect.settlement_correction_id=v_correction.id
                  AND effect.customer_credit_application_id<>p_application.id
                  AND other.calculation_trace->>'draft_id'=v_correction.correlation_id::text
                  AND other.calculation_trace->>'step_sequence'=v_detail.calculation_trace->>'step_sequence')
        THEN RAISE EXCEPTION 'A post-settlement correction Credit application pays exactly the obligation of its Credit step, once'
            USING ERRCODE='23514'; END IF;
    END $$;

    -- The Refund source check of a correction's own Deposit Refund (owner answer 3 to
    -- Q-2026-10-07-41), called by the 8d source check for a Refund whose correction details row names
    -- a Deposit: only the Refund of a correction confirmed in this transaction, linked to it before
    -- it is written, processed by its approver, matching a Refund step of that correction's plan, at
    -- most one per Deposit per correction, with the 8d rules (DL-032 path, no waiting receipt
    -- reversal or forfeiture draft, active method, BR-REFUND-015 recipient, held amount, chronology,
    -- no open debt a Deposit could pay). Shape and source mismatches 23514; business state 55000; a
    -- Refund not processed by the correction's approver 42501.
    CREATE FUNCTION app.assert_settlement_correction_deposit_refund_source(p_refund app.refunds)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_detail app.settlement_correction_refund_details%ROWTYPE;
        v_correction app.settlement_corrections%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_lease app.leases%ROWTYPE; v_deposit app.deposits%ROWTYPE; v_steps jsonb; v_ground text;
        v_staff_pet_step boolean; v_open bigint; v_pet_open bigint;
    BEGIN
        SELECT * INTO v_detail FROM app.settlement_correction_refund_details WHERE refund_id=p_refund.id;
        SELECT * INTO v_correction FROM app.settlement_corrections
        WHERE id=v_detail.settlement_correction_id AND correlation_id=v_detail.draft_id;
        IF v_detail.deposit_id IS DISTINCT FROM p_refund.source_deposit_id OR v_correction.id IS NULL
            OR app.settlement_correction_linked(v_correction.final_settlement_id,'refunds',p_refund.id) IS NOT TRUE
            OR NOT EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                WHERE effect.settlement_correction_id=v_correction.id AND effect.refund_id=p_refund.id)
        THEN RAISE EXCEPTION 'A post-settlement correction Deposit Refund is written only by its correction'
            USING ERRCODE='23514'; END IF;
        -- Lock order of the Deposit writers (8a, 8d): the Settlement, then the Deposit.
        SELECT * INTO STRICT v_settlement FROM app.final_settlements
        WHERE id=v_correction.final_settlement_id FOR UPDATE;
        -- BR-AUTH-010: the correction's approver, a person.
        IF p_refund.processed_by IS DISTINCT FROM v_correction.actor_id
            OR NOT EXISTS(SELECT 1 FROM app.actor_identities identity
                WHERE identity.actor_id=p_refund.processed_by AND identity.identity_kind='HUMAN')
        THEN RAISE EXCEPTION 'A post-settlement correction Deposit Refund is processed by the correction''s approver'
            USING ERRCODE='42501'; END IF;
        PERFORM app.assert_active_financial_actor(p_refund.processed_by,NULL);
        PERFORM app.assert_active_financial_actor(p_refund.processed_by,v_settlement.property_id);
        SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_settlement.lease_id;
        SELECT * INTO v_deposit FROM app.deposits WHERE id=p_refund.source_deposit_id;
        IF NOT FOUND OR v_deposit.lease_id IS DISTINCT FROM v_settlement.lease_id
            OR v_deposit.deposit_type NOT IN ('SECURITY','PET')
            OR v_deposit.customer_id IS DISTINCT FROM v_lease.primary_tenant_id
            OR v_lease.status IS DISTINCT FROM 'TERMINATED'
        THEN RAISE EXCEPTION 'The Refund source must be a Deposit of the terminated Settlement Lease'
            USING ERRCODE='23514'; END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || v_deposit.id::text,0));
        PERFORM app.serialize_deposit_state(v_deposit.id);
        -- A kept Deposit is never refunded (BR-DEP-026).
        IF app.lease_deposit_settlement_path(v_settlement.property_id,v_deposit.id)->>'path'
            IS DISTINCT FROM 'DL_032'
        THEN RAISE EXCEPTION 'Only a Deposit that follows DL-032 is refunded by a post-settlement correction'
            USING ERRCODE='23514'; END IF;
        -- The owner's 8r rule: no Refund while a receipt reversal or forfeiture draft waits.
        IF EXISTS(SELECT 1 FROM app.financial_drafts draft
            WHERE draft.kind='DEPOSIT_FORFEITURE' AND draft.payload->>'deposit_id'=v_deposit.id::text
              AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                  WHERE decision.draft_id=draft.id))
        THEN RAISE EXCEPTION 'A Deposit receipt reversal or forfeiture draft for this Deposit is waiting'
            USING ERRCODE='55000'; END IF;
        -- BR-REFUND-014: an active Refund method.
        PERFORM 1 FROM app.refund_methods WHERE id=v_detail.refund_method_id AND active FOR SHARE;
        IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        -- BR-REFUND-015: the Primary Tenant (the Deposit owner), or another signed Signer of the Lease
        -- with the written agreement of all Signers.
        IF p_refund.recipient_customer_id=v_deposit.customer_id THEN
            IF v_detail.signer_agreement IS NOT NULL THEN
                RAISE EXCEPTION 'The Primary Tenant needs no Signer agreement' USING ERRCODE='23514'; END IF;
        ELSIF v_detail.signer_agreement IS NULL OR NOT EXISTS(SELECT 1 FROM app.lease_signers signer
            WHERE signer.lease_id=v_lease.id AND signer.customer_id=p_refund.recipient_customer_id
              AND signer.signed_at IS NOT NULL)
        THEN RAISE EXCEPTION 'A Refund to another Signer needs a signed Signer and the written agreement of all Signers'
            USING ERRCODE='23514'; END IF;
        -- BR-AUTH-010: a Refund step of the correction's plan, exactly as prepared, once per Deposit.
        SELECT CASE WHEN jsonb_typeof(draft.payload->'plan'->'steps')='array' THEN draft.payload->'plan'->'steps'
            ELSE '[]'::jsonb END INTO v_steps
        FROM app.financial_drafts draft WHERE draft.id=v_correction.correlation_id;
        IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v_steps) step
                WHERE step->>'kind'='DEPOSIT_REFUNDS'
                  AND app.final_settlement_plan_id(step->'deposit_id')=v_deposit.id::text
                  AND step->>'amount_usd_cents'=p_refund.usd_accounting_value_cents::text
                  AND app.final_settlement_plan_id(step->'recipient_customer_id')=p_refund.recipient_customer_id::text
                  AND app.final_settlement_plan_id(step->'refund_method_id')=v_detail.refund_method_id::text
                  AND step->>'reference_note'=v_detail.reference_note
                  AND step->>'signer_agreement' IS NOT DISTINCT FROM v_detail.signer_agreement)
            OR EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                JOIN app.refunds other ON other.id=effect.refund_id
                WHERE effect.settlement_correction_id=v_correction.id AND other.source_deposit_id=v_deposit.id
                  AND other.id<>p_refund.id)
        THEN RAISE EXCEPTION 'A post-settlement correction Deposit Refund must be a Refund step of its correction, once per Deposit'
            USING ERRCODE='23514'; END IF;
        IF p_refund.usd_accounting_value_cents NOT BETWEEN 1 AND 9000000000000000
            OR p_refund.usd_accounting_value_cents>app.deposit_held_value_at(v_deposit.id,'infinity')
            OR NOT isfinite(p_refund.processed_at) OR p_refund.processed_at<v_correction.occurred_at
            OR p_refund.processed_at<=COALESCE(app.deposit_balance_latest_at(v_deposit.id),'-infinity')
            OR p_refund.processed_at>clock_timestamp()+interval '5 seconds'
            OR app.lease_notice_text_valid(p_refund.reason,1000) IS NOT TRUE
            OR p_refund.authorization_reference IS DISTINCT FROM 'financial.approve'
        THEN RAISE EXCEPTION 'Post-settlement correction Deposit Refund amount, authorization or chronology is invalid'
            USING ERRCODE='23514'; END IF;
        -- Owner answer 3 to Q-2026-10-05-20 and BR-SETTLE-008, read as sub-slice 8d reads it: no Refund
        -- while the Lease still has open debt that a Deposit could pay.
        SELECT COALESCE(sum(line_value.amount),0),
            COALESCE(sum(line_value.amount) FILTER (WHERE app.invoice_line_is_pet_damage(line.id,v_lease.id)),0)
        INTO v_open,v_pet_open
        FROM app.invoices invoice JOIN app.invoice_lines line ON line.invoice_id=invoice.id
        CROSS JOIN LATERAL (SELECT app.invoice_line_outstanding(line.id) AS amount) line_value
        WHERE invoice.lease_id=v_lease.id AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID')
            AND line_value.amount>0;
        v_open:=v_open+COALESCE((SELECT sum(position.remaining_balance_usd_cents)
            FROM app.late_payment_charges charge
            JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
            JOIN app.late_payment_charge_financial_position position
                ON position.late_payment_charge_id=charge.id
            WHERE invoice.lease_id=v_lease.id AND position.remaining_balance_usd_cents>0),0);
        v_ground:=app.lease_termination_forfeiture_rule(v_settlement.property_id,v_lease.id,'SECURITY');
        v_staff_pet_step:=v_ground IS NULL OR v_ground NOT IN ('BR-LEASE-005','BR-LEASE-025','BR-LEASE-028');
        IF (v_deposit.deposit_type='PET' AND v_pet_open>0)
            OR (v_open>0 AND (v_deposit.deposit_type='SECURITY' OR v_staff_pet_step
                OR EXISTS(SELECT 1 FROM app.deposits other
                    WHERE other.lease_id=v_lease.id AND other.deposit_type='SECURITY' AND other.id<>v_deposit.id
                      AND app.deposit_held_value_at(other.id,'infinity')>0
                      AND app.lease_deposit_settlement_path(v_settlement.property_id,other.id)->>'path'='DL_032')))
        THEN RAISE EXCEPTION 'No Deposit Refund while the Lease still has open debt that a Deposit could pay'
            USING ERRCODE='55000'; END IF;
    END $$;

    -- The writer of a correction's Deposit Refund (BR-REFUND-007, BR-REFUND-014, BR-REFUND-015): the
    -- details row first (deferred key), so the source check reads it, then the Refund, linked to the
    -- correction before both are written, with a fresh id. No role may call it.
    CREATE FUNCTION app.post_settlement_correction_deposit_refund(p_property uuid,p_actor uuid,p_correction uuid,
        p_draft uuid,p_deposit uuid,p_amount bigint,p_recipient uuid,p_refund_method uuid,p_reference_note text,
        p_signer_agreement text,p_reason text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_correction app.settlement_corrections%ROWTYPE; v_refund uuid:=gen_random_uuid(); v_at timestamptz;
    BEGIN
        IF p_correction IS NULL OR p_draft IS NULL OR p_deposit IS NULL OR p_recipient IS NULL
            OR p_refund_method IS NULL OR p_amount IS NULL OR p_actor IS NULL OR p_reason IS NULL
            OR p_reference_note IS NULL
        THEN RAISE EXCEPTION 'Post-settlement correction Refund input is invalid' USING ERRCODE='22023'; END IF;
        SELECT * INTO v_correction FROM app.settlement_corrections
        WHERE id=p_correction AND correlation_id=p_draft;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Post-settlement correction was not found' USING ERRCODE='P0002'; END IF;
        -- Lock order of the Deposit writers (8a, 8d): the Settlement row, then the Deposit's draft lock
        -- and row, before the details row takes its key locks.
        PERFORM 1 FROM app.final_settlements
        WHERE id=v_correction.final_settlement_id AND property_id=p_property FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || p_deposit::text,0));
        PERFORM app.serialize_deposit_state(p_deposit);
        -- Both checks of the details row and the Refund's link key wait for commit, even after an
        -- earlier SET CONSTRAINTS ALL IMMEDIATE in this transaction (as the 8d writer).
        SET CONSTRAINTS app.settlement_correction_refund_details_refund_id_fkey,
            app.settlement_correction_refund_details_approver,
            app.settlement_correction_effects_refund_id_fkey DEFERRED;
        -- Strictly later than the Deposit's latest event (the Deposit applications just written).
        v_at:=GREATEST(clock_timestamp(),app.deposit_balance_latest_at(p_deposit)+interval '1 microsecond');
        PERFORM app.link_settlement_correction_effect(p_correction,'refund_id',v_refund);
        INSERT INTO app.settlement_correction_refund_details(refund_id,settlement_correction_id,draft_id,
            refund_method_id,reference_note,recorded_at,deposit_id,signer_agreement)
        VALUES(v_refund,p_correction,p_draft,p_refund_method,p_reference_note,v_at,p_deposit,p_signer_agreement);
        INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_deposit_id,
            usd_accounting_value_cents,refund_currency,refund_amount_minor,reason,processed_at,
            processed_by,authorization_reference)
        VALUES(v_refund,'REF-'||v_refund::text,p_recipient,p_deposit,p_amount,'USD',p_amount,
            p_reason,v_at,p_actor,'financial.approve');
        RETURN jsonb_build_object('refund_id',v_refund,'refund_number','REF-'||v_refund::text,
            'settlement_correction_id',p_correction,'deposit_id',p_deposit,'draft_id',p_draft,
            'recipient_customer_id',p_recipient,'amount_usd_cents',p_amount,
            'refund_method_id',p_refund_method,'reference_note',p_reference_note,
            'signer_agreement',p_signer_agreement,'processed_at',v_at);
    END $$;

    -- The shared DL-032 step of a post-settlement correction (owner answer 1 to Q-2026-10-07-41,
    -- answers 1 and 2 to Q-2026-10-07-42). A variant calls it inside its correction, after its own
    -- release: the plan check again on the real state (the overlay keeps only the released Credit
    -- keys, with nothing added), compared with the result the draft recorded (otherwise stale,
    -- P5S02, and the transaction rolls back); then each record, linked to the correction before it
    -- is written and with a fresh id: the Credit steps in the plan's order (the 8e-2 writer), the
    -- Deposit applications in the plan's order and the Deposit Refunds in Deposit id order. It sets
    -- nothing IMMEDIATE; the variant does at its end.
    CREATE FUNCTION app.post_settlement_correction_plan(p_property uuid,p_approver uuid,p_draft uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_correction app.settlement_corrections%ROWTYPE;
        v_plan jsonb; v_steps jsonb; v_overlay jsonb:='{}'::jsonb; v_expected jsonb; v_result jsonb;
        v_item jsonb; v_position bigint; v_key text; v_credit uuid; v_map jsonb:='{}'::jsonb; v_left jsonb;
        v_order integer; v_id uuid; v_reason text; v_credit_ids uuid[]:='{}'; v_application_ids uuid[]:='{}';
        v_refund_ids uuid[]:='{}';
    BEGIN
        SELECT * INTO v_draft FROM app.financial_drafts
        WHERE id=p_draft AND property_id=p_property AND kind='SETTLEMENT_CORRECTION';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        -- Only inside the draft's own correction, confirmed in this transaction by this approver.
        SELECT correction.* INTO v_correction FROM app.settlement_corrections correction
        WHERE correction.id=app.settlement_correction_id(p_draft) AND correction.correlation_id=p_draft
          AND correction.actor_id=p_approver
          AND EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
              WHERE decision.draft_id=p_draft AND decision.decision='CONFIRMED' AND decision.decided_by=p_approver
                AND decision.authorization_reference='financial.approve'
                AND decision.result->>'transaction_id'=pg_current_xact_id()::text
                AND decision.decided_at>=transaction_timestamp());
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The DL-032 step of a post-settlement correction runs only inside that correction'
                USING ERRCODE='23514'; END IF;
        -- Each record is linked before it is written (deferred keys). An earlier writer of the same
        -- transaction (for example app.adjust_invoice) may have set every constraint IMMEDIATE, so
        -- the step moves its own link keys back to commit (as the 8d and 8e-2 writers do their checks).
        SET CONSTRAINTS app.settlement_correction_effects_customer_credit_application__fkey,
            app.settlement_correction_effects_deposit_application_id_fkey,
            app.settlement_correction_effects_refund_id_fkey DEFERRED;
        -- The rules that span several records are checked once, under the step's locks, at READ
        -- COMMITTED, as every correction confirm (review round 1); the locks a variant took before
        -- its correction are held already.
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction is confirmed at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        PERFORM app.lock_settlement_correction_plan(p_draft);
        v_plan:=v_draft.payload->'plan';
        v_expected:=v_draft.payload->'plan_result';
        IF jsonb_typeof(v_plan) IS DISTINCT FROM 'object' OR jsonb_typeof(v_plan->'steps') IS DISTINCT FROM 'array'
            OR jsonb_typeof(v_expected) IS DISTINCT FROM 'object'
            OR jsonb_typeof(v_draft.payload->'plan_overlay'->'credits') IS DISTINCT FROM 'object'
        THEN RAISE EXCEPTION 'Post-settlement correction plan is invalid' USING ERRCODE='22023'; END IF;
        -- Each Credit key names a Credit that exists now (a released Payment allocation's value was
        -- recognized by the variant's release); released Credit keeps its R2 rule with nothing added.
        FOR v_key IN SELECT key FROM jsonb_object_keys(v_draft.payload->'plan_overlay'->'credits') key LOOP
            v_credit:=app.settlement_correction_credit_id(p_draft,app.final_settlement_plan_id(to_jsonb(v_key))::uuid);
            IF v_credit IS NULL THEN
                RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
                    USING ERRCODE='P5S02'; END IF;
            v_map:=v_map||jsonb_build_object(v_key,v_credit);
            v_overlay:=v_overlay||jsonb_build_object(v_credit::text,jsonb_build_object(
                'customer_id',v_draft.payload->'plan_overlay'->'credits'->v_key->'customer_id',
                'add_usd_cents',0,'released_payment_allocation_id',NULL));
        END LOOP;
        SELECT COALESCE(jsonb_agg(CASE WHEN item.step->>'kind'='CUSTOMER_CREDIT'
                    AND v_map ? app.final_settlement_plan_id(item.step->'customer_credit_id')
                THEN jsonb_set(item.step,'{customer_credit_id}',
                    v_map->app.final_settlement_plan_id(item.step->'customer_credit_id'))
                ELSE item.step END ORDER BY item.ordinality),'[]'::jsonb)
        INTO v_steps FROM jsonb_array_elements(v_plan->'steps') WITH ORDINALITY AS item(step,ordinality);
        v_result:=app.settlement_correction_plan_result(p_property,p_approver,v_correction.final_settlement_id,
            jsonb_build_object('steps',v_steps,'pet_remainder',COALESCE(v_plan->'pet_remainder','null'::jsonb)),
            jsonb_build_object('obligations','{}'::jsonb,'credits',v_overlay,'deposits','{}'::jsonb));
        SELECT COALESCE(jsonb_object_agg(item.key,v_result->'credit_left'->(item.value#>>'{}')),'{}'::jsonb)
        INTO v_left FROM jsonb_each(v_map) item;
        -- The whole recorded result, the released Credit keyed back to the plan's keys (review round 1).
        IF (v_result-'source_revision'-'credit_left') IS DISTINCT FROM (v_expected-'credit_left')
            OR v_left IS DISTINCT FROM v_expected->'credit_left'
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        -- DL-032 step 2: each Credit step, in the plan's order (the 8e-2 writer with the correction link).
        FOR v_item,v_position IN SELECT step.value,step.ordinality
            FROM jsonb_array_elements(v_plan->'steps') WITH ORDINALITY AS step(value,ordinality)
            WHERE step.value->>'kind'='CUSTOMER_CREDIT' ORDER BY step.ordinality
        LOOP
            v_credit_ids:=v_credit_ids||(app.post_final_settlement_credit_application(p_property,p_approver,
                v_correction.final_settlement_id,p_draft,v_position::integer)->>'id')::uuid;
        END LOOP;
        -- DL-032 steps 3 to 5: each Deposit application, in the plan's order, numbered after the
        -- Settlement's last; the remaining Pet Deposit records the staff reason of its step 5 decision.
        SELECT COALESCE(max(application.application_order),0) INTO v_order FROM app.deposit_applications application
        WHERE application.final_settlement_id=v_correction.final_settlement_id;
        FOR v_item IN SELECT step.value
            FROM jsonb_array_elements(v_plan->'steps') WITH ORDINALITY AS step(value,ordinality)
            WHERE step.value->>'kind' IN ('PET_DEPOSIT_PET_DAMAGE','SECURITY_DEPOSIT','PET_DEPOSIT_REMAINDER')
            ORDER BY step.ordinality
        LOOP
            v_order:=v_order+1;
            v_reason:=v_draft.reason;
            IF v_item->>'kind'='PET_DEPOSIT_REMAINDER' THEN
                v_reason:=v_plan->'pet_remainder'->>'staff_reason';
            END IF;
            v_id:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(v_correction.id,'deposit_application_id',v_id);
            PERFORM app.post_deposit_application(p_property,p_approver,v_correction.final_settlement_id,v_id,
                app.final_settlement_plan_id(v_item->'deposit_id')::uuid,
                CASE v_item->>'kind' WHEN 'PET_DEPOSIT_PET_DAMAGE' THEN 'PET_RELATED_FIRST'
                    WHEN 'SECURITY_DEPOSIT' THEN 'SECURITY_EXPLICIT' ELSE 'PET_REMAINDER_EXPLICIT' END,
                v_item->>'target_kind',app.final_settlement_plan_id(v_item->'target_id')::uuid,
                (v_item->>'amount_usd_cents')::bigint,v_order,v_reason);
            v_application_ids:=v_application_ids||v_id;
        END LOOP;
        -- DL-032 step 7: the Deposit Refunds, in Deposit id order.
        FOR v_item IN SELECT step.value FROM jsonb_array_elements(v_plan->'steps') step
            WHERE step.value->>'kind'='DEPOSIT_REFUNDS'
            ORDER BY app.final_settlement_plan_id(step.value->'deposit_id')::uuid
        LOOP
            v_refund_ids:=v_refund_ids||(app.post_settlement_correction_deposit_refund(p_property,p_approver,
                v_correction.id,p_draft,app.final_settlement_plan_id(v_item->'deposit_id')::uuid,
                (v_item->>'amount_usd_cents')::bigint,
                app.final_settlement_plan_id(v_item->'recipient_customer_id')::uuid,
                app.final_settlement_plan_id(v_item->'refund_method_id')::uuid,v_item->>'reference_note',
                CASE WHEN jsonb_typeof(v_item->'signer_agreement')='string' THEN v_item->>'signer_agreement' END,
                v_draft.reason)->>'refund_id')::uuid;
        END LOOP;
        RETURN jsonb_build_object('settlement_correction_id',v_correction.id,
            'credit_application_ids',to_jsonb(v_credit_ids),
            'deposit_application_ids',to_jsonb(v_application_ids),'refund_ids',to_jsonb(v_refund_ids),
            'credit_ids',v_map,'credit_left',v_left,
            'closing_balance_usd_cents',v_result->'closing_balance_usd_cents',
            'closing_balances',v_result->'closing_balances');
    END $$;
"""


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
            raise RuntimeError(f"Settlement correction plan source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(STEP_SQL)
    _patch(CREDIT_WRITER, CREDIT_WRITER_REPLACEMENTS)
    _patch(CREDIT_SOURCE, CREDIT_SOURCE_REPLACEMENTS)
    _patch(CREDIT_CONFIRMED, CREDIT_CONFIRMED_REPLACEMENTS)
    _patch(DEPOSIT_APPLICATION, DEPOSIT_APPLICATION_REPLACEMENTS)
    _patch(REFUND_SOURCE, REFUND_SOURCE_REPLACEMENTS)
    _patch(CREDIT_REFUND_ALLOWED, CREDIT_REFUND_ALLOWED_REPLACEMENTS)
    _patch(REFUND_DETAIL, REFUND_DETAIL_REPLACEMENTS)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Settlement correction plan migration is forward-only")
