# ruff: noqa: E501
"""Unit cleaning rate history and the move-out Unit cleaning charge (BR-UNIT-014, BR-MOVEOUT-013).

The rate is an append-only chain per Unit, set under property.manage. The cleaning charge is
an explicit staff command under invoices.create (owner answer to plan Q13): it records a
Miscellaneous one-time charge source from the Unit's current rate through the existing
app.record_one_time_charge, so the Invoice DRAFT, issue, BR-INV-018 Due Date and credit
Adjustment paths stay the same. A link row identifies the charge, keeps the rate snapshot and
allows at most one cleaning charge per Lease. No charge when the Customer never moved in.
"""

from alembic import op

revision = "20261016_81"
down_revision = "20261015_80"
branch_labels = None
depends_on = None

SET_RATE = "app.set_unit_cleaning_rate(uuid,uuid,uuid,uuid,uuid,bigint,text)"
READ_RATE = "app.unit_cleaning_rate_current(uuid,uuid,uuid)"
RECORD_CHARGE = "app.record_unit_cleaning_charge(uuid,uuid,uuid,uuid,uuid)"
INTERNAL = (
    "app.unit_cleaning_rate_snapshot(uuid)",
    "app.unit_cleaning_charge_snapshot(uuid)",
    "app.validate_unit_cleaning_rate()",
    "app.validate_unit_cleaning_charge()",
    "app.reject_unit_cleaning_history_change()",
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.unit_cleaning_rates (
            id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            rate_usd_cents bigint NOT NULL
                CHECK (rate_usd_cents BETWEEN 0 AND 9000000000000000),
            supersedes_rate_id uuid UNIQUE REFERENCES app.unit_cleaning_rates(id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK (reason=btrim(reason) AND length(reason) BETWEEN 1 AND 500),
            recorded_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL CHECK (isfinite(recorded_at)),
            audit_event_id uuid NOT NULL UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT,
            CHECK (supersedes_rate_id IS NULL OR supersedes_rate_id<>id)
        );
        CREATE UNIQUE INDEX unit_cleaning_rates_one_first_rate
            ON app.unit_cleaning_rates(unit_id) WHERE supersedes_rate_id IS NULL;
        COMMENT ON TABLE app.unit_cleaning_rates IS
            'Append-only Unit cleaning rate chain (BR-UNIT-014); the current rate has no successor';

        CREATE TABLE app.unit_cleaning_charges (
            obligation_id uuid PRIMARY KEY
                REFERENCES app.authorized_nonrecurring_obligations(id) ON DELETE RESTRICT,
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL UNIQUE REFERENCES app.leases(id) ON DELETE RESTRICT,
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            cleaning_rate_id uuid NOT NULL REFERENCES app.unit_cleaning_rates(id) ON DELETE RESTRICT,
            rate_usd_cents bigint NOT NULL CHECK (rate_usd_cents>0),
            physical_move_out_event_id uuid NOT NULL
                REFERENCES app.physical_move_out_events(id) ON DELETE RESTRICT,
            recorded_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL CHECK (isfinite(recorded_at))
        );
        COMMENT ON TABLE app.unit_cleaning_charges IS
            'Move-out Unit cleaning charge (BR-MOVEOUT-013): at most one per Lease, with the rate snapshot';

        CREATE FUNCTION app.reject_unit_cleaning_history_change()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Unit cleaning history is append-only' USING ERRCODE='55000';
        END $$;
        CREATE TRIGGER unit_cleaning_rates_immutable BEFORE UPDATE OR DELETE
            ON app.unit_cleaning_rates FOR EACH ROW
            EXECUTE FUNCTION app.reject_unit_cleaning_history_change();
        CREATE TRIGGER unit_cleaning_rates_no_truncate BEFORE TRUNCATE
            ON app.unit_cleaning_rates FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_unit_cleaning_history_change();
        CREATE TRIGGER unit_cleaning_charges_immutable BEFORE UPDATE OR DELETE
            ON app.unit_cleaning_charges FOR EACH ROW
            EXECUTE FUNCTION app.reject_unit_cleaning_history_change();
        CREATE TRIGGER unit_cleaning_charges_no_truncate BEFORE TRUNCATE
            ON app.unit_cleaning_charges FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_unit_cleaning_history_change();

        CREATE FUNCTION app.validate_unit_cleaning_rate()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM app.units WHERE id=NEW.unit_id AND property_id=NEW.property_id)
            THEN RAISE EXCEPTION 'Unit cleaning rate must match its Unit Property' USING ERRCODE='23514'; END IF;
            IF NEW.supersedes_rate_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM app.unit_cleaning_rates WHERE id=NEW.supersedes_rate_id AND unit_id=NEW.unit_id)
            THEN RAISE EXCEPTION 'Unit cleaning rate must supersede a rate of the same Unit'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER unit_cleaning_rates_10_source BEFORE INSERT ON app.unit_cleaning_rates
            FOR EACH ROW EXECUTE FUNCTION app.validate_unit_cleaning_rate();

        CREATE FUNCTION app.validate_unit_cleaning_charge()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM app.authorized_nonrecurring_obligations AS obligation
                JOIN app.leases AS lease ON lease.id=obligation.lease_id
                JOIN app.units AS unit ON unit.id=lease.unit_id
                JOIN app.unit_cleaning_rates AS rate ON rate.id=NEW.cleaning_rate_id
                JOIN app.physical_move_out_events AS move_out ON move_out.id=NEW.physical_move_out_event_id
                WHERE obligation.id=NEW.obligation_id
                  AND obligation.category='MISCELLANEOUS_CHARGES'
                  AND obligation.lease_id=NEW.lease_id
                  AND obligation.customer_id=lease.primary_tenant_id
                  AND obligation.authorized_amount_usd_cents=NEW.rate_usd_cents
                  AND unit.id=NEW.unit_id AND unit.property_id=NEW.property_id
                  AND rate.unit_id=NEW.unit_id AND rate.rate_usd_cents=NEW.rate_usd_cents
                  AND move_out.lease_id=NEW.lease_id
            ) THEN RAISE EXCEPTION 'Unit cleaning charge must match its source, Lease, Unit and rate'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER unit_cleaning_charges_10_source BEFORE INSERT ON app.unit_cleaning_charges
            FOR EACH ROW EXECUTE FUNCTION app.validate_unit_cleaning_charge();

        CREATE FUNCTION app.unit_cleaning_rate_snapshot(p_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
            SELECT jsonb_build_object('id',r.id,'property_id',r.property_id,'unit_id',r.unit_id,
                'rate_usd_cents',r.rate_usd_cents,'supersedes_rate_id',r.supersedes_rate_id,
                'reason',r.reason,'recorded_by',r.recorded_by,'recorded_at',r.recorded_at)
            FROM app.unit_cleaning_rates r WHERE r.id=p_id
        $$;

        CREATE FUNCTION app.unit_cleaning_charge_snapshot(p_obligation uuid)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
            SELECT app.one_time_charge_snapshot(c.obligation_id) || jsonb_build_object(
                'unit_id',c.unit_id,'cleaning_rate_id',c.cleaning_rate_id,
                'rate_usd_cents',c.rate_usd_cents,
                'physical_move_out_event_id',c.physical_move_out_event_id)
            FROM app.unit_cleaning_charges c WHERE c.obligation_id=p_obligation
        $$;

        CREATE FUNCTION app.set_unit_cleaning_rate(p_property uuid,p_actor uuid,p_unit uuid,p_id uuid,
            p_expected_current uuid,p_rate_usd_cents bigint,p_reason text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_existing app.unit_cleaning_rates%ROWTYPE; v_current app.unit_cleaning_rates%ROWTYPE;
            v_timezone text; v_now timestamptz; v_audit uuid;
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_unit IS NULL OR p_id IS NULL
                OR p_id='00000000-0000-0000-0000-000000000000'
                OR p_expected_current='00000000-0000-0000-0000-000000000000'
                OR p_rate_usd_cents IS NULL OR p_rate_usd_cents NOT BETWEEN 0 AND 9000000000000000
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Unit cleaning rate is invalid' USING ERRCODE='22023'; END IF;
            v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
            IF NOT EXISTS (SELECT 1 FROM app.units WHERE id=p_unit AND property_id=p_property)
            THEN RAISE EXCEPTION 'Unit was not found in Property scope' USING ERRCODE='P0002'; END IF;
            -- One rate change per Unit at a time; the Unit row itself is not locked.
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('unit-cleaning-rate:' || p_unit::text,0));
            SELECT * INTO v_existing FROM app.unit_cleaning_rates WHERE id=p_id;
            IF FOUND THEN
                IF v_existing.property_id IS DISTINCT FROM p_property
                    OR v_existing.unit_id IS DISTINCT FROM p_unit
                    OR v_existing.supersedes_rate_id IS DISTINCT FROM p_expected_current
                    OR v_existing.rate_usd_cents IS DISTINCT FROM p_rate_usd_cents
                    OR v_existing.reason IS DISTINCT FROM p_reason
                    OR v_existing.recorded_by IS DISTINCT FROM p_actor
                THEN RAISE EXCEPTION 'Unit cleaning rate identity was reused' USING ERRCODE='23505'; END IF;
                RETURN app.unit_cleaning_rate_snapshot(p_id);
            END IF;
            SELECT rate.* INTO v_current FROM app.unit_cleaning_rates AS rate
            WHERE rate.unit_id=p_unit AND NOT EXISTS (
                SELECT 1 FROM app.unit_cleaning_rates AS later WHERE later.supersedes_rate_id=rate.id);
            IF v_current.id IS DISTINCT FROM p_expected_current THEN
                RAISE EXCEPTION 'Unit cleaning rate changed' USING ERRCODE='P4503'; END IF;
            v_now:=clock_timestamp();
            v_audit:=gen_random_uuid();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
                source,outcome,authorization_evidence,unit_id)
            VALUES(v_audit,v_now,timezone(v_timezone,v_now)::date,p_actor,'unit.cleaning_rate.set',
                'unit_cleaning_rate',p_id,p_reason,'property.manage',p_property,
                COALESCE(app.unit_cleaning_rate_snapshot(v_current.id),'{}'::jsonb),
                jsonb_build_object('rate_usd_cents',p_rate_usd_cents,'supersedes_rate_id',p_expected_current),
                p_id,'API','SUCCEEDED',jsonb_build_object('capability','property.manage'),p_unit);
            INSERT INTO app.unit_cleaning_rates(id,property_id,unit_id,rate_usd_cents,supersedes_rate_id,
                reason,recorded_by,recorded_at,audit_event_id)
            VALUES(p_id,p_property,p_unit,p_rate_usd_cents,p_expected_current,p_reason,p_actor,v_now,v_audit);
            RETURN app.unit_cleaning_rate_snapshot(p_id);
        END $$;

        CREATE FUNCTION app.unit_cleaning_rate_current(p_property uuid,p_actor uuid,p_unit uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_id uuid;
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_unit IS NULL
            THEN RAISE EXCEPTION 'Unit cleaning rate read is invalid' USING ERRCODE='22023'; END IF;
            IF NOT EXISTS (SELECT 1 FROM app.user_accounts WHERE actor_id=p_actor AND lifecycle_state='active')
            THEN RAISE EXCEPTION 'Invoice command requires an active human actor' USING ERRCODE='P4506'; END IF;
            IF NOT EXISTS (SELECT 1 FROM app.units WHERE id=p_unit AND property_id=p_property)
            THEN RAISE EXCEPTION 'Unit was not found in Property scope' USING ERRCODE='P0002'; END IF;
            SELECT rate.id INTO v_id FROM app.unit_cleaning_rates AS rate
            WHERE rate.unit_id=p_unit AND NOT EXISTS (
                SELECT 1 FROM app.unit_cleaning_rates AS later WHERE later.supersedes_rate_id=rate.id);
            RETURN app.unit_cleaning_rate_snapshot(v_id);
        END $$;

        CREATE FUNCTION app.record_unit_cleaning_charge(p_property uuid,p_actor uuid,p_id uuid,
            p_lease uuid,p_expected_rate uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_existing app.unit_cleaning_charges%ROWTYPE; v_lease app.leases%ROWTYPE;
            v_rate app.unit_cleaning_rates%ROWTYPE; v_move_out uuid; v_now timestamptz;
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_lease IS NULL OR p_expected_rate IS NULL
                OR p_id IS NULL OR p_id='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Unit cleaning charge is invalid' USING ERRCODE='22023'; END IF;
            PERFORM app.require_invoice_command_actor(p_property,p_actor);
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('invoice-lease:' || p_lease::text,0));
            SELECT * INTO v_existing FROM app.unit_cleaning_charges WHERE obligation_id=p_id;
            IF FOUND THEN
                IF v_existing.property_id IS DISTINCT FROM p_property
                    OR v_existing.lease_id IS DISTINCT FROM p_lease
                    OR v_existing.cleaning_rate_id IS DISTINCT FROM p_expected_rate
                    OR v_existing.recorded_by IS DISTINCT FROM p_actor
                THEN RAISE EXCEPTION 'Unit cleaning charge identity was reused' USING ERRCODE='23505'; END IF;
                RETURN app.unit_cleaning_charge_snapshot(p_id);
            END IF;
            IF EXISTS (SELECT 1 FROM app.authorized_nonrecurring_obligations WHERE id=p_id)
            THEN RAISE EXCEPTION 'Unit cleaning charge identity was reused' USING ERRCODE='23505'; END IF;
            SELECT lease.* INTO v_lease FROM app.leases AS lease
            JOIN app.units AS unit ON unit.id=lease.unit_id
            WHERE lease.id=p_lease AND unit.property_id=p_property;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found in Property scope'
                USING ERRCODE='P0002'; END IF;
            IF NOT EXISTS (SELECT 1 FROM app.occupancies WHERE lease_id=p_lease) THEN
                RAISE EXCEPTION 'No Unit cleaning charge: the Customer never moved in'
                    USING ERRCODE='22023'; END IF;
            SELECT move_out.id INTO v_move_out FROM app.physical_move_out_events AS move_out
            WHERE move_out.lease_id=p_lease AND NOT EXISTS (
                SELECT 1 FROM app.physical_move_out_events AS later WHERE later.supersedes_event_id=move_out.id);
            IF v_move_out IS NULL THEN
                RAISE EXCEPTION 'Unit cleaning charge needs a recorded move-out' USING ERRCODE='22023'; END IF;
            IF EXISTS (SELECT 1 FROM app.unit_cleaning_charges WHERE lease_id=p_lease) THEN
                RAISE EXCEPTION 'The Unit cleaning charge is already recorded for this Lease'
                    USING ERRCODE='P4503'; END IF;
            SELECT rate.* INTO v_rate FROM app.unit_cleaning_rates AS rate
            WHERE rate.unit_id=v_lease.unit_id AND NOT EXISTS (
                SELECT 1 FROM app.unit_cleaning_rates AS later WHERE later.supersedes_rate_id=rate.id);
            IF NOT FOUND THEN RAISE EXCEPTION 'The Unit has no cleaning rate' USING ERRCODE='22023'; END IF;
            IF v_rate.id<>p_expected_rate THEN
                RAISE EXCEPTION 'Unit cleaning rate changed' USING ERRCODE='P4503'; END IF;
            IF v_rate.rate_usd_cents=0 THEN
                RAISE EXCEPTION 'The Unit cleaning rate is zero; there is no cleaning charge'
                    USING ERRCODE='22023'; END IF;
            PERFORM app.record_one_time_charge(p_property,p_actor,p_id,'MISCELLANEOUS_CHARGES',
                v_lease.primary_tenant_id,p_lease,NULL,'Unit cleaning charge',v_rate.rate_usd_cents,
                'Unit cleaning charge at move-out (BR-MOVEOUT-013)',
                'unit-cleaning-rate:' || v_rate.id::text);
            v_now:=clock_timestamp();
            INSERT INTO app.unit_cleaning_charges(obligation_id,property_id,lease_id,unit_id,cleaning_rate_id,
                rate_usd_cents,physical_move_out_event_id,recorded_by,recorded_at)
            VALUES(p_id,p_property,p_lease,v_lease.unit_id,v_rate.id,v_rate.rate_usd_cents,v_move_out,
                p_actor,v_now);
            RETURN app.unit_cleaning_charge_snapshot(p_id);
        END $$;
    """)
    op.execute(
        "REVOKE ALL ON TABLE app.unit_cleaning_rates, app.unit_cleaning_charges "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in (SET_RATE, READ_RATE, RECORD_CHARGE, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {SET_RATE}, {READ_RATE} TO prm_runtime")
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD_CHARGE} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Unit cleaning charge migration is forward-only")
