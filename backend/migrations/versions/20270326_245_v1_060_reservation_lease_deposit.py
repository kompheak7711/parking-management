# ruff: noqa: E501
"""A Lease from a Reservation may change its Security Deposit on the draft (V1-060 B6; DL-101).

Revision ID: 20270326_245
Revises: 20270325_244
Create Date: 2026-10-27

Owner rule of 2026-10-27 (DL-101, amending DL-100): the Security Deposit amount is a Lease term like
the monthly Rent, written on the Lease before any money comes in, so every draft Lease records and
shows it. A Lease from a Reservation starts at the Reservation's Security Deposit amount and staff
may change it on the draft with a reason; it can never be less than the money already received into
that Security Deposit. Nothing on the Reservation's Security Deposit changes until the Lease is
signed: Sign Lease then records the new required amount and receives the rest. A renewal still
keeps the Security Deposit it carries.

- app.set_lease_planned_security_deposit (same signature, still `leases.draft`) now keeps an amount
  for a draft from a Reservation too (even the Reservation's own amount, so the draft records its
  term): refused when it is less than the money received into the Reservation's Security Deposit.
- New app.lease_held_security_deposit_id (internal, no grant): the Security Deposit a Lease takes
  over, from its draft command (the Reservation's) or the Reservation that names it as its Lease.
- New app.lease_held_security_deposit (STABLE, SECURITY DEFINER, EXECUTE to prm_runtime): that
  Security Deposit's id, required amount and money received, or NULL.
- New app.apply_lease_planned_security_deposit (SECURITY DEFINER, EXECUTE to prm_financial; the
  API checks `leases.sign` first): once the Lease is SIGNED, records the draft's amount as one
  INCREASE or DECREASE of the required amount (app.deposit_required_amount_adjustments, effective
  the business date) with the draft's reason and the `lease.security_deposit.applied` audit event.
  At most once per Lease; the same adjustment id replays; nothing when there is no planned amount
  or it already equals the required amount; refused when the amount is less than the money
  received.

No table or column change; the table comment names DL-101.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270326_245"
down_revision: str | None = "20270325_244"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        COMMENT ON TABLE app.lease_planned_security_deposits IS
            'The Security Deposit a draft Lease will take at signing (DL-100, DL-101); latest row wins';

        CREATE FUNCTION app.lease_held_security_deposit_id(p_lease_id uuid) RETURNS uuid
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT coalesce(
                (SELECT (command.result_snapshot->>'security_deposit_id')::uuid
                 FROM app.lease_commands AS command
                 WHERE command.lease_id = p_lease_id AND command.action = 'lease.draft'
                   AND command.result_snapshot->>'security_deposit_id' IS NOT NULL
                 ORDER BY command.event_id LIMIT 1),
                (SELECT deposit.id FROM app.deposits AS deposit
                 JOIN app.reservations AS reservation ON reservation.id = deposit.reservation_id
                 WHERE reservation.resulting_lease_id = p_lease_id
                   AND deposit.deposit_type = 'SECURITY'
                 ORDER BY deposit.id LIMIT 1))
        $$;
        REVOKE ALL ON FUNCTION app.lease_held_security_deposit_id(uuid) FROM PUBLIC;

        CREATE FUNCTION app.lease_held_security_deposit(p_property_id uuid, p_lease_id uuid)
        RETURNS jsonb
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_deposit uuid;
            v_snapshot jsonb;
        BEGIN
            PERFORM 1 FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            v_deposit := app.lease_held_security_deposit_id(p_lease_id);
            IF v_deposit IS NULL THEN RETURN NULL; END IF;
            v_snapshot := app.deposit_snapshot(v_deposit);
            RETURN jsonb_build_object(
                'deposit_id', v_deposit,
                'required_usd_cents', (v_snapshot->>'required_usd_cents')::bigint,
                'received_usd_cents', (v_snapshot->>'received_usd_cents')::bigint);
        END $$;

        CREATE OR REPLACE FUNCTION app.set_lease_planned_security_deposit(
            p_property_id uuid, p_lease_id uuid, p_id uuid, p_actor_id uuid,
            p_required_usd_cents bigint, p_reason text, p_authorization_reference text
        ) RETURNS bigint
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_lease app.leases%ROWTYPE;
            v_timezone text;
            v_before bigint;
            v_held uuid;
            v_snapshot jsonb;
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
            IF v_lease.predecessor_lease_id IS NOT NULL THEN
                RAISE EXCEPTION 'A renewal Lease keeps the Security Deposit it carries'
                    USING ERRCODE = '55000';
            END IF;
            -- DL-101: a draft from a Reservation never goes below the money already received into
            -- the Reservation's Security Deposit. Its amount is a Lease term like the Rent, so the
            -- draft records it even when it equals the Reservation's amount.
            v_held := app.lease_held_security_deposit_id(p_lease_id);
            IF v_held IS NOT NULL THEN
                v_snapshot := app.deposit_snapshot(v_held);
                IF p_required_usd_cents < (v_snapshot->>'received_usd_cents')::bigint THEN
                    RAISE EXCEPTION 'The Security Deposit cannot be less than the money already received'
                        USING ERRCODE = '23514';
                END IF;
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

        CREATE FUNCTION app.apply_lease_planned_security_deposit(
            p_property_id uuid, p_lease_id uuid, p_adjustment_id uuid, p_actor_id uuid,
            p_authorization_reference text
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_lease app.leases%ROWTYPE;
            v_deposit uuid;
            v_planned bigint;
            v_reason text;
            v_snapshot jsonb;
            v_required bigint;
            v_received bigint;
            v_timezone text;
            v_now timestamptz := clock_timestamp();
            v_audit uuid := gen_random_uuid();
        BEGIN
            IF p_property_id IS NULL OR p_lease_id IS NULL OR p_actor_id IS NULL
                OR p_adjustment_id IS NULL
                OR p_adjustment_id = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_authorization_reference IS DISTINCT FROM 'leases.sign'
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
            v_deposit := app.lease_held_security_deposit_id(p_lease_id);
            -- The same adjustment again is a replay; another adjustment id is never reused.
            IF EXISTS (SELECT 1 FROM app.deposit_required_amount_adjustments WHERE id = p_adjustment_id)
            THEN
                IF NOT EXISTS (
                    SELECT 1 FROM app.deposit_required_amount_adjustments AS adjustment
                    WHERE adjustment.id = p_adjustment_id
                      AND adjustment.deposit_id IS NOT DISTINCT FROM v_deposit)
                THEN
                    RAISE EXCEPTION 'Planned Security Deposit evidence is invalid' USING ERRCODE = '22023';
                END IF;
                v_snapshot := app.deposit_snapshot(v_deposit);
                RETURN jsonb_build_object('changed', true,
                    'required_usd_cents', (v_snapshot->>'required_usd_cents')::bigint);
            END IF;
            IF v_lease.status <> 'SIGNED' THEN
                RAISE EXCEPTION 'Sign the Lease before its Security Deposit changes'
                    USING ERRCODE = '55000';
            END IF;
            v_planned := app.lease_planned_security_deposit(p_lease_id);
            IF v_deposit IS NULL OR v_planned IS NULL THEN
                RETURN jsonb_build_object('changed', false, 'required_usd_cents', NULL);
            END IF;
            PERFORM 1 FROM app.deposits WHERE id = v_deposit FOR UPDATE;
            v_snapshot := app.deposit_snapshot(v_deposit);
            v_required := (v_snapshot->>'required_usd_cents')::bigint;
            v_received := (v_snapshot->>'received_usd_cents')::bigint;
            -- At most once per Lease: a later change of the required amount is not undone.
            IF v_planned = v_required OR EXISTS (
                SELECT 1 FROM app.audit_events AS event
                WHERE event.lease_id = p_lease_id AND event.action = 'lease.security_deposit.applied')
            THEN
                RETURN jsonb_build_object('changed', false, 'required_usd_cents', v_required);
            END IF;
            IF v_planned < v_received THEN
                RAISE EXCEPTION 'The Security Deposit cannot be less than the money already received'
                    USING ERRCODE = '23514';
            END IF;
            SELECT planned.reason INTO v_reason FROM app.lease_planned_security_deposits AS planned
            WHERE planned.lease_id = p_lease_id
            ORDER BY planned.recorded_at DESC, planned.id DESC LIMIT 1;
            SELECT property.timezone_name INTO v_timezone
            FROM app.properties AS property WHERE property.id = p_property_id;
            INSERT INTO app.audit_events(id, occurred_at, business_date, actor_id, action,
                entity_type, entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                authorization_evidence, customer_id, lease_id, unit_id)
            VALUES (v_audit, v_now, timezone(v_timezone, v_now)::date, p_actor_id,
                'lease.security_deposit.applied', 'deposit_required_amount_adjustment',
                p_adjustment_id, v_reason, p_authorization_reference, p_property_id,
                jsonb_build_object('required_usd_cents', v_required),
                jsonb_build_object('required_usd_cents', v_planned),
                p_adjustment_id, 'API', 'SUCCEEDED',
                jsonb_build_object('capability', p_authorization_reference, 'lease_id', p_lease_id,
                    'deposit_id', v_deposit),
                v_lease.primary_tenant_id, p_lease_id, v_lease.unit_id);
            INSERT INTO app.deposit_required_amount_adjustments(id, deposit_id, adjustment_type,
                amount_usd_cents, effective_date, reason, occurred_at, actor_id,
                authorization_reference)
            VALUES (p_adjustment_id, v_deposit,
                CASE WHEN v_planned > v_required THEN 'INCREASE' ELSE 'DECREASE' END,
                abs(v_planned - v_required), timezone(v_timezone, v_now)::date, v_reason, v_now,
                p_actor_id, p_authorization_reference);
            RETURN jsonb_build_object('changed', true, 'required_usd_cents', v_planned);
        END $$;
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.lease_held_security_deposit(uuid, uuid) "
        "FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.lease_held_security_deposit(uuid, uuid) TO prm_runtime"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.apply_lease_planned_security_deposit(uuid, uuid, uuid, uuid, text) "
        "FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.apply_lease_planned_security_deposit(uuid, uuid, uuid, uuid, text) "
        "TO prm_financial"
    )


def downgrade() -> None:
    raise RuntimeError("V1-060 Reservation Lease deposit migration is forward-only")
