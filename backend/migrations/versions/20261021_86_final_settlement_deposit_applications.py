# ruff: noqa: E501
"""Final Settlement record and Deposit application record (V1-056 sub-slice 8a-1).

Owner answers to Q-2026-10-05-20 and Q-2026-10-05-21 (2026-10-05):
- One Final Settlement per TERMINATED Lease (BR-SETTLE-001). Staff holding
  final_settlements.prepare open it; opening it has no financial effect. A closed Settlement is
  never changed or reopened; the single closure transition is written by the confirm (8e).
- A Deposit application (DB-DEP-005) pays an Invoice line or a Late-payment Charge of the
  Settlement Lease, whoever is named on the Invoice (answers 1 and 5), from a Lease Security or
  Pet Deposit, in the DL-032 stages PET_RELATED_FIRST, SECURITY_EXPLICIT, PET_REMAINDER_EXPLICIT.
  A kept Deposit is never applied (BR-DEP-026, BR-DEP-022): when the termination record gives a
  forfeiture ground for that Deposit, or the Deposit has an active disposition, it is refused.
  The first Pet stage pays only pet-related Damage charge lines (current inspection).
- No role may write a Deposit application; only the internal app.post_deposit_application,
  which the Settlement confirm (8e) calls with the financial.approve reference. Deposit
  application reversals are not built (plan Q15).
- A Deposit application counts as paid wherever Invoice line, Invoice status and Late-payment
  Charge balances are derived, and it reduces the Deposit's held amount. VOID, Adjustments and
  Late-payment Charge corrections refuse an obligation a Deposit application paid; a Deposit
  receipt reversal is refused while the Deposit has an application. These refusals concern a
  record that did not exist before this migration, so no earlier input is refused.

Additive: new tables, functions and triggers. Replaced in place with the same behavior for
existing data: the Invoice line application value, the Late-payment Charge application summary,
the allocation target chronology, the Deposit balance events, the Deposit snapshot, the receipt
reversal guard, the termination Invoice readiness (one more line field), the hand-back basis
(applied value through the shared function) and the forfeiture source (its ground rule moved to a
shared function that the Deposit application guard also uses).
"""

from alembic import op
from sqlalchemy import text

revision = "20261021_86"
down_revision = "20261020_85"
branch_labels = None
depends_on = None

