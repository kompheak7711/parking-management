# ruff: noqa: E501
"""Post-settlement correction: pet classification of a Damage line (V1-056 sub-slice 10c-2a-5).

DL-032, BR-SETTLE-008, BR-SETTLE-012, BR-SETTLE-013, BR-DEP-027, BR-AUTH-010; owner answer to
Q-2026-10-07-45 (option (a)), answer 3 to Q-2026-10-07-44:

- A new correction kind, variant PET_DAMAGE_RECLASSIFICATION, for one Damage line whose pet
  classification is wrong after closure, in both directions. Staff record it under
  final_settlements.prepare with a reason and an evidence reference; only a financial.approve
  holder confirms it. The charge amount stays the same and the closed inspection record is not
  changed: the correction writes an append-only classification record (DB-SETTLE-007), linked to
  it (DB-SETTLE-005 settlement_pet_classification_id), and app.invoice_line_is_pet_damage reads the
  line's latest record before the inspection.
- The confirm reverses the line's Deposit applications where the corrected classification changes
  which Deposit should pay: to not pet damage, its Pet-Deposit-first applications; to pet damage,
  its Security Deposit applications while a Pet Deposit of the Lease holds money. Each is reversed
  whole (sub-slice 10c-2a-1). It then runs the shared DL-032 step after closure (sub-slice
  10c-2a-2) with every Settlement rule and, at a BR-DEP-027 termination, a Customer choice given
  for this correction. A Deposit refunded at closure is not taken back.
- The step's plan check reads the corrected classification from the draft's overlay before the
  record exists; the lock function takes the line's Invoice FOR UPDATE in its Invoice pass.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from sqlalchemy import text

revision = "20261109_105"
down_revision = "20261108_104"
branch_labels = None
depends_on = None

VARIANT = "PET_DAMAGE_RECLASSIFICATION"

INTERNAL = (
    "app.settlement_pet_classification_line(uuid,uuid)",
    "app.validate_settlement_pet_classification()",
    "app.settlement_pet_classification_input(jsonb)",
    "app.settlement_pet_classification_reversals(uuid,uuid,boolean)",
    "app.settlement_pet_classification_source_state(uuid,uuid,uuid)",
    "app.settlement_pet_classification_plan(uuid,uuid,jsonb)",
    "app.settlement_pet_classification_overlay(jsonb,uuid,boolean)",
    "app.settlement_pet_classification_result(uuid)",
)
RECORD = "app.record_settlement_pet_classification_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_pet_classification(uuid,uuid,uuid,text)"

PLAN_RESULT = "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)"
PLAN_RESULT_REPLACEMENTS = (
    (
        "            OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(p_overlay) key)\n"
        "                IS DISTINCT FROM ARRAY['credits','deposits','obligations']\n",
        "            OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(p_overlay) key\n"
        "                    WHERE key<>'pet_damage')\n"
        "                IS DISTINCT FROM ARRAY['credits','deposits','obligations']\n"
        "            -- Sub-slice 10c-2a-5: a pet classification correction's corrected classification of\n"
        "            -- its line, a Damage line key with true or false.\n"
        "            OR jsonb_typeof(COALESCE(p_overlay->'pet_damage','{}'::jsonb)) IS DISTINCT FROM 'object'\n"
        "            OR EXISTS(SELECT 1 FROM jsonb_each(COALESCE(p_overlay->'pet_damage','{}'::jsonb)) item\n"
        "                WHERE split_part(item.key,':',1)<>'INVOICE_LINE'\n"
        "                   OR app.final_settlement_plan_id(to_jsonb(substr(item.key,strpos(item.key,':')+1)))\n"
        "                       IS DISTINCT FROM substr(item.key,strpos(item.key,':')+1)\n"
        "                   OR jsonb_typeof(item.value) IS DISTINCT FROM 'boolean')\n",
    ),
    (
        "        v_open_start:=v_open;\n",
        "        v_open_start:=v_open;\n"
        "        -- Sub-slice 10c-2a-5: a pet classification correction's draft is checked under the\n"
        "        -- corrected classification of its line before the classification record exists; at\n"
        "        -- the step the record exists and the overlay has no such key.\n"
        "        FOR v_entry IN SELECT item.key,item.value\n"
        "            FROM jsonb_each(COALESCE(p_overlay->'pet_damage','{}'::jsonb)) item\n"
        "        LOOP\n"
        "            IF NOT EXISTS(SELECT 1 FROM app.invoice_lines line\n"
        "                JOIN app.invoices invoice ON invoice.id=line.invoice_id\n"
        "                WHERE line.id=split_part(v_entry.key,':',2)::uuid AND invoice.lease_id=v_lease\n"
        "                  AND line.category='DAMAGE_CHARGES'\n"
        "                  AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID'))\n"
        "            THEN RAISE EXCEPTION 'The overlay names an obligation outside this Final Settlement'\n"
        "                USING ERRCODE='55000'; END IF;\n"
        "            v_pet:=array_remove(v_pet,v_entry.key);\n"
        "            IF v_entry.value='true'::jsonb THEN v_pet:=v_pet||v_entry.key; END IF;\n"
        "        END LOOP;\n",
    ),
)

LOCK_PLAN = "app.lock_settlement_correction_plan(uuid)"
LOCK_PLAN_REPLACEMENTS = (
    (
        "        IF v_draft.payload->>'variant'='REFUND' THEN\n"
        "            v_target_invoices:=v_target_invoices\n"
        "                ||ARRAY[app.final_settlement_plan_id(v_draft.payload->'refund'->'invoice_id')::uuid];\n"
        "        END IF;\n",
        "        IF v_draft.payload->>'variant'='REFUND' THEN\n"
        "            v_target_invoices:=v_target_invoices\n"
        "                ||ARRAY[app.final_settlement_plan_id(v_draft.payload->'refund'->'invoice_id')::uuid];\n"
        "        END IF;\n"
        "        -- Sub-slice 10c-2a-5: a pet classification correction's line Invoice, FOR UPDATE in the\n"
        "        -- same Invoice pass (its Deposit application reversals lock the Deposit, then it).\n"
        "        IF v_draft.payload->>'variant'='PET_DAMAGE_RECLASSIFICATION' THEN\n"
        "            v_target_invoices:=v_target_invoices\n"
        "                ||ARRAY[app.final_settlement_plan_id(v_draft.payload->'classification'->'invoice_id')::uuid];\n"
        "        END IF;\n",
    ),
)

TABLE_SQL = r"""
    -- DB-SETTLE-007 (owner answer to Q-2026-10-07-45): the corrected pet classification of one
    -- Damage line, written only by a post-settlement correction of the line's own (closed)
    -- Settlement. The closed inspection record is never changed.
    CREATE TABLE app.settlement_pet_classifications (
        id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'),
        settlement_correction_id uuid NOT NULL UNIQUE
            REFERENCES app.settlement_corrections(id) ON DELETE RESTRICT,
        invoice_line_id uuid NOT NULL REFERENCES app.invoice_lines(id) ON DELETE RESTRICT,
        pet_related boolean NOT NULL,
        evidence_reference text NOT NULL CHECK (app.lease_notice_text_valid(evidence_reference,500)),
        reason text NOT NULL CHECK (app.lease_notice_text_valid(reason,500)),
        recorded_at timestamptz NOT NULL CHECK (isfinite(recorded_at)),
        actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
        authorization_reference text NOT NULL CHECK (authorization_reference='financial.approve')
    );
    CREATE INDEX settlement_pet_classifications_line
        ON app.settlement_pet_classifications(invoice_line_id,recorded_at,id);
    CREATE TRIGGER settlement_pet_classifications_append_only BEFORE UPDATE OR DELETE
        ON app.settlement_pet_classifications
        FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation();
    CREATE TRIGGER settlement_pet_classifications_no_truncate BEFORE TRUNCATE
        ON app.settlement_pet_classifications
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate();
"""

FUNCTION_SQL = r"""
    -- Valid pet damage (plan Q12, migrations 60, 65 and 86): a Damage charge line billed from an
    -- inspection finding of the Lease. Sub-slice 10c-2a-5: the line's latest classification record
    -- (a post-settlement correction) decides when one exists; otherwise the finding's flag on the
    -- current inspection, as before. Records exist only after closure.
    CREATE OR REPLACE FUNCTION app.invoice_line_is_pet_damage(p_line uuid,p_lease uuid)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT EXISTS(SELECT 1 FROM app.invoice_lines line
            JOIN app.authorized_nonrecurring_obligations obligation ON obligation.id=line.authorized_obligation_id
            JOIN app.inspection_damage_findings finding ON finding.id=obligation.inspection_damage_finding_id
            JOIN app.move_out_inspections inspection ON inspection.id=finding.inspection_id
            WHERE line.id=p_line AND line.category='DAMAGE_CHARGES' AND obligation.category='DAMAGE_CHARGES'
                AND inspection.lease_id=p_lease
                AND COALESCE((SELECT classification.pet_related
                        FROM app.settlement_pet_classifications classification
                        WHERE classification.invoice_line_id=line.id
                        ORDER BY classification.recorded_at DESC,classification.id DESC LIMIT 1),
                    finding.pet_related AND NOT EXISTS(SELECT 1 FROM app.move_out_inspections later
                        WHERE later.supersedes_inspection_id=inspection.id)))
    $$;

    -- Whether a line may take a pet classification correction: a Damage line billed from a finding
    -- of a current inspection of this Lease (review round 1: a line billed from an inspection
    -- superseded before closure is left to the owner's open point on carrying a finding forward,
    -- Q-2026-10-07-45), on an issued, non-VOID Invoice of the Lease.
    CREATE FUNCTION app.settlement_pet_classification_line(p_line uuid,p_lease uuid)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT EXISTS(SELECT 1 FROM app.invoice_lines line
            JOIN app.invoices invoice ON invoice.id=line.invoice_id
            JOIN app.authorized_nonrecurring_obligations obligation ON obligation.id=line.authorized_obligation_id
            JOIN app.inspection_damage_findings finding ON finding.id=obligation.inspection_damage_finding_id
            JOIN app.move_out_inspections inspection ON inspection.id=finding.inspection_id
            WHERE line.id=p_line AND invoice.lease_id=p_lease AND inspection.lease_id=p_lease
              AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID')
              AND line.category='DAMAGE_CHARGES' AND obligation.category='DAMAGE_CHARGES'
              AND NOT EXISTS(SELECT 1 FROM app.move_out_inspections later
                  WHERE later.supersedes_inspection_id=inspection.id))
    $$;

    -- BEFORE INSERT: a classification record is written only inside its own correction of the
    -- line's own Settlement, confirmed in this transaction by its approver, exactly as its
    -- PET_DAMAGE_RECLASSIFICATION draft prepared it (review round 1), for a line that may take it,
    -- with a classification that differs from the current one, later than the line's latest
    -- record (review round 1: the latest record decides), not before the correction and not later
    -- than the clock plus 5 seconds. The line's Invoice is locked first.
    CREATE FUNCTION app.validate_settlement_pet_classification()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_correction app.settlement_corrections%ROWTYPE; v_lease uuid; v_closed timestamptz;
        v_invoice uuid; v_draft app.financial_drafts%ROWTYPE;
    BEGIN
        SELECT line.invoice_id INTO v_invoice FROM app.invoice_lines line WHERE line.id=NEW.invoice_line_id;
        IF v_invoice IS NOT NULL THEN PERFORM 1 FROM app.invoices WHERE id=v_invoice FOR UPDATE; END IF;
        SELECT * INTO v_correction FROM app.settlement_corrections WHERE id=NEW.settlement_correction_id;
        SELECT settlement.lease_id,settlement.closed_at INTO v_lease,v_closed FROM app.final_settlements settlement
        WHERE settlement.id=v_correction.final_settlement_id;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=v_correction.correlation_id;
        IF v_correction.id IS NULL OR v_closed IS NULL
            OR app.settlement_correction_linked(v_correction.final_settlement_id,
                'settlement_pet_classifications',NEW.id) IS NOT TRUE
            OR NOT EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                WHERE effect.settlement_pet_classification_id=NEW.id
                  AND effect.settlement_correction_id=NEW.settlement_correction_id)
            OR v_draft.kind IS DISTINCT FROM 'SETTLEMENT_CORRECTION'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'PET_DAMAGE_RECLASSIFICATION'
            OR v_draft.payload->'classification'->>'invoice_line_id' IS DISTINCT FROM NEW.invoice_line_id::text
            OR v_draft.payload->'classification'->'pet_related' IS DISTINCT FROM to_jsonb(NEW.pet_related)
            OR v_draft.payload->'classification'->>'evidence_reference' IS DISTINCT FROM NEW.evidence_reference
            OR v_draft.reason IS DISTINCT FROM NEW.reason
            OR NEW.actor_id IS DISTINCT FROM v_correction.actor_id
            OR app.settlement_pet_classification_line(NEW.invoice_line_id,v_lease) IS NOT TRUE
            OR app.invoice_line_is_pet_damage(NEW.invoice_line_id,v_lease)=NEW.pet_related
            OR NEW.recorded_at IS NULL OR NEW.recorded_at<v_correction.occurred_at
            OR NEW.recorded_at>clock_timestamp()+interval '5 seconds'
            OR NEW.recorded_at<=(SELECT max(classification.recorded_at)
                FROM app.settlement_pet_classifications classification
                WHERE classification.invoice_line_id=NEW.invoice_line_id)
        THEN RAISE EXCEPTION 'Pet classification correction source is invalid' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER settlement_pet_classifications_source BEFORE INSERT
        ON app.settlement_pet_classifications
        FOR EACH ROW EXECUTE FUNCTION app.validate_settlement_pet_classification();

    -- The stored form of a pet classification correction (the plan is kept apart).
    CREATE FUNCTION app.settlement_pet_classification_input(p_input jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_invoice text; v_line text;
    BEGIN
        IF p_input IS NULL OR jsonb_typeof(p_input) IS DISTINCT FROM 'object'
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_input) key
                WHERE key NOT IN ('invoice_id','invoice_line_id','pet_related','evidence_reference'))
        THEN RAISE EXCEPTION 'Pet classification correction input is invalid' USING ERRCODE='22023'; END IF;
        v_invoice:=app.final_settlement_plan_id(p_input->'invoice_id');
        v_line:=app.final_settlement_plan_id(p_input->'invoice_line_id');
        IF v_invoice IS NULL OR v_line IS NULL
            OR jsonb_typeof(p_input->'pet_related') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(p_input->'evidence_reference') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_input->>'evidence_reference',500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Pet classification correction input is invalid' USING ERRCODE='22023'; END IF;
        RETURN jsonb_build_object('invoice_id',v_invoice,'invoice_line_id',v_line,
            'pet_related',p_input->'pet_related','evidence_reference',p_input->>'evidence_reference');
    END $$;

    -- The Deposit applications the correction reverses, where the corrected classification changes
    -- which Deposit should pay (owner answer to Q-2026-10-07-45), newest first: to not pet damage,
    -- the line's Pet-Deposit-first applications; to pet damage, its Security Deposit applications
    -- while a Pet Deposit of the Lease holds money. A Pet Deposit remainder application stays: the
    -- same Deposit pays.
    CREATE FUNCTION app.settlement_pet_classification_reversals(p_line uuid,p_lease uuid,p_pet boolean)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT COALESCE(jsonb_agg(jsonb_build_object('id',application.id,'deposit_id',application.deposit_id,
                'application_stage',application.application_stage,
                'amount_usd_cents',application.amount_usd_cents)
            ORDER BY application.occurred_at DESC,application.id DESC),'[]'::jsonb)
        FROM app.deposit_applications application
        WHERE application.invoice_line_id=p_line
          AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
              WHERE reversal.deposit_application_id=application.id)
          AND ((p_pet IS FALSE AND application.application_stage='PET_RELATED_FIRST')
            OR (p_pet IS TRUE AND application.application_stage='SECURITY_EXPLICIT'
                AND EXISTS(SELECT 1 FROM app.deposits deposit
                    WHERE deposit.lease_id=p_lease AND deposit.deposit_type='PET'
                      AND app.deposit_held_value_at(deposit.id,'infinity')>0
                      -- Review round 1: only a Pet Deposit the plan may use (the DL-032 path).
                      AND app.lease_deposit_settlement_path((SELECT settlement.property_id
                          FROM app.final_settlements settlement WHERE settlement.lease_id=p_lease),
                          deposit.id)->>'path'='DL_032')))
    $$;

    -- The state a pet classification correction depends on; its digest is the draft's source
    -- revision: the closure, the line's Invoice, what the line still owes, its Deposit applications
    -- and their reversals, its classification records and the Lease's Deposits' held values.
    CREATE FUNCTION app.settlement_pet_classification_source_state(p_settlement uuid,p_invoice uuid,p_line uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT jsonb_build_object(
            'settlement',(SELECT jsonb_build_object('id',settlement.id,'closed_at',settlement.closed_at,
                    'lease_id',settlement.lease_id)
                FROM app.final_settlements settlement WHERE settlement.id=p_settlement),
            'invoice',(SELECT jsonb_build_object('id',invoice.id,'lease_id',invoice.lease_id,
                    'customer_id',invoice.customer_id,
                    'issued',invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID'))
                FROM app.invoices invoice WHERE invoice.id=p_invoice),
            'line',(SELECT jsonb_build_object('id',line.id,'invoice_id',line.invoice_id,
                    'outstanding_usd_cents',app.invoice_line_outstanding(line.id))
                FROM app.invoice_lines line WHERE line.id=p_line),
            'deposit_applications',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',application.id,
                    'reversed',EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                        WHERE reversal.deposit_application_id=application.id))
                    ORDER BY application.id),'[]'::jsonb)
                FROM app.deposit_applications application WHERE application.invoice_line_id=p_line),
            'classifications',(SELECT COALESCE(jsonb_agg(classification.id
                    ORDER BY classification.recorded_at,classification.id),'[]'::jsonb)
                FROM app.settlement_pet_classifications classification
                WHERE classification.invoice_line_id=p_line),
            'deposits',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',deposit.id,
                    'held_usd_cents',app.deposit_held_value_at(deposit.id,'infinity')) ORDER BY deposit.id),
                    '[]'::jsonb)
                FROM app.deposits deposit JOIN app.final_settlements settlement
                    ON settlement.lease_id=deposit.lease_id
                WHERE settlement.id=p_settlement))
    $$;

    -- Checks a stored-form pet classification correction against the current state and returns
    -- what the draft records: the Lease, the line's Invoice Customer, the correction, the Deposit
    -- applications it reverses and the source revision. An unknown Settlement, Invoice or line
    -- P0002; a state the correction does not allow 55000.
    CREATE FUNCTION app.settlement_pet_classification_plan(p_property uuid,p_settlement uuid,p_input jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_invoice app.invoices%ROWTYPE; v_line uuid;
        v_pet boolean;
    BEGIN
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT * INTO v_invoice FROM app.invoices
        WHERE id=(p_input->>'invoice_id')::uuid AND lease_id=v_settlement.lease_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The corrected Invoice is not an Invoice of this Final Settlement'
                USING ERRCODE='P0002'; END IF;
        IF v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID') THEN
            RAISE EXCEPTION 'The corrected Invoice is not an issued obligation of this Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT line.id INTO v_line FROM app.invoice_lines line
        WHERE line.id=(p_input->>'invoice_line_id')::uuid AND line.invoice_id=v_invoice.id;
        IF NOT FOUND THEN RAISE EXCEPTION 'Invoice line was not found' USING ERRCODE='P0002'; END IF;
        IF app.settlement_pet_classification_line(v_line,v_settlement.lease_id) IS NOT TRUE THEN
            RAISE EXCEPTION 'A pet classification correction corrects only a Damage line billed from a finding of a current inspection'
                USING ERRCODE='55000'; END IF;
        v_pet:=(p_input->>'pet_related')::boolean;
        IF app.invoice_line_is_pet_damage(v_line,v_settlement.lease_id)=v_pet THEN
            RAISE EXCEPTION 'The line already has this pet classification' USING ERRCODE='55000'; END IF;
        RETURN jsonb_build_object('lease_id',v_settlement.lease_id,'customer_id',v_invoice.customer_id,
            'classification',p_input,
            'reversed_applications',app.settlement_pet_classification_reversals(v_line,
                v_settlement.lease_id,v_pet),
            'source_revision','settlement-correction:' || encode(sha256(convert_to(
                app.settlement_pet_classification_source_state(p_settlement,v_invoice.id,v_line)::text,
                'UTF8')),'hex'));
    END $$;

    -- The overlay of the shared step's check (sub-slice 10c-2a-2) for the state after the
    -- correction's own reversals: the line owes the reversed amounts again, each Deposit gets them
    -- back, and the line has its corrected classification.
    CREATE FUNCTION app.settlement_pet_classification_overlay(p_reversed jsonb,p_line uuid,p_pet boolean)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT jsonb_build_object(
            'obligations',CASE WHEN jsonb_array_length(p_reversed)=0 THEN '{}'::jsonb
                ELSE jsonb_build_object('INVOICE_LINE:' || p_line::text,app.invoice_line_outstanding(p_line)
                    +(SELECT sum((item->>'amount_usd_cents')::bigint) FROM jsonb_array_elements(p_reversed) item))
                END,
            'deposits',COALESCE((SELECT jsonb_object_agg(deposit.id,deposit.total) FROM (
                    SELECT item->>'deposit_id' AS id,sum((item->>'amount_usd_cents')::bigint) AS total
                    FROM jsonb_array_elements(p_reversed) item GROUP BY 1) deposit),'{}'::jsonb),
            'credits','{}'::jsonb,
            'pet_damage',jsonb_build_object('INVOICE_LINE:' || p_line::text,p_pet))
    $$;

    -- Staff record a pet classification correction draft (final_settlements.prepare); it has no
    -- effect until a financial.approve holder confirms it. The draft keeps the staff's DL-032 plan,
    -- the overlay of its reversals and the plan check's result (sub-slice 10c-2a-2).
    CREATE FUNCTION app.record_settlement_pet_classification_draft(p_property uuid,p_actor uuid,p_draft uuid,
        p_settlement uuid,p_classification jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_plan jsonb; v_payload jsonb;
        v_steps jsonb; v_overlay jsonb; v_result jsonb; v_choice text;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The reason is at most 500 characters: the classification record keeps it.
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
            OR p_classification IS NULL OR jsonb_typeof(p_classification) IS DISTINCT FROM 'object'
        THEN RAISE EXCEPTION 'Pet classification correction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_pet_classification_input(p_classification-'plan');
        v_steps:=COALESCE(p_classification->'plan',
            jsonb_build_object('steps','[]'::jsonb,'pet_remainder','null'::jsonb));
        IF jsonb_typeof(v_steps) IS DISTINCT FROM 'object' OR jsonb_typeof(v_steps->'steps') IS DISTINCT FROM 'array'
        THEN RAISE EXCEPTION 'Pet classification correction input is invalid' USING ERRCODE='22023'; END IF;
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='PET_DAMAGE_RECLASSIFICATION'
                AND v_existing.prepared_by=p_actor AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->'classification'=v_input AND v_existing.payload->'plan'=v_steps
            -- The decision's transaction id never leaves the database (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        v_plan:=app.settlement_pet_classification_plan(p_property,p_settlement,v_input);
        -- Owner answer 3 to Q-2026-10-07-44: the remaining Pet Deposit is used by the Customer's
        -- choice given for this correction; neither the Final Settlement's nor an earlier
        -- confirmed correction's choice is reused (the recorded text is compared, as 10c-2a-3).
        IF v_steps->'pet_remainder'->>'basis'='CUSTOMER_CHOICE' THEN
            SELECT draft.payload->'pet_remainder'->>'customer_choice' INTO v_choice
            FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision
                ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
            WHERE draft.kind='FINAL_SETTLEMENT' AND draft.payload->>'final_settlement_id'=p_settlement::text;
            IF v_choice IS NOT NULL AND v_choice=v_steps->'pet_remainder'->>'customer_choice' THEN
                RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; the Final Settlement''s choice is not reused'
                    USING ERRCODE='55000'; END IF;
            IF EXISTS(SELECT 1 FROM app.financial_drafts draft
                JOIN app.financial_draft_decisions decision
                    ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
                WHERE draft.kind='SETTLEMENT_CORRECTION'
                  AND draft.payload->>'final_settlement_id'=p_settlement::text
                  AND draft.payload->'plan'->'pet_remainder'->>'customer_choice'
                      =v_steps->'pet_remainder'->>'customer_choice')
            THEN RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; an earlier correction''s choice is not reused'
                USING ERRCODE='55000'; END IF;
        END IF;
        -- The shared step's check on the state after the reversals, under the corrected
        -- classification (sub-slice 10c-2a-2).
        v_overlay:=app.settlement_pet_classification_overlay(v_plan->'reversed_applications',
            (v_input->>'invoice_line_id')::uuid,(v_input->>'pet_related')::boolean);
        v_result:=app.settlement_correction_plan_result(p_property,p_actor,p_settlement,v_steps,v_overlay)
            -'source_revision';
        v_payload:=jsonb_build_object('variant','PET_DAMAGE_RECLASSIFICATION','final_settlement_id',p_settlement,
            'lease_id',v_plan->'lease_id','customer_id',v_plan->'customer_id',
            'classification',v_input,'reversed_applications',v_plan->'reversed_applications',
            'plan',v_steps,'plan_overlay',v_overlay,'plan_result',v_result);
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,v_plan->>'source_revision',p_reason);
    END $$;

    -- What the confirm returns, also for an exact repeat (rebuilt from the stored records).
    CREATE FUNCTION app.settlement_pet_classification_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT jsonb_build_object('draft_id',p_draft,'settlement_correction_id',correction.id,
            'final_settlement_id',correction.final_settlement_id,'variant','PET_DAMAGE_RECLASSIFICATION',
            'occurred_at',correction.occurred_at,
            'classification',(SELECT jsonb_build_object('id',classification.id,
                    'invoice_line_id',classification.invoice_line_id,'pet_related',classification.pet_related,
                    'evidence_reference',classification.evidence_reference,
                    'recorded_at',classification.recorded_at)
                FROM app.settlement_pet_classifications classification
                WHERE classification.settlement_correction_id=correction.id),
            'deposit_application_reversals',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
                    'id',reversal.id,'deposit_application_id',reversal.deposit_application_id)
                    ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.deposit_application_reversals reversal
                    ON reversal.id=effect.deposit_application_reversal_id
                WHERE effect.settlement_correction_id=correction.id),
            'credit_application_ids',(SELECT COALESCE(jsonb_agg(effect.customer_credit_application_id
                    ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                WHERE effect.settlement_correction_id=correction.id
                  AND effect.customer_credit_application_id IS NOT NULL),
            'deposit_application_ids',(SELECT COALESCE(jsonb_agg(effect.deposit_application_id
                    ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                WHERE effect.settlement_correction_id=correction.id
                  AND effect.deposit_application_id IS NOT NULL),
            'deposit_refund_ids',(SELECT COALESCE(jsonb_agg(effect.refund_id
                    ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                WHERE effect.settlement_correction_id=correction.id AND effect.refund_id IS NOT NULL))
        FROM app.settlement_corrections correction WHERE correction.correlation_id=p_draft
    $$;

    -- A financial.approve holder confirms a pet classification correction: in one transaction the
    -- decision and the header (sub-slice 10a), then, each linked before it is written, the
    -- classification record, the reversal of the line's Deposit applications where the corrected
    -- classification changes which Deposit should pay, and the shared DL-032 step (sub-slice
    -- 10c-2a-2). No Adjustment: the charge amount stays the same.
    CREATE FUNCTION app.confirm_settlement_pet_classification(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_invoice app.invoices%ROWTYPE; v_timezone text; v_now timestamptz; v_business_date date;
        v_input jsonb; v_plan jsonb; v_correction uuid; v_line uuid; v_pet boolean; v_unit uuid;
        v_evidence jsonb; v_result jsonb; v_source jsonb; v_new uuid; v_classification uuid;
        v_step jsonb; v_method uuid;
    BEGIN
        v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
        -- BR-AUTH-010: a person confirms; an inactive approver is refused above (P4506).
        IF NOT EXISTS(SELECT 1 FROM app.actor_identities identity
            WHERE identity.actor_id=p_actor AND identity.identity_kind='HUMAN')
        THEN RAISE EXCEPTION 'A post-settlement correction is confirmed only by a human approver'
            USING ERRCODE='42501'; END IF;
        IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
            RAISE EXCEPTION 'Only financial.approve may confirm a post-settlement correction'
                USING ERRCODE='42501'; END IF;
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' THEN
            RAISE EXCEPTION 'Post-settlement correction input is invalid' USING ERRCODE='22023'; END IF;
        -- The serialization of every decision on this draft, then the replay of an exact repeat.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        IF EXISTS(SELECT 1 FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
            WHERE draft.id=p_draft AND draft.property_id=p_property AND draft.kind='SETTLEMENT_CORRECTION'
              AND draft.payload->>'variant'='PET_DAMAGE_RECLASSIFICATION' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_pet_classification_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'PET_DAMAGE_RECLASSIFICATION'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
            RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=app.final_settlement_plan_id(v_draft.payload->'final_settlement_id')::uuid
          AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        -- The checks below rely on READ COMMITTED: each statement sees the commits the locks
        -- waited for (as the other correction confirms).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction is confirmed at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        -- The stored correction passes the recorder's shape check again.
        v_input:=app.settlement_pet_classification_input(v_draft.payload->'classification');
        IF v_input IS DISTINCT FROM v_draft.payload->'classification' THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_line:=(v_input->>'invoice_line_id')::uuid;
        v_pet:=(v_input->>'pet_related')::boolean;
        -- Lock order, the 8e-3 order (as sub-slice 10c-2a-3): the draft lock (above); the
        -- Settlement's draft lock; the Lease row FOR UPDATE; then the shared step's locks
        -- (app.lock_settlement_correction_plan), which for this variant take the line's Invoice FOR
        -- UPDATE in their id-ordered Invoice pass, then the Settlement row and each Deposit's draft
        -- lock and row; the plan's Refund methods FOR SHARE come last. A detected deadlock (40P01)
        -- is a conflict.
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        PERFORM 1 FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE;
        PERFORM app.lock_settlement_correction_plan(p_draft);
        -- Owner answer 3 to Q-2026-10-07-44, checked again under the Settlement's draft lock (review
        -- round 1): a Customer choice for the remaining Pet Deposit is neither the Final
        -- Settlement's nor that of a correction of this Settlement confirmed since this draft was
        -- recorded (two pending drafts may carry the same text; every correction confirm takes the
        -- Settlement's draft lock first).
        IF v_draft.payload->'plan'->'pet_remainder'->>'basis'='CUSTOMER_CHOICE' THEN
            IF EXISTS(SELECT 1 FROM app.financial_drafts draft
                JOIN app.financial_draft_decisions decision
                    ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
                WHERE draft.kind='FINAL_SETTLEMENT' AND draft.payload->>'final_settlement_id'=v_settlement.id::text
                  AND draft.payload->'pet_remainder'->>'customer_choice'
                      =v_draft.payload->'plan'->'pet_remainder'->>'customer_choice')
            THEN RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; the Final Settlement''s choice is not reused'
                USING ERRCODE='55000'; END IF;
            IF EXISTS(SELECT 1 FROM app.financial_drafts draft
                JOIN app.financial_draft_decisions decision
                    ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
                WHERE draft.kind='SETTLEMENT_CORRECTION' AND draft.id<>p_draft
                  AND draft.payload->>'final_settlement_id'=v_settlement.id::text
                  AND draft.payload->'plan'->'pet_remainder'->>'customer_choice'
                      =v_draft.payload->'plan'->'pet_remainder'->>'customer_choice')
            THEN RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; an earlier correction''s choice is not reused'
                USING ERRCODE='55000'; END IF;
        END IF;
        SELECT * INTO v_invoice FROM app.invoices WHERE id=(v_input->>'invoice_id')::uuid;
        -- Under the locks, the sources still have the digest the draft recorded, and the check of
        -- the recorder still gives the same reversals; otherwise the draft is stale and stays pending.
        IF 'settlement-correction:' || encode(sha256(convert_to(app.settlement_pet_classification_source_state(
                v_settlement.id,(v_input->>'invoice_id')::uuid,v_line)::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_plan:=app.settlement_pet_classification_plan(p_property,v_settlement.id,v_input);
        IF v_plan->>'source_revision' IS DISTINCT FROM v_draft.source_revision
            OR v_plan->'lease_id' IS DISTINCT FROM v_draft.payload->'lease_id'
            OR v_plan->'customer_id' IS DISTINCT FROM v_draft.payload->'customer_id'
            OR v_plan->'reversed_applications' IS DISTINCT FROM v_draft.payload->'reversed_applications'
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        -- BR-REFUND-014: each Refund method of the plan stays active until its Refunds are written.
        FOR v_method IN SELECT DISTINCT app.final_settlement_plan_id(step->'refund_method_id')::uuid
            FROM jsonb_array_elements(v_draft.payload->'plan'->'steps') step
            WHERE step->>'kind'='DEPOSIT_REFUNDS' ORDER BY 1
        LOOP
            PERFORM 1 FROM app.refund_methods WHERE id=v_method AND active FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        END LOOP;
        SELECT lease.unit_id INTO STRICT v_unit FROM app.leases lease WHERE lease.id=v_settlement.lease_id;

        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written, and every id is fresh, never derived from the draft (sub-slice 10b).
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve');
        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,
            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
            'variant','PET_DAMAGE_RECLASSIFICATION');
        -- Later than the line's latest classification record (review round 1: the latest decides).
        v_now:=GREATEST(clock_timestamp(),COALESCE((SELECT max(classification.recorded_at)
            FROM app.settlement_pet_classifications classification
            WHERE classification.invoice_line_id=v_line),'-infinity')+interval '1 microsecond');
        v_business_date:=timezone(v_timezone,v_now)::date;
        -- The corrected classification first, so the step reads it (app.invoice_line_is_pet_damage).
        v_classification:=gen_random_uuid();
        PERFORM app.link_settlement_correction_effect(v_correction,'settlement_pet_classification_id',
            v_classification);
        INSERT INTO app.settlement_pet_classifications(id,settlement_correction_id,invoice_line_id,
            pet_related,evidence_reference,reason,recorded_at,actor_id,authorization_reference)
        VALUES(v_classification,v_correction,v_line,v_pet,v_input->>'evidence_reference',v_draft.reason,
            v_now,p_actor,'financial.approve');
        -- Each reversed Deposit application gives its value back to its Deposit (sub-slice 10c-2a-1),
        -- dated after the latest events of the Invoice and of the Deposit.
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_plan->'reversed_applications') LOOP
            v_new:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(v_correction,'deposit_application_reversal_id',v_new);
            INSERT INTO app.deposit_application_reversals(id,deposit_application_id,reason,
                occurred_at,actor_id,authorization_reference)
            VALUES(v_new,(v_source->>'id')::uuid,v_draft.reason,
                GREATEST(app.credit_excess_instant(v_invoice.id,NULL),
                    COALESCE(app.deposit_balance_latest_at((v_source->>'deposit_id')::uuid),'-infinity')
                        +interval '1 microsecond'),
                p_actor,'financial.approve');
        END LOOP;
        -- The shared DL-032 step (sub-slice 10c-2a-2): under the same locks, the plan check again
        -- on the real state (stale P5S02 otherwise), then each Customer's Credit, the Deposit
        -- applications and the Deposit Refunds of the plan.
        v_step:=app.post_settlement_correction_plan(p_property,p_actor,p_draft);
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing Invoice writers run them (sub-slice 10b plan note).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_result:=app.settlement_pet_classification_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'final_settlement.correction.confirmed',
            'settlement_correction',v_correction,v_draft.reason,'financial.approve',p_property,
            '{}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','PET_DAMAGE_RECLASSIFICATION',
                'invoice_id',v_invoice.id,'invoice_line_id',v_line,'customer_id',v_invoice.customer_id,
                'pet_related',v_pet,'pet_classification_id',v_classification,
                'deposit_application_reversals',v_result->'deposit_application_reversals',
                'credit_application_ids',v_step->'credit_application_ids',
                'deposit_application_ids',v_step->'deposit_application_ids',
                'deposit_refund_ids',v_step->'refund_ids'),
            v_correction,'API','SUCCEEDED',v_evidence,v_invoice.customer_id,v_settlement.lease_id,v_unit);
        RETURN v_result;
    END $$;
"""


def _link_sql() -> str:
    """DB-SETTLE-005 gains settlement_pet_classification_id; the link functions are rebuilt."""
    links = (
        *_module("20261102_98_settlement_extra_charge.py", "settlement_extra_charge_98").LINKS,
        ("deposit_application_reversal_id", "app.deposit_application_reversals"),
        ("settlement_pet_classification_id", "app.settlement_pet_classifications"),
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
        -- Owner answer to Q-2026-10-07-45: the pet classification record of a correction.
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
        raise RuntimeError(f"Pet classification correction source is missing: {file_name}")
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
            raise RuntimeError(f"Pet classification correction source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(TABLE_SQL)
    op.execute(_link_sql())
    op.execute(FUNCTION_SQL)
    _patch(PLAN_RESULT, PLAN_RESULT_REPLACEMENTS)
    _patch(LOCK_PLAN, LOCK_PLAN_REPLACEMENTS)
    op.execute(
        "REVOKE ALL ON TABLE app.settlement_pet_classifications "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in (*INTERNAL, RECORD, CONFIRM):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in (RECORD, CONFIRM):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Pet classification correction migration is forward-only")
