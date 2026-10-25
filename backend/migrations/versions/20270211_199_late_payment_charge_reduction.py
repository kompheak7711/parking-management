"""Reduce or waive a Late-payment Charge after a staff mistake (V1-056 slice 11g-2; DL-076 answer 4).

BR-LATE-005, BR-CREDIT-014, BR-SETTLE-012, DL-076 answer 4 and reading (d):

1. New append-only table `app.late_payment_charge_reductions`: one row per reduction or waiver,
   naming its Late-payment Charge correction (REDUCTION, or CHARGE_REVERSAL for a waiver), one of
   the three fixed reasons, the "What happened" text (1 to 500 characters) and the paid value it
   released. The correction row keeps the actor, the time and the previous and resulting amount.
2. `app.reduce_late_payment_charge` (financial role): the Owner or a Manager
   (`late_payment.charge_correction`, in their default bundles only) sets a lower amount; 0 waives
   the Charge. The amount only goes down. When the Charge was paid above the new amount, the paid
   sources are reversed whole, newest first; each source's unreleased rest is posted again to the
   same Charge; released Payment value becomes Customer Credit of the Charge's Customer at once
   (BR-CREDIT-014, also when another person paid) and released Credit value goes back to its
   Credit, through the release record of migration `20261117_113`. A Charge a Deposit application
   paid is refused (only a Final Settlement applies Deposits; after closure the post-settlement
   corrections of BR-SETTLE-013 apply, and the closed Final Settlement refusal of migration
   `20261027_92` refuses this command).
3. `app.late_payment_charge_snapshot` names the reduction of each correction.

4. `app.correct_late_payment_charge` refuses (P4603) to reverse a reduction made here: its paid
   value was already released as Credit.

Additive: a new table, new functions, a read change and one added refusal. The old correction
route stays until slice 11g-3.
"""

from alembic import op
from sqlalchemy import text

revision = "20270211_199"
down_revision = "20270210_198"
branch_labels = None
depends_on = None

RELEASE_REASON = "Late-payment Charge correction credit excess"
AUTHORIZATION = "late_payment.charge_correction"

