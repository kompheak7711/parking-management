# ruff: noqa: E501
"""The draft Lease's Security Deposit and the amounts due at signing (V1-060 B6; DL-100).

Revision ID: 20270325_244
Revises: 20270324_243
Create Date: 2026-10-27

Owner rule of 2026-10-27 (DL-100): a walk-in Lease's draft carries the Security Deposit the
customer will pay, so the printed draft shows it; Sign Lease first receives the full money due at
signing (the rest of the Security Deposit and the Initial Rent Invoice), and the Lease is signed
only after that money is saved.

- New append-only table app.lease_planned_security_deposits: each save of the draft's Security
  Deposit amount is a new row; the latest row is the amount. Rows never change or go away.
- New app.set_lease_planned_security_deposit (SECURITY DEFINER, EXECUTE to prm_runtime; the API
  checks `leases.draft` first): only a DRAFTED Lease of the Property, never one drafted from a
  Reservation (its Security Deposit is the Reservation's, BR-DEP-005) and never a renewal (it
  keeps the Security Deposit it carries, DL-066), an active human actor, an
  amount of at least one cent; the same amount again adds nothing. Each save writes the
  `lease.security_deposit.planned` audit event.
- New app.lease_signing_preview (STABLE, SECURITY DEFINER, EXECUTE to prm_runtime): what the
  Initial Rent Invoice of the Lease will hold if it is made today, read with the generator's own
  rules (migrations 30, 64 and 237): the period from the Lease Start Date to its month end (to the
  next month end when the start is on the 21st or later), the Due Date (Start + 5 days or the
  latest authorized Due Date), the prorated Rent and every Service whose term and approval cover
  the whole month at the rate in force on the month's first billed day. A Service that covers only
  part of a month, or has no rate, is named as a problem instead (the generator refuses it). It
  also gives the draft's planned Security Deposit. Nothing is written.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270325_244"
down_revision: str | None = "20270324_243"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIGNATURES = (
    "app.set_lease_planned_security_deposit(uuid, uuid, uuid, uuid, bigint, text, text)",
    "app.lease_signing_preview(uuid, uuid)",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.lease_planned_security_deposits (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            required_usd_cents bigint NOT NULL
                CHECK (required_usd_cents BETWEEN 1 AND 9000000000000000),
            reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            audit_event_id uuid NOT NULL UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL CHECK (isfinite(recorded_at))
        );
        COMMENT ON TABLE app.lease_planned_security_deposits IS
            'The Security Deposit a walk-in draft Lease will take at signing (DL-100); latest row wins';
        CREATE INDEX lease_planned_security_deposits_lease_idx
            ON app.lease_planned_security_deposits(lease_id, recorded_at, id);
        CREATE TRIGGER lease_planned_security_deposits_reject_mutation BEFORE UPDATE OR DELETE
            ON app.lease_planned_security_deposits FOR EACH ROW
            EXECUTE FUNCTION app.reject_lease_append_only_mutation();
        CREATE TRIGGER lease_planned_security_deposits_reject_truncate BEFORE TRUNCATE
            ON app.lease_planned_security_deposits FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_lease_storage_truncate();
        REVOKE ALL ON app.lease_planned_security_deposits FROM PUBLIC, prm_runtime, prm_bootstrap;

        CREATE FUNCTION app.lease_planned_security_deposit(p_lease_id uuid) RETURNS bigint
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT planned.required_usd_cents FROM app.lease_planned_security_deposits AS planned
            WHERE planned.lease_id = p_lease_id
            ORDER BY planned.recorded_at DESC, planned.id DESC LIMIT 1
        $$;
        REVOKE ALL ON FUNCTION app.lease_planned_security_deposit(uuid) FROM PUBLIC;

        CREATE FUNCTION app.set_lease_planned_security_deposit(
            p_property_id uuid, p_lease_id uuid, p_id uuid, p_actor_id uuid,
            p_required_usd_cents bigint, p_reason text, p_authorization_reference text
        ) RETURNS bigint
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_lease app.leases%ROWTYPE;
            v_timezone text;
            v_before bigint;
            v_now timestamptz := clock_timestamp();
            v_audit uuid := gen_random_uuid();
        BEGIN
            IF p_property_id IS NULL OR p_lease_id IS NULL OR p_actor_id IS NULL
                OR p_id IS NULL OR p_id = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_authorization_reference IS DISTINCT FROM 'leases.draft'
                OR p_required_usd_cents IS NULL
                OR p_required_usd_cents NOT BETWEEN 1 AND 9000000000000000
                OR p_reason IS NULL OR p_reason <> btrim(p_reason)
                OR length(p_reason) NOT BETWEEN 1 AND 500
            THEN
                RAISE EXCEPTION 'Planned Security Deposit evidence is invalid' USING ERRCODE = '22023';
            END IF;
            PERFORM 1 FROM app.user_accounts AS account
            WHERE account.actor_id = p_actor_id AND account.lifecycle_state = 'active';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'An active user saves a planned Security Deposit' USING ERRCODE = '55000';
            END IF;
            SELECT lease.* INTO v_lease FROM app.leases AS lease
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id
            FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            -- The same identity again is a replay of a save already made.
            IF EXISTS (SELECT 1 FROM app.lease_planned_security_deposits WHERE id = p_id) THEN
                RETURN app.lease_planned_security_deposit(p_lease_id);
            END IF;
            IF v_lease.status <> 'DRAFTED' THEN
                RAISE EXCEPTION 'Only a drafted Lease takes a planned Security Deposit'
                    USING ERRCODE = '55000';
            END IF;
            IF EXISTS (
                SELECT 1 FROM app.lease_commands AS command
                WHERE command.lease_id = p_lease_id AND command.action = 'lease.draft'
                  AND command.result_snapshot->>'security_deposit_id' IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM app.reservations AS reservation
                WHERE reservation.resulting_lease_id = p_lease_id
            ) THEN
                RAISE EXCEPTION 'A Lease from a Reservation keeps the Reservation''s Security Deposit'
                    USING ERRCODE = '55000';
            END IF;
            IF v_lease.predecessor_lease_id IS NOT NULL THEN
                RAISE EXCEPTION 'A renewal Lease keeps the Security Deposit it carries'
                    USING ERRCODE = '55000';
            END IF;
            v_before := app.lease_planned_security_deposit(p_lease_id);
            IF v_before IS NOT DISTINCT FROM p_required_usd_cents THEN RETURN v_before; END IF;
            SELECT property.timezone_name INTO v_timezone
            FROM app.properties AS property WHERE property.id = p_property_id;
            INSERT INTO app.audit_events(id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                authorization_evidence, customer_id, lease_id, unit_id)
            VALUES (v_audit, v_now, timezone(v_timezone, v_now)::date, p_actor_id,
                'lease.security_deposit.planned', 'lease_planned_security_deposit', p_id,
                p_reason, p_authorization_reference, p_property_id,
                jsonb_build_object('required_usd_cents', v_before),
                jsonb_build_object('required_usd_cents', p_required_usd_cents),
                p_id, 'API', 'SUCCEEDED',
                jsonb_build_object('capability', p_authorization_reference, 'lease_id', p_lease_id),
                v_lease.primary_tenant_id, p_lease_id, v_lease.unit_id);
            INSERT INTO app.lease_planned_security_deposits(id, property_id, lease_id,
                required_usd_cents, reason, actor_id, audit_event_id, recorded_at)
            VALUES (p_id, p_property_id, p_lease_id, p_required_usd_cents, p_reason, p_actor_id,
                v_audit, v_now);
            RETURN p_required_usd_cents;
        END $$;

        CREATE FUNCTION app.lease_signing_preview(p_property_id uuid, p_lease_id uuid)
        RETURNS jsonb
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_lease app.leases%ROWTYPE;
            v_first_end date;
            v_second_start date;
            v_period_end date;
            v_due date;
            v_rent bigint;
            v_month record;
            v_service record;
            v_rate bigint;
            v_amount bigint;
            v_lines jsonb := '[]'::jsonb;
            v_total bigint;
            v_problem text;
        BEGIN
            SELECT lease.* INTO v_lease FROM app.leases AS lease
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            IF v_lease.start_date IS NULL OR v_lease.monthly_rent_usd_cents IS NULL THEN
                RETURN jsonb_build_object('initial', NULL, 'planned_security_deposit_usd_cents',
                    app.lease_planned_security_deposit(p_lease_id));
            END IF;
            v_first_end := (date_trunc('month', v_lease.start_date) + interval '1 month - 1 day')::date;
            v_period_end := v_first_end;
            IF extract(day FROM v_lease.start_date) >= 21 THEN
                v_second_start := v_first_end + 1;
                v_period_end := (date_trunc('month', v_lease.start_date) + interval '2 months - 1 day')::date;
            END IF;
            SELECT override.due_date INTO v_due FROM app.initial_rent_due_date_overrides AS override
            WHERE override.lease_id = p_lease_id
            ORDER BY override.occurred_at DESC, override.id DESC LIMIT 1;
            v_due := coalesce(v_due, v_lease.start_date + 5);
            v_rent := app.calculate_prorated_monthly_usd_cents(
                v_lease.monthly_rent_usd_cents, v_lease.start_date, v_first_end);
            IF v_second_start IS NOT NULL THEN
                v_rent := v_rent + v_lease.monthly_rent_usd_cents;
            END IF;
            v_total := v_rent;
            FOR v_month IN
                SELECT * FROM (VALUES (1, v_lease.start_date, v_first_end),
                                      (2, v_second_start, v_period_end))
                    AS month(month_index, month_start, month_end)
                WHERE month.month_start IS NOT NULL ORDER BY month.month_index
            LOOP
                FOR v_service IN
                    SELECT service.id, service.display_name, service.service_code,
                        EXISTS (
                            SELECT 1 FROM app.lease_service_terms AS term
                            JOIN app.property_service_approval_periods AS approval
                              ON approval.id = term.service_approval_period_id
                            WHERE term.property_service_id = service.id AND term.lease_id = p_lease_id
                              AND v_month.month_start >= term.applicable_from
                              AND v_month.month_end <= coalesce(term.applicable_through, v_month.month_end)
                              AND v_month.month_start >= approval.effective_from
                              AND v_month.month_end <= coalesce(approval.effective_through, v_month.month_end)
                        ) AS covers
                    FROM app.property_services AS service
                    WHERE service.property_id = p_property_id
                      AND EXISTS (
                        SELECT 1 FROM app.lease_service_terms AS term
                        JOIN app.property_service_approval_periods AS approval
                          ON approval.id = term.service_approval_period_id
                        WHERE term.property_service_id = service.id AND term.lease_id = p_lease_id
                          AND term.applicable_from <= v_month.month_end
                          AND coalesce(term.applicable_through, v_month.month_end) >= v_month.month_start
                          AND approval.effective_from <= v_month.month_end
                          AND coalesce(approval.effective_through, v_month.month_end) >= v_month.month_start)
                    ORDER BY (service.service_code <> 'TRASH_COLLECTION'),
                        service.display_name COLLATE "C", service.id
                LOOP
                    IF NOT v_service.covers THEN
                        v_problem := coalesce(v_problem, 'PARTIAL_SERVICE:' || v_service.display_name);
                        CONTINUE;
                    END IF;
                    SELECT rate.monthly_rate_usd_cents INTO v_rate FROM app.service_rates AS rate
                    WHERE rate.property_service_id = v_service.id
                      AND rate.effective_date <= v_month.month_start
                    ORDER BY rate.effective_date DESC, rate.id DESC LIMIT 1;
                    IF NOT FOUND THEN
                        v_problem := coalesce(v_problem, 'NO_RATE:' || v_service.display_name);
                        CONTINUE;
                    END IF;
                    v_amount := CASE v_month.month_index
                        WHEN 1 THEN app.calculate_prorated_monthly_usd_cents(
                            v_rate, v_month.month_start, v_month.month_end)
                        ELSE v_rate END;
                    v_total := v_total + v_amount;
                    v_lines := v_lines || jsonb_build_object(
                        'name', v_service.display_name,
                        'period_start', v_month.month_start,
                        'period_end', v_month.month_end,
                        'amount_usd_cents', v_amount);
                END LOOP;
            END LOOP;
            RETURN jsonb_build_object(
                'initial', jsonb_build_object(
                    'period_start', v_lease.start_date,
                    'period_end', v_period_end,
                    'due_date', v_due,
                    'rent_usd_cents', v_rent,
                    'service_lines', v_lines,
                    'total_usd_cents', v_total,
                    'problem', v_problem,
                    'invoice_id', (
                        SELECT invoice.id FROM app.invoices AS invoice
                        WHERE invoice.lease_id = p_lease_id AND invoice.rent_billing_kind = 'INITIAL'
                          AND invoice.status <> 'VOID'
                        ORDER BY invoice.id LIMIT 1)),
                'planned_security_deposit_usd_cents', app.lease_planned_security_deposit(p_lease_id));
        END $$;
        """
    )
    for signature in SIGNATURES:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC, prm_runtime, prm_bootstrap")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("V1-060 sign-with-payment migration is forward-only")
