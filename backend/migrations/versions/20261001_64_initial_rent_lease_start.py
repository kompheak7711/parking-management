# ruff: noqa: E501
"""Bill Initial Rent from the signed Lease Start Date with a proposed or authorized Due Date."""

from alembic import op
from sqlalchemy import text

revision = "20261001_64"
down_revision = "20260917_63"
branch_labels = None
depends_on = None

GENERATOR = (
    "app.generate_rent_service_invoice(uuid,uuid,text,uuid,text,uuid,uuid,text,date,"
    "timestamp with time zone,uuid,uuid)"
)
VALIDATOR = "app.validate_invoice_record()"
ELIGIBILITY = "app.lease_is_billable_for_recurring_period(uuid,date,date,timestamp with time zone)"

INITIAL_PERIOD_END = """(
                            date_trunc('month',v_move_in)::date
                            + CASE WHEN extract(day FROM v_move_in)<=20
                                THEN interval '1 month - 1 day' ELSE interval '2 months - 1 day' END
                        )::date"""

GENERATOR_REPLACEMENTS = (
    (
        "            v_service_lock_id uuid;\n",
        "            v_service_lock_id uuid;\n"
        "            v_override_reason text; v_override_by uuid; v_override_at timestamptz;\n",
    ),
    (
        "                OR (p_billing_kind='INITIAL' AND p_source_occupancy_id IS NULL)\n",
        "                OR (p_billing_kind='INITIAL' AND p_source_occupancy_id IS NOT NULL)\n",
    ),
    (
        """                SELECT occupancy.move_in_date,occupancy.created_at,occupancy.updated_at
                INTO v_occupancy_date,v_occupancy_created_at,v_occupancy_updated_at
                FROM app.occupancies AS occupancy
                WHERE occupancy.id=p_source_occupancy_id
                  AND occupancy.lease_id=p_lease_id
                  AND occupancy.customer_id=v_customer_id;
                IF NOT FOUND OR v_occupancy_date<>p_period_start
                    OR v_invoice_date<>v_occupancy_date
                THEN RAISE EXCEPTION 'Initial Rent billing source is invalid'
                    USING ERRCODE='22023'; END IF;
""",
        """                -- BR-RENT-005/009: coverage starts at the signed Lease Start Date and
                -- does not depend on a recorded Occupancy or the actual move-in.
                v_occupancy_date:=v_lease.start_date;
                IF v_occupancy_date IS NULL OR v_occupancy_date<>p_period_start
                THEN RAISE EXCEPTION 'Initial Rent billing source is invalid'
                    USING ERRCODE='22023'; END IF;
""",
    ),
    (
        "                v_due_date:=v_occupancy_date+7;\n",
        """                SELECT override.due_date,override.reason,override.actor_id,override.occurred_at
                INTO v_due_date,v_override_reason,v_override_by,v_override_at
                FROM app.initial_rent_due_date_overrides AS override
                WHERE override.lease_id=p_lease_id
                ORDER BY override.occurred_at DESC,override.id DESC LIMIT 1;
                IF v_override_at IS NULL THEN
                    v_due_date:=v_occupancy_date+5;
                END IF;
                IF v_due_date<v_invoice_date THEN
                    RAISE EXCEPTION 'Initial Rent Due Date precedes the issue date; record an authorized Due Date'
                        USING ERRCODE='22023';
                END IF;
""",
    ),
    (
        "                due_date_rule,due_date_source,created_at,created_by,updated_at,updated_by,\n"
        "                originating_billing_run_attempt_id\n"
        "            ) VALUES (\n"
        "                p_invoice_id,p_invoice_number,v_customer_id,p_lease_id,p_source_occupancy_id,\n",
        "                due_date_rule,due_date_source,created_at,created_by,updated_at,updated_by,\n"
        "                originating_billing_run_attempt_id,\n"
        "                due_date_override_reason,due_date_set_by,due_date_set_at\n"
        "            ) VALUES (\n"
        "                p_invoice_id,p_invoice_number,v_customer_id,p_lease_id,p_source_occupancy_id,\n",
    ),
    (
        "                CASE p_billing_kind WHEN 'INITIAL' THEN 'INITIAL_RENT_SEVEN_DAYS'\n",
        "                CASE p_billing_kind WHEN 'INITIAL' THEN 'INITIAL_RENT_LEASE_START_PLUS_FIVE'\n",
    ),
    (
        "                v_source_selection_cutoff,p_actor_id,\n"
        "                v_source_selection_cutoff,p_actor_id,\n"
        "                p_originating_billing_run_attempt_id\n"
        "            );\n",
        "                v_source_selection_cutoff,p_actor_id,\n"
        "                v_source_selection_cutoff,p_actor_id,\n"
        "                p_originating_billing_run_attempt_id,\n"
        "                v_override_reason,v_override_by,v_override_at\n"
        "            );\n",
    ),
)

