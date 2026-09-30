# ruff: noqa: E501
"""Record manual one-time Damage and Miscellaneous charges with an issue-time Due Date."""

from alembic import op
from sqlalchemy import text

revision = "20261002_65"
down_revision = "20261001_64"
branch_labels = None
depends_on = None

ONE_TIME_RULE = "ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS"

CREATE_DRAFT = "app.create_invoice_draft(uuid,uuid,uuid,uuid,text,uuid,uuid,uuid,uuid)"
CORRECT_DRAFT = "app.correct_invoice_draft(uuid,uuid,uuid,uuid,uuid,text,integer,text,uuid)"
LINE_VALIDATOR = "app.validate_invoice_line()"
ISSUANCE_VALIDATOR = "app.validate_invoice_issuance_lines()"
ISSUE_WITH_DUE_DATE = "app.issue_invoice(uuid,uuid,uuid,uuid,text,integer,uuid,uuid,date,text)"
RECORD = "app.record_one_time_charge(uuid,uuid,uuid,text,uuid,uuid,uuid,text,bigint,text,text)"
SET_DUE_DAYS = "app.set_one_time_charge_due_days(uuid,uuid,integer,integer,text,uuid)"

OBLIGATION_DUE_MATCH = (
    (
        "OR v_obligation.governing_due_date<>v_invoice.due_date",
        "OR v_obligation.due_date_rule<>v_invoice.due_date_rule\n"
        "                    OR (v_obligation.due_date_rule='GOVERNING_SOURCE'\n"
        "                        AND v_obligation.governing_due_date<>v_invoice.due_date)",
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
            raise RuntimeError(f"One-time charge source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(f"""
        ALTER TABLE app.properties ADD COLUMN one_time_charge_due_days smallint NOT NULL DEFAULT 7
            CONSTRAINT properties_one_time_charge_due_days_range
            CHECK (one_time_charge_due_days BETWEEN 1 AND 90);

        ALTER TABLE app.authorized_nonrecurring_obligations
            ALTER COLUMN governing_due_date DROP NOT NULL,
            ADD COLUMN due_date_rule text NOT NULL DEFAULT 'GOVERNING_SOURCE'
                CONSTRAINT authorized_nonrecurring_due_date_rule_allowed
                CHECK (due_date_rule IN ('GOVERNING_SOURCE','{ONE_TIME_RULE}')),
            ADD COLUMN reason text CONSTRAINT authorized_nonrecurring_reason_text
                CHECK (reason IS NULL OR (reason=btrim(reason) AND length(reason) BETWEEN 1 AND 500)),
            ADD COLUMN evidence_reference text CONSTRAINT authorized_nonrecurring_evidence_text
                CHECK (evidence_reference IS NULL OR (evidence_reference=btrim(evidence_reference)
                    AND length(evidence_reference) BETWEEN 1 AND 500)),
            ADD COLUMN audit_event_id uuid UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT;
        ALTER TABLE app.authorized_nonrecurring_obligations
            ADD CONSTRAINT authorized_nonrecurring_due_date_rule_shape CHECK (
                (due_date_rule='GOVERNING_SOURCE' AND governing_due_date IS NOT NULL)
                OR (due_date_rule='{ONE_TIME_RULE}' AND governing_due_date IS NULL
                    AND due_date_source='BR-INV-018' AND reason IS NOT NULL
                    AND evidence_reference IS NOT NULL AND audit_event_id IS NOT NULL)
            ),
            ADD CONSTRAINT authorized_nonrecurring_damage_one_time CHECK (
                category<>'DAMAGE_CHARGES' OR (due_date_rule='{ONE_TIME_RULE}' AND lease_id IS NOT NULL)
            ),
            ADD CONSTRAINT authorized_nonrecurring_damage_finding_fk
                FOREIGN KEY (inspection_damage_finding_id)
                REFERENCES app.inspection_damage_findings(id) ON DELETE RESTRICT,
            ADD CONSTRAINT authorized_nonrecurring_damage_finding_once
                UNIQUE (inspection_damage_finding_id);
        ALTER TABLE app.authorized_nonrecurring_obligations
            DROP CONSTRAINT authorized_nonrecurring_damage_source_deferred;
        COMMENT ON COLUMN app.authorized_nonrecurring_obligations.inspection_damage_finding_id IS
            'Recorded inspection damage finding billed at most once by a Damage charge';

        CREATE FUNCTION app.validate_damage_obligation_source()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF NEW.category='DAMAGE_CHARGES' AND NOT EXISTS (
                SELECT 1 FROM app.inspection_damage_findings AS finding
                JOIN app.move_out_inspections AS inspection ON inspection.id=finding.inspection_id
                JOIN app.leases AS lease ON lease.id=inspection.lease_id
                WHERE finding.id=NEW.inspection_damage_finding_id
                  AND inspection.lease_id=NEW.lease_id
                  AND lease.primary_tenant_id=NEW.customer_id
                  AND NOT EXISTS (SELECT 1 FROM app.move_out_inspections AS later
                      WHERE later.supersedes_inspection_id=inspection.id)
            ) THEN RAISE EXCEPTION 'Damage charge must match a current inspection finding'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER authorized_nonrecurring_obligations_10_damage_source
            BEFORE INSERT ON app.authorized_nonrecurring_obligations
            FOR EACH ROW EXECUTE FUNCTION app.validate_damage_obligation_source();

        CREATE FUNCTION app.one_time_charge_snapshot(p_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
            SELECT jsonb_build_object('obligation_id',o.id,'category',o.category,
                'customer_id',o.customer_id,'lease_id',o.lease_id,
                'inspection_damage_finding_id',o.inspection_damage_finding_id,
                'description',o.description,'amount_usd_cents',o.authorized_amount_usd_cents,
                'reason',o.reason,'evidence_reference',o.evidence_reference,
                'due_date_rule',o.due_date_rule,'authorized_by',o.authorized_by,
                'authorized_at',o.authorized_at,'authorization_reference',o.authorization_reference)
            FROM app.authorized_nonrecurring_obligations o WHERE o.id=p_id
        $$;

        CREATE FUNCTION app.record_one_time_charge(p_property uuid,p_actor uuid,p_id uuid,
            p_category text,p_customer uuid,p_lease uuid,p_finding uuid,p_description text,
            p_amount_usd_cents bigint,p_reason text,p_evidence_reference text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_existing app.authorized_nonrecurring_obligations%ROWTYPE; v_lease app.leases%ROWTYPE;
            v_timezone text; v_now timestamptz; v_audit uuid; v_capability text;
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_id IS NULL
                OR p_id='00000000-0000-0000-0000-000000000000' OR p_customer IS NULL
                OR p_category IS NULL OR p_category NOT IN ('DAMAGE_CHARGES','MISCELLANEOUS_CHARGES')
                OR (p_category='DAMAGE_CHARGES' AND (p_finding IS NULL OR p_lease IS NULL))
                OR (p_category='MISCELLANEOUS_CHARGES' AND p_finding IS NOT NULL)
                OR p_amount_usd_cents IS NULL OR p_amount_usd_cents<=0
                OR p_description IS NULL OR p_description<>btrim(p_description)
                OR length(p_description) NOT BETWEEN 1 AND 1000
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 500
                OR p_evidence_reference IS NULL OR p_evidence_reference<>btrim(p_evidence_reference)
                OR length(p_evidence_reference) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'One-time charge is invalid' USING ERRCODE='22023'; END IF;
            v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
            IF p_lease IS NOT NULL THEN
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended('invoice-lease:' || p_lease::text,0));
            END IF;
            SELECT * INTO v_existing FROM app.authorized_nonrecurring_obligations WHERE id=p_id;
            IF FOUND THEN
                IF v_existing.category IS DISTINCT FROM p_category
                    OR v_existing.customer_id IS DISTINCT FROM p_customer
                    OR v_existing.lease_id IS DISTINCT FROM p_lease
                    OR v_existing.inspection_damage_finding_id IS DISTINCT FROM p_finding
                    OR v_existing.description IS DISTINCT FROM p_description
                    OR v_existing.authorized_amount_usd_cents IS DISTINCT FROM p_amount_usd_cents
                    OR v_existing.reason IS DISTINCT FROM p_reason
                    OR v_existing.evidence_reference IS DISTINCT FROM p_evidence_reference
                    OR v_existing.authorized_by IS DISTINCT FROM p_actor
                THEN RAISE EXCEPTION 'One-time charge identity was reused' USING ERRCODE='23505'; END IF;
                RETURN app.one_time_charge_snapshot(p_id);
            END IF;
            IF p_lease IS NOT NULL THEN
                SELECT lease.* INTO v_lease FROM app.leases AS lease
                JOIN app.units AS unit ON unit.id=lease.unit_id
                WHERE lease.id=p_lease AND unit.property_id=p_property;
                IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found in Property scope'
                    USING ERRCODE='P0002'; END IF;
                IF v_lease.primary_tenant_id<>p_customer THEN
                    RAISE EXCEPTION 'One-time charge Customer does not match the Lease'
                        USING ERRCODE='22023'; END IF;
            ELSIF NOT EXISTS (SELECT 1 FROM app.customers WHERE id=p_customer) THEN
                RAISE EXCEPTION 'Customer was not found' USING ERRCODE='P0002';
            END IF;
            IF p_finding IS NOT NULL AND EXISTS (SELECT 1 FROM app.authorized_nonrecurring_obligations
                WHERE inspection_damage_finding_id=p_finding)
            THEN RAISE EXCEPTION 'The damage finding is already billed' USING ERRCODE='P4503'; END IF;
            v_capability:=CASE p_category WHEN 'DAMAGE_CHARGES' THEN 'damage_charges.bill'
                ELSE 'invoices.create' END;
            v_now:=clock_timestamp();
            v_audit:=gen_random_uuid();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
                source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
            VALUES(v_audit,v_now,timezone(v_timezone,v_now)::date,p_actor,'invoice.one_time_charge.recorded',
                'authorized_nonrecurring_obligation',p_id,p_reason,v_capability,p_property,'{{}}'::jsonb,
                jsonb_build_object('category',p_category,'amount_usd_cents',p_amount_usd_cents,
                    'description',p_description,'evidence_reference',p_evidence_reference,
                    'inspection_damage_finding_id',p_finding),
                p_id,'API','SUCCEEDED',jsonb_build_object('capability',v_capability),
                p_customer,p_lease,v_lease.unit_id);
            INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,lease_id,category,
                inspection_damage_finding_id,description,authorized_amount_usd_cents,governing_due_date,
                due_date_source,source_reference,authorized_at,authorized_by,authorization_reference,
                due_date_rule,reason,evidence_reference,audit_event_id)
            VALUES(p_id,p_customer,p_lease,p_category,p_finding,p_description,p_amount_usd_cents,NULL,
                'BR-INV-018','one-time-charge:' || p_id::text,v_now,p_actor,v_capability,
                '{ONE_TIME_RULE}',p_reason,p_evidence_reference,v_audit);
            RETURN app.one_time_charge_snapshot(p_id);
        END $$;

        CREATE FUNCTION app.set_one_time_charge_due_days(p_property uuid,p_actor uuid,
            p_expected_version integer,p_days integer,p_reason text,p_audit_id uuid)
        RETURNS TABLE(property_id uuid,one_time_charge_due_days smallint,version integer)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_property app.properties%ROWTYPE; v_timezone text; v_now timestamptz;
        BEGIN
            IF p_days IS NULL OR p_days NOT BETWEEN 1 AND 90 OR p_expected_version IS NULL
                OR p_audit_id IS NULL OR p_reason IS NULL OR p_reason<>btrim(p_reason)
                OR length(p_reason) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'One-time charge Due Date days are invalid' USING ERRCODE='22023'; END IF;
            v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
            SELECT * INTO v_property FROM app.properties AS configuration
            WHERE configuration.id=p_property FOR UPDATE;
            IF v_property.version<>p_expected_version THEN RETURN; END IF;
            v_now:=clock_timestamp();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
                source,outcome,authorization_evidence)
            VALUES(p_audit_id,v_now,timezone(v_timezone,v_now)::date,p_actor,
                'property.one_time_charge_due_days.set','property',p_property,p_reason,'property.manage',
                p_property,jsonb_build_object('one_time_charge_due_days',v_property.one_time_charge_due_days,
                    'version',v_property.version),
                jsonb_build_object('one_time_charge_due_days',p_days,'version',v_property.version+1),
                p_audit_id,'API','SUCCEEDED',jsonb_build_object('capability','property.manage'));
            RETURN QUERY
            UPDATE app.properties AS configuration
            SET one_time_charge_due_days=p_days, updated_at=v_now, updated_by=p_actor,
                version=configuration.version+1
            WHERE configuration.id=p_property
            RETURNING configuration.id,configuration.one_time_charge_due_days,configuration.version;
        END $$;

        CREATE FUNCTION app.issue_invoice(
            p_property_id uuid,p_invoice_id uuid,p_actor_id uuid,p_idempotency_key uuid,
            p_request_digest text,p_expected_version integer,p_audit_id uuid,p_correlation_id uuid,
            p_due_date date,p_due_date_reason text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_replay jsonb; v_before jsonb; v_result jsonb; v_invoice app.invoices%ROWTYPE;
        DECLARE v_timezone text; v_now timestamptz; v_business_date date; v_due date;
        BEGIN
            v_replay:=app.invoice_command_replay(p_property_id,p_actor_id,'issue',
                p_idempotency_key,p_request_digest);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            v_timezone:=app.require_invoice_command_actor(p_property_id,p_actor_id);
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice_id FOR UPDATE;
            IF NOT FOUND OR app.invoice_property_id(p_invoice_id) IS DISTINCT FROM p_property_id
            THEN RAISE EXCEPTION 'Invoice was not found' USING ERRCODE='P4501'; END IF;
            IF p_expected_version IS NULL OR v_invoice.version<>p_expected_version THEN
                RAISE EXCEPTION 'Invoice version:%',v_invoice.version USING ERRCODE='P4504'; END IF;
            IF v_invoice.version=2147483647 THEN
                RAISE EXCEPTION 'Invoice version cannot advance' USING ERRCODE='P4507'; END IF;
            IF v_invoice.status<>'DRAFT' THEN RAISE EXCEPTION 'Only a DRAFT Invoice may be issued'
                USING ERRCODE='P4502'; END IF;
            IF (p_due_date IS NULL)<>(p_due_date_reason IS NULL)
                OR (p_due_date IS NOT NULL AND (NOT isfinite(p_due_date)
                    OR v_invoice.due_date_rule<>'{ONE_TIME_RULE}'
                    OR p_due_date_reason<>btrim(p_due_date_reason)
                    OR length(p_due_date_reason) NOT BETWEEN 1 AND 500))
            THEN RAISE EXCEPTION 'Invoice Due Date override is invalid' USING ERRCODE='P4502'; END IF;
            v_before:=app.invoice_resource_snapshot(p_invoice_id);
            v_now:=clock_timestamp(); v_business_date:=timezone(v_timezone,v_now)::date;
            v_due:=v_invoice.due_date;
            IF v_invoice.due_date_rule='{ONE_TIME_RULE}' THEN
                SELECT COALESCE(p_due_date,v_business_date+property.one_time_charge_due_days)
                INTO v_due FROM app.properties AS property WHERE property.id=p_property_id;
                IF v_due<v_business_date THEN
                    RAISE EXCEPTION 'Invoice Due Date precedes the issue date' USING ERRCODE='P4502';
                END IF;
            END IF;
            UPDATE app.invoices SET status='UNPAID',issued_at=v_now,issued_by=p_actor_id,
                due_date=v_due,due_date_override_reason=COALESCE(p_due_date_reason,due_date_override_reason),
                due_date_set_by=CASE WHEN p_due_date IS NULL THEN due_date_set_by ELSE p_actor_id END,
                due_date_set_at=CASE WHEN p_due_date IS NULL THEN due_date_set_at ELSE v_now END,
                version=version+1,updated_at=v_now,updated_by=p_actor_id WHERE id=p_invoice_id;
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.invoice_resource_snapshot(p_invoice_id);
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
                entity_id,reason,authorization_reference,property_id,previous_state,
                resulting_state,correlation_id,source,outcome,authorization_evidence,
                customer_id,lease_id)
            VALUES (p_audit_id,v_now,v_business_date,p_actor_id,'invoice.issued','invoice',
                p_invoice_id,COALESCE(p_due_date_reason,'Invoice issued'),'invoices.issue',p_property_id,
                v_before,v_result,p_correlation_id,'API','SUCCEEDED',
                jsonb_build_object('capability','invoices.issue','due_date',v_due,
                    'due_date_override',p_due_date IS NOT NULL),
                v_invoice.customer_id,v_invoice.lease_id);
            PERFORM app.record_invoice_command(p_property_id,p_actor_id,'issue',
                p_idempotency_key,p_request_digest,p_invoice_id,200::smallint,v_result,v_now);
            RETURN v_result;
        END $$;

        CREATE OR REPLACE FUNCTION app.issue_invoice(
            p_property_id uuid,p_invoice_id uuid,p_actor_id uuid,p_idempotency_key uuid,
            p_request_digest text,p_expected_version integer,p_audit_id uuid,p_correlation_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            RETURN app.issue_invoice(p_property_id,p_invoice_id,p_actor_id,p_idempotency_key,
                p_request_digest,p_expected_version,p_audit_id,p_correlation_id,NULL::date,NULL::text);
        END $$;
    """)
    _patch(
        CREATE_DRAFT,
        (
            (
                "v_source.authorized_amount_usd_cents,'GOVERNING_SOURCE',v_source.due_date_source,",
                "v_source.authorized_amount_usd_cents,v_source.due_date_rule,v_source.due_date_source,",
            ),
        ),
    )
    _patch(
        CORRECT_DRAFT,
        (
            (
                "due_date_rule='GOVERNING_SOURCE',due_date_source=v_source.due_date_source,",
                "due_date_rule=v_source.due_date_rule,due_date_source=v_source.due_date_source,",
            ),
        ),
    )
    _patch(LINE_VALIDATOR, OBLIGATION_DUE_MATCH)
    _patch(ISSUANCE_VALIDATOR, OBLIGATION_DUE_MATCH)
    for function in (
        "app.validate_damage_obligation_source()",
        "app.one_time_charge_snapshot(uuid)",
        RECORD,
        SET_DUE_DAYS,
        ISSUE_WITH_DUE_DATE,
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD},{ISSUE_WITH_DUE_DATE} TO prm_financial")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SET_DUE_DAYS} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("One-time charge migration is forward-only")