START = "app.start_final_settlement(uuid,uuid,uuid)"
POST = "app.post_deposit_application(uuid,uuid,uuid,uuid,uuid,text,text,uuid,bigint,integer,text)"
INTERNAL = (
    "app.final_settlement_json(uuid)",
    "app.lease_deposit_forfeiture_rule(text,text,text,uuid,date,date)",
    "app.lease_deposit_kept_rule(uuid,uuid)",
    "app.invoice_line_is_pet_damage(uuid,uuid)",
    "app.invoice_line_deposit_value_at(uuid,timestamptz)",
    "app.validate_final_settlement()",
    "app.reject_final_settlement_change()",
    "app.validate_deposit_application()",
    "app.validate_deposit_application_complete()",
    "app.reject_deposit_application_mutation()",
    "app.refuse_deposit_applied_obligation_change()",
)


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = _definition(signature)
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Final Settlement integration source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def _patch_forfeiture_source() -> None:
    """Move the slice 6 ground rule into one shared function without changing it."""
    signature = "app.lease_deposit_forfeiture_source(uuid,uuid)"
    definition = _definition(signature)
    start_marker = "            v_rule:=CASE\n"
    end_marker = "            END;\n"
    if definition.count(start_marker) != 1:
        raise RuntimeError(f"Final Settlement integration source contract changed: {signature}")
    start = definition.index(start_marker)
    end = definition.index(end_marker, start) + len(end_marker)
    block = definition[start:end]
    expected = {
        "'BR-DEP-022'": 2,
        "'BR-LEASE-021'": 1,
        "'BR-DEP-023'": 1,
        "'BR-LEASE-005'": 2,
        "'BR-LEASE-025'": 2,
        "'BR-LEASE-028'": 2,
        "'THIRTY_DAY_SERIOUS_DEFAULT'": 1,
    }
    if any(block.count(literal) != count for literal, count in expected.items()):
        raise RuntimeError(f"Final Settlement integration source contract changed: {signature}")
    op.execute(
        definition[:start]
        + "            v_rule:=app.lease_deposit_forfeiture_rule(v_deposit.deposit_type,\n"
        + "                v_event.governing_event_reference,v_basis,v_lease.id,\n"
        + "                v_lease.actual_termination_date,v_lease.end_date);\n"
        + definition[end:]
    )


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.final_settlements (
            id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL UNIQUE REFERENCES app.leases(id) ON DELETE RESTRICT,
            started_at timestamptz NOT NULL CHECK (isfinite(started_at)),
            started_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            actual_termination_date_snapshot date NOT NULL CHECK (isfinite(actual_termination_date_snapshot)),
            move_out_date_snapshot date CHECK (move_out_date_snapshot IS NULL OR isfinite(move_out_date_snapshot)),
            closed_at timestamptz CHECK (closed_at IS NULL OR isfinite(closed_at)),
            closed_by uuid REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            source_snapshot jsonb CHECK (source_snapshot IS NULL OR (jsonb_typeof(source_snapshot)='object'
                AND octet_length(source_snapshot::text)<=1000000)),
            closing_balance_due_usd_cents bigint CHECK (closing_balance_due_usd_cents IS NULL
                OR closing_balance_due_usd_cents BETWEEN 0 AND 9000000000000000),
            CONSTRAINT final_settlements_closure_shape CHECK (
                (closed_at IS NULL AND closed_by IS NULL AND source_snapshot IS NULL
                    AND closing_balance_due_usd_cents IS NULL)
                OR (closed_at IS NOT NULL AND closed_by IS NOT NULL AND source_snapshot IS NOT NULL
                    AND closing_balance_due_usd_cents IS NOT NULL AND closed_at>=started_at))
        );
        COMMENT ON TABLE app.final_settlements IS
            'One Final Settlement per TERMINATED Lease (BR-SETTLE-001, DB-SETTLE-001); closed once, never reopened';

        CREATE FUNCTION app.validate_final_settlement()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_lease app.leases%ROWTYPE; v_property uuid;
        BEGIN
            SELECT * INTO v_lease FROM app.leases WHERE id=NEW.lease_id;
            SELECT unit.property_id INTO v_property FROM app.units unit WHERE unit.id=v_lease.unit_id;
            IF v_lease.id IS NULL OR v_property IS DISTINCT FROM NEW.property_id
                OR v_lease.status IS DISTINCT FROM 'TERMINATED'
                OR v_lease.actual_termination_date IS DISTINCT FROM NEW.actual_termination_date_snapshot
                OR NEW.started_at<v_lease.terminated_at
                OR NEW.closed_at IS NOT NULL
            THEN RAISE EXCEPTION 'A Final Settlement needs its TERMINATED Lease and starts open'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER final_settlements_validate BEFORE INSERT ON app.final_settlements
            FOR EACH ROW EXECUTE FUNCTION app.validate_final_settlement();

        -- Only one transition exists: an open Settlement is closed once with its closure fields.
        CREATE FUNCTION app.reject_final_settlement_change()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF TG_OP<>'UPDATE' THEN
                RAISE EXCEPTION 'Final Settlements are never deleted' USING ERRCODE='55000'; END IF;
            IF OLD.closed_at IS NOT NULL THEN
                RAISE EXCEPTION 'A closed Final Settlement is never reopened or changed' USING ERRCODE='55000'; END IF;
            IF NEW.closed_at IS NULL OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.property_id IS DISTINCT FROM OLD.property_id OR NEW.lease_id IS DISTINCT FROM OLD.lease_id
                OR NEW.started_at IS DISTINCT FROM OLD.started_at OR NEW.started_by IS DISTINCT FROM OLD.started_by
                OR NEW.actual_termination_date_snapshot IS DISTINCT FROM OLD.actual_termination_date_snapshot
                OR NEW.move_out_date_snapshot IS DISTINCT FROM OLD.move_out_date_snapshot
            THEN RAISE EXCEPTION 'A Final Settlement changes only by its single closure' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER final_settlements_close_once BEFORE UPDATE OR DELETE ON app.final_settlements
            FOR EACH ROW EXECUTE FUNCTION app.reject_final_settlement_change();
        CREATE TRIGGER final_settlements_no_truncate BEFORE TRUNCATE ON app.final_settlements
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_final_settlement_change();

        CREATE FUNCTION app.final_settlement_json(p_settlement uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT jsonb_build_object('id',settlement.id,'property_id',settlement.property_id,
                'lease_id',settlement.lease_id,'started_at',settlement.started_at,
                'started_by',settlement.started_by,
                'actual_termination_date',settlement.actual_termination_date_snapshot,
                'move_out_date',settlement.move_out_date_snapshot,
                'closed',settlement.closed_at IS NOT NULL,'closed_at',settlement.closed_at,
                'closed_by',settlement.closed_by,
                'closing_balance_due_usd_cents',settlement.closing_balance_due_usd_cents)
            FROM app.final_settlements settlement WHERE settlement.id=p_settlement
        $$;

        -- Staff open the one Settlement of a TERMINATED Lease (final_settlements.prepare, checked by
        -- the application). An existing Settlement is returned unchanged.
        CREATE FUNCTION app.start_final_settlement(p_property uuid,p_actor uuid,p_lease uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_lease app.leases%ROWTYPE; v_property uuid; v_existing uuid; v_id uuid;
            v_at timestamptz; v_current bigint; v_move_out date;
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_lease IS NULL
            THEN RAISE EXCEPTION 'Final Settlement input is invalid' USING ERRCODE='22023'; END IF;
            PERFORM app.require_invoice_command_actor(p_property,p_actor);
            PERFORM app.assert_active_financial_actor(p_actor,p_property);
            SELECT unit.property_id INTO v_property
            FROM app.leases lease JOIN app.units unit ON unit.id=lease.unit_id WHERE lease.id=p_lease;
            IF NOT FOUND OR v_property IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE='P0002'; END IF;
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=p_lease FOR UPDATE;
            SELECT id INTO v_existing FROM app.final_settlements WHERE lease_id=p_lease;
            IF FOUND THEN
                RETURN app.final_settlement_json(v_existing)||jsonb_build_object('created',false);
            END IF;
            IF v_lease.status IS DISTINCT FROM 'TERMINATED' THEN
                RAISE EXCEPTION 'A Final Settlement starts only for a TERMINATED Lease' USING ERRCODE='55000'; END IF;
            SELECT count(*) INTO v_current FROM app.physical_move_out_events move_out
            WHERE move_out.lease_id=p_lease AND NOT EXISTS (
                SELECT 1 FROM app.physical_move_out_events later WHERE later.supersedes_event_id=move_out.id);
            IF v_current>1 THEN
                RAISE EXCEPTION 'The current move-out record is ambiguous' USING ERRCODE='55000'; END IF;
            SELECT move_out.actual_move_out_date INTO v_move_out FROM app.physical_move_out_events move_out
            WHERE move_out.lease_id=p_lease AND NOT EXISTS (
                SELECT 1 FROM app.physical_move_out_events later WHERE later.supersedes_event_id=move_out.id);
            v_id:=gen_random_uuid(); v_at:=clock_timestamp();
            INSERT INTO app.final_settlements(id,property_id,lease_id,started_at,started_by,
                actual_termination_date_snapshot,move_out_date_snapshot)
            VALUES(v_id,p_property,p_lease,v_at,p_actor,v_lease.actual_termination_date,v_move_out);
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,resulting_state,correlation_id,source,outcome,
                customer_id,lease_id)
            VALUES(gen_random_uuid(),v_at,(v_at AT TIME ZONE 'Asia/Phnom_Penh')::date,p_actor,
                'final_settlement.started','final_settlement',v_id,'Final Settlement started',
                'final_settlements.prepare',p_property,
                jsonb_build_object('lease_id',p_lease,'actual_termination_date',v_lease.actual_termination_date,
                    'move_out_date',v_move_out,'started_at',v_at),
                v_id,'API','SUCCESS',v_lease.primary_tenant_id,p_lease);
            RETURN app.final_settlement_json(v_id)||jsonb_build_object('created',true);
        END $$;

        -- The slice 6 forfeiture ground rule, shared by the forfeiture source and the Deposit
        -- application guard so both read the termination record the same way.
        CREATE FUNCTION app.lease_deposit_forfeiture_rule(p_deposit_type text,p_governing text,p_basis text,
            p_lease uuid,p_actual date,p_end date)
        RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT CASE
                WHEN p_governing='BR-DEP-022' AND p_basis='CUSTOMER_VIOLATION' THEN 'BR-DEP-022'
                WHEN p_deposit_type<>'SECURITY' THEN NULL
                WHEN p_governing='BR-LEASE-021' AND p_actual<p_end
                    AND (p_basis IS NULL OR p_basis='VOLUNTARY_EARLY') THEN 'BR-DEP-023'
                WHEN p_governing='BR-LEASE-005' AND p_basis='UNPAID_INITIAL_OBLIGATION' THEN 'BR-LEASE-005'
                WHEN p_governing='BR-LEASE-025' AND p_basis='CUSTOMER_VIOLATION' THEN 'BR-LEASE-025'
                WHEN p_governing='BR-LEASE-028' AND EXISTS(
                    SELECT 1 FROM app.rent_nonpayment_events default_event
                    JOIN app.rent_nonpayment_cases nonpayment ON nonpayment.id=default_event.rent_nonpayment_case_id
                    WHERE nonpayment.lease_id=p_lease AND default_event.event_kind='THIRTY_DAY_SERIOUS_DEFAULT'
                      AND default_event.event_date<=p_actual) THEN 'BR-LEASE-028'
            END
        $$;

        -- The kept-Deposit ground of a terminated Lease's Deposit, or NULL when the Deposit is not
        -- kept (BR-DEP-026, BR-DEP-022; owner answer 2 to Q-2026-10-05-20).
        CREATE FUNCTION app.lease_deposit_kept_rule(p_property uuid,p_deposit uuid)
        RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_deposit app.deposits%ROWTYPE; v_lease app.leases%ROWTYPE; v_event app.lease_commands%ROWTYPE;
            v_basis text; v_events bigint;
        BEGIN
            SELECT * INTO v_deposit FROM app.deposits WHERE id=p_deposit;
            IF NOT FOUND OR app.deposit_property_id(p_deposit) IS DISTINCT FROM p_property
                OR v_deposit.lease_id IS NULL
            THEN RAISE EXCEPTION 'Lease Deposit was not found' USING ERRCODE='P0002'; END IF;
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_deposit.lease_id;
            IF v_lease.status IS DISTINCT FROM 'TERMINATED' THEN
                RAISE EXCEPTION 'The Lease is not terminated' USING ERRCODE='22023'; END IF;
            SELECT count(*) INTO v_events FROM app.lease_commands event
            WHERE event.lease_id=v_lease.id AND event.property_id=p_property AND event.action='lease.terminate'
              AND event.occurred_at=v_lease.terminated_at;
            IF v_events<>1 THEN
                RAISE EXCEPTION 'The termination record is ambiguous' USING ERRCODE='22023'; END IF;
            SELECT event.* INTO STRICT v_event FROM app.lease_commands event
            WHERE event.lease_id=v_lease.id AND event.property_id=p_property AND event.action='lease.terminate'
              AND event.occurred_at=v_lease.terminated_at;
            SELECT context.context_data->>'basis' INTO v_basis FROM app.lease_termination_contexts context
            WHERE context.command_event_id=v_event.event_id;
            RETURN app.lease_deposit_forfeiture_rule(v_deposit.deposit_type,v_event.governing_event_reference,
                v_basis,v_lease.id,v_lease.actual_termination_date,v_lease.end_date);
        END $$;

        -- Valid pet damage: a Damage charge line whose finding is pet-related on the Lease's current
        -- inspection (plan Q12, migrations 60 and 65).
        CREATE FUNCTION app.invoice_line_is_pet_damage(p_line uuid,p_lease uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT EXISTS(SELECT 1 FROM app.invoice_lines line
                JOIN app.authorized_nonrecurring_obligations obligation ON obligation.id=line.authorized_obligation_id
                JOIN app.inspection_damage_findings finding ON finding.id=obligation.inspection_damage_finding_id
                JOIN app.move_out_inspections inspection ON inspection.id=finding.inspection_id
                WHERE line.id=p_line AND line.category='DAMAGE_CHARGES' AND obligation.category='DAMAGE_CHARGES'
                    AND finding.pet_related AND inspection.lease_id=p_lease
                    AND NOT EXISTS(SELECT 1 FROM app.move_out_inspections later
                        WHERE later.supersedes_inspection_id=inspection.id))
        $$;

        CREATE TABLE app.deposit_applications (
            id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            final_settlement_id uuid NOT NULL REFERENCES app.final_settlements(id) ON DELETE RESTRICT,
            deposit_id uuid NOT NULL REFERENCES app.deposits(id) ON DELETE RESTRICT,
            target_kind text NOT NULL CHECK (target_kind IN ('INVOICE_LINE','LATE_PAYMENT_CHARGE')),
            invoice_id uuid REFERENCES app.invoices(id) ON DELETE RESTRICT,
            invoice_line_id uuid REFERENCES app.invoice_lines(id) ON DELETE RESTRICT,
            late_payment_charge_id uuid REFERENCES app.late_payment_charges(id) ON DELETE RESTRICT,
            application_stage text NOT NULL CHECK (application_stage IN
                ('PET_RELATED_FIRST','SECURITY_EXPLICIT','PET_REMAINDER_EXPLICIT')),
            amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents BETWEEN 1 AND 9000000000000000),
            application_order integer NOT NULL CHECK (application_order BETWEEN 1 AND 100000),
            reason text NOT NULL CHECK (reason=btrim(reason) AND length(reason) BETWEEN 1 AND 1000),
            occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK (authorization_reference='financial.approve'),
            CONSTRAINT deposit_applications_target_shape CHECK (
                (target_kind='INVOICE_LINE' AND invoice_id IS NOT NULL AND invoice_line_id IS NOT NULL
                    AND late_payment_charge_id IS NULL)
                OR (target_kind='LATE_PAYMENT_CHARGE' AND invoice_id IS NULL AND invoice_line_id IS NULL
                    AND late_payment_charge_id IS NOT NULL)),
            CONSTRAINT deposit_applications_pet_first_targets_a_line CHECK (
                application_stage<>'PET_RELATED_FIRST' OR target_kind='INVOICE_LINE'),
            CONSTRAINT deposit_applications_settlement_order UNIQUE (final_settlement_id,application_order)
        );
        CREATE INDEX deposit_applications_deposit_idx ON app.deposit_applications(deposit_id);
        CREATE INDEX deposit_applications_invoice_idx ON app.deposit_applications(invoice_id)
            WHERE invoice_id IS NOT NULL;
        CREATE INDEX deposit_applications_line_idx ON app.deposit_applications(invoice_line_id)
            WHERE invoice_line_id IS NOT NULL;
        CREATE INDEX deposit_applications_charge_idx ON app.deposit_applications(late_payment_charge_id)
            WHERE late_payment_charge_id IS NOT NULL;
        COMMENT ON TABLE app.deposit_applications IS
            'Append-only Final Settlement Deposit applications (DB-DEP-005, BR-DEP-014, DL-032); written only by the Settlement confirm';

        CREATE FUNCTION app.invoice_line_deposit_value_at(p_line_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT COALESCE(sum(application.amount_usd_cents),0)::bigint
            FROM app.deposit_applications application
            WHERE application.invoice_line_id=p_line_id AND application.occurred_at<=p_as_of
        $$;

        CREATE FUNCTION app.validate_deposit_application()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_settlement app.final_settlements%ROWTYPE; v_lease app.leases%ROWTYPE;
            v_deposit app.deposits%ROWTYPE; v_invoice app.invoices%ROWTYPE; v_line app.invoice_lines%ROWTYPE;
            v_charge app.late_payment_charges%ROWTYPE; v_balance bigint; v_target_at timestamptz;
            v_last_order integer; v_last_rank integer; v_rank integer;
        BEGIN
            -- Lock order: Settlement, Deposit, then the target Invoice (8e keeps it).
            SELECT * INTO v_settlement FROM app.final_settlements WHERE id=NEW.final_settlement_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='23503'; END IF;
            IF v_settlement.closed_at IS NOT NULL THEN
                RAISE EXCEPTION 'A closed Final Settlement takes no new Deposit application' USING ERRCODE='55000'; END IF;
            -- Every writer inherits the human-approver rule (BR-AUTH-010).
            IF NOT EXISTS(SELECT 1 FROM app.actor_identities identity
                WHERE identity.actor_id=NEW.actor_id AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'A Deposit application needs a human approver' USING ERRCODE='42501'; END IF;
            PERFORM app.assert_active_financial_actor(NEW.actor_id,v_settlement.property_id);
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_settlement.lease_id;
            IF v_lease.status IS DISTINCT FROM 'TERMINATED' THEN
                RAISE EXCEPTION 'Deposits are applied only after Lease termination' USING ERRCODE='23514'; END IF;
            SELECT * INTO v_deposit FROM app.deposits WHERE id=NEW.deposit_id;
            IF NOT FOUND OR v_deposit.lease_id IS DISTINCT FROM v_settlement.lease_id THEN
                RAISE EXCEPTION 'The Deposit does not belong to the Settlement Lease' USING ERRCODE='23514'; END IF;
            IF (NEW.application_stage='SECURITY_EXPLICIT') IS DISTINCT FROM (v_deposit.deposit_type='SECURITY')
                OR v_deposit.deposit_type NOT IN ('SECURITY','PET')
            THEN RAISE EXCEPTION 'The application stage does not match the Deposit type' USING ERRCODE='23514'; END IF;
            PERFORM app.serialize_deposit_state(NEW.deposit_id);
            -- A kept Deposit is never used to pay what the Customer owes (BR-DEP-026, BR-DEP-022).
            IF app.lease_deposit_kept_rule(v_settlement.property_id,NEW.deposit_id) IS NOT NULL
                OR EXISTS(SELECT 1 FROM app.deposit_dispositions disposition
                    WHERE disposition.deposit_id=NEW.deposit_id AND NOT EXISTS(
                        SELECT 1 FROM app.deposit_disposition_reversals reversal
                        WHERE reversal.deposit_disposition_id=disposition.id))
            THEN RAISE EXCEPTION 'A kept Deposit is never applied to what the Customer owes'
                USING ERRCODE='23514'; END IF;
            IF NEW.target_kind='INVOICE_LINE' THEN
                PERFORM app.lock_payment_allocation_target('INVOICE',NEW.invoice_id);
                SELECT * INTO v_invoice FROM app.invoices WHERE id=NEW.invoice_id;
                SELECT * INTO v_line FROM app.invoice_lines WHERE id=NEW.invoice_line_id;
                IF v_line.invoice_id IS DISTINCT FROM NEW.invoice_id
                    OR v_invoice.lease_id IS DISTINCT FROM v_settlement.lease_id
                    OR v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID')
                THEN RAISE EXCEPTION 'The target must be a line of an issued Invoice of the Settlement Lease'
                    USING ERRCODE='23514'; END IF;
                IF NEW.application_stage='PET_RELATED_FIRST'
                    AND NOT app.invoice_line_is_pet_damage(NEW.invoice_line_id,v_settlement.lease_id)
                THEN RAISE EXCEPTION 'The first Pet Deposit stage pays only valid pet damage' USING ERRCODE='23514'; END IF;
                v_balance:=app.invoice_line_outstanding(NEW.invoice_line_id);
                v_target_at:=app.allocation_target_latest_at('INVOICE',NEW.invoice_id);
            ELSE
                PERFORM app.lock_payment_allocation_target('LATE_PAYMENT_CHARGE',NEW.late_payment_charge_id);
                SELECT * INTO v_charge FROM app.late_payment_charges WHERE id=NEW.late_payment_charge_id;
                SELECT * INTO v_invoice FROM app.invoices WHERE id=v_charge.source_invoice_id;
                IF v_invoice.lease_id IS DISTINCT FROM v_settlement.lease_id THEN
                    RAISE EXCEPTION 'The target must be a Late-payment Charge of the Settlement Lease'
                    USING ERRCODE='23514'; END IF;
                SELECT position.remaining_balance_usd_cents INTO v_balance
                FROM app.late_payment_charge_financial_position position
                WHERE position.late_payment_charge_id=NEW.late_payment_charge_id;
                v_target_at:=GREATEST(v_charge.created_at,v_charge.payable_at,
                    app.allocation_target_latest_at('LATE_PAYMENT_CHARGE',NEW.late_payment_charge_id));
            END IF;
            v_rank:=CASE NEW.application_stage WHEN 'PET_RELATED_FIRST' THEN 1
                WHEN 'SECURITY_EXPLICIT' THEN 2 ELSE 3 END;
            SELECT max(application.application_order),max(CASE application.application_stage
                    WHEN 'PET_RELATED_FIRST' THEN 1 WHEN 'SECURITY_EXPLICIT' THEN 2 ELSE 3 END)
            INTO v_last_order,v_last_rank
            FROM app.deposit_applications application WHERE application.final_settlement_id=NEW.final_settlement_id;
            IF NEW.application_order<=COALESCE(v_last_order,0) OR v_rank<COALESCE(v_last_rank,1) THEN
                RAISE EXCEPTION 'Deposit applications follow the DL-032 order' USING ERRCODE='23514'; END IF;
            IF NEW.amount_usd_cents>COALESCE(v_balance,0)
                OR NEW.amount_usd_cents>app.deposit_held_value_at(NEW.deposit_id,'infinity')
                OR NEW.occurred_at<v_settlement.started_at
                OR NEW.occurred_at<=COALESCE(v_target_at,'-infinity')
                OR NEW.occurred_at<=COALESCE(app.deposit_balance_latest_at(NEW.deposit_id),'-infinity')
                OR NEW.occurred_at>clock_timestamp()+interval '5 seconds'
            THEN RAISE EXCEPTION 'Deposit application source, target, amount or chronology is invalid'
                USING ERRCODE='23514'; END IF;
            IF app.lease_notice_text_valid(NEW.reason,1000) IS NOT TRUE THEN
                RAISE EXCEPTION 'Deposit application reason is invalid' USING ERRCODE='22023'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER deposit_applications_validate BEFORE INSERT ON app.deposit_applications
            FOR EACH ROW EXECUTE FUNCTION app.validate_deposit_application();

        CREATE FUNCTION app.validate_deposit_application_complete()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF EXISTS(SELECT 1 FROM (
                    SELECT event_at,sum(amount) OVER (ORDER BY event_at RANGE UNBOUNDED PRECEDING) AS held
                    FROM app.deposit_balance_events(NEW.deposit_id)
                ) positions WHERE held<0 OR NOT isfinite(event_at))
                OR (NEW.invoice_line_id IS NOT NULL AND app.invoice_line_outstanding(NEW.invoice_line_id)<0)
                OR EXISTS(SELECT 1 FROM app.late_payment_charge_financial_position position
                    WHERE position.late_payment_charge_id=NEW.late_payment_charge_id
                        AND position.remaining_balance_usd_cents<0)
            THEN RAISE EXCEPTION 'Deposit application and financial position must reconcile' USING ERRCODE='23514'; END IF;
            IF NEW.invoice_id IS NOT NULL THEN
                -- Advance the Invoice version even when its status stays the same.
                PERFORM app.refresh_allocated_invoice(NEW.invoice_id,NEW.actor_id,true);
            END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER deposit_applications_complete AFTER INSERT ON app.deposit_applications
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_deposit_application_complete();

        CREATE FUNCTION app.reject_deposit_application_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Deposit applications are append-only' USING ERRCODE='55000';
        END $$;
        CREATE TRIGGER deposit_applications_immutable BEFORE UPDATE OR DELETE ON app.deposit_applications
            FOR EACH ROW EXECUTE FUNCTION app.reject_deposit_application_mutation();
        CREATE TRIGGER deposit_applications_no_truncate BEFORE TRUNCATE ON app.deposit_applications
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_deposit_application_mutation();

        -- The only writer: the Settlement confirm (8e) passes the financial.approve reference.
        CREATE FUNCTION app.post_deposit_application(p_property uuid,p_actor uuid,p_settlement uuid,
            p_application uuid,p_deposit uuid,p_stage text,p_target_kind text,p_target uuid,
            p_amount bigint,p_order integer,p_reason text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_settlement app.final_settlements%ROWTYPE; v_invoice uuid; v_at timestamptz;
            v_customer uuid;
        BEGIN
            SELECT * INTO v_settlement FROM app.final_settlements WHERE id=p_settlement;
            IF NOT FOUND OR v_settlement.property_id IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
            -- The approver is a person (BR-AUTH-010); the trigger checks that the account is active.
            IF NOT EXISTS(SELECT 1 FROM app.actor_identities identity
                WHERE identity.actor_id=p_actor AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'A Deposit application needs a human approver' USING ERRCODE='42501'; END IF;
            IF p_target_kind='INVOICE_LINE' THEN
                SELECT line.invoice_id INTO v_invoice FROM app.invoice_lines line WHERE line.id=p_target;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Deposit application target was not found' USING ERRCODE='P0002'; END IF;
            ELSIF p_target_kind='LATE_PAYMENT_CHARGE' THEN
                PERFORM 1 FROM app.late_payment_charges charge WHERE charge.id=p_target;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Deposit application target was not found' USING ERRCODE='P0002'; END IF;
            ELSE RAISE EXCEPTION 'Deposit application target kind is invalid' USING ERRCODE='22023';
            END IF;
            v_at:=clock_timestamp();
            INSERT INTO app.deposit_applications(id,final_settlement_id,deposit_id,target_kind,invoice_id,
                invoice_line_id,late_payment_charge_id,application_stage,amount_usd_cents,application_order,
                reason,occurred_at,actor_id,authorization_reference)
            VALUES(p_application,p_settlement,p_deposit,p_target_kind,v_invoice,
                CASE WHEN p_target_kind='INVOICE_LINE' THEN p_target END,
                CASE WHEN p_target_kind='LATE_PAYMENT_CHARGE' THEN p_target END,
                p_stage,p_amount,p_order,p_reason,v_at,p_actor,'financial.approve');
            SELECT customer_id INTO v_customer FROM app.deposits WHERE id=p_deposit;
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,resulting_state,correlation_id,source,outcome,
                customer_id,lease_id)
            VALUES(gen_random_uuid(),v_at,(v_at AT TIME ZONE 'Asia/Phnom_Penh')::date,p_actor,
                'deposit_application.recorded','deposit_application',p_application,p_reason,'financial.approve',
                p_property,jsonb_build_object('final_settlement_id',p_settlement,'deposit_id',p_deposit,
                    'target_kind',p_target_kind,'target_id',p_target,'stage_kind',p_stage,
                    'amount_usd_cents',p_amount,'application_sequence',p_order),
                p_settlement,'API','SUCCESS',v_customer,v_settlement.lease_id);
            RETURN jsonb_build_object('id',p_application,'final_settlement_id',p_settlement,
                'deposit_id',p_deposit,'stage',p_stage,'target_kind',p_target_kind,'target_id',p_target,
                'amount_usd_cents',p_amount,'application_order',p_order,'occurred_at',v_at);
        END $$;

        -- An obligation a Deposit application paid changes only through a post-settlement correction.
        CREATE FUNCTION app.refuse_deposit_applied_obligation_change()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            -- Separate branches: each table's row has only its own target column.
            IF TG_TABLE_NAME='late_payment_charge_corrections' THEN
                -- P4603 is the Late-payment command conflict; its only writer inserts after the
                -- replay lookup, so the service reports a conflict, not an unresolved outcome.
                IF EXISTS(SELECT 1 FROM app.deposit_applications application
                    WHERE application.late_payment_charge_id=NEW.late_payment_charge_id)
                THEN RAISE EXCEPTION 'A Deposit application paid this obligation at Final Settlement'
                    USING ERRCODE='P4603'; END IF;
            ELSIF EXISTS(SELECT 1 FROM app.deposit_applications application
                WHERE application.invoice_id=NEW.invoice_id)
            THEN RAISE EXCEPTION 'A Deposit application paid this obligation at Final Settlement'
                USING ERRCODE='55000'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER a_invoice_void_events_deposit_applied BEFORE INSERT ON app.invoice_void_events
            FOR EACH ROW EXECUTE FUNCTION app.refuse_deposit_applied_obligation_change();
        CREATE TRIGGER a_invoice_adjustments_deposit_applied BEFORE INSERT ON app.invoice_adjustments
            FOR EACH ROW EXECUTE FUNCTION app.refuse_deposit_applied_obligation_change();
        CREATE TRIGGER a_late_payment_charge_corrections_deposit_applied
            BEFORE INSERT ON app.late_payment_charge_corrections
            FOR EACH ROW EXECUTE FUNCTION app.refuse_deposit_applied_obligation_change();

        -- A Deposit application counts as paid wherever an Invoice line balance is derived.
        CREATE OR REPLACE FUNCTION app.invoice_line_application_value_at(p_line_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT (app.invoice_line_payment_value_at(p_line_id,p_as_of)::numeric
                +app.invoice_line_credit_value_at(p_line_id,p_as_of)
                +app.invoice_line_deposit_value_at(p_line_id,p_as_of))::bigint
        $$;

        -- ... and wherever a Late-payment Charge balance is derived (owner answer 1).
        CREATE OR REPLACE FUNCTION app.late_payment_charge_application_summary(p_charge_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            WITH active AS (
                SELECT 'PAYMENT_ALLOCATION'::text AS kind,allocation.id,allocation.payment_id,NULL::uuid AS credit_id,
                    NULL::uuid AS deposit_id,allocation.amount_usd_cents,allocation.posted_at
                FROM app.payment_allocations allocation WHERE allocation.late_payment_charge_id=p_charge_id
                    AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal WHERE reversal.payment_allocation_id=allocation.id)
                UNION ALL SELECT 'CREDIT_APPLICATION',application.id,NULL::uuid,application.customer_credit_id,
                    NULL::uuid,application.amount_usd_cents,application.occurred_at
                FROM app.customer_credit_applications application WHERE application.late_payment_charge_id=p_charge_id
                    AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal WHERE reversal.credit_application_id=application.id)
                UNION ALL SELECT 'DEPOSIT_APPLICATION',application.id,NULL::uuid,NULL::uuid,application.deposit_id,
                    application.amount_usd_cents,application.occurred_at
                FROM app.deposit_applications application WHERE application.late_payment_charge_id=p_charge_id
            ) SELECT CASE WHEN EXISTS(SELECT 1 FROM app.late_payment_charges WHERE id=p_charge_id)
            THEN jsonb_build_object('active_total_usd_cents',COALESCE(sum(amount_usd_cents),0),
                'payment_total_usd_cents',COALESCE(sum(amount_usd_cents) FILTER(WHERE kind='PAYMENT_ALLOCATION'),0),
                'credit_total_usd_cents',COALESCE(sum(amount_usd_cents) FILTER(WHERE kind='CREDIT_APPLICATION'),0),
                'deposit_total_usd_cents',COALESCE(sum(amount_usd_cents) FILTER(WHERE kind='DEPOSIT_APPLICATION'),0),
                'items',COALESCE(jsonb_agg(CASE WHEN kind='PAYMENT_ALLOCATION'
                    THEN jsonb_build_object('kind',kind,'id',id,'payment_id',payment_id,'amount_usd_cents',amount_usd_cents,'posted_at',posted_at)
                    WHEN kind='CREDIT_APPLICATION'
                    THEN jsonb_build_object('kind',kind,'id',id,'customer_credit_id',credit_id,'amount_usd_cents',amount_usd_cents,'posted_at',posted_at)
                    ELSE jsonb_build_object('kind',kind,'id',id,'deposit_id',deposit_id,'amount_usd_cents',amount_usd_cents,'posted_at',posted_at)
                    END ORDER BY posted_at,id),'[]'::jsonb)) ELSE NULL END FROM active
        $$;

        -- ... and the Deposit's held amount is lower by it.
        CREATE OR REPLACE FUNCTION app.deposit_balance_events(p_deposit_id uuid)
        RETURNS TABLE(event_at timestamptz,amount numeric)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT occurred_at,amount_usd_cents::numeric FROM app.deposit_receipts WHERE deposit_id=p_deposit_id
            UNION ALL SELECT reversal.occurred_at,-receipt.amount_usd_cents::numeric
                FROM app.deposit_receipt_reversals reversal JOIN app.deposit_receipts receipt ON receipt.id=reversal.deposit_receipt_id
                WHERE receipt.deposit_id=p_deposit_id
            UNION ALL SELECT occurred_at,-amount_usd_cents::numeric FROM app.deposit_dispositions WHERE deposit_id=p_deposit_id
            UNION ALL SELECT reversal.occurred_at,disposition.amount_usd_cents::numeric
                FROM app.deposit_disposition_reversals reversal JOIN app.deposit_dispositions disposition ON disposition.id=reversal.deposit_disposition_id
                WHERE disposition.deposit_id=p_deposit_id
            UNION ALL SELECT processed_at,-usd_accounting_value_cents::numeric FROM app.refunds WHERE source_deposit_id=p_deposit_id
            UNION ALL SELECT correction.occurred_at,correction.source_balance_effect_usd_cents::numeric
                FROM app.refund_corrections correction JOIN app.refunds refund ON refund.id=correction.refund_id
                WHERE refund.source_deposit_id=p_deposit_id
            UNION ALL SELECT occurred_at,-amount_usd_cents::numeric FROM app.deposit_applications WHERE deposit_id=p_deposit_id
        $$;
    """)
    _patch(
        "app.allocation_target_latest_at(text,uuid)",
        (
            (
                ") events",
                "    UNION ALL SELECT occurred_at FROM app.deposit_applications\n"
                "                    WHERE (p_kind='INVOICE' AND invoice_id=p_target_id)\n"
                "                        OR (p_kind='LATE_PAYMENT_CHARGE' AND late_payment_charge_id=p_target_id)\n"
                "            ) events",
            ),
        ),
    )
    _patch(
        "app.deposit_snapshot(uuid)",
        (
            (
                "                        FROM app.refunds AS refund WHERE refund.source_deposit_id = deposit.id), 0)\n",
                "                        FROM app.refunds AS refund WHERE refund.source_deposit_id = deposit.id), 0)\n"
                "                    - COALESCE((SELECT sum(application.amount_usd_cents)\n"
                "                        FROM app.deposit_applications AS application\n"
                "                        WHERE application.deposit_id = deposit.id), 0)\n",
            ),
        ),
    )
    _patch(
        "app.validate_deposit_receipt_reversal()",
        (
            (
                "            ) OR app.deposit_has_unresolved_refund(v_deposit_id)\n",
                "            ) OR app.deposit_has_unresolved_refund(v_deposit_id)\n"
                "              OR app.deposit_has_active_application(v_deposit_id)\n",
            ),
        ),
    )
    _patch(
        "app.lease_termination_invoice_readiness(uuid,uuid,uuid,integer,uuid)",
        (
            (
                "                    app.invoice_line_credit_value_at(line.id,'infinity') AS credit_applied_usd_cents,\n",
                "                    app.invoice_line_credit_value_at(line.id,'infinity') AS credit_applied_usd_cents,\n"
                "                    app.invoice_line_deposit_value_at(line.id,'infinity') AS deposit_applied_usd_cents,\n",
            ),
        ),
    )
    _patch(
        "app.hand_back_rent_invoice_basis(uuid,uuid,uuid)",
        (
            (
                "            SELECT COALESCE(sum(app.invoice_line_payment_value_at(line.id,'infinity')\n"
                "                    +app.invoice_line_credit_value_at(line.id,'infinity')),0),\n",
                "            SELECT COALESCE(sum(app.invoice_line_application_value_at(line.id,'infinity')),0),\n",
            ),
            (
                "                    'applied_usd_cents',app.invoice_line_payment_value_at(line.id,'infinity')\n"
                "                        +app.invoice_line_credit_value_at(line.id,'infinity'),\n",
                "                    'applied_usd_cents',app.invoice_line_application_value_at(line.id,'infinity'),\n",
            ),
        ),
    )
    # The Payment reversal and financial action contexts read the Late-payment Charge's active
    # applications from its financial position, so a Deposit application counts there too.
    _patch(
        "app.payment_reversal_context_page(uuid,uuid,uuid,text,integer,integer,uuid)",
        (
            (
                "                -COALESCE((SELECT sum(a.amount_usd_cents) FROM app.payment_allocations a\n"
                "                    WHERE a.late_payment_charge_id=c.id AND NOT EXISTS(\n"
                "                        SELECT 1 FROM app.payment_allocation_reversals r WHERE\n"
                "                r.payment_allocation_id=a.id)),0)\n"
                "                -COALESCE((SELECT sum(a.amount_usd_cents) FROM app.customer_credit_applications a\n"
                "                    WHERE a.late_payment_charge_id=c.id AND NOT EXISTS(\n"
                "                        SELECT 1 FROM app.customer_credit_application_reversals r WHERE\n"
                "                r.credit_application_id=a.id)),0))\n",
                "                -COALESCE((SELECT position.active_applications_usd_cents\n"
                "                    FROM app.late_payment_charge_financial_position position\n"
                "                    WHERE position.late_payment_charge_id=c.id),0))\n",
            ),
        ),
    )
    _patch(
        "app.financial_action_context_page(uuid,uuid,text,uuid,uuid,text,uuid,integer,integer,uuid)",
        (
            (
                "                        -COALESCE((SELECT sum(a.amount_usd_cents) FROM app.payment_allocations a\n"
                "                            WHERE a.late_payment_charge_id=v_charge.id AND NOT EXISTS(\n"
                "                                SELECT 1 FROM app.payment_allocation_reversals r WHERE\n"
                "                                    r.payment_allocation_id=a.id)),0)\n"
                "                        -COALESCE((SELECT sum(a.amount_usd_cents) FROM\n"
                "                            app.customer_credit_applications a\n"
                "                            WHERE a.late_payment_charge_id=v_charge.id AND NOT EXISTS(\n"
                "                                SELECT 1 FROM app.customer_credit_application_reversals r WHERE\n"
                "                                    r.credit_application_id=a.id)),0))\n",
                "                        -COALESCE((SELECT position.active_applications_usd_cents\n"
                "                            FROM app.late_payment_charge_financial_position position\n"
                "                            WHERE position.late_payment_charge_id=v_charge.id),0))\n",
            ),
        ),
    )
    _patch_forfeiture_source()
    op.execute(
        "REVOKE ALL ON TABLE app.final_settlements, app.deposit_applications "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in (START, POST, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {START} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Final Settlement migration is forward-only")
