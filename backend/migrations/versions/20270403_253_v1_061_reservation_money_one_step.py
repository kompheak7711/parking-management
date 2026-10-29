# ruff: noqa: E501
"""Make Reservation and Receive Security Deposit save in one step (V1-061; DL-112).

Revision ID: 20270403_253
Revises: 20270402_252
Create Date: 2026-10-29

Owner bug list of 2026-10-29 ("Bugs first, then V1.1"): Make Reservation and Receive Security
Deposit must save in one step. The screens saved the money first and the Reservation or the
Security Deposit after it, as separate requests, so a lost answer could leave money saved with
nothing holding it. AGENTS.md: database transactions for multi-step financial operations.

1. app.create_reservation_with_payment(...), in one transaction:
   - confirms the Payment and its Receipt, the Customer's own money (app.confirm_usd_payment);
   - makes the Reservation, which takes its deposit receipt from that Payment
     (app.create_reservation).
2. app.receive_lease_security_deposit_with_payment(...), in one transaction:
   - confirms the Payment and its Receipt, the Primary Tenant's own money;
   - makes a walk-in Lease's Security Deposit when an amount is given
     (app.create_lease_security_deposit);
   - puts the money into the Security Deposit (app.record_lease_deposit_receipt).
Every step keeps its own checks and its own replay by key; the API makes the step keys from the
request's key, so the same request answers the same records and anything else with the key is
refused. Each step was written as its own transaction, so each starts with the deferred checks
deferred, and all of them are checked before the function returns. Any refusal saves nothing.

Additive only: two new functions. SECURITY DEFINER with a fixed search_path; EXECUTE to
prm_financial only (the API checks reservations.create and payments.record, or payments.record,
payments.allocate and, for a new Security Deposit, deposits.manage).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270403_253"
down_revision: str | None = "20270402_252"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RESERVE = (
    "app.create_reservation_with_payment(uuid,uuid,uuid,jsonb,uuid,text,uuid,uuid,uuid,date,"
    "bigint,date,uuid,bigint,text,text,text,jsonb,uuid,bigint,uuid)"
)
RECEIVE = (
    "app.receive_lease_security_deposit_with_payment(uuid,uuid,uuid,jsonb,uuid,text,uuid,uuid,"
    "bigint,text,uuid,text,uuid,bigint)"
)


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION app.create_reservation_with_payment(
            p_property_id uuid, p_actor_id uuid, p_payment_key uuid, p_payment jsonb,
            p_key uuid, p_digest text, p_reservation_id uuid, p_unit_id uuid, p_customer_id uuid,
            p_reservation_date date, p_rent_usd_cents bigint, p_expiration_date date,
            p_acceptance_id uuid, p_accepted_usd_cents bigint, p_acceptance_kind text,
            p_acceptance_reason text, p_authorization_reference text, p_calculation_trace jsonb,
            p_deposit_id uuid, p_required_usd_cents bigint, p_receipt_id uuid
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog SET timezone = 'UTC' AS $$
        DECLARE
            v_confirm jsonb;
            v_payment uuid;
            v_reservation record;
            v_now timestamptz;
        BEGIN
            IF p_payment IS NULL OR jsonb_typeof(p_payment) <> 'object'
                OR p_payment ->> 'payer_customer_id' IS DISTINCT FROM p_customer_id::text
                OR p_payment -> 'received_amount_minor' IS DISTINCT FROM to_jsonb(p_accepted_usd_cents)
            THEN
                RAISE EXCEPTION 'Reservation money is invalid' USING ERRCODE = '22023';
            END IF;
            -- 1. The money: the Customer's own Payment with its Receipt.
            v_confirm := app.confirm_usd_payment(p_property_id, p_actor_id, p_payment_key, p_payment);
            v_payment := (v_confirm -> 'payment' ->> 'id')::uuid;
            -- 2. The Reservation takes its deposit receipt from that Payment. The acceptance and
            -- the receipt share one time, taken after the Payment was confirmed.
            v_now := clock_timestamp();
            SET CONSTRAINTS ALL DEFERRED;
            SELECT * INTO STRICT v_reservation FROM app.create_reservation(
                p_property_id, p_key, p_digest, p_reservation_id, p_unit_id, p_customer_id,
                p_reservation_date, p_rent_usd_cents, p_expiration_date, p_acceptance_id,
                p_accepted_usd_cents, p_acceptance_kind, v_now,
                p_acceptance_reason, p_authorization_reference, p_calculation_trace,
                p_deposit_id, p_required_usd_cents, p_receipt_id, v_payment,
                v_now, p_actor_id);
            SET CONSTRAINTS ALL IMMEDIATE;
            RETURN jsonb_build_object('payment', v_confirm -> 'payment',
                'receipt', v_confirm -> 'receipt', 'reservation', to_jsonb(v_reservation));
        END
        $$;

        CREATE FUNCTION app.receive_lease_security_deposit_with_payment(
            p_property_id uuid, p_actor_id uuid, p_payment_key uuid, p_payment jsonb,
            p_create_key uuid, p_create_digest text, p_deposit_id uuid, p_lease_id uuid,
            p_required_usd_cents bigint, p_reason text, p_receipt_key uuid,
            p_receipt_digest text, p_receipt_id uuid, p_amount_usd_cents bigint
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog SET timezone = 'UTC' AS $$
        DECLARE
            v_tenant uuid;
            v_confirm jsonb;
            v_payment uuid;
            v_receipt jsonb;
        BEGIN
            SELECT lease.primary_tenant_id INTO v_tenant FROM app.leases AS lease
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            IF p_payment IS NULL OR jsonb_typeof(p_payment) <> 'object'
                OR p_payment ->> 'payer_customer_id' IS DISTINCT FROM v_tenant::text
                OR p_payment -> 'received_amount_minor' IS DISTINCT FROM to_jsonb(p_amount_usd_cents)
                OR (p_required_usd_cents IS NULL) <> (p_create_key IS NULL)
            THEN
                RAISE EXCEPTION 'Security Deposit money is invalid' USING ERRCODE = '22023';
            END IF;
            -- 1. The money: the Primary Tenant's own Payment with its Receipt.
            v_confirm := app.confirm_usd_payment(p_property_id, p_actor_id, p_payment_key, p_payment);
            v_payment := (v_confirm -> 'payment' ->> 'id')::uuid;
            -- 2. A walk-in Lease's Security Deposit, when an amount is given.
            IF p_required_usd_cents IS NOT NULL THEN
                SET CONSTRAINTS ALL DEFERRED;
                PERFORM app.create_lease_security_deposit(p_property_id, p_actor_id, p_create_key,
                    p_create_digest, p_deposit_id, p_lease_id, p_required_usd_cents, p_reason,
                    'deposits.manage');
                SET CONSTRAINTS ALL IMMEDIATE;
            END IF;
            -- 3. The money goes into the Security Deposit.
            SET CONSTRAINTS ALL DEFERRED;
            v_receipt := app.record_lease_deposit_receipt(p_property_id, p_actor_id, p_receipt_key,
                p_receipt_digest, p_receipt_id, p_deposit_id, v_payment, p_amount_usd_cents,
                p_reason, 'payments.allocate');
            SET CONSTRAINTS ALL IMMEDIATE;
            RETURN jsonb_build_object('payment', v_confirm -> 'payment',
                'receipt', v_confirm -> 'receipt', 'deposit', v_receipt);
        END
        $$;
        """
    )
    for signature in (RESERVE, RECEIVE):
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Migration 20270403_253 is forward-only")
