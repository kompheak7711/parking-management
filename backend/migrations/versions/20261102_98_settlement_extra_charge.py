# ruff: noqa: E501
"""Post-settlement correction: extra charge (V1-056 sub-slice 10b).

BR-SETTLE-013, BR-SETTLE-016, BR-INV-044, BR-AUTH-010; DB-SETTLE-003, DB-SETTLE-005 (amended by
owner answer 4 to Q-2026-10-06-37); owner answer 6 to Q-2026-10-06-36.

- A missed amount after closure is billed by an EXTRA_CHARGE correction: Staff record a
  SETTLEMENT_CORRECTION draft under final_settlements.prepare with a reason
  (app.record_settlement_extra_charge_draft); only a financial.approve holder confirms it
  (app.confirm_settlement_extra_charge). The confirmation writes, in one transaction and linked
  to the correction, a one-time charge record (Miscellaneous or Damage, BR-INV-044) and its
  Invoice with the Lease, issued with the Due Date of a one-time charge (issue date plus the
  Property's days, or the authorized override).
- The charge goes to the Customer of the corrected Invoice when the draft names one, otherwise
  to the Primary Tenant (owner answer 6; BR-SETTLE-016); a Damage charge always goes to the
  Primary Tenant (the existing Damage rule). No Late-payment Charge: the 8e-1 refusal of
  Late-payment Decisions after closure stays.
- DB-SETTLE-005 gains the link authorized_nonrecurring_obligation_id (owner answer 4); the link
  functions are rebuilt with it, and the 8e-1 refusal lets a one-time charge record through when
  it is linked to a correction of the same Settlement confirmed in the same transaction.
- A deferred check refuses the commit while an Invoice linked to a correction is not issued
  (sub-slice 10a security review round 2 note): DRAFT, VOID or not yet written. No writer
  linked an Invoice before this migration, so no stored correction is affected.

Additive and relaxing except that one commit check on correction effects, which the plan's
writer notes require of the first writer that links an Invoice; it refuses nothing any role
could do before (the link functions have no grant and no correction existed).
"""

from alembic import op
from sqlalchemy import text

revision = "20261102_98"
down_revision = "20261101_97"
branch_labels = None
depends_on = None

ONE_TIME_RULE = "ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS"
RECORD = "app.record_settlement_extra_charge_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_extra_charge(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.assert_settlement_correction_invoice_issued()",
    "app.settlement_extra_charge_input(jsonb)",
    "app.settlement_extra_charge_source_state(uuid,uuid,uuid)",
    "app.settlement_extra_charge_plan(uuid,uuid,jsonb,date)",
    "app.settlement_extra_charge_result(uuid)",
)
CLOSED_GUARD = "app.refuse_closed_final_settlement_change()"

# One link column per linked table (DB-SETTLE-005 as amended by owner answer 2 to
# Q-2026-10-06-36 and owner answer 4 to Q-2026-10-06-37).
LINKS = (
    ("invoice_id", "app.invoices"),
    ("invoice_adjustment_id", "app.invoice_adjustments"),
    ("invoice_adjustment_reversal_id", "app.invoice_adjustment_reversals"),
    ("payment_allocation_id", "app.payment_allocations"),
    ("payment_allocation_reversal_id", "app.payment_allocation_reversals"),
    ("payment_reversal_id", "app.payment_reversals"),
    ("customer_credit_application_id", "app.customer_credit_applications"),
    ("credit_application_reversal_id", "app.customer_credit_application_reversals"),
    ("customer_credit_reversal_id", "app.customer_credit_reversals"),
    ("deposit_application_id", "app.deposit_applications"),
    ("deposit_disposition_reversal_id", "app.deposit_disposition_reversals"),
    ("deposit_receipt_reversal_id", "app.deposit_receipt_reversals"),
    ("late_payment_charge_correction_id", "app.late_payment_charge_corrections"),
    ("refund_id", "app.refunds"),
    ("refund_correction_id", "app.refund_corrections"),
    ("authorized_nonrecurring_obligation_id", "app.authorized_nonrecurring_obligations"),
)