VALIDATOR_REPLACEMENTS = (
    (
        "                IF v_invoice.rent_billing_kind='INITIAL' THEN\n"
        "                    SELECT occupancy.move_in_date INTO v_move_in\n",
        """                IF v_invoice.rent_billing_kind='INITIAL'
                    AND v_invoice.due_date_rule='INITIAL_RENT_LEASE_START_PLUS_FIVE' THEN
                    SELECT lease.start_date INTO v_move_in
                    FROM app.leases AS lease WHERE lease.id=v_invoice.lease_id;
                    IF v_move_in IS NULL OR v_invoice.billing_period_start<>v_move_in
                        OR v_invoice.billing_period_end<>"""
        + INITIAL_PERIOD_END
        + """
                        OR (v_invoice.due_date_override_reason IS NULL
                            AND v_invoice.due_date IS DISTINCT FROM v_move_in+5)
                        OR (v_invoice.due_date_override_reason IS NOT NULL AND NOT EXISTS (
                            SELECT 1 FROM app.initial_rent_due_date_overrides AS override
                            WHERE override.lease_id=v_invoice.lease_id
                              AND override.due_date=v_invoice.due_date
                              AND override.reason=v_invoice.due_date_override_reason
                              AND override.actor_id=v_invoice.due_date_set_by
                              AND override.occurred_at=v_invoice.due_date_set_at
                        ))
                    THEN RAISE EXCEPTION 'Initial Rent period or Due Date is invalid'
                        USING ERRCODE='23514'; END IF;
                END IF;
                IF v_invoice.rent_billing_kind='INITIAL'
                    AND v_invoice.due_date_rule='INITIAL_RENT_SEVEN_DAYS' THEN
                    SELECT occupancy.move_in_date INTO v_move_in
""",
    ),
)

