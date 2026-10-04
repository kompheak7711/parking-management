# ruff: noqa: E501
"""Hand-back month Rent Invoices (BR-RENT-030, BR-RENT-026, BR-LEASE-021; owner answers Q-2026-10-04-8 and -9).

Voluntary early leaving only (a VOLUNTARY_EARLY_VERIFIED termination). The date that counts is the
actual move-out date of the current physical move-out record. Covered: the monthly Rent Invoice
(generated on the 25th) for the hand-back month when the hand-back is before the 5th, and for the
next month when the hand-back is on or after the 25th. Payments and Customer Credit count as paid:
nothing applied gives VOID (invoices.void), something applied and something outstanding gives one
credit Adjustment per line for its outstanding amount (invoices.adjust), and nothing outstanding is
kept as issued. One explicit staff command per Invoice with a reason; nothing runs automatically.
The command runs the existing app.void_invoice and app.adjust_invoice, so every earlier Invoice
rule still applies, and records an append-only resolution linked to the move-out record.
"""

from alembic import op

revision = "20261017_82"
down_revision = "20261016_81"
branch_labels = None
depends_on = None

ASSESS = "app.hand_back_rent_invoice_assessment(uuid,uuid,uuid)"
RESOLVE = "app.resolve_hand_back_rent_invoice(uuid,uuid,uuid,uuid,text,integer,bigint,text)"
INTERNAL = (
    "app.hand_back_rent_invoice_basis(uuid,uuid,uuid)",
    "app.reject_hand_back_rent_resolution_change()",
    "app.validate_hand_back_rent_resolution()",
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.hand_back_rent_resolutions (
            id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK (idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            invoice_id uuid NOT NULL UNIQUE REFERENCES app.invoices(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            physical_move_out_event_id uuid NOT NULL
                REFERENCES app.physical_move_out_events(id) ON DELETE RESTRICT,
            hand_back_date date NOT NULL CHECK (isfinite(hand_back_date)),
            coverage text NOT NULL CHECK (coverage IN ('HAND_BACK_MONTH','NEXT_MONTH')),
            action text NOT NULL CHECK (action IN ('VOID','CREDIT_ADJUSTMENT')),
            authorization_reference text NOT NULL
                CHECK ((action='VOID' AND authorization_reference='invoices.void')
                    OR (action='CREDIT_ADJUSTMENT' AND authorization_reference='invoices.adjust')),
            expected_version integer NOT NULL CHECK (expected_version>0),
            expected_outstanding_usd_cents bigint NOT NULL CHECK (expected_outstanding_usd_cents>0),
            reason text NOT NULL CHECK (reason=btrim(reason) AND length(reason) BETWEEN 1 AND 500),
            invoice_void_event_id uuid UNIQUE REFERENCES app.invoice_void_events(id) ON DELETE RESTRICT,
            adjustment_ids uuid[] NOT NULL DEFAULT '{}',
            audit_event_id uuid NOT NULL UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT,
            response_body jsonb NOT NULL CHECK (jsonb_typeof(response_body)='object'),
            recorded_at timestamptz NOT NULL CHECK (isfinite(recorded_at)),
            UNIQUE (property_id,actor_id,idempotency_key),
            CHECK ((action='VOID')=(invoice_void_event_id IS NOT NULL)),
            CHECK ((action='VOID')=(cardinality(adjustment_ids)=0))
        );
        COMMENT ON TABLE app.hand_back_rent_resolutions IS
            'Append-only BR-RENT-030 resolutions of a monthly Rent Invoice after a voluntary early hand-back';

        CREATE FUNCTION app.reject_hand_back_rent_resolution_change()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Hand-back Rent resolutions are append-only' USING ERRCODE='55000';
        END $$;
        CREATE TRIGGER hand_back_rent_resolutions_immutable BEFORE UPDATE OR DELETE
            ON app.hand_back_rent_resolutions FOR EACH ROW
            EXECUTE FUNCTION app.reject_hand_back_rent_resolution_change();
        CREATE TRIGGER hand_back_rent_resolutions_no_truncate BEFORE TRUNCATE
            ON app.hand_back_rent_resolutions FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_hand_back_rent_resolution_change();

        CREATE FUNCTION app.validate_hand_back_rent_resolution()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM app.invoices AS invoice
                    JOIN app.physical_move_out_events AS move_out ON move_out.lease_id=invoice.lease_id
                    WHERE invoice.id=NEW.invoice_id AND invoice.lease_id=NEW.lease_id
                      AND move_out.id=NEW.physical_move_out_event_id
                      AND move_out.property_id=NEW.property_id
                      AND move_out.actual_move_out_date=NEW.hand_back_date)
                OR (NEW.invoice_void_event_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM app.invoice_void_events
                    WHERE id=NEW.invoice_void_event_id AND invoice_id=NEW.invoice_id))
                OR EXISTS (SELECT 1 FROM unnest(NEW.adjustment_ids) AS adjustment(id)
                    WHERE NOT EXISTS (SELECT 1 FROM app.invoice_adjustments AS recorded
                        WHERE recorded.id=adjustment.id AND recorded.invoice_id=NEW.invoice_id
                          AND recorded.adjustment_type='CREDIT'))
            THEN RAISE EXCEPTION 'Hand-back resolution must match its Invoice, Lease, move-out and effects'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER hand_back_rent_resolutions_10_source BEFORE INSERT
            ON app.hand_back_rent_resolutions FOR EACH ROW
            EXECUTE FUNCTION app.validate_hand_back_rent_resolution();

        -- Internal: the assessment with the Lease and move-out identities the command records.
        CREATE FUNCTION app.hand_back_rent_invoice_basis(p_property uuid,p_actor uuid,p_invoice uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_invoice app.invoices%ROWTYPE; v_lease app.leases%ROWTYPE; v_move_out app.physical_move_out_events%ROWTYPE;
            v_current bigint; v_evidence text; v_coverage text; v_action text; v_month date;
            v_applied numeric; v_outstanding numeric; v_lines jsonb;
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_invoice IS NULL
            THEN RAISE EXCEPTION 'Hand-back assessment is invalid' USING ERRCODE='22023'; END IF;
            IF NOT EXISTS (SELECT 1 FROM app.user_accounts account
                JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
                WHERE account.actor_id=p_actor AND account.lifecycle_state='active'
                    AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Invoice command requires an active human actor' USING ERRCODE='P4506'; END IF;
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice;
            IF NOT FOUND OR app.invoice_property_id(p_invoice) IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Invoice was not found' USING ERRCODE='P4501'; END IF;
            IF v_invoice.primary_category<>'RENT' OR v_invoice.rent_billing_kind IS DISTINCT FROM 'RECURRING'
                OR v_invoice.lease_id IS NULL OR v_invoice.billing_period_start IS NULL
            THEN RAISE EXCEPTION 'The hand-back rule covers only monthly Rent Invoices generated on the 25th'
                USING ERRCODE='22023'; END IF;
            IF v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID')
            THEN RAISE EXCEPTION 'The hand-back rule covers only an issued Invoice that is not VOID'
                USING ERRCODE='22023'; END IF;
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_invoice.lease_id;
            v_evidence:=app.lease_termination_invoice_readiness(p_property,v_lease.id,p_actor,1,NULL)->>'evidence_status';
            IF v_evidence IS DISTINCT FROM 'VOLUNTARY_EARLY_VERIFIED' THEN
                RAISE EXCEPTION 'The hand-back rule covers only a verified voluntary early termination'
                    USING ERRCODE='22023'; END IF;
            SELECT count(*) INTO v_current FROM app.physical_move_out_events AS move_out
            WHERE move_out.lease_id=v_lease.id AND NOT EXISTS (
                SELECT 1 FROM app.physical_move_out_events AS later WHERE later.supersedes_event_id=move_out.id);
            IF v_current=0 THEN RAISE EXCEPTION 'The hand-back rule needs a recorded move-out'
                USING ERRCODE='22023'; END IF;
            IF v_current>1 THEN RAISE EXCEPTION 'The current move-out record is ambiguous'
                USING ERRCODE='55000'; END IF;
            SELECT move_out.* INTO STRICT v_move_out FROM app.physical_move_out_events AS move_out
            WHERE move_out.lease_id=v_lease.id AND NOT EXISTS (
                SELECT 1 FROM app.physical_move_out_events AS later WHERE later.supersedes_event_id=move_out.id);
            v_month:=date_trunc('month',v_invoice.billing_period_start)::date;
            v_coverage:=CASE
                WHEN extract(day FROM v_move_out.actual_move_out_date)<5
                    AND v_month=date_trunc('month',v_move_out.actual_move_out_date)::date THEN 'HAND_BACK_MONTH'
                WHEN extract(day FROM v_move_out.actual_move_out_date)>=25
                    AND v_month=(date_trunc('month',v_move_out.actual_move_out_date)+interval '1 month')::date
                    THEN 'NEXT_MONTH'
            END;
            IF v_coverage IS NULL THEN
                RAISE EXCEPTION 'The Invoice month is not covered by the hand-back date' USING ERRCODE='22023'; END IF;
            SELECT COALESCE(sum(app.invoice_line_payment_value_at(line.id,'infinity')
                    +app.invoice_line_credit_value_at(line.id,'infinity')),0),
                COALESCE(sum(app.invoice_line_outstanding(line.id)),0),
                COALESCE(jsonb_agg(jsonb_build_object('invoice_line_id',line.id,'category',line.category,
                    'line_sequence',line.line_sequence,
                    'applied_usd_cents',app.invoice_line_payment_value_at(line.id,'infinity')
                        +app.invoice_line_credit_value_at(line.id,'infinity'),
                    'outstanding_usd_cents',app.invoice_line_outstanding(line.id))
                    ORDER BY line.line_sequence,line.id),'[]'::jsonb)
            INTO v_applied,v_outstanding,v_lines
            FROM app.invoice_lines AS line WHERE line.invoice_id=p_invoice;
            v_action:=CASE WHEN v_applied=0 THEN 'VOID' WHEN v_outstanding=0 THEN 'KEEP'
                ELSE 'CREDIT_ADJUSTMENT' END;
            RETURN jsonb_build_object('invoice_id',p_invoice,'invoice_version',v_invoice.version,
                'invoice_status',v_invoice.status,'billing_period_start',v_invoice.billing_period_start,
                'coverage',v_coverage,'action',v_action,
                'applied_usd_cents',v_applied,'outstanding_usd_cents',v_outstanding,'lines',v_lines,
                'lease_id',v_lease.id,'customer_id',v_invoice.customer_id,
                'physical_move_out_event_id',v_move_out.id,'hand_back_date',v_move_out.actual_move_out_date);
        END $$;

        -- Shown to an invoices.read and leases.read holder: no Lease, move-out or date identities.
        CREATE FUNCTION app.hand_back_rent_invoice_assessment(p_property uuid,p_actor uuid,p_invoice uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        BEGIN
            RETURN app.hand_back_rent_invoice_basis(p_property,p_actor,p_invoice)
                - ARRAY['lease_id','customer_id','physical_move_out_event_id','hand_back_date'];
        END $$;

        CREATE FUNCTION app.resolve_hand_back_rent_invoice(p_property uuid,p_actor uuid,p_invoice uuid,
            p_key uuid,p_expected_action text,p_expected_version integer,p_expected_outstanding bigint,
            p_reason text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_existing app.hand_back_rent_resolutions%ROWTYPE; v_invoice app.invoices%ROWTYPE;
            v_basis jsonb; v_line jsonb; v_version integer; v_adjustment uuid; v_adjustments uuid[]:='{}';
            v_void_event uuid; v_line_id uuid; v_amount bigint; v_digest text; v_result jsonb; v_response jsonb;
            v_now timestamptz; v_timezone text; v_audit uuid; v_capability text; v_resolution uuid:=gen_random_uuid();
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_invoice IS NULL
                OR p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000'
                OR p_expected_action IS NULL OR p_expected_action NOT IN ('VOID','CREDIT_ADJUSTMENT')
                OR p_expected_version IS NULL OR p_expected_version<1
                OR p_expected_outstanding IS NULL OR p_expected_outstanding<1
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Hand-back resolution is invalid' USING ERRCODE='22023'; END IF;
            v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
            -- One request per key at a time, so a concurrent repeat replays the stored response.
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'hand-back-rent:' || p_property::text || ':' || p_actor::text || ':' || p_key::text,0));
            SELECT * INTO v_existing FROM app.hand_back_rent_resolutions
            WHERE property_id=p_property AND actor_id=p_actor AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_existing.invoice_id IS DISTINCT FROM p_invoice
                    OR v_existing.action IS DISTINCT FROM p_expected_action
                    OR v_existing.expected_version IS DISTINCT FROM p_expected_version
                    OR v_existing.expected_outstanding_usd_cents IS DISTINCT FROM p_expected_outstanding
                    OR v_existing.reason IS DISTINCT FROM p_reason
                THEN RAISE EXCEPTION 'Hand-back resolution key was reused' USING ERRCODE='P4505'; END IF;
                RETURN v_existing.response_body;
            END IF;
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice FOR UPDATE;
            IF NOT FOUND OR app.invoice_property_id(p_invoice) IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Invoice was not found' USING ERRCODE='P4501'; END IF;
            -- The termination and the current move-out must not change while this command runs.
            IF v_invoice.lease_id IS NOT NULL THEN
                PERFORM 1 FROM app.leases WHERE id=v_invoice.lease_id FOR SHARE NOWAIT;
            END IF;
            IF EXISTS (SELECT 1 FROM app.hand_back_rent_resolutions WHERE invoice_id=p_invoice) THEN
                RAISE EXCEPTION 'The Invoice already has a hand-back resolution' USING ERRCODE='P4503'; END IF;
            IF v_invoice.version<>p_expected_version THEN
                RAISE EXCEPTION 'Invoice version:%',v_invoice.version USING ERRCODE='P4504'; END IF;
            v_basis:=app.hand_back_rent_invoice_basis(p_property,p_actor,p_invoice);
            IF v_basis->>'action'='KEEP' THEN
                RAISE EXCEPTION 'A fully paid hand-back Invoice is kept as issued' USING ERRCODE='22023'; END IF;
            IF v_basis->>'action'<>p_expected_action
                OR (v_basis->>'outstanding_usd_cents')::numeric<>p_expected_outstanding
            THEN RAISE EXCEPTION 'The hand-back assessment changed' USING ERRCODE='P4503'; END IF;
            v_capability:=CASE p_expected_action WHEN 'VOID' THEN 'invoices.void' ELSE 'invoices.adjust' END;
            IF p_expected_action='VOID' THEN
                v_void_event:=gen_random_uuid();
                v_digest:=encode(sha256(convert_to(concat_ws('|','hand-back-rent','void',p_invoice,
                    p_expected_version,p_expected_outstanding,p_reason,p_key),'UTF8')),'hex');
                v_result:=app.void_invoice(p_property,p_invoice,p_actor,
                    md5('hand-back-rent|void|' || p_key::text)::uuid,v_digest,p_expected_version,
                    p_reason,v_void_event,gen_random_uuid());
                IF NOT EXISTS (SELECT 1 FROM app.invoice_void_events
                    WHERE id=v_void_event AND invoice_id=p_invoice)
                THEN RAISE EXCEPTION 'Hand-back VOID did not record its own VOID event' USING ERRCODE='55000'; END IF;
            ELSE
                v_version:=p_expected_version;
                FOR v_line IN SELECT value FROM jsonb_array_elements(v_basis->'lines')
                LOOP
                    CONTINUE WHEN (v_line->>'outstanding_usd_cents')::numeric<=0;
                    v_adjustment:=gen_random_uuid();
                    v_line_id:=(v_line->>'invoice_line_id')::uuid;
                    v_amount:=(v_line->>'outstanding_usd_cents')::bigint;
                    v_digest:=encode(sha256(convert_to(concat_ws('|','hand-back-rent','adjust',p_invoice,
                        v_line_id,v_amount,p_expected_version,p_reason,p_key),'UTF8')),'hex');
                    -- app.adjust_invoice ends with SET CONSTRAINTS ALL IMMEDIATE, which stays in force;
                    -- defer again so each call checks its deferred constraints after its own update,
                    -- as it does when called alone (precedent: migrations 39 and 41).
                    SET CONSTRAINTS ALL DEFERRED;
                    v_result:=app.adjust_invoice(p_property,p_invoice,v_line_id,p_actor,
                        md5('hand-back-rent|adjust|' || p_key::text || '|' || v_line_id::text)::uuid,
                        v_digest,v_version,'CREDIT',v_amount,
                        'hand-back-rent-resolution:' || v_resolution::text,p_reason,
                        v_adjustment,gen_random_uuid());
                    IF NOT EXISTS (SELECT 1 FROM app.invoice_adjustments WHERE id=v_adjustment
                        AND invoice_id=p_invoice AND invoice_line_id=v_line_id
                        AND adjustment_type='CREDIT' AND amount_usd_cents=v_amount)
                    THEN RAISE EXCEPTION 'Hand-back Adjustment did not record its own Adjustment'
                        USING ERRCODE='55000'; END IF;
                    v_adjustments:=v_adjustments || v_adjustment;
                    SELECT version INTO STRICT v_version FROM app.invoices WHERE id=p_invoice;
                END LOOP;
            END IF;
            v_now:=clock_timestamp();
            v_response:=jsonb_build_object('invoice',v_result,'coverage',v_basis->'coverage',
                'action',p_expected_action,'adjustment_ids',to_jsonb(v_adjustments),'reason',p_reason);
            v_audit:=gen_random_uuid();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
                source,outcome,authorization_evidence,customer_id,lease_id)
            VALUES(v_audit,v_now,timezone(v_timezone,v_now)::date,p_actor,'invoice.hand_back_rent.resolved',
                'invoice',p_invoice,p_reason,v_capability,p_property,
                v_basis-ARRAY['customer_id'],v_response,p_key,'API','SUCCEEDED',
                jsonb_build_object('capability',v_capability,'rule','BR-RENT-030',
                    'physical_move_out_event_id',v_basis->'physical_move_out_event_id'),
                (v_basis->>'customer_id')::uuid,(v_basis->>'lease_id')::uuid);
            INSERT INTO app.hand_back_rent_resolutions(id,property_id,actor_id,idempotency_key,invoice_id,lease_id,
                physical_move_out_event_id,hand_back_date,coverage,action,authorization_reference,
                expected_version,expected_outstanding_usd_cents,reason,invoice_void_event_id,adjustment_ids,
                audit_event_id,response_body,recorded_at)
            VALUES(v_resolution,p_property,p_actor,p_key,p_invoice,(v_basis->>'lease_id')::uuid,
                (v_basis->>'physical_move_out_event_id')::uuid,(v_basis->>'hand_back_date')::date,
                v_basis->>'coverage',p_expected_action,v_capability,p_expected_version,p_expected_outstanding,
                p_reason,v_void_event,v_adjustments,v_audit,v_response,v_now);
            RETURN v_response;
        END $$;
    """)
    op.execute(
        "REVOKE ALL ON TABLE app.hand_back_rent_resolutions "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in (ASSESS, RESOLVE, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {ASSESS} TO prm_runtime")
    op.execute(f"GRANT EXECUTE ON FUNCTION {RESOLVE} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Hand-back Rent migration is forward-only")