SQL = rf"""
    -- "What happened": 1 to 500 characters, no white space at either end (by the database
    -- locale, never wider than the API's Unicode rule), no C0 or C1 control character but tab,
    -- line feed and carriage return.
    CREATE FUNCTION app.late_payment_reduction_text_valid(p_text text)
    RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
        SELECT p_text IS NOT NULL AND length(p_text) BETWEEN 1 AND 500
            AND p_text ~ '^\S([\s\S]*\S)?$' AND p_text !~ '[\x01-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]'
    $$;

    CREATE TABLE app.late_payment_charge_reductions (
        late_payment_charge_correction_id uuid PRIMARY KEY
            REFERENCES app.late_payment_charge_corrections(id) ON DELETE RESTRICT,
        late_payment_charge_id uuid NOT NULL
            REFERENCES app.late_payment_charges(id) ON DELETE RESTRICT,
        reason_code text NOT NULL CHECK (reason_code IN
            ('WRONG_INVOICE','PAID_ON_TIME_RECORDED_LATE','OTHER_STAFF_MISTAKE')),
        what_happened text NOT NULL CHECK (app.late_payment_reduction_text_valid(what_happened)),
        released_usd_cents bigint NOT NULL CHECK (released_usd_cents>=0),
        recorded_at timestamptz NOT NULL
    );
    CREATE INDEX late_payment_charge_reductions_charge_idx
        ON app.late_payment_charge_reductions(late_payment_charge_id);
    CREATE TRIGGER late_payment_charge_reductions_append_only BEFORE UPDATE OR DELETE
        ON app.late_payment_charge_reductions FOR EACH ROW
        EXECUTE FUNCTION app.reject_invoice_append_only_mutation();
    CREATE TRIGGER late_payment_charge_reductions_reject_truncate BEFORE TRUNCATE
        ON app.late_payment_charge_reductions FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_invoice_storage_truncate();

    -- The fixed reason's words (DL-076 answer 4), also stored as the correction's reason.
    CREATE FUNCTION app.late_payment_reduction_reason(p_code text)
    RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
        SELECT CASE p_code
            WHEN 'WRONG_INVOICE' THEN 'Staff recorded the payment on the wrong Invoice'
            WHEN 'PAID_ON_TIME_RECORDED_LATE' THEN 'Paid on time but recorded late'
            WHEN 'OTHER_STAFF_MISTAKE' THEN 'Other staff mistake' END
    $$;

    -- A reduction row names a REDUCTION or CHARGE_REVERSAL of its own Charge, made by this
    -- command, with the fixed reason's words; the release is at most what the Charge's paid
    -- sources lost (the release rows of the correction add up to it).
    CREATE FUNCTION app.validate_late_payment_charge_reduction()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_correction app.late_payment_charge_corrections%ROWTYPE; v_released bigint;
    BEGIN
        SELECT * INTO v_correction FROM app.late_payment_charge_corrections
        WHERE id=NEW.late_payment_charge_correction_id;
        SELECT COALESCE(sum(release.released_usd_cents),0) INTO v_released
        FROM app.invoice_credit_excess_releases release
        WHERE release.late_payment_charge_correction_id=NEW.late_payment_charge_correction_id;
        IF v_correction.id IS NULL OR v_correction.late_payment_charge_id IS DISTINCT FROM NEW.late_payment_charge_id
            OR v_correction.correction_kind NOT IN ('REDUCTION','CHARGE_REVERSAL')
            OR v_correction.authorization_reference IS DISTINCT FROM '{AUTHORIZATION}'
            OR v_correction.reason IS DISTINCT FROM app.late_payment_reduction_reason(NEW.reason_code)
            OR v_released<>NEW.released_usd_cents
            OR NEW.recorded_at<v_correction.occurred_at
        THEN RAISE EXCEPTION 'Late-payment Charge reduction does not match its correction'
            USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END $$;
    CREATE CONSTRAINT TRIGGER late_payment_charge_reductions_valid
        AFTER INSERT ON app.late_payment_charge_reductions DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION app.validate_late_payment_charge_reduction();

    -- The reduction of one correction as the Charge read shows it; null for any other correction.
    CREATE FUNCTION app.late_payment_charge_reduction_detail(p_correction uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT jsonb_build_object('reason_code',reduction.reason_code,
            'what_happened',reduction.what_happened,
            'released',jsonb_build_object('currency','USD','minor_units',reduction.released_usd_cents),
            'customer_credit_ids',COALESCE((SELECT jsonb_agg(release.customer_credit_id
                    ORDER BY release.customer_credit_id)
                FROM app.invoice_credit_excess_releases release
                WHERE release.late_payment_charge_correction_id=reduction.late_payment_charge_correction_id
                  AND release.customer_credit_id IS NOT NULL),'[]'::jsonb),
            'recorded_at',reduction.recorded_at)
        FROM app.late_payment_charge_reductions reduction
        WHERE reduction.late_payment_charge_correction_id=p_correction
    $$;

    -- The Owner or a Manager reduces or waives a Late-payment Charge (DL-076 answer 4). Refusals:
    -- a bad request identity or input P4602; an unknown Property or Charge P4601; an inactive
    -- actor P4606; a reused idempotency key P4605; business state (a waived Charge, a Charge a
    -- Deposit application paid, payments changed under the locks, the amount not lower) P4603; a
    -- closed Final Settlement P5S01. Nothing is written unless everything succeeds.
    CREATE FUNCTION app.reduce_late_payment_charge(
        p_property_id uuid,p_charge_id uuid,p_actor_id uuid,p_idempotency_key uuid,
        p_request_digest text,p_request_id text,p_resulting bigint,p_reason_code text,
        p_what_happened text,p_correction_id uuid,p_audit_id uuid
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog
    SET "TimeZone"='UTC' AS $$
    DECLARE v_replay jsonb; v_before jsonb; v_result jsonb; v_response jsonb;
        v_charge app.late_payment_charges%ROWTYPE; v_timezone text; v_now timestamptz;
        v_business_date date; v_current bigint; v_amount bigint; v_kind text; v_reason text;
        v_summary jsonb; v_sources jsonb; v_payments uuid[]; v_credits uuid[];
        v_remaining bigint; v_release bigint; v_source jsonb; v_released jsonb:='[]'::jsonb;
        v_total_released bigint:=0; v_new uuid; v_credit uuid; v_rest bigint; v_at timestamptz;
        v_allocation app.payment_allocations%ROWTYPE;
        v_application app.customer_credit_applications%ROWTYPE;
        v_correlation_id uuid; v_lease uuid; v_id uuid;
    BEGIN
        IF p_request_id IS NULL OR p_request_id!~'^[A-Za-z0-9][A-Za-z0-9._:-]{{0,127}}$'
        THEN RAISE EXCEPTION 'Late-payment request identity is invalid' USING ERRCODE='P4602'; END IF;
        v_replay:=app.late_payment_command_replay(p_property_id,p_actor_id,'correction',
            p_idempotency_key,p_request_digest);
        IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
        v_timezone:=app.require_late_payment_actor(p_property_id,p_actor_id);
        v_reason:=app.late_payment_reduction_reason(p_reason_code);
        IF p_correction_id IS NULL OR p_correction_id='00000000-0000-0000-0000-000000000000'::uuid
            OR p_audit_id IS NULL OR p_audit_id='00000000-0000-0000-0000-000000000000'::uuid
            OR v_reason IS NULL OR NOT app.late_payment_reduction_text_valid(p_what_happened)
            OR p_resulting IS NULL OR p_resulting<0 OR p_resulting>9000000000000000
        THEN RAISE EXCEPTION 'Late-payment reduction input is invalid' USING ERRCODE='P4602'; END IF;
        -- The checks below rely on READ COMMITTED: each statement sees the commits the locks
        -- waited for (as the post-settlement correction confirms).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A Late-payment Charge reduction runs at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        SELECT * INTO v_charge FROM app.late_payment_charges WHERE id=p_charge_id;
        IF NOT FOUND OR app.invoice_property_id(v_charge.source_invoice_id) IS DISTINCT FROM p_property_id
        THEN RAISE EXCEPTION 'Late-payment Charge was not found' USING ERRCODE='P4601'; END IF;
        -- Lock order (as app.lock_settlement_correction_plan): one id-ordered Payment pass over
        -- the Payments of every source that pays the Charge (a Credit application's through its
        -- Credit's source Payment), each through its serializer and then FOR UPDATE; then those
        -- Credits in id order; then the Charge FOR UPDATE and its source Invoice FOR UPDATE (as
        -- every one-call Charge writer). A source added before the Charge lock from another
        -- Payment or Credit is refused below (P4603; the client tries again).
        v_sources:=app.settlement_late_charge_refund_sources(p_charge_id);
        SELECT COALESCE(array_agg(DISTINCT (value->>'payment_id')::uuid)
                FILTER (WHERE value->>'payment_id' IS NOT NULL),'{{}}'),
            COALESCE(array_agg(DISTINCT (value->>'credit_id')::uuid)
                FILTER (WHERE value->>'kind'='CREDIT_APPLICATION'),'{{}}')
        INTO v_payments,v_credits FROM jsonb_array_elements(v_sources);
        -- (A Credit source's payment_id is its Credit's source Payment already; the union keeps
        -- the pass the same as the shared plan's.)
        FOR v_id IN SELECT payment.id FROM (SELECT credit.source_payment_id AS id
                FROM app.customer_credits credit WHERE credit.id=ANY(v_credits)
                UNION SELECT unnest(v_payments)) payment
            WHERE payment.id IS NOT NULL ORDER BY 1
        LOOP
            PERFORM app.serialize_payment_state(v_id);
            PERFORM 1 FROM app.payments WHERE id=v_id FOR UPDATE;
        END LOOP;
        PERFORM 1 FROM app.customer_credits WHERE id=ANY(v_credits) ORDER BY id FOR UPDATE;
        SELECT * INTO STRICT v_charge FROM app.late_payment_charges WHERE id=p_charge_id FOR UPDATE;
        SELECT invoice.lease_id INTO v_lease FROM app.invoices invoice
        WHERE invoice.id=v_charge.source_invoice_id FOR UPDATE;
        v_sources:=app.settlement_late_charge_refund_sources(p_charge_id);
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_sources) source
            WHERE (source.value->>'kind'='PAYMENT_ALLOCATION'
                    AND NOT (source.value->>'payment_id')::uuid=ANY(v_payments))
               OR (source.value->>'kind'='CREDIT_APPLICATION'
                    AND NOT (source.value->>'credit_id')::uuid=ANY(v_credits)))
        THEN RAISE EXCEPTION 'The Late-payment Charge was paid again meanwhile; try again'
            USING ERRCODE='P4603'; END IF;
        IF EXISTS(SELECT 1 FROM app.late_payment_charge_corrections
            WHERE late_payment_charge_id=p_charge_id AND correction_kind='CHARGE_REVERSAL')
        THEN RAISE EXCEPTION 'A waived Late-payment Charge is terminal' USING ERRCODE='P4603'; END IF;
        v_summary:=app.late_payment_charge_application_summary(p_charge_id);
        IF (v_summary->>'deposit_total_usd_cents')::bigint>0 THEN
            RAISE EXCEPTION 'A Deposit application paid this Late-payment Charge at Final Settlement'
                USING ERRCODE='P4603'; END IF;
        v_current:=app.settlement_late_charge_obligation(p_charge_id);
        -- DL-076 answer 4: the amount only goes down.
        IF p_resulting>=v_current THEN
            RAISE EXCEPTION 'A Late-payment Charge reduction must lower the amount' USING ERRCODE='P4603';
        END IF;
        v_amount:=v_current-p_resulting;
        v_kind:=CASE WHEN p_resulting=0 THEN 'CHARGE_REVERSAL' ELSE 'REDUCTION' END;
        -- DL-076 reading (d): paid value above the new amount is released; whole sources, newest
        -- first, until it is covered (migration 67; as the post-settlement Refund correction).
        v_remaining:=GREATEST((v_summary->>'active_total_usd_cents')::bigint-p_resulting,0);
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_sources) LOOP
            EXIT WHEN v_remaining<=0;
            v_release:=LEAST((v_source->>'on_charge_usd_cents')::bigint,v_remaining);
            v_released:=v_released||jsonb_build_array(v_source||jsonb_build_object('released_usd_cents',v_release));
            v_remaining:=v_remaining-v_release;
            v_total_released:=v_total_released+v_release;
        END LOOP;
        IF v_remaining>0 THEN
            RAISE EXCEPTION 'Credit excess exceeds the applied value of the Late-payment Charge'
                USING ERRCODE='23514'; END IF;
        v_before:=app.late_payment_charge_snapshot(p_charge_id);
        v_correlation_id:=pg_catalog.md5('late-payment-command:'||p_property_id::text||':'||
            p_actor_id::text||':correction:'||p_idempotency_key::text)::uuid;
        -- Phase 1: reverse each released source whole, each dated after the Charge's latest event
        -- and, for a Credit application, its Credit's.
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_released) LOOP
            IF v_source->>'kind'='PAYMENT_ALLOCATION' THEN
                INSERT INTO app.payment_allocation_reversals(id,payment_allocation_id,reason,
                    occurred_at,actor_id,authorization_reference)
                VALUES(gen_random_uuid(),(v_source->>'id')::uuid,'{RELEASE_REASON}',
                    app.settlement_late_charge_instant(p_charge_id,NULL),p_actor_id,
                    'payments.allocations.reverse');
            ELSE
                INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,reason,
                    occurred_at,actor_id,authorization_reference)
                VALUES(gen_random_uuid(),(v_source->>'id')::uuid,'{RELEASE_REASON}',
                    app.settlement_late_charge_instant(p_charge_id,(v_source->>'credit_id')::uuid),
                    p_actor_id,'credits.applications.reverse');
            END IF;
        END LOOP;
        -- The Charge correction, stamped after every record on the Charge; its deferred validator
        -- (no result below the active applications) runs once the rests below are posted again.
        v_now:=app.settlement_late_charge_instant(p_charge_id,NULL);
        v_business_date:=timezone(v_timezone,v_now)::date;
        INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,correction_kind,
            amount_usd_cents,reverses_correction_id,reason,previous_obligation_usd_cents,
            resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,correlation_id)
        VALUES (p_correction_id,p_charge_id,v_kind,v_amount,NULL,v_reason,v_current,p_resulting,
            v_now,p_actor_id,'{AUTHORIZATION}',v_correlation_id);
        -- Phase 2 (migration 67, as migration 113): each source's unreleased rest is posted again
        -- to the same Charge with its release row naming the correction; released Payment value
        -- becomes Credit of the Charge's Customer (BR-CREDIT-014), released Credit value returns
        -- to its Credit.
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_released) LOOP
            v_release:=(v_source->>'released_usd_cents')::bigint;
            IF v_source->>'kind'='PAYMENT_ALLOCATION' THEN
                SELECT * INTO STRICT v_allocation FROM app.payment_allocations
                WHERE id=(v_source->>'id')::uuid;
                v_rest:=v_allocation.amount_usd_cents-v_release;
                v_new:=CASE WHEN v_rest>0 THEN gen_random_uuid() END;
                v_credit:=gen_random_uuid();
                INSERT INTO app.invoice_credit_excess_releases(id,late_payment_charge_correction_id,
                    source_kind,reversed_payment_allocation_id,replacement_payment_allocation_id,
                    customer_credit_id,released_usd_cents,reason,actor_id,created_at)
                VALUES(gen_random_uuid(),p_correction_id,'PAYMENT_ALLOCATION',v_allocation.id,v_new,
                    v_credit,v_release,'{RELEASE_REASON}',p_actor_id,clock_timestamp());
                IF v_new IS NOT NULL THEN
                    v_at:=app.settlement_late_charge_instant(p_charge_id,NULL);
                    INSERT INTO app.payment_allocations(id,payment_id,target_customer_id,proposal_batch_id,
                        between_invoice_sequence,target_kind,invoice_id,late_payment_charge_id,amount_usd_cents,
                        between_invoice_basis,within_invoice_basis,customer_designation_reference,
                        selected_invoice_due_date,selected_invoice_issued_at,selected_invoice_number_snapshot,
                        proposal_generated_at,proposal_trace,posted_at,posted_by,authorization_reference)
                    VALUES(v_new,v_allocation.payment_id,v_allocation.target_customer_id,NULL,NULL,
                        'LATE_PAYMENT_CHARGE',NULL,p_charge_id,v_rest,v_allocation.between_invoice_basis,
                        v_allocation.within_invoice_basis,v_allocation.customer_designation_reference,
                        NULL,NULL,NULL,NULL,NULL,v_at,p_actor_id,'payments.allocate');
                    INSERT INTO app.payment_allocation_details(id,payment_allocation_id,invoice_line_id,
                        late_payment_charge_id,obligation_kind,invoice_line_category_snapshot,
                        proposed_amount_usd_cents,posted_amount_usd_cents,attribution_basis,detail_sequence,
                        calculation_trace)
                    SELECT gen_random_uuid(),v_new,NULL,detail.late_payment_charge_id,detail.obligation_kind,
                        detail.invoice_line_category_snapshot,NULL,v_rest,detail.attribution_basis,1::smallint,
                        jsonb_build_object('reason','{RELEASE_REASON}','replaces_detail_id',detail.id,
                            'late_payment_charge_correction_id',p_correction_id)
                    FROM app.payment_allocation_details detail
                    WHERE detail.payment_allocation_id=v_allocation.id;
                END IF;
                INSERT INTO app.customer_credits(id,customer_id,source_payment_id,recognized_usd_cents,
                    customer_authorization_reference,recognized_at,recognized_by,reason,authorization_reference)
                VALUES(v_credit,v_charge.customer_id,v_allocation.payment_id,v_release,
                    'late-payment-charge-correction:' || p_correction_id::text,
                    app.settlement_late_charge_instant(p_charge_id,NULL),p_actor_id,
                    '{RELEASE_REASON}','credits.recognize');
            ELSE
                SELECT * INTO STRICT v_application FROM app.customer_credit_applications
                WHERE id=(v_source->>'id')::uuid;
                v_rest:=v_application.amount_usd_cents-v_release;
                v_new:=CASE WHEN v_rest>0 THEN gen_random_uuid() END;
                INSERT INTO app.invoice_credit_excess_releases(id,late_payment_charge_correction_id,
                    source_kind,reversed_credit_application_id,replacement_credit_application_id,
                    released_usd_cents,reason,actor_id,created_at)
                VALUES(gen_random_uuid(),p_correction_id,'CREDIT_APPLICATION',v_application.id,v_new,
                    v_release,'{RELEASE_REASON}',p_actor_id,clock_timestamp());
                IF v_new IS NOT NULL THEN
                    v_at:=app.settlement_late_charge_instant(p_charge_id,v_application.customer_credit_id);
                    INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,invoice_id,
                        late_payment_charge_id,final_settlement_id,amount_usd_cents,within_invoice_basis,
                        customer_designation_reference,proposal_generated_at,proposal_trace,occurred_at,
                        actor_id,authorization_reference)
                    VALUES(v_new,v_application.customer_credit_id,'LATE_PAYMENT_CHARGE',NULL,p_charge_id,NULL,
                        v_rest,v_application.within_invoice_basis,v_application.customer_designation_reference,
                        NULL,NULL,v_at,p_actor_id,'credits.apply');
                    INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,
                        invoice_line_id,late_payment_charge_id,obligation_kind,invoice_line_category_snapshot,
                        proposed_amount_usd_cents,applied_amount_usd_cents,attribution_basis,detail_sequence,
                        calculation_trace)
                    SELECT gen_random_uuid(),v_new,NULL,detail.late_payment_charge_id,detail.obligation_kind,
                        detail.invoice_line_category_snapshot,NULL,v_rest,detail.attribution_basis,1::smallint,
                        jsonb_build_object('reason','{RELEASE_REASON}','replaces_detail_id',detail.id,
                            'late_payment_charge_correction_id',p_correction_id)
                    FROM app.customer_credit_application_details detail
                    WHERE detail.customer_credit_application_id=v_application.id;
                END IF;
            END IF;
        END LOOP;
        INSERT INTO app.late_payment_charge_reductions(late_payment_charge_correction_id,
            late_payment_charge_id,reason_code,what_happened,released_usd_cents,recorded_at)
        VALUES (p_correction_id,p_charge_id,p_reason_code,p_what_happened,v_total_released,
            GREATEST(clock_timestamp(),v_now));
        -- Every record is written: the deferred checks run now, inside this definer function.
        SET CONSTRAINTS ALL IMMEDIATE;
        v_result:=app.late_payment_charge_snapshot(p_charge_id);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
            entity_id,reason,authorization_reference,property_id,previous_state,resulting_state,
            correlation_id,source,outcome,authorization_evidence,linked_source_event_id,customer_id,
            lease_id)
        VALUES (p_audit_id,v_now,v_business_date,p_actor_id,'late_payment.charge_corrected',
            'late_payment_charge',p_charge_id,v_reason,'{AUTHORIZATION}',p_property_id,v_before,
            v_result,v_correlation_id,'API','SUCCEEDED',
            jsonb_build_object('capability','{AUTHORIZATION}','kind',v_kind,
                'amount_usd_cents',v_amount,'reason_code',p_reason_code,
                'released_usd_cents',v_total_released,
                'released_sources',(SELECT COALESCE(jsonb_agg(jsonb_build_object('kind',source.value->>'kind',
                    'id',source.value->>'id','released_usd_cents',
                    (source.value->>'released_usd_cents')::bigint)),'[]'::jsonb)
                    FROM jsonb_array_elements(v_released) source)),
            p_correction_id,v_charge.customer_id,v_lease);
        v_response:=jsonb_build_object('data',v_result,'meta',jsonb_build_object('request_id',p_request_id));
        PERFORM app.record_late_payment_command(p_property_id,p_actor_id,'correction',
            p_idempotency_key,p_request_digest,'CHARGE',p_charge_id,p_correction_id,v_response,v_now);
        RETURN jsonb_build_object('status_code',200,'body',v_response);
    END $$;
"""

