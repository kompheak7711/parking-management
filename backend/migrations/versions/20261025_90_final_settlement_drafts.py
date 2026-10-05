# ruff: noqa: E501
"""Final Settlement drafts (V1-056 sub-slice 8c).

BR-AUTH-010, BR-SETTLE-004 to BR-SETTLE-008, BR-SETTLE-017, BR-DEP-027, BR-CREDIT-006,
BR-CREDIT-008, DL-032; owner answers to Q-2026-10-05-20 (strict order), Q-2026-10-05-21,
Q-2026-10-05-23 (answer 4), Q-2026-10-05-25, Q-2026-10-05-28 and Q-2026-10-05-29.

- app.record_final_settlement_draft (financial role; the application checks
  final_settlements.prepare) records the FINAL_SETTLEMENT draft of one open Final Settlement: the
  DL-032 steps in order with amounts in cents (Customer Credit, Pet Deposit to pet damage,
  Security Deposit, remaining Pet Deposit, Deposit Refunds with method, reference note and
  recipient), the Customer's choice or the staff reason for the remaining Pet Deposit, the
  expected closing balance and a digest of every Settlement source (the source revision). It has
  no financial effect; the confirm comes in sub-slice 8e. It is refused while the preview shows a
  blocking issue, while another draft of the Settlement waits, and when the plan breaks the strict
  order (owner answer 3 to Q-2026-10-05-20) or the Credit rules (owner answers to
  Q-2026-10-05-29: each Customer's Credit pays that Customer's own open debt, up to what it can
  pay, before any Deposit; on an Invoice with Rent or Service lines it follows the Rent-first
  proposal unless the Customer designated the line, BR-CREDIT-006). Withdraw and reject use the
  slice 2 functions.
- app.final_settlement_plan_result (internal) checks a plan against the current preview and, in
  the same call and snapshot, returns the source revision: the digest of
  app.final_settlement_source_state (internal). One exception: the preview's Late-payment review
  (app.late_payment_review_snapshot, an earlier VOLATILE function) reads its own snapshot; a
  Late-payment Charge it sees that the digest does not makes the draft stale, which fails safe.
  The confirm (8e) calls it again and must serialize with Late-payment Decisions first.
- Owner answer 4 to Q-2026-10-05-23: a receipt reversal draft is not recorded or confirmed while a
  Final Settlement draft that applies or refunds that Deposit waits, and a Final Settlement draft
  is not confirmed while a receipt reversal draft of a Deposit it uses waits. A receipt reversal
  draft already waiting blocks the Settlement draft through the preview's pending-draft issue.
- Owner answer to Q-2026-10-05-28: the preview also lists, under "information", each one-time
  charge a draft correction replaced, with the charge that replaced it, on any Lease or none.

Every change is additive: new functions, and checks that see a draft kind no function could
record before this migration.
"""

from alembic import op
from sqlalchemy import text

revision = "20261025_90"
down_revision = "20261024_89"
branch_labels = None
depends_on = None

RECORD = "app.record_final_settlement_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
INTERNAL = (
    "app.final_settlement_plan_id(jsonb)",
    "app.final_settlement_source_state(uuid,uuid)",
    "app.final_settlement_plan_result(uuid,uuid,uuid,jsonb)",
    "app.final_settlement_rent_first_line(uuid,jsonb)",
)
PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"
RECEIPT_GUARD = "app.validate_deposit_receipt_reversal()"
RECEIPT_RECORD = "app.record_deposit_receipt_reversal_draft(uuid,uuid,uuid,uuid,uuid,text,text)"
WAIT_GUARD = "app.refuse_confirmation_during_receipt_reversal_draft()"