ELIGIBILITY_REPLACEMENTS = (
    (
        """                JOIN LATERAL (
                    SELECT min(occupancy.move_in_date) AS first_move_in
                    FROM app.occupancies AS occupancy
                    WHERE occupancy.lease_id=lease.id
                      AND occupancy.created_at<=p_as_of
                ) AS move_in ON move_in.first_move_in IS NOT NULL
""",
        """                JOIN LATERAL (
                    -- A historical seven-day Initial Rent Invoice keeps its move-in coverage;
                    -- otherwise Initial coverage follows the Lease Start Date (BR-RENT-005).
                    SELECT CASE WHEN EXISTS (
                        SELECT 1 FROM app.invoices AS legacy
                        WHERE legacy.lease_id=lease.id AND legacy.rent_billing_kind='INITIAL'
                          AND legacy.due_date_rule='INITIAL_RENT_SEVEN_DAYS'
                          AND legacy.status<>'VOID'
                    ) THEN (
                        SELECT min(occupancy.move_in_date)
                        FROM app.occupancies AS occupancy
                        WHERE occupancy.lease_id=lease.id
                          AND occupancy.created_at<=p_as_of
                    ) ELSE lease.start_date END AS first_move_in
                ) AS move_in ON move_in.first_move_in IS NOT NULL
""",
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
            raise RuntimeError(f"Initial Rent source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    rule_check = (
        op.get_bind()
        .execute(
            text(
                "SELECT conname FROM pg_catalog.pg_constraint "
                "WHERE conrelid='app.invoices'::regclass AND contype='c' "
                "AND conname<>'invoices_rent_shape' "
                "AND pg_catalog.pg_get_constraintdef(oid) LIKE '%due_date_rule%INITIAL_RENT_SEVEN_DAYS%'"
            )
        )
        .scalars()
        .all()
    )
    if len(rule_check) != 1:
        raise RuntimeError("Invoice Due Date rule constraint is not unique")
    op.execute(f"""
        ALTER TABLE app.invoices ALTER COLUMN due_date DROP NOT NULL;
        ALTER TABLE app.invoices
            ADD COLUMN due_date_override_reason text,
            ADD COLUMN due_date_set_by uuid REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            ADD COLUMN due_date_set_at timestamptz;
        ALTER TABLE app.invoices ADD CONSTRAINT invoices_due_date_issued
            CHECK (status='DRAFT' OR due_date IS NOT NULL);
        ALTER TABLE app.invoices ADD CONSTRAINT invoices_due_date_override_shape CHECK (
            (due_date_override_reason IS NULL AND due_date_set_by IS NULL AND due_date_set_at IS NULL)
            OR (due_date_override_reason IS NOT NULL AND due_date_set_by IS NOT NULL
                AND due_date_set_at IS NOT NULL AND isfinite(due_date_set_at)
                AND due_date_override_reason=btrim(due_date_override_reason)
                AND length(due_date_override_reason) BETWEEN 1 AND 500)
        );
        ALTER TABLE app.invoices DROP CONSTRAINT {rule_check[0]};
        ALTER TABLE app.invoices ADD CONSTRAINT {rule_check[0]} CHECK (due_date_rule IN (
            'INITIAL_RENT_SEVEN_DAYS','INITIAL_RENT_LEASE_START_PLUS_FIVE','RECURRING_RENT_FIFTH',
            'ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS','GOVERNING_SOURCE'
        ));
        ALTER TABLE app.invoices DROP CONSTRAINT invoices_rent_shape;
        ALTER TABLE app.invoices ADD CONSTRAINT invoices_rent_shape CHECK (
            (primary_category='RENT' AND lease_id IS NOT NULL
                AND billing_period_start IS NOT NULL AND rent_billing_kind IS NOT NULL
                AND ((rent_billing_kind='INITIAL' AND source_occupancy_id IS NOT NULL
                        AND due_date_rule='INITIAL_RENT_SEVEN_DAYS')
                    OR (rent_billing_kind='INITIAL' AND source_occupancy_id IS NULL
                        AND due_date_rule='INITIAL_RENT_LEASE_START_PLUS_FIVE')
                    OR (rent_billing_kind='RECURRING' AND source_occupancy_id IS NULL
                        AND due_date_rule='RECURRING_RENT_FIFTH')))
            OR (primary_category<>'RENT' AND rent_billing_kind IS NULL
                AND source_occupancy_id IS NULL
                AND due_date_rule IN ('GOVERNING_SOURCE','ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS'))
        );

        CREATE FUNCTION app.protect_invoice_due_date_override()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF OLD.status<>'DRAFT' AND (
                NEW.due_date IS DISTINCT FROM OLD.due_date
                OR NEW.due_date_override_reason IS DISTINCT FROM OLD.due_date_override_reason
                OR NEW.due_date_set_by IS DISTINCT FROM OLD.due_date_set_by
                OR NEW.due_date_set_at IS DISTINCT FROM OLD.due_date_set_at
            ) THEN RAISE EXCEPTION 'An issued Invoice Due Date is fixed' USING ERRCODE='55000'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER invoices_due_date_fixed_after_issue BEFORE UPDATE ON app.invoices
            FOR EACH ROW EXECUTE FUNCTION app.protect_invoice_due_date_override();

        CREATE TABLE app.initial_rent_due_date_overrides (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            due_date date NOT NULL CHECK(isfinite(due_date)),
            reason text NOT NULL CHECK(reason=btrim(reason) AND length(reason) BETWEEN 1 AND 500),
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            audit_event_id uuid NOT NULL UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT,
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at))
        );
        CREATE INDEX initial_rent_due_date_overrides_lease_idx
            ON app.initial_rent_due_date_overrides(lease_id,occurred_at,id);
        CREATE TRIGGER initial_rent_due_date_overrides_reject_mutation BEFORE UPDATE OR DELETE
            ON app.initial_rent_due_date_overrides FOR EACH ROW
            EXECUTE FUNCTION app.reject_lease_append_only_mutation();
        CREATE TRIGGER initial_rent_due_date_overrides_reject_truncate BEFORE TRUNCATE
            ON app.initial_rent_due_date_overrides FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_lease_storage_truncate();

        CREATE FUNCTION app.initial_rent_due_date_override_snapshot(p_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
            SELECT jsonb_build_object('override_id',o.id,'property_id',o.property_id,
                'lease_id',o.lease_id,'due_date',o.due_date,'proposed_due_date',l.start_date+5,
                'reason',o.reason,'actor_id',o.actor_id,'occurred_at',o.occurred_at)
            FROM app.initial_rent_due_date_overrides o JOIN app.leases l ON l.id=o.lease_id
            WHERE o.id=p_id
        $$;

        CREATE FUNCTION app.set_initial_rent_due_date(p_property uuid,p_lease uuid,p_actor uuid,
            p_id uuid,p_due_date date,p_reason text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_lease app.leases%ROWTYPE; v_existing app.initial_rent_due_date_overrides%ROWTYPE;
            v_now timestamptz; v_audit uuid; v_timezone text;
        BEGIN
            IF p_property IS NULL OR p_lease IS NULL OR p_actor IS NULL OR p_id IS NULL
                OR p_id='00000000-0000-0000-0000-000000000000'
                OR p_due_date IS NULL OR NOT isfinite(p_due_date)
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Initial Rent Due Date override is invalid' USING ERRCODE='22023'; END IF;
            PERFORM app.assert_active_financial_actor(p_actor,p_property);
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('invoice-lease:' || p_lease::text,0));
            SELECT * INTO v_existing FROM app.initial_rent_due_date_overrides WHERE id=p_id;
            IF FOUND THEN
                IF v_existing.lease_id IS DISTINCT FROM p_lease
                    OR v_existing.property_id IS DISTINCT FROM p_property
                    OR v_existing.actor_id IS DISTINCT FROM p_actor
                    OR v_existing.due_date IS DISTINCT FROM p_due_date
                    OR v_existing.reason IS DISTINCT FROM p_reason
                THEN RAISE EXCEPTION 'Initial Rent Due Date override identity was reused'
                    USING ERRCODE='23505'; END IF;
                RETURN app.initial_rent_due_date_override_snapshot(p_id);
            END IF;
            SELECT lease.* INTO v_lease FROM app.leases AS lease
            JOIN app.units AS unit ON unit.id=lease.unit_id
            WHERE lease.id=p_lease AND unit.property_id=p_property FOR SHARE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found in Property scope'
                USING ERRCODE='P0002'; END IF;
            IF v_lease.status<>'SIGNED' THEN
                RAISE EXCEPTION 'Initial Rent Due Date requires a signed Lease' USING ERRCODE='55000';
            END IF;
            IF EXISTS (SELECT 1 FROM app.invoices WHERE lease_id=p_lease
                AND rent_billing_kind='INITIAL' AND status<>'VOID')
            THEN RAISE EXCEPTION 'The Initial Rent Invoice is already issued' USING ERRCODE='55000'; END IF;
            v_now:=clock_timestamp();
            SELECT timezone_name INTO v_timezone FROM app.properties WHERE id=p_property;
            v_audit:=gen_random_uuid();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
                source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
            VALUES(v_audit,v_now,timezone(v_timezone,v_now)::date,p_actor,'invoice.initial_rent_due_date.set',
                'initial_rent_due_date_override',p_id,p_reason,'billing.generate',p_property,
                jsonb_build_object('proposed_due_date',v_lease.start_date+5),
                jsonb_build_object('due_date',p_due_date,'reason',p_reason),
                p_id,'API','SUCCEEDED',jsonb_build_object('capability','billing.generate','lease_id',p_lease),
                v_lease.primary_tenant_id,p_lease,v_lease.unit_id);
            INSERT INTO app.initial_rent_due_date_overrides(id,property_id,lease_id,due_date,reason,
                actor_id,audit_event_id,occurred_at)
            VALUES(p_id,p_property,p_lease,p_due_date,p_reason,p_actor,v_audit,v_now);
            RETURN app.initial_rent_due_date_override_snapshot(p_id);
        END $$;
    """)
    _patch(GENERATOR, GENERATOR_REPLACEMENTS)
    _patch(VALIDATOR, VALIDATOR_REPLACEMENTS)
    _patch(ELIGIBILITY, ELIGIBILITY_REPLACEMENTS)
    op.execute(
        "REVOKE ALL ON TABLE app.initial_rent_due_date_overrides FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
    )
    for function in (
        "app.protect_invoice_due_date_override()",
        "app.initial_rent_due_date_override_snapshot(uuid)",
        "app.set_initial_rent_due_date(uuid,uuid,uuid,uuid,date,text)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.set_initial_rent_due_date(uuid,uuid,uuid,uuid,date,text) TO prm_financial"
    )


def downgrade() -> None:
    raise RuntimeError("Initial Rent Lease Start billing is forward-only")
