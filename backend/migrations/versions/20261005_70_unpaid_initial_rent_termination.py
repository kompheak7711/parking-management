# ruff: noqa: E501
"""Explicit termination paths for an unpaid Initial obligation (BR-LEASE-005, DL-064)."""

from alembic import op
from sqlalchemy import text

revision = "20261005_70"
down_revision = "20261005_69"
branch_labels = None
depends_on = None

BASIS = "UNPAID_INITIAL_OBLIGATION"
CAUSE = "CUSTOMER_UNPAID_INITIAL_OBLIGATION"

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.lease_termination_context_shape_valid(jsonb)",
        (
            (
                "OR p_context->>'basis' NOT IN ('VOLUNTARY_EARLY','CUSTOMER_VIOLATION','SIGNED_LEASE_OTHER')",
                "OR p_context->>'basis' NOT IN ('VOLUNTARY_EARLY','CUSTOMER_VIOLATION','SIGNED_LEASE_OTHER',\n"
                f"                    '{BASIS}')",
            ),
        ),
    ),
    (
        "app.require_lease_termination_context(uuid,uuid,text,uuid,uuid,integer,date,timestamp with time zone,text,text,uuid)",
        (
            (
                "THEN RAISE EXCEPTION 'Termination context governing basis is invalid' USING ERRCODE='22023'; END IF;",
                f"""THEN RAISE EXCEPTION 'Termination context governing basis is invalid' USING ERRCODE='22023'; END IF;
            -- BR-LEASE-005: the ground is verified at termination time, after Lease Start plus five days.
            IF v_context.context_data->>'basis'='{BASIS}' AND (
                p_governing IS DISTINCT FROM 'BR-LEASE-005'
                OR timezone('Asia/Phnom_Penh',p_occurred)::date<=v_lease.start_date+5
                OR NOT (
                    EXISTS(SELECT 1 FROM app.invoices invoice
                        JOIN app.invoice_lines line ON line.invoice_id=invoice.id
                        WHERE invoice.lease_id=p_lease AND invoice.rent_billing_kind='INITIAL'
                          AND invoice.status NOT IN ('DRAFT','VOID')
                          AND app.invoice_line_outstanding_at(line.id,p_occurred)>0)
                    OR EXISTS(SELECT 1 FROM app.deposits deposit
                        WHERE deposit.lease_id=p_lease AND deposit.deposit_type='SECURITY'
                          AND app.deposit_held_value_at(deposit.id,p_occurred)<deposit.required_usd_cents)))
            THEN RAISE EXCEPTION 'Unpaid Initial obligation ground is not met' USING ERRCODE='22023'; END IF;""",
            ),
        ),
    ),
    (
        "app.record_lease_deposit_disposition_with_context(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text,uuid,text,bigint)",
        (
            (
                "OR p_rule IS NULL OR p_rule NOT IN ('BR-DEP-022','BR-DEP-023')",
                "OR p_rule IS NULL OR p_rule NOT IN ('BR-DEP-022','BR-DEP-023','BR-LEASE-005')",
            ),
        ),
    ),
    (
        "app.require_lease_deposit_disposition_context(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text)",
        (
            (
                "            ELSE RAISE EXCEPTION 'Unsupported Deposit disposition rule' USING ERRCODE='22023';",
                f"""            ELSIF v_context.governing_rule='BR-LEASE-005' THEN
                IF v_deposit.deposit_type IS DISTINCT FROM 'SECURITY'
                    OR v_event.governing_event_reference IS DISTINCT FROM 'BR-LEASE-005'
                    OR v_termination.command_event_id IS NULL
                    OR v_termination.context_data->>'basis' IS DISTINCT FROM '{BASIS}'
                    OR EXISTS(SELECT 1 FROM app.occupancies WHERE lease_id=p_lease)
                THEN RAISE EXCEPTION 'Unpaid Initial Security forfeiture source is invalid' USING ERRCODE='22023'; END IF;
            ELSE RAISE EXCEPTION 'Unsupported Deposit disposition rule' USING ERRCODE='22023';""",
            ),
        ),
    ),
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Unpaid Initial termination source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    rule_checks = (
        op.get_bind()
        .execute(
            text(
                "SELECT conname FROM pg_catalog.pg_constraint "
                "WHERE conrelid='app.lease_deposit_disposition_contexts'::regclass AND contype='c' "
                "AND pg_catalog.pg_get_constraintdef(oid) LIKE '%governing_rule%BR-DEP-023%'"
            )
        )
        .scalars()
        .all()
    )
    if len(rule_checks) != 1:
        raise RuntimeError("Deposit disposition rule constraint is not unique")
    op.execute(f"""
        ALTER TABLE app.lease_deposit_disposition_contexts DROP CONSTRAINT {rule_checks[0]};
        ALTER TABLE app.lease_deposit_disposition_contexts ADD CONSTRAINT {rule_checks[0]}
            CHECK (governing_rule IN ('BR-DEP-022','BR-DEP-023','BR-LEASE-005'));

        CREATE TABLE app.unpaid_initial_termination_resolutions (
            id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK (idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            request_digest text NOT NULL CHECK (request_digest~'^[0-9a-f]{{64}}$'),
            termination_event_id uuid NOT NULL UNIQUE REFERENCES app.lease_commands(event_id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            path text NOT NULL CHECK (path IN ('NEVER_MOVED_IN','MOVED_IN')),
            cause text NOT NULL CHECK (cause='{CAUSE}'),
            reason text NOT NULL CHECK (reason=btrim(reason) AND length(reason) BETWEEN 1 AND 500),
            resulting_unit_status text CHECK (resulting_unit_status IN ('VACANT','CLEANING')),
            unit_status_reason text CHECK (unit_status_reason=btrim(unit_status_reason)
                AND length(unit_status_reason) BETWEEN 1 AND 500),
            deposit_disposition_id uuid REFERENCES app.deposit_dispositions(id) ON DELETE RESTRICT,
            invoice_void_event_id uuid REFERENCES app.invoice_void_events(id) ON DELETE RESTRICT,
            adjustment_ids jsonb NOT NULL CHECK (jsonb_typeof(adjustment_ids)='array'),
            credit_usd_cents bigint NOT NULL CHECK (credit_usd_cents>=0),
            audit_event_id uuid NOT NULL UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT,
            result_snapshot jsonb NOT NULL CHECK (jsonb_typeof(result_snapshot)='object'),
            occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
            UNIQUE (property_id,actor_id,idempotency_key),
            CONSTRAINT unpaid_initial_resolution_shape CHECK (
                (path='NEVER_MOVED_IN' AND resulting_unit_status IS NOT NULL
                    AND (resulting_unit_status='VACANT') = (unit_status_reason IS NULL))
                OR (path='MOVED_IN' AND resulting_unit_status IS NULL AND unit_status_reason IS NULL
                    AND deposit_disposition_id IS NULL AND invoice_void_event_id IS NULL))
        );

        CREATE FUNCTION app.unpaid_initial_derived_key(p_key uuid,p_step text) RETURNS uuid
        LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
            SELECT md5(p_key::text || ':' || p_step)::uuid
        $$;
        CREATE FUNCTION app.unpaid_initial_derived_digest(p_digest text,p_step text) RETURNS text
        LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
            SELECT encode(sha256(convert_to(p_digest || ':' || p_step,'UTF8')),'hex')
        $$;

        -- Shared check: the termination used the unpaid-Initial basis in this Property.
        CREATE FUNCTION app.unpaid_initial_termination_source(p_property uuid,p_event uuid)
        RETURNS app.leases LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_lease app.leases%ROWTYPE; v_event app.lease_commands%ROWTYPE;
        BEGIN
            SELECT * INTO v_event FROM app.lease_commands WHERE event_id=p_event;
            IF NOT FOUND OR v_event.action<>'lease.terminate' OR v_event.property_id<>p_property
            THEN RAISE EXCEPTION 'Termination event was not found' USING ERRCODE='P0002'; END IF;
            SELECT lease.* INTO STRICT v_lease FROM app.leases lease WHERE lease.id=v_event.lease_id FOR UPDATE;
            IF v_lease.status<>'TERMINATED' OR v_event.governing_event_reference IS DISTINCT FROM 'BR-LEASE-005'
                OR NOT EXISTS(SELECT 1 FROM app.lease_termination_contexts context
                    WHERE context.command_event_id=p_event AND context.context_data->>'basis'='{BASIS}')
            THEN RAISE EXCEPTION 'Termination was not for an unpaid Initial obligation' USING ERRCODE='22023'; END IF;
            RETURN v_lease;
        END $$;

        -- BR-LEASE-005 never moved in: forfeit the Security Deposit, VOID or credit the unpaid Initial
        -- Invoice, and release the Unit. The Pet Deposit and the COMPLETED Reservation are not touched.
        CREATE FUNCTION app.resolve_unpaid_initial_never_moved_in(p_property uuid,p_actor uuid,p_key uuid,
            p_digest text,p_resolution uuid,p_event uuid,p_unit_status text,p_unit_reason text,p_reason text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_prior app.unpaid_initial_termination_resolutions%ROWTYPE; v_lease app.leases%ROWTYPE;
            v_unit app.units%ROWTYPE; v_deposit app.deposits%ROWTYPE; v_invoice app.invoices%ROWTYPE;
            v_line record; v_disposition uuid; v_void uuid; v_adjustments jsonb:='[]'::jsonb; v_adjustment uuid;
            v_held bigint; v_applied numeric; v_credit bigint:=0; v_now timestamptz; v_audit uuid; v_result jsonb;
            v_step integer:=0;
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_key IS NULL OR p_resolution IS NULL OR p_event IS NULL
                OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{{64}}$'
                OR p_unit_status IS NULL OR p_unit_status NOT IN ('VACANT','CLEANING')
                OR (p_unit_status='CLEANING') <> (p_unit_reason IS NOT NULL)
                OR (p_unit_reason IS NOT NULL AND (p_unit_reason<>btrim(p_unit_reason)
                    OR length(p_unit_reason) NOT BETWEEN 1 AND 500))
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Unpaid Initial resolution is invalid' USING ERRCODE='22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                p_property::text || '|' || p_actor::text || '|unpaid-initial|' || p_key::text,0));
            SELECT * INTO v_prior FROM app.unpaid_initial_termination_resolutions
            WHERE property_id=p_property AND actor_id=p_actor AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_prior.request_digest<>p_digest THEN
                    RAISE EXCEPTION 'Unpaid Initial resolution key was reused' USING ERRCODE='23505'; END IF;
                RETURN v_prior.result_snapshot;
            END IF;
            v_lease:=app.unpaid_initial_termination_source(p_property,p_event);
            IF EXISTS(SELECT 1 FROM app.occupancies WHERE lease_id=v_lease.id)
                OR NOT EXISTS(SELECT 1 FROM app.lease_signing_outcomes WHERE lease_id=v_lease.id)
                OR EXISTS(SELECT 1 FROM app.unpaid_initial_termination_resolutions WHERE termination_event_id=p_event)
            THEN RAISE EXCEPTION 'Never-moved-in resolution does not apply' USING ERRCODE='22023'; END IF;
            SELECT * INTO STRICT v_unit FROM app.units WHERE id=v_lease.unit_id FOR UPDATE;
            IF v_unit.status<>'OCCUPIED' THEN
                RAISE EXCEPTION 'Unit is not held by this Lease' USING ERRCODE='22023'; END IF;
            SELECT * INTO v_deposit FROM app.deposits
            WHERE lease_id=v_lease.id AND deposit_type='SECURITY' FOR UPDATE;
            IF FOUND THEN
                v_held:=app.deposit_held_value_at(v_deposit.id,statement_timestamp());
                IF v_held>0 THEN
                    v_disposition:=gen_random_uuid();
                    PERFORM app.record_lease_deposit_disposition_with_context(p_property,p_actor,
                        app.unpaid_initial_derived_key(p_key,'deposit'),
                        app.unpaid_initial_derived_digest(p_digest,'deposit'),v_disposition,v_deposit.id,
                        v_lease.id,v_held,v_lease.actual_termination_date,p_reason,'deposits.dispose',p_event,
                        'BR-LEASE-005',app.deposit_disposition_state_version(v_deposit.id));
                END IF;
            END IF;
            SELECT * INTO v_invoice FROM app.invoices
            WHERE lease_id=v_lease.id AND rent_billing_kind='INITIAL' AND status NOT IN ('DRAFT','VOID')
            ORDER BY issued_at DESC LIMIT 1;
            IF FOUND THEN
                SELECT COALESCE(sum(app.invoice_line_application_value_at(line.id,'infinity')),0)
                INTO v_applied FROM app.invoice_lines line WHERE line.invoice_id=v_invoice.id;
                IF v_applied=0 THEN
                    v_void:=gen_random_uuid();
                    PERFORM app.void_invoice(p_property,v_invoice.id,p_actor,
                        app.unpaid_initial_derived_key(p_key,'void'),
                        app.unpaid_initial_derived_digest(p_digest,'void'),v_invoice.version,p_reason,
                        v_void,gen_random_uuid());
                ELSE
                    FOR v_line IN SELECT line.id,app.invoice_line_outstanding(line.id) AS outstanding
                        FROM app.invoice_lines line WHERE line.invoice_id=v_invoice.id ORDER BY line.line_sequence
                    LOOP
                        CONTINUE WHEN v_line.outstanding<=0;
                        v_step:=v_step+1;
                        v_adjustment:=gen_random_uuid();
                        PERFORM app.adjust_invoice(p_property,v_invoice.id,v_line.id,p_actor,
                            app.unpaid_initial_derived_key(p_key,'credit-' || v_step),
                            app.unpaid_initial_derived_digest(p_digest,'credit-' || v_step),
                            (SELECT version FROM app.invoices WHERE id=v_invoice.id),'CREDIT',v_line.outstanding,
                            'unpaid-initial-termination:' || p_resolution::text || ':' || v_step,p_reason,
                            v_adjustment,gen_random_uuid());
                        v_adjustments:=v_adjustments || jsonb_build_array(v_adjustment);
                        v_credit:=v_credit+v_line.outstanding;
                    END LOOP;
                END IF;
            END IF;
            v_now:=clock_timestamp();
            UPDATE app.units SET status=p_unit_status,version=version+1,updated_at=v_now,updated_by=p_actor
            WHERE id=v_unit.id;
            v_result:=jsonb_build_object('resolution_id',p_resolution,'termination_event_id',p_event,
                'lease_id',v_lease.id,'path','NEVER_MOVED_IN','cause','{CAUSE}',
                'resulting_unit_status',p_unit_status,'deposit_disposition_id',v_disposition,
                'invoice_void_event_id',v_void,'adjustment_ids',v_adjustments,'credit_usd_cents',v_credit);
            v_audit:=gen_random_uuid();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
                source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
            VALUES(v_audit,v_now,timezone('Asia/Phnom_Penh',v_now)::date,p_actor,
                'lease.unpaid_initial_termination.resolved','unpaid_initial_termination_resolution',p_resolution,
                p_reason,'leases.terminate',p_property,jsonb_build_object('unit_status',v_unit.status),v_result,
                p_event,'API','SUCCEEDED',jsonb_build_object('capability','leases.terminate',
                    'cause','{CAUSE}','unit_status_reason',p_unit_reason),
                v_lease.primary_tenant_id,v_lease.id,v_unit.id);
            INSERT INTO app.unpaid_initial_termination_resolutions(id,property_id,actor_id,idempotency_key,
                request_digest,termination_event_id,lease_id,path,cause,reason,resulting_unit_status,
                unit_status_reason,deposit_disposition_id,invoice_void_event_id,adjustment_ids,credit_usd_cents,
                audit_event_id,result_snapshot,occurred_at)
            VALUES(p_resolution,p_property,p_actor,p_key,p_digest,p_event,v_lease.id,'NEVER_MOVED_IN','{CAUSE}',
                p_reason,p_unit_status,p_unit_reason,v_disposition,v_void,v_adjustments,v_credit,v_audit,
                v_result,v_now);
            SET CONSTRAINTS ALL IMMEDIATE;
            RETURN v_result;
        END $$;

        -- BR-LEASE-005 moved in: keep the Initial Invoice and credit the Rent for days after the
        -- termination date with BR-RENT-007 proration; move-out and final charges follow their own rules.
        CREATE FUNCTION app.credit_initial_rent_after_termination(p_property uuid,p_actor uuid,p_key uuid,
            p_digest text,p_resolution uuid,p_event uuid,p_reason text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_prior app.unpaid_initial_termination_resolutions%ROWTYPE; v_lease app.leases%ROWTYPE;
            v_invoice app.invoices%ROWTYPE; v_line app.invoice_lines%ROWTYPE; v_component record;
            v_credit bigint:=0; v_adjustments jsonb:='[]'::jsonb; v_adjustment uuid; v_now timestamptz;
            v_audit uuid; v_result jsonb; v_term date;
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_key IS NULL OR p_resolution IS NULL OR p_event IS NULL
                OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{{64}}$'
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Initial Rent termination credit is invalid' USING ERRCODE='22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                p_property::text || '|' || p_actor::text || '|unpaid-initial|' || p_key::text,0));
            SELECT * INTO v_prior FROM app.unpaid_initial_termination_resolutions
            WHERE property_id=p_property AND actor_id=p_actor AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_prior.request_digest<>p_digest THEN
                    RAISE EXCEPTION 'Unpaid Initial resolution key was reused' USING ERRCODE='23505'; END IF;
                RETURN v_prior.result_snapshot;
            END IF;
            v_lease:=app.unpaid_initial_termination_source(p_property,p_event);
            IF NOT EXISTS(SELECT 1 FROM app.occupancies WHERE lease_id=v_lease.id)
                OR EXISTS(SELECT 1 FROM app.unpaid_initial_termination_resolutions WHERE termination_event_id=p_event)
            THEN RAISE EXCEPTION 'Moved-in termination credit does not apply' USING ERRCODE='22023'; END IF;
            v_term:=v_lease.actual_termination_date;
            SELECT * INTO v_invoice FROM app.invoices
            WHERE lease_id=v_lease.id AND rent_billing_kind='INITIAL' AND status NOT IN ('DRAFT','VOID')
            ORDER BY issued_at DESC LIMIT 1;
            IF FOUND THEN
                SELECT * INTO STRICT v_line FROM app.invoice_lines
                WHERE invoice_id=v_invoice.id AND category='RENT';
                FOR v_component IN
                    SELECT component.period_start,component.period_end,
                        component.contractual_monthly_usd_cents AS monthly,component.amount_usd_cents AS amount
                    FROM app.invoice_line_calculation_components component
                    WHERE component.invoice_line_id=v_line.id
                    UNION ALL
                    SELECT v_invoice.billing_period_start,v_invoice.billing_period_end,
                        v_lease.monthly_rent_usd_cents,v_line.amount_usd_cents
                    WHERE NOT EXISTS(SELECT 1 FROM app.invoice_line_calculation_components
                        WHERE invoice_line_id=v_line.id)
                LOOP
                    IF v_component.period_start>v_term THEN
                        v_credit:=v_credit+v_component.amount;
                    ELSIF v_component.period_end>v_term THEN
                        v_credit:=v_credit+v_component.amount-app.calculate_prorated_monthly_usd_cents(
                            v_component.monthly,v_component.period_start,v_term);
                    END IF;
                END LOOP;
                IF v_credit>0 THEN
                    v_adjustment:=gen_random_uuid();
                    PERFORM app.adjust_invoice(p_property,v_invoice.id,v_line.id,p_actor,
                        app.unpaid_initial_derived_key(p_key,'credit'),
                        app.unpaid_initial_derived_digest(p_digest,'credit'),v_invoice.version,'CREDIT',v_credit,
                        'unpaid-initial-termination:' || p_resolution::text,p_reason,v_adjustment,gen_random_uuid());
                    v_adjustments:=jsonb_build_array(v_adjustment);
                END IF;
            END IF;
            v_now:=clock_timestamp();
            v_result:=jsonb_build_object('resolution_id',p_resolution,'termination_event_id',p_event,
                'lease_id',v_lease.id,'path','MOVED_IN','cause','{CAUSE}','adjustment_ids',v_adjustments,
                'credit_usd_cents',v_credit);
            v_audit:=gen_random_uuid();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
                source,outcome,authorization_evidence,customer_id,lease_id)
            VALUES(v_audit,v_now,timezone('Asia/Phnom_Penh',v_now)::date,p_actor,
                'lease.unpaid_initial_termination.resolved','unpaid_initial_termination_resolution',p_resolution,
                p_reason,'leases.terminate',p_property,'{{}}'::jsonb,v_result,p_event,'API','SUCCEEDED',
                jsonb_build_object('capability','leases.terminate','cause','{CAUSE}'),
                v_lease.primary_tenant_id,v_lease.id);
            INSERT INTO app.unpaid_initial_termination_resolutions(id,property_id,actor_id,idempotency_key,
                request_digest,termination_event_id,lease_id,path,cause,reason,adjustment_ids,credit_usd_cents,
                audit_event_id,result_snapshot,occurred_at)
            VALUES(p_resolution,p_property,p_actor,p_key,p_digest,p_event,v_lease.id,'MOVED_IN','{CAUSE}',
                p_reason,v_adjustments,v_credit,v_audit,v_result,v_now);
            SET CONSTRAINTS ALL IMMEDIATE;
            RETURN v_result;
        END $$;
    """)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    op.execute(
        "CREATE TRIGGER unpaid_initial_termination_resolutions_reject_mutation BEFORE UPDATE OR DELETE "
        "ON app.unpaid_initial_termination_resolutions FOR EACH ROW "
        "EXECUTE FUNCTION app.reject_lease_append_only_mutation()"
    )
    op.execute(
        "CREATE TRIGGER unpaid_initial_termination_resolutions_reject_truncate BEFORE TRUNCATE "
        "ON app.unpaid_initial_termination_resolutions FOR EACH STATEMENT "
        "EXECUTE FUNCTION app.reject_lease_storage_truncate()"
    )
    op.execute(
        "REVOKE ALL ON TABLE app.unpaid_initial_termination_resolutions "
        "FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
    )
    op.execute(
        "GRANT SELECT ON TABLE app.unpaid_initial_termination_resolutions TO prm_runtime,prm_financial"
    )
    never = (
        "app.resolve_unpaid_initial_never_moved_in(uuid,uuid,uuid,text,uuid,uuid,text,text,text)"
    )
    moved = "app.credit_initial_rent_after_termination(uuid,uuid,uuid,text,uuid,uuid,text)"
    for function in (
        "app.unpaid_initial_derived_key(uuid,text)",
        "app.unpaid_initial_derived_digest(text,text)",
        "app.unpaid_initial_termination_source(uuid,uuid)",
        never,
        moved,
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {never},{moved} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Unpaid Initial termination migration is forward-only")