REPLACED_BEFORE = (
    "                    'replaced',EXISTS(SELECT 1 FROM app.invoice_draft_revision_events revision\n"
    "                        WHERE revision.entity_kind='LINE' AND revision.operation='UPDATE'\n"
    "                          AND revision.before_state->>'authorized_obligation_id'=obligation.id::text\n"
    "                          AND revision.after_state->>'authorized_obligation_id'\n"
    "                              IS DISTINCT FROM obligation.id::text))\n"
)
REPLACED_AFTER = (
    "                    'replaced',EXISTS(SELECT 1 FROM app.invoice_draft_revision_events revision\n"
    "                        WHERE revision.entity_kind='LINE' AND revision.operation='UPDATE'\n"
    "                          AND revision.before_state->>'authorized_obligation_id'=obligation.id::text\n"
    "                          AND revision.after_state->>'authorized_obligation_id'\n"
    "                              IS DISTINCT FROM obligation.id::text),\n"
    "                    -- The charge that replaced it, from the latest draft correction (Q-2026-10-05-28).\n"
    "                    'replacement_authorized_obligation_id',(SELECT revision.after_state->'authorized_obligation_id'\n"
    "                        FROM app.invoice_draft_revision_events revision\n"
    "                        WHERE revision.entity_kind='LINE' AND revision.operation='UPDATE'\n"
    "                          AND revision.before_state->>'authorized_obligation_id'=obligation.id::text\n"
    "                          AND revision.after_state->>'authorized_obligation_id'\n"
    "                              IS DISTINCT FROM obligation.id::text\n"
    "                        ORDER BY revision.id DESC LIMIT 1))\n"
)
INFORMATION_BEFORE = "                WHERE (item->>'voided')::boolean),'[]'::jsonb);\n"
INFORMATION_AFTER = (
    "                WHERE (item->>'voided')::boolean),'[]'::jsonb)\n"
    "                -- A charge a draft correction replaced, with the charge that replaced it, whether that\n"
    "                -- charge is on this Lease, another Lease or no Lease (owner answer to Q-2026-10-05-28).\n"
    "                ||COALESCE((SELECT jsonb_agg(jsonb_build_object('code','CHARGE_REPLACED_BY_DRAFT_CORRECTION',\n"
    "                    'authorized_obligation_id',item->'authorized_obligation_id',\n"
    "                    'customer_id',item->'customer_id','category',item->'category',\n"
    "                    'amount_usd_cents',item->'amount_usd_cents',\n"
    "                    'replacement_authorized_obligation_id',item->'replacement_authorized_obligation_id',\n"
    "                    'replacement_lease_id',(SELECT replacement.lease_id\n"
    "                        FROM app.authorized_nonrecurring_obligations replacement\n"
    "                        WHERE replacement.id=(item->>'replacement_authorized_obligation_id')::uuid))\n"
    "                    ORDER BY entry.ordinal)\n"
    "                FROM jsonb_array_elements(v_unbilled) WITH ORDINALITY AS entry(item,ordinal)\n"
    "                WHERE (item->>'replaced')::boolean),'[]'::jsonb);\n"
)
RECEIPT_GUARD_BEFORE = (
    "                      OR draft.payload->>'deposit_id' = deposit.id::text)\n"
    "                 AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE')\n"
)
RECEIPT_GUARD_AFTER = (
    "                      OR draft.payload->>'deposit_id' = deposit.id::text)\n"
    "                 AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE')\n"
    "                  OR (draft.kind = 'FINAL_SETTLEMENT'\n"
    "                      AND draft.payload->'deposit_ids' @> jsonb_build_array(deposit.id))\n"
)
RECEIPT_RECORD_BEFORE = (
    "                      OR draft.payload->>'reservation_id'=deposit.reservation_id::text)\n"
    "                 AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE')\n"
)
RECEIPT_RECORD_AFTER = (
    "                      OR draft.payload->>'reservation_id'=deposit.reservation_id::text)\n"
    "                 AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE')\n"
    "                  OR (draft.kind='FINAL_SETTLEMENT'\n"
    "                      AND draft.payload->'deposit_ids' @> jsonb_build_array(deposit.id))\n"
)
WAIT_GUARD_BEFORE = (
    "            SELECT * INTO v_draft FROM app.financial_drafts WHERE id=NEW.draft_id;\n"
)
WAIT_GUARD_AFTER = (
    "            SELECT * INTO v_draft FROM app.financial_drafts WHERE id=NEW.draft_id;\n"
    "            -- A Final Settlement draft that applies or refunds a Deposit waits for a receipt\n"
    "            -- reversal draft of that Deposit (owner answer 4 to Q-2026-10-05-23; sub-slice 8c).\n"
    "            IF v_draft.kind='FINAL_SETTLEMENT' THEN\n"
    "                IF EXISTS (SELECT 1 FROM app.financial_drafts reversal\n"
    "                    WHERE reversal.kind='DEPOSIT_FORFEITURE'\n"
    "                      AND reversal.payload->>'variant'='DEPOSIT_RECEIPT_REVERSAL'\n"
    "                      AND v_draft.payload->'deposit_ids' @> jsonb_build_array(reversal.payload->>'deposit_id')\n"
    "                      AND NOT EXISTS (SELECT 1 FROM app.financial_draft_decisions decision\n"
    "                          WHERE decision.draft_id=reversal.id))\n"
    "                THEN RAISE EXCEPTION 'A Deposit receipt reversal draft for this Deposit is waiting'\n"
    "                    USING ERRCODE='55000'; END IF;\n"
    "                RETURN NEW;\n"
    "            END IF;\n"
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
            raise RuntimeError(f"Final Settlement draft source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    _patch(PREVIEW, ((REPLACED_BEFORE, REPLACED_AFTER), (INFORMATION_BEFORE, INFORMATION_AFTER)))
    _patch(RECEIPT_GUARD, ((RECEIPT_GUARD_BEFORE, RECEIPT_GUARD_AFTER),))
    _patch(RECEIPT_RECORD, ((RECEIPT_RECORD_BEFORE, RECEIPT_RECORD_AFTER),))
    _patch(WAIT_GUARD, ((WAIT_GUARD_BEFORE, WAIT_GUARD_AFTER),))
    op.execute("""
        -- A plan identity: a JSON string holding a nonzero UUID, in its canonical text, or NULL.
        CREATE FUNCTION app.final_settlement_plan_id(p_value jsonb)
        RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
            SELECT CASE WHEN jsonb_typeof(p_value)='string' AND (p_value#>>'{}')
                ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN CASE WHEN (p_value#>>'{}')::uuid<>'00000000-0000-0000-0000-000000000000'::uuid
                THEN (p_value#>>'{}')::uuid::text END END
        $$;

        -- The state of every Settlement source in a fixed order: the Settlement, each Invoice of the
        -- Lease with its version and open lines, the Late-payment Charges, the Credit of every
        -- Customer of the Lease and the Lease's Deposits. Its digest is a draft's source revision;
        -- the confirm (8e) recomputes it, so a draft whose sources changed is stale.
        CREATE FUNCTION app.final_settlement_source_state(p_property uuid,p_settlement uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_settlement app.final_settlements%ROWTYPE; v_lease app.leases%ROWTYPE; v_people uuid[];
        BEGIN
            SELECT * INTO v_settlement FROM app.final_settlements
            WHERE id=p_settlement AND property_id=p_property;
            IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_settlement.lease_id;
            SELECT array_agg(people.person ORDER BY people.person) INTO v_people FROM (
                SELECT v_lease.primary_tenant_id AS person
                UNION SELECT invoice.customer_id FROM app.invoices invoice WHERE invoice.lease_id=v_lease.id
                UNION SELECT charge.customer_id FROM app.late_payment_charges charge
                    JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                    WHERE invoice.lease_id=v_lease.id
            ) people;
            RETURN jsonb_build_object(
                'settlement',jsonb_build_object('id',v_settlement.id,'closed_at',v_settlement.closed_at),
                'invoices',COALESCE((SELECT jsonb_agg(jsonb_build_object('invoice_id',invoice.id,
                        'status',invoice.status,'version',invoice.version,'customer_id',invoice.customer_id,
                        'latest_at',app.allocation_target_latest_at('INVOICE',invoice.id),
                        'lines',(SELECT COALESCE(jsonb_agg(jsonb_build_object('invoice_line_id',line.id,
                                'outstanding_usd_cents',app.invoice_line_outstanding(line.id)) ORDER BY line.id),
                                '[]'::jsonb)
                            FROM app.invoice_lines line WHERE line.invoice_id=invoice.id
                              AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID')))
                        ORDER BY invoice.id)
                    FROM app.invoices invoice WHERE invoice.lease_id=v_lease.id),'[]'::jsonb),
                'late_payment_charges',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                        'late_payment_charge_id',charge.id,
                        'remaining_usd_cents',position.remaining_balance_usd_cents,
                        'latest_at',app.allocation_target_latest_at('LATE_PAYMENT_CHARGE',charge.id))
                        ORDER BY charge.id)
                    FROM app.late_payment_charges charge
                    JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                    JOIN app.late_payment_charge_financial_position position
                        ON position.late_payment_charge_id=charge.id
                    WHERE invoice.lease_id=v_lease.id),'[]'::jsonb),
                'credits',COALESCE((SELECT jsonb_agg(jsonb_build_object('customer_credit_id',credit.id,
                        'available_usd_cents',app.credit_available_value(credit.id)) ORDER BY credit.id)
                    FROM app.customer_credits credit JOIN app.payments payment ON payment.id=credit.source_payment_id
                    WHERE credit.customer_id=ANY(v_people) AND payment.property_id=p_property),'[]'::jsonb),
                'deposits',COALESCE((SELECT jsonb_agg(jsonb_build_object('deposit_id',deposit.id,
                        'state_version',app.deposit_disposition_state_version(deposit.id),
                        'held_usd_cents',app.deposit_held_value_at(deposit.id,'infinity')) ORDER BY deposit.id)
                    FROM app.deposits deposit WHERE deposit.lease_id=v_lease.id),'[]'::jsonb));
        END $$;

        -- BR-CREDIT-006 (owner answer 1 to Q-2026-10-05-29): on an Invoice with Rent or Service
        -- lines, Credit without the Customer's designation follows the Rent-first, then recurring
        -- Service proposal order (the order of app.credit_application_proposal). Returns the first
        -- line of that Invoice in that order that still owes in p_open ('INVOICE_LINE:<id>' keys),
        -- or NULL when the Invoice has no Rent or Service line.
        CREATE FUNCTION app.final_settlement_rent_first_line(p_invoice uuid,p_open jsonb)
        RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT line.id FROM app.invoice_lines line
            WHERE line.invoice_id=p_invoice
              AND EXISTS(SELECT 1 FROM app.invoice_lines mixed
                  WHERE mixed.invoice_id=p_invoice AND mixed.category IN ('RENT','SERVICE_CHARGES'))
              AND COALESCE((p_open->>('INVOICE_LINE:'||line.id::text))::bigint,0)>0
            ORDER BY CASE line.category WHEN 'RENT' THEN 0 WHEN 'SERVICE_CHARGES' THEN 1 ELSE 2 END,
                line.line_sequence,line.id
            LIMIT 1
        $$;

        -- Checks a Final Settlement plan against the current preview and returns what the draft
        -- records. Malformed input is 22023; a plan the current Settlement does not allow is 55000.
        -- Strict order (owner answer 3 to Q-2026-10-05-20; answer 2 to Q-2026-10-05-29): each
        -- Customer's Credit pays that Customer's own open debt, up to what it can pay, before any
        -- Deposit pays; pet damage before any other Pet Deposit use or Refund; and no Deposit
        -- Refund while the Lease still has open debt that the Deposit could pay. Without the
        -- Customer's choice a Pet Deposit at a BR-DEP-027 termination cannot pay other debt, so its
        -- Refund does not wait for that debt (Q-2026-10-05-21). Every Deposit that follows DL-032
        -- ends with nothing held (BR-SETTLE-008). Staff choose every step; nothing is inferred
        -- between Deposit types (BR-SETTLE-006). Everything, the source revision included, is read
        -- in one STABLE call, so the plan check and the digest describe the same state (except the
        -- preview's VOLATILE Late-payment review, which reads its own snapshot and fails safe).
        CREATE FUNCTION app.final_settlement_plan_result(p_property uuid,p_actor uuid,p_settlement uuid,
            p_plan jsonb)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_preview jsonb; v_open jsonb; v_owner jsonb; v_pet text[]; v_credit jsonb; v_credit_owner jsonb;
            v_may_use jsonb; v_held jsonb; v_type jsonb; v_left jsonb; v_used_credit jsonb:='{}'::jsonb;
            v_invoice_of jsonb; v_first uuid; v_refund jsonb:='{}'::jsonb; v_step_five boolean:=false;
            v_chosen_by text; v_primary uuid; v_lease uuid; v_item jsonb; v_step integer; v_last integer:=0;
            v_amount bigint; v_key text; v_target_left bigint; v_credit_id text; v_deposit text;
            v_pet_after_three bigint; v_basis jsonb; v_closing bigint; v_keys text[]; v_expected text[];
            v_method text; v_recipient text;
        BEGIN
            IF p_plan IS NULL OR jsonb_typeof(p_plan)<>'object'
                OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_plan) key WHERE key NOT IN ('steps','pet_remainder'))
                OR jsonb_typeof(p_plan->'steps') IS DISTINCT FROM 'array'
                OR jsonb_array_length(p_plan->'steps')>200
                OR COALESCE(jsonb_typeof(p_plan->'pet_remainder'),'null') NOT IN ('null','object')
            THEN RAISE EXCEPTION 'Final Settlement plan is invalid' USING ERRCODE='22023'; END IF;
            v_preview:=app.final_settlement_preview(p_property,p_actor,p_settlement,
                ARRAY['final_settlements.prepare']);
            IF (v_preview->>'ready')::boolean IS NOT TRUE THEN
                RAISE EXCEPTION 'The Final Settlement has blocking issues' USING ERRCODE='55000'; END IF;
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
            SELECT COALESCE(jsonb_object_agg(person->>'customer_id',person->'credit_may_use_usd_cents'),'{}'::jsonb)
            INTO v_may_use FROM jsonb_array_elements(v_preview->'customers') person;
            SELECT COALESCE(jsonb_object_agg(credit->>'customer_credit_id',credit->'available_usd_cents'),'{}'::jsonb),
                COALESCE(jsonb_object_agg(credit->>'customer_credit_id',person->'customer_id'),'{}'::jsonb)
            INTO v_credit,v_credit_owner
            FROM jsonb_array_elements(v_preview->'customers') person,jsonb_array_elements(person->'credits') credit;
            -- Only a Deposit that follows DL-032 and holds money may be applied or refunded.
            SELECT COALESCE(jsonb_object_agg(deposit->>'deposit_id',deposit->'held_usd_cents'),'{}'::jsonb),
                COALESCE(jsonb_object_agg(deposit->>'deposit_id',deposit->'deposit_type'),'{}'::jsonb)
            INTO v_held,v_type
            FROM jsonb_array_elements(v_preview->'deposits') deposit
            WHERE deposit->>'path'='DL_032' AND (deposit->>'held_usd_cents')::bigint>0;
            v_left:=v_held;

            FOR v_item IN SELECT value FROM jsonb_array_elements(p_plan->'steps') LOOP
                v_step:=CASE WHEN jsonb_typeof(v_item)='object' THEN CASE v_item->>'kind'
                    WHEN 'CUSTOMER_CREDIT' THEN 2 WHEN 'PET_DEPOSIT_PET_DAMAGE' THEN 3
                    WHEN 'SECURITY_DEPOSIT' THEN 4 WHEN 'PET_DEPOSIT_REMAINDER' THEN 5
                    WHEN 'DEPOSIT_REFUNDS' THEN 7 END END;
                IF v_step IS NULL THEN
                    RAISE EXCEPTION 'Final Settlement step kind is invalid' USING ERRCODE='22023'; END IF;
                IF v_step<v_last THEN
                    RAISE EXCEPTION 'Final Settlement steps must follow the DL-032 order' USING ERRCODE='22023'; END IF;
                -- The pet damage still open once step 3 ends.
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
                THEN RAISE EXCEPTION 'Final Settlement step is invalid' USING ERRCODE='22023'; END IF;
                v_amount:=(v_item->>'amount_usd_cents')::bigint;
                IF v_amount>9000000000000000 THEN
                    RAISE EXCEPTION 'Final Settlement step is invalid' USING ERRCODE='22023'; END IF;
                IF v_step<7 THEN
                    IF COALESCE(v_item->>'target_kind','') NOT IN ('INVOICE_LINE','LATE_PAYMENT_CHARGE')
                        OR app.final_settlement_plan_id(v_item->'target_id') IS NULL
                        OR app.final_settlement_plan_id(v_item->CASE WHEN v_step=2 THEN 'customer_credit_id'
                            ELSE 'deposit_id' END) IS NULL
                    THEN RAISE EXCEPTION 'Final Settlement step is invalid' USING ERRCODE='22023'; END IF;
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
                        -- BR-CREDIT-006: the Customer's designation as text (who, the date, how), or
                        -- on an Invoice with Rent or Service lines the Rent-first proposal order.
                        IF jsonb_typeof(v_item->'customer_designation') NOT IN ('null','string')
                            OR (jsonb_typeof(v_item->'customer_designation')='string'
                                AND app.lease_notice_text_valid(v_item->>'customer_designation',500) IS NOT TRUE)
                        THEN RAISE EXCEPTION 'Final Settlement step is invalid' USING ERRCODE='22023'; END IF;
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
                    THEN RAISE EXCEPTION 'Final Settlement Refund step is invalid' USING ERRCODE='22023'; END IF;
                    IF v_refund ? v_deposit THEN
                        RAISE EXCEPTION 'A Deposit has at most one Refund in a Final Settlement draft'
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

            -- The remaining Pet Deposit (DL-032 step 5): the Customer's choice (who, the date, how)
            -- with the staff reason, or, outside the BR-DEP-027 terminations, the staff reason when
            -- the Customer will not pay (BR-SETTLE-005, BR-SETTLE-017, BR-DEP-027).
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
            -- Owner answer 2 to Q-2026-10-05-29: each Customer's Credit pays that Customer's own open
            -- debt, up to what it can pay (the lower of the Credit available and that debt), before
            -- any Deposit pays (step 2 comes first); never another Customer's debt (checked above).
            IF EXISTS(SELECT 1 FROM jsonb_each_text(v_may_use) item
                WHERE COALESCE((v_used_credit->>item.key)::bigint,0)<item.value::bigint)
            THEN RAISE EXCEPTION 'Each Customer''s Credit must pay that Customer''s open debt, up to what it can pay, before any Deposit pays'
                USING ERRCODE='55000'; END IF;
            -- Owner answer 3 (ii): the Pet Deposit pays open pet damage before any other use or Refund.
            IF v_pet_after_three>0 AND (v_step_five OR EXISTS(SELECT 1 FROM jsonb_object_keys(v_refund) deposit
                WHERE v_type->>deposit='PET'))
            THEN RAISE EXCEPTION 'The Pet Deposit pays open pet damage before any other use or Refund'
                USING ERRCODE='55000'; END IF;
            SELECT COALESCE(sum(item.value::bigint),0) INTO v_closing FROM jsonb_each_text(v_open) item;
            -- Owner answer 3 (iii): no Deposit Refund while the Lease still has open debt that the
            -- Deposit could pay.
            IF v_closing>0 AND EXISTS(SELECT 1 FROM jsonb_object_keys(v_refund) deposit
                WHERE v_type->>deposit='SECURITY' OR v_chosen_by='CUSTOMER_OR_STAFF_WITH_REASON')
            THEN RAISE EXCEPTION 'No Deposit Refund while the Lease still has open debt that the Deposit could pay'
                USING ERRCODE='55000'; END IF;

            RETURN jsonb_build_object('lease_id',v_lease,
                'termination_ground',v_preview->'lease'->'termination_ground',
                'pet_remainder_chosen_by',v_chosen_by,
                'deposit_ids',(SELECT COALESCE(jsonb_agg(key ORDER BY key),'[]'::jsonb) FROM jsonb_object_keys(v_held) key),
                'open_total_usd_cents',v_preview->'open_total_usd_cents',
                'closing_balance_usd_cents',v_closing,
                'closing_balances',(SELECT COALESCE(jsonb_agg(jsonb_build_object('customer_id',owed.customer,
                        'open_usd_cents',owed.total) ORDER BY owed.customer<>v_primary::text,owed.customer),'[]'::jsonb)
                    FROM (SELECT v_owner->>item.key AS customer,sum(item.value::bigint) AS total
                        FROM jsonb_each_text(v_open) item GROUP BY 1 HAVING sum(item.value::bigint)>0) owed),
                -- The digest of every Settlement source, read in this same call (same snapshot).
                'source_revision','final-settlement:' || encode(sha256(convert_to(
                    app.final_settlement_source_state(p_property,p_settlement)::text,'UTF8')),'hex'));
        END $$;

        -- Staff record the Final Settlement draft (final_settlements.prepare); it has no financial
        -- effect until a financial.approve holder confirms it (sub-slice 8e).
        CREATE FUNCTION app.record_final_settlement_draft(p_property uuid,p_actor uuid,p_draft uuid,
            p_settlement uuid,p_plan jsonb,p_reason text,p_authorization text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_existing app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
            v_deposit uuid; v_result jsonb; v_payload jsonb;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property,p_actor);
            PERFORM app.assert_active_financial_actor(p_actor,p_property);
            IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
                RAISE EXCEPTION 'Final Settlement draft authorization is invalid' USING ERRCODE='42501'; END IF;
            IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
                OR p_plan IS NULL OR app.lease_notice_text_valid(p_reason,1000) IS NOT TRUE
            THEN RAISE EXCEPTION 'Final Settlement draft input is invalid' USING ERRCODE='22023'; END IF;
            -- An exact repeat replays before any current-state check.
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
            SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
            IF FOUND THEN
                IF v_existing.property_id=p_property AND v_existing.kind='FINAL_SETTLEMENT'
                    AND v_existing.prepared_by=p_actor AND v_existing.reason=p_reason
                    AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                    AND v_existing.payload->'steps'=p_plan->'steps'
                    AND v_existing.payload->'pet_remainder'=COALESCE(p_plan->'pet_remainder','null'::jsonb)
                THEN RETURN app.financial_draft_json(v_existing); END IF;
                RAISE EXCEPTION 'Final Settlement draft identity was reused' USING ERRCODE='P5205';
            END IF;
            SELECT * INTO v_settlement FROM app.final_settlements WHERE id=p_settlement AND property_id=p_property;
            IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
            -- One pending draft per Settlement.
            PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || p_settlement::text,0));
            IF EXISTS(SELECT 1 FROM app.financial_drafts draft
                WHERE draft.property_id=p_property AND draft.kind='FINAL_SETTLEMENT'
                  AND draft.payload->>'final_settlement_id'=p_settlement::text
                  AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                      WHERE decision.draft_id=draft.id))
            THEN RAISE EXCEPTION 'A Final Settlement draft is already waiting' USING ERRCODE='55000'; END IF;
            -- The Lease's Deposits in a fixed order, with the per-Deposit lock of the other Deposit
            -- drafts and the Deposit row lock of the receipt reversal recorder: a receipt reversal
            -- draft being recorded is waited for and then seen as a pending draft (READ COMMITTED),
            -- and that recorder waits for this draft and then sees it.
            FOR v_deposit IN SELECT deposit.id FROM app.deposits deposit
                WHERE deposit.lease_id=v_settlement.lease_id ORDER BY deposit.id
            LOOP
                PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || v_deposit::text,0));
                PERFORM 1 FROM app.deposits WHERE id=v_deposit FOR UPDATE;
            END LOOP;
            v_result:=app.final_settlement_plan_result(p_property,p_actor,p_settlement,p_plan);
            -- One call checks the plan and computes the source revision on the same snapshot.
            v_payload:=jsonb_build_object('variant','FINAL_SETTLEMENT','final_settlement_id',p_settlement,
                'steps',p_plan->'steps','pet_remainder',COALESCE(p_plan->'pet_remainder','null'::jsonb))
                || (v_result-'source_revision');
            IF octet_length(v_payload::text)>16000 THEN
                RAISE EXCEPTION 'The Final Settlement draft exceeds the stored draft size of 16000 bytes'
                    USING ERRCODE='22023'; END IF;
            RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'FINAL_SETTLEMENT',
                'final_settlements.prepare',v_payload,v_result->>'source_revision',p_reason);
        END $$;
    """)
    for function in (RECORD, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Final Settlement draft migration is forward-only")