CLOSED_GUARD_REPLACEMENTS = (
    (
        "                'late_payment_charge_corrections') THEN\n",
        "                'late_payment_charge_corrections','authorized_nonrecurring_obligations') THEN\n",
    ),
)

EXTRA_CHARGE_SQL = """
    -- The draft's charge, checked for shape only and stored in one form: malformed input 22023.
    CREATE FUNCTION app.settlement_extra_charge_input(p_charge jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_finding text; v_corrects text; v_due date;
    BEGIN
        IF p_charge IS NULL OR jsonb_typeof(p_charge) IS DISTINCT FROM 'object'
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_charge) key WHERE key NOT IN ('category',
                'description','amount_usd_cents','evidence_reference','inspection_damage_finding_id',
                'corrects_invoice_id','due_date','due_date_reason'))
        THEN RAISE EXCEPTION 'Extra charge input is invalid' USING ERRCODE='22023'; END IF;
        v_finding:=app.final_settlement_plan_id(p_charge->'inspection_damage_finding_id');
        v_corrects:=app.final_settlement_plan_id(p_charge->'corrects_invoice_id');
        IF jsonb_typeof(p_charge->'category') IS DISTINCT FROM 'string'
            OR p_charge->>'category' NOT IN ('MISCELLANEOUS_CHARGES','DAMAGE_CHARGES')
            OR jsonb_typeof(p_charge->'description') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_charge->>'description',1000) IS NOT TRUE
            OR jsonb_typeof(p_charge->'amount_usd_cents') IS DISTINCT FROM 'number'
            OR (p_charge->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
            OR jsonb_typeof(p_charge->'evidence_reference') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_charge->>'evidence_reference',500) IS NOT TRUE
            OR (COALESCE(p_charge->'inspection_damage_finding_id','null'::jsonb)<>'null'::jsonb
                AND v_finding IS NULL)
            OR (COALESCE(p_charge->'corrects_invoice_id','null'::jsonb)<>'null'::jsonb
                AND v_corrects IS NULL)
            -- BR-INV-044: a Damage charge bills one inspection finding; a Miscellaneous one none.
            OR ((p_charge->>'category'='DAMAGE_CHARGES')<>(v_finding IS NOT NULL))
            OR ((COALESCE(p_charge->'due_date','null'::jsonb)='null'::jsonb)
                <>(COALESCE(p_charge->'due_date_reason','null'::jsonb)='null'::jsonb))
            OR (COALESCE(p_charge->'due_date','null'::jsonb)<>'null'::jsonb AND (
                jsonb_typeof(p_charge->'due_date') IS DISTINCT FROM 'string'
                OR (p_charge->>'due_date') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                OR jsonb_typeof(p_charge->'due_date_reason') IS DISTINCT FROM 'string'
                OR app.lease_notice_text_valid(p_charge->>'due_date_reason',500) IS NOT TRUE))
        THEN RAISE EXCEPTION 'Extra charge input is invalid' USING ERRCODE='22023'; END IF;
        -- The cap of the other money writers (review round 1); a JSON number always casts.
        IF (p_charge->>'amount_usd_cents')::numeric>9000000000000000 THEN
            RAISE EXCEPTION 'Extra charge input is invalid' USING ERRCODE='22023'; END IF;
        IF p_charge->>'due_date' IS NOT NULL THEN
            BEGIN
                v_due:=(p_charge->>'due_date')::date;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'Extra charge input is invalid' USING ERRCODE='22023';
            END;
            IF NOT isfinite(v_due) OR to_char(v_due,'YYYY-MM-DD')<>p_charge->>'due_date' THEN
                RAISE EXCEPTION 'Extra charge input is invalid' USING ERRCODE='22023'; END IF;
        END IF;
        RETURN jsonb_build_object('category',p_charge->>'category',
            'description',p_charge->>'description',
            'amount_usd_cents',(p_charge->>'amount_usd_cents')::bigint,
            'evidence_reference',p_charge->>'evidence_reference',
            'inspection_damage_finding_id',v_finding,
            'corrects_invoice_id',v_corrects,
            'due_date',v_due,
            'due_date_reason',CASE WHEN v_due IS NOT NULL THEN p_charge->>'due_date_reason' END);
    END $$;

    -- The state an extra charge depends on; its digest is the draft's source revision.
    CREATE FUNCTION app.settlement_extra_charge_source_state(p_settlement uuid,p_corrects uuid,
        p_finding uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT jsonb_build_object(
            'settlement',(SELECT jsonb_build_object('id',settlement.id,'closed_at',settlement.closed_at,
                    'lease_id',lease.id,'primary_tenant_id',lease.primary_tenant_id)
                FROM app.final_settlements settlement
                JOIN app.leases lease ON lease.id=settlement.lease_id
                WHERE settlement.id=p_settlement),
            'corrected_invoice',(SELECT jsonb_build_object('id',invoice.id,'lease_id',invoice.lease_id,
                    'customer_id',invoice.customer_id,
                    'issued',invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID'))
                FROM app.invoices invoice WHERE invoice.id=p_corrects),
            'finding',(SELECT jsonb_build_object('id',finding.id,'lease_id',inspection.lease_id,
                    'current',NOT EXISTS(SELECT 1 FROM app.move_out_inspections later
                        WHERE later.supersedes_inspection_id=inspection.id),
                    'billed',EXISTS(SELECT 1 FROM app.authorized_nonrecurring_obligations obligation
                        WHERE obligation.inspection_damage_finding_id=finding.id))
                FROM app.inspection_damage_findings finding
                JOIN app.move_out_inspections inspection ON inspection.id=finding.inspection_id
                WHERE finding.id=p_finding))
    $$;

    -- Checks a stored-form extra charge against the current state and returns what the draft
    -- records: the Lease, the Customer, the charge and the source revision. An unknown
    -- Settlement, Invoice or finding P0002; a state the correction does not allow 55000.
    CREATE FUNCTION app.settlement_extra_charge_plan(p_property uuid,p_settlement uuid,p_charge jsonb,
        p_business_date date)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_lease app.leases%ROWTYPE;
        v_invoice app.invoices%ROWTYPE; v_corrects uuid; v_finding uuid; v_customer uuid;
        v_inspection uuid;
    BEGIN
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_settlement.lease_id;
        v_corrects:=(p_charge->>'corrects_invoice_id')::uuid;
        v_finding:=(p_charge->>'inspection_damage_finding_id')::uuid;
        -- Owner answer 6 to Q-2026-10-06-36 (BR-SETTLE-016): the Customer of the corrected
        -- obligation, or the Primary Tenant when the charge corrects nothing on an Invoice.
        v_customer:=v_lease.primary_tenant_id;
        IF v_corrects IS NOT NULL THEN
            SELECT * INTO v_invoice FROM app.invoices WHERE id=v_corrects AND lease_id=v_lease.id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'The corrected Invoice is not an Invoice of this Final Settlement'
                    USING ERRCODE='P0002'; END IF;
            IF v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID') THEN
                RAISE EXCEPTION 'The corrected Invoice is not an issued obligation of this Final Settlement'
                    USING ERRCODE='55000'; END IF;
            v_customer:=v_invoice.customer_id;
        END IF;
        IF p_charge->>'category'='DAMAGE_CHARGES' THEN
            IF v_customer<>v_lease.primary_tenant_id THEN
                RAISE EXCEPTION 'A Damage charge goes to the Primary Tenant' USING ERRCODE='55000'; END IF;
            SELECT inspection.id INTO v_inspection FROM app.inspection_damage_findings finding
            JOIN app.move_out_inspections inspection ON inspection.id=finding.inspection_id
            WHERE finding.id=v_finding AND inspection.lease_id=v_lease.id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Inspection damage finding was not found' USING ERRCODE='P0002'; END IF;
            IF EXISTS(SELECT 1 FROM app.move_out_inspections later
                WHERE later.supersedes_inspection_id=v_inspection)
            THEN RAISE EXCEPTION 'The damage finding is not on the current inspection'
                USING ERRCODE='55000'; END IF;
            IF EXISTS(SELECT 1 FROM app.authorized_nonrecurring_obligations obligation
                WHERE obligation.inspection_damage_finding_id=v_finding)
            THEN RAISE EXCEPTION 'The damage finding is already billed' USING ERRCODE='55000'; END IF;
        END IF;
        IF (p_charge->>'due_date')::date<p_business_date THEN
            RAISE EXCEPTION 'The extra charge Due Date precedes the issue date' USING ERRCODE='55000'; END IF;
        RETURN jsonb_build_object('lease_id',v_lease.id,'customer_id',v_customer,'charge',p_charge,
            'source_revision','settlement-correction:' || encode(sha256(convert_to(
                app.settlement_extra_charge_source_state(p_settlement,v_corrects,v_finding)::text,
                'UTF8')),'hex'));
    END $$;

    -- Staff record an extra charge correction draft (final_settlements.prepare); it has no
    -- financial effect until a financial.approve holder confirms it.
    CREATE FUNCTION app.record_settlement_extra_charge_draft(p_property uuid,p_actor uuid,p_draft uuid,
        p_settlement uuid,p_charge jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_timezone text; v_input jsonb; v_plan jsonb;
        v_payload jsonb;
    BEGIN
        v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The reason is at most 500 characters: the one-time charge record keeps it.
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Extra charge input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_extra_charge_input(p_charge);
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='EXTRA_CHARGE' AND v_existing.prepared_by=p_actor
                AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->'charge'=v_input
            -- The decision's transaction id never leaves the database (review round 1).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        v_plan:=app.settlement_extra_charge_plan(p_property,p_settlement,v_input,
            timezone(v_timezone,clock_timestamp())::date);
        v_payload:=jsonb_build_object('variant','EXTRA_CHARGE','final_settlement_id',p_settlement,
            'lease_id',v_plan->'lease_id','customer_id',v_plan->'customer_id','charge',v_plan->'charge');
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,v_plan->>'source_revision',p_reason);
    END $$;

    -- What the confirm returns, also for an exact repeat (rebuilt from the stored records): the
    -- draft without the decision's transaction id (review round 1), the correction header, and
    -- the one-time charge record and Invoice the correction links.
    CREATE FUNCTION app.settlement_extra_charge_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT jsonb_build_object(
            'draft',app.financial_draft_json(draft) #- '{decision,result,transaction_id}',
            'settlement_correction',(SELECT jsonb_build_object('id',correction.id,
                    'final_settlement_id',correction.final_settlement_id,'reason',correction.reason,
                    'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
                    'authorization_reference',correction.authorization_reference)
                FROM app.settlement_corrections correction
                WHERE correction.id=app.settlement_correction_id(draft.id)),
            'one_time_charge',app.one_time_charge_snapshot((SELECT
                    effect.authorized_nonrecurring_obligation_id
                FROM app.settlement_correction_effects effect
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)
                  AND effect.authorized_nonrecurring_obligation_id IS NOT NULL)),
            'invoice',app.invoice_resource_snapshot((SELECT effect.invoice_id
                FROM app.settlement_correction_effects effect
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)
                  AND effect.invoice_id IS NOT NULL)))
        FROM app.financial_drafts draft WHERE draft.id=p_draft
    $$;

    -- A financial.approve holder confirms an extra charge correction. Refusals: an unknown
    -- Property, draft or Settlement P0002/P4501; an inactive or missing approver P4506 or 42501;
    -- business state (a decided draft, an open Settlement, a Due Date before the issue date)
    -- 55000; a draft whose sources changed P5S02 (stale; it stays pending). Nothing is written
    -- unless everything succeeds.
    CREATE FUNCTION app.confirm_settlement_extra_charge(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_timezone text; v_now timestamptz; v_business_date date; v_plan jsonb; v_charge jsonb;
        v_correction uuid; v_obligation uuid; v_invoice uuid; v_line uuid; v_due date;
        v_customer uuid; v_lease uuid; v_unit uuid; v_amount bigint; v_category text;
        v_override boolean; v_draft_state jsonb; v_issued jsonb; v_result jsonb; v_evidence jsonb;
        v_audit uuid;
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
              AND draft.payload->>'variant'='EXTRA_CHARGE' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_extra_charge_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'EXTRA_CHARGE'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
            RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=app.final_settlement_plan_id(v_draft.payload->'final_settlement_id')::uuid
          AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        -- The checks below rely on READ COMMITTED: each statement sees the commits the locks
        -- waited for (as the Settlement confirm, plan note 15; review round 1).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction is confirmed at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        -- Lock order: the draft lock (above); the Settlement's draft lock (as
        -- app.begin_settlement_correction takes it); the Lease row, as the Settlement confirm and
        -- the inspection writer take it, so no superseding inspection commits in between (review
        -- round 1); then the Lease key lock of the one-time charge recorder, so a charge on the
        -- Lease and this correction never interleave.
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        PERFORM 1 FROM app.leases WHERE id=v_settlement.lease_id FOR SHARE;
        PERFORM pg_advisory_xact_lock(hashtextextended('invoice-lease:' || v_settlement.lease_id::text,0));
        -- Under the locks, the sources still have the digest the draft recorded, and the check of
        -- the recorder still gives the same result; otherwise the draft is stale and stays pending.
        IF 'settlement-correction:' || encode(sha256(convert_to(app.settlement_extra_charge_source_state(
                v_settlement.id,
                app.final_settlement_plan_id(v_draft.payload->'charge'->'corrects_invoice_id')::uuid,
                app.final_settlement_plan_id(v_draft.payload->'charge'->'inspection_damage_finding_id')::uuid
            )::text,'UTF8')),'hex') IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        -- The stored charge passes the recorder's shape check again, so a later recorder of
        -- another shape never reaches the writes below (review round 2).
        IF app.settlement_extra_charge_input(v_draft.payload->'charge')
            IS DISTINCT FROM v_draft.payload->'charge'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_now:=clock_timestamp();
        v_business_date:=timezone(v_timezone,v_now)::date;
        v_plan:=app.settlement_extra_charge_plan(p_property,v_settlement.id,v_draft.payload->'charge',
            v_business_date);
        IF v_plan->>'source_revision' IS DISTINCT FROM v_draft.source_revision
            OR v_plan->'lease_id' IS DISTINCT FROM v_draft.payload->'lease_id'
            OR v_plan->'customer_id' IS DISTINCT FROM v_draft.payload->'customer_id'
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_charge:=v_plan->'charge';
        v_customer:=(v_plan->>'customer_id')::uuid;
        v_lease:=(v_plan->>'lease_id')::uuid;
        SELECT lease.unit_id INTO STRICT v_unit FROM app.leases lease WHERE lease.id=v_lease;
        v_category:=v_charge->>'category';
        v_amount:=(v_charge->>'amount_usd_cents')::bigint;
        v_override:=v_charge->>'due_date' IS NOT NULL;

        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written.
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve');
        -- Every record is stamped after the approval (review round 1).
        v_now:=clock_timestamp();
        v_business_date:=timezone(v_timezone,v_now)::date;
        -- The Due Date of a one-time charge: the issue date plus the Property's days, or the
        -- authorized override, never before the issue date.
        IF (v_charge->>'due_date')::date<v_business_date THEN
            RAISE EXCEPTION 'The extra charge Due Date precedes the issue date' USING ERRCODE='55000'; END IF;
        SELECT COALESCE((v_charge->>'due_date')::date,v_business_date+property.one_time_charge_due_days)
        INTO STRICT v_due FROM app.properties property WHERE property.id=p_property;
        -- Fresh ids, never derived from the draft: a client chooses one-time charge, Invoice and
        -- audit ids elsewhere and could take a derived id first (security review round 1). An
        -- exact repeat finds its records through the correction's links.
        v_obligation:=gen_random_uuid();
        v_invoice:=gen_random_uuid();
        v_line:=gen_random_uuid();
        v_audit:=gen_random_uuid();
        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,
            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
            'variant','EXTRA_CHARGE');

        PERFORM app.link_settlement_correction_effect(v_correction,'authorized_nonrecurring_obligation_id',
            v_obligation);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES(v_audit,v_now,v_business_date,
            p_actor,'invoice.one_time_charge.recorded','authorized_nonrecurring_obligation',v_obligation,
            v_draft.reason,'financial.approve',p_property,'{}'::jsonb,
            jsonb_build_object('category',v_category,'amount_usd_cents',v_amount,
                'description',v_charge->>'description','evidence_reference',v_charge->>'evidence_reference',
                'inspection_damage_finding_id',v_charge->'inspection_damage_finding_id'),
            v_correction,'API','SUCCEEDED',v_evidence,v_customer,v_lease,v_unit);
        INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,lease_id,category,
            inspection_damage_finding_id,description,authorized_amount_usd_cents,governing_due_date,
            due_date_source,source_reference,authorized_at,authorized_by,authorization_reference,
            due_date_rule,reason,evidence_reference,audit_event_id)
        VALUES(v_obligation,v_customer,v_lease,v_category,
            (v_charge->>'inspection_damage_finding_id')::uuid,v_charge->>'description',v_amount,NULL,
            'BR-INV-018','settlement-correction:' || v_correction::text,v_now,p_actor,'financial.approve',
            '__ONE_TIME_RULE__',v_draft.reason,v_charge->>'evidence_reference',v_audit);

        PERFORM app.link_settlement_correction_effect(v_correction,'invoice_id',v_invoice);
        INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,status,
            invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,created_at,
            created_by,updated_at,updated_by)
        VALUES (v_invoice,'INV-' || to_char(v_business_date,'YYYYMMDD') || '-'
                || upper(substr(replace(v_invoice::text,'-',''),1,12)),
            v_customer,v_lease,v_category,'DRAFT',v_business_date,NULL,v_amount,'__ONE_TIME_RULE__',
            'BR-INV-018',v_now,p_actor,v_now,p_actor);
        INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,amount_usd_cents,
            authorized_obligation_id,calculation_trace,created_at,last_changed_at,created_by,last_changed_by)
        VALUES (v_line,v_invoice,1,v_category,v_charge->>'description',v_amount,v_obligation,
            jsonb_build_object('formula','authorized_source_exact_amount',
                'authorized_obligation_id',v_obligation,'authorized_amount_usd_cents',v_amount,
                'source_reference','settlement-correction:' || v_correction::text),
            v_now,v_now,p_actor,p_actor);
        v_draft_state:=app.invoice_resource_snapshot(v_invoice);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
            entity_id,reason,authorization_reference,property_id,previous_state,resulting_state,
            correlation_id,source,outcome,authorization_evidence,customer_id,lease_id)
        VALUES (gen_random_uuid(),v_now,
            v_business_date,p_actor,'invoice.created','invoice',v_invoice,
            'Invoice DRAFT created from a post-settlement correction','financial.approve',p_property,
            '{}'::jsonb,v_draft_state,v_correction,'API','SUCCEEDED',
            v_evidence || jsonb_build_object('authorized_obligation_id',v_obligation),v_customer,v_lease);
        -- Issued in the same call: a linked Invoice never stays DRAFT (writer notes, 10a).
        UPDATE app.invoices SET status='UNPAID',issued_at=v_now,issued_by=p_actor,due_date=v_due,
            due_date_override_reason=CASE WHEN v_override THEN v_charge->>'due_date_reason' END,
            due_date_set_by=CASE WHEN v_override THEN p_actor END,
            due_date_set_at=CASE WHEN v_override THEN v_now END,
            version=version+1,updated_at=v_now,updated_by=p_actor
        WHERE id=v_invoice;
        v_issued:=app.invoice_resource_snapshot(v_invoice);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
            entity_id,reason,authorization_reference,property_id,previous_state,resulting_state,
            correlation_id,source,outcome,authorization_evidence,customer_id,lease_id)
        VALUES (gen_random_uuid(),v_now,
            v_business_date,p_actor,'invoice.issued','invoice',v_invoice,
            COALESCE(v_charge->>'due_date_reason','Invoice issued by a post-settlement correction'),
            'financial.approve',p_property,v_draft_state,v_issued,v_correction,'API','SUCCEEDED',
            v_evidence || jsonb_build_object('due_date',v_due,'due_date_override',v_override),
            v_customer,v_lease);
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing Invoice writers run them (the Invoice validators read tables
        -- the financial role cannot read).
        SET CONSTRAINTS ALL IMMEDIATE;
        -- The writer's end check: every Invoice linked to this correction is issued.
        IF EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
            JOIN app.invoices invoice ON invoice.id=effect.invoice_id
            WHERE effect.settlement_correction_id=v_correction AND invoice.status='DRAFT')
        THEN RAISE EXCEPTION 'An Invoice linked to a post-settlement correction must be issued'
            USING ERRCODE='23514'; END IF;
        v_result:=app.settlement_extra_charge_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_now,
            v_business_date,p_actor,'final_settlement.correction.confirmed','settlement_correction',
            v_correction,v_draft.reason,'financial.approve',p_property,'{}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','EXTRA_CHARGE',
                'authorized_nonrecurring_obligation_id',v_obligation,'invoice_id',v_invoice,
                'customer_id',v_customer,'amount_usd_cents',v_amount,'due_date',v_due),
            v_correction,'API','SUCCEEDED',v_evidence,v_customer,v_lease,v_unit);
        RETURN v_result;
    END $$;

    -- Sub-slice 10a security review round 2 note: the database, not only the writer, refuses the
    -- commit while an Invoice linked to a correction is not issued. The check is positive, so it
    -- also fails when it runs before the Invoice is written (a caller may set it IMMEDIATE) or
    -- when the Invoice is VOID (security review round 1).
    CREATE FUNCTION app.assert_settlement_correction_invoice_issued()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        IF NOT EXISTS(SELECT 1 FROM app.invoices invoice
            WHERE invoice.id=NEW.invoice_id AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID'))
        THEN RAISE EXCEPTION 'An Invoice linked to a post-settlement correction must be issued'
            USING ERRCODE='23514'; END IF;
        RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER settlement_correction_effects_invoice_issued AFTER INSERT
        ON app.settlement_correction_effects DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        WHEN (NEW.invoice_id IS NOT NULL)
        EXECUTE FUNCTION app.assert_settlement_correction_invoice_issued();
""".replace("__ONE_TIME_RULE__", ONE_TIME_RULE)


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
            raise RuntimeError(f"Settlement extra charge source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    column, table = LINKS[-1]
    link_names = ",".join(name for name, _ in LINKS)
    link_match = "\n                OR ".join(
        f"(p_table='{linked.removeprefix('app.')}' AND effect.{name}=p_record)"
        for name, linked in LINKS
    )
    link_allowed = ",".join(f"'{name}'" for name, _ in LINKS)
    link_values = ",".join(f"CASE WHEN p_link='{name}' THEN p_record END" for name, _ in LINKS)
    op.execute(f"""
        -- Owner answer 4 to Q-2026-10-06-37: the one-time charge record of an extra charge.
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
    """)
    op.execute(EXTRA_CHARGE_SQL)
    _patch(CLOSED_GUARD, CLOSED_GUARD_REPLACEMENTS)
    for function in (RECORD, CONFIRM, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD}, {CONFIRM} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Settlement extra charge migration is forward-only")