SNAPSHOT = "app.late_payment_charge_snapshot(uuid)"
SNAPSHOT_REPLACEMENTS = (
    (
        "                    'reason',correction.reason,\n",
        "                    'reason',correction.reason,\n"
        "                    -- V1-056 slice 11g-2: the reduction or waiver of DL-076 answer 4.\n"
        "                    'reduction',app.late_payment_charge_reduction_detail(correction.id),\n",
    ),
)

CORRECT = (
    "app.correct_late_payment_charge(uuid,uuid,uuid,uuid,text,text,text,bigint,uuid,text,uuid,uuid)"
)
CORRECT_REPLACEMENTS = (
    (
        "                IF NOT FOUND OR EXISTS (SELECT 1 FROM app.late_payment_charge_corrections\n"
        "                    WHERE reverses_correction_id=p_reverses_correction_id)\n",
        "                IF NOT FOUND OR EXISTS (SELECT 1 FROM app.late_payment_charge_corrections\n"
        "                    WHERE reverses_correction_id=p_reverses_correction_id)\n"
        "                    -- V1-056 slice 11g-2: a reduction of DL-076 answer 4 released its paid\n"
        "                    -- value as Credit; it is not reversed here.\n"
        "                    OR EXISTS (SELECT 1 FROM app.late_payment_charge_reductions\n"
        "                        WHERE late_payment_charge_correction_id=p_reverses_correction_id)\n",
    ),
)

INTERNAL = (
    "app.late_payment_reduction_text_valid(text)",
    "app.late_payment_reduction_reason(text)",
    "app.validate_late_payment_charge_reduction()",
    "app.late_payment_charge_reduction_detail(uuid)",
)
COMMAND = "app.reduce_late_payment_charge(uuid,uuid,uuid,uuid,text,text,bigint,text,text,uuid,uuid)"


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
            raise RuntimeError(f"Late-payment Charge contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SQL)
    _patch(SNAPSHOT, SNAPSHOT_REPLACEMENTS)
    _patch(CORRECT, CORRECT_REPLACEMENTS)
    op.execute(
        "REVOKE ALL ON TABLE app.late_payment_charge_reductions "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in (*INTERNAL, COMMAND):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {COMMAND} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Late-payment Charge reduction migration is forward-only")
