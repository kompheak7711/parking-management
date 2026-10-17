# ruff: noqa: E501
"""The receipt writer for an existing Deposit of a Lease (V1-056 sub-slice 10e-2b-4b-2b).

BR-DEP-002, BR-DEP-004, BR-DEP-005, BR-DEP-006, BR-DEP-010, BR-SETTLE-012, BR-SETTLE-013; DB-DEP-002;
owner answer to Q-2026-10-12-92: staff record a Deposit receipt under `payments.allocate`, with no
draft and no `financial.approve`; it is refused once the Lease's Final Settlement is closed.

- New app.record_lease_deposit_receipt (SECURITY DEFINER, EXECUTE only to the financial role, as
  the other Deposit commands the Deposit service calls): a receipt from a RECEIVED Payment into an
  existing Deposit of a signed or terminated Lease, a Pet Deposit or a later Security Deposit
  receipt. The input comes first (22023); then the idempotency lock and the replay of an exact
  repeat (action `deposit.receipt.record`; a reused key with another body 23505); then READ
  COMMITTED (55000), an active financial actor (app.assert_active_financial_actor; the service
  checks the actor's Property scope and payments.allocate), and the locks in the order of the
  receipt's insert triggers: the Payment (its serialization guard, then the row), then the Deposit
  (`app.serialize_deposit_state`). P0002 for a Payment or Deposit not of the Property.
- Refused after the locks, in this order: a Deposit with no Lease (55000; a Reservation's Deposit
  before signing waits for sub-slice 10e-2b-4c); a closed Final Settlement of the Deposit's Lease
  (P5S01, the 8e-1 message, for both Deposit types; read after the Deposit lock, which the closing
  confirm also takes, so at READ COMMITTED a closure committed while this writer waited is read);
  a Lease that is not SIGNED or TERMINATED (55000); an active forfeiture of the Deposit (55000,
  staff reverse the forfeiture first; the receipt correction's rule of Q-2026-10-11-83 point 3); a
  Payment confirmed for an Invoice or a Late-payment Charge (55000; review round 1, security: such
  a Payment's value is allocated only to its identified target, BR-PAY-024 and BR-PAY-026, as the
  allocation check requires; what is left after that target may become Credit or a Refund, never a
  Deposit receipt, so the whole Payment is refused, Q-2026-10-18-128).
- The receipt's time is the database's: the later of the clock and one microsecond after the
  Deposit's latest balance event (owner answer to Q-2026-10-14-112). Every table check still runs:
  the Payment source (RECEIVED, after its confirmation, the same Property, the Deposit's Customer
  or, for a third-party Payment, the Deposit's Lease, within the Payment's available value), one
  active receipt per Payment, a Security Deposit's first receipt equal to the accepted amount,
  within the required amount, not before the acceptance or the pet approval.
- It writes the receipt, the `deposit.receipt.recorded` Deposit audit event (its id the receipt's,
  its correlation the idempotency key) and the command record. Result: the Deposit snapshot with
  the receipt id, the Payment, the amount, the time and the Payment's available value.

Relaxing change: `deposit_commands_action_check` also allows `deposit.receipt.record`. No other
function, table, trigger or grant changes.
"""

from alembic import op

revision = "20261228_154"
down_revision = "20261227_153"
branch_labels = None
depends_on = None

SQL = r"""
    ALTER TABLE app.deposit_commands
        DROP CONSTRAINT deposit_commands_action_check,
        ADD CONSTRAINT deposit_commands_action_check CHECK (action IN (
            'deposit.pet.create', 'deposit.required.adjust', 'deposit.receipt.reverse',
            'deposit.disposition.record', 'deposit.disposition.reverse',
            'deposit.pet_refund.qualify', 'deposit.pet_departure.record',
            'deposit.pet_refund.review', 'deposit.reservation_disposition.correct',
            'deposit.receipt.record'
        ));

    -- Sub-slice 10e-2b-4b-2b (owner answer to Q-2026-10-12-92): a receipt into an existing
    -- Deposit of a signed or terminated Lease, recorded under payments.allocate.
    CREATE FUNCTION app.record_lease_deposit_receipt(p_property_id uuid, p_actor_id uuid,
        p_idempotency_key uuid, p_request_digest text, p_receipt_id uuid, p_deposit_id uuid,
        p_payment_id uuid, p_amount_usd_cents bigint, p_reason text,
        p_authorization_reference text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
    SET search_path=pg_catalog SET "TimeZone" TO 'UTC' AS $$
        DECLARE v_result jsonb; v_deposit app.deposits%ROWTYPE; v_status text; v_at timestamptz;
        BEGIN
            IF p_property_id IS NULL OR p_actor_id IS NULL OR p_idempotency_key IS NULL
                OR p_receipt_id IS NULL OR p_deposit_id IS NULL OR p_payment_id IS NULL
                OR '00000000-0000-0000-0000-000000000000'::uuid IN (p_property_id,p_actor_id,
                    p_idempotency_key,p_receipt_id,p_deposit_id,p_payment_id)
                OR p_authorization_reference IS DISTINCT FROM 'payments.allocate'
                OR p_request_digest IS NULL OR p_request_digest !~ '^[0-9a-f]{64}$'
                OR p_amount_usd_cents IS NULL OR p_amount_usd_cents <= 0
                OR p_reason IS NULL OR btrim(p_reason) = '' OR p_reason <> btrim(p_reason)
                OR length(p_reason) > 1000
            THEN RAISE EXCEPTION 'Deposit receipt evidence is invalid' USING ERRCODE='22023'; END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                p_property_id::text || ':' || p_actor_id::text ||
                '-deposit.receipt.record-' || p_idempotency_key::text, 0));
            v_result := app.replay_deposit_command(p_property_id,p_actor_id,
                'deposit.receipt.record',p_idempotency_key,p_request_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
                RAISE EXCEPTION 'A Deposit receipt is recorded at READ COMMITTED'
                    USING ERRCODE='55000'; END IF;
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            -- Lock order of the receipt's insert triggers: the Payment (its guard, then the row),
            -- then the Deposit (its row and guard).
            IF NOT EXISTS(SELECT 1 FROM app.payments payment
                WHERE payment.id=p_payment_id AND payment.property_id=p_property_id)
            THEN RAISE EXCEPTION 'Payment was not found' USING ERRCODE='P0002'; END IF;
            PERFORM app.serialize_payment_state(p_payment_id);
            PERFORM 1 FROM app.payments WHERE id=p_payment_id FOR UPDATE;
            IF app.deposit_property_id(p_deposit_id) IS DISTINCT FROM p_property_id
            THEN RAISE EXCEPTION 'Deposit was not found' USING ERRCODE='P0002'; END IF;
            PERFORM app.serialize_deposit_state(p_deposit_id);
            SELECT * INTO STRICT v_deposit FROM app.deposits WHERE id=p_deposit_id;
            IF v_deposit.lease_id IS NULL THEN
                RAISE EXCEPTION 'The Deposit has no Lease yet; this receipt is not recorded here'
                    USING ERRCODE='55000'; END IF;
            -- Read after the Deposit lock: the closing confirm also locks every Deposit of the
            -- Lease, so a closure committed while this writer waited is read here.
            IF EXISTS(SELECT 1 FROM app.final_settlements settlement
                WHERE settlement.lease_id=v_deposit.lease_id AND settlement.closed_at IS NOT NULL)
            THEN RAISE EXCEPTION 'A closed Final Settlement changes only through a post-settlement correction'
                USING ERRCODE='P5S01'; END IF;
            SELECT lease.status INTO v_status FROM app.leases lease WHERE lease.id=v_deposit.lease_id;
            IF v_status IS NULL OR v_status NOT IN ('SIGNED','TERMINATED') THEN
                RAISE EXCEPTION 'The Deposit''s Lease is not signed' USING ERRCODE='55000'; END IF;
            IF EXISTS(SELECT 1 FROM app.deposit_dispositions disposition
                WHERE disposition.deposit_id=p_deposit_id
                  AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal
                      WHERE reversal.deposit_disposition_id=disposition.id))
            THEN RAISE EXCEPTION 'The Deposit has an active forfeiture; reverse the forfeiture first'
                USING ERRCODE='55000'; END IF;
            -- Review round 1 (security): a Payment confirmed for an Invoice or a Late-payment
            -- Charge is allocated only there (BR-PAY-024, BR-PAY-026; the allocation check refuses
            -- any other target), and its rest becomes Credit or a Refund, never a Deposit receipt
            -- (the whole Payment is refused; Q-2026-10-18-128).
            IF EXISTS(SELECT 1 FROM app.payments payment WHERE payment.id=p_payment_id
                AND (payment.identified_invoice_id IS NOT NULL
                    OR payment.identified_late_payment_charge_id IS NOT NULL))
            THEN RAISE EXCEPTION 'A Payment confirmed for an Invoice or a Late-payment Charge is not a Deposit receipt'
                USING ERRCODE='55000'; END IF;
            v_at := GREATEST(clock_timestamp(),
                COALESCE(app.deposit_balance_latest_at(p_deposit_id),'-infinity')
                    + interval '1 microsecond');
            INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,occurred_at,
                actor_id)
            VALUES (p_receipt_id,p_deposit_id,p_payment_id,p_amount_usd_cents,v_at,p_actor_id);
            PERFORM app.record_deposit_audit(p_receipt_id,'deposit.receipt.recorded',
                'deposit_receipt',p_receipt_id,p_deposit_id,p_reason,p_authorization_reference,
                p_actor_id,p_idempotency_key,app.deposit_resource_snapshot(p_deposit_id));
            v_result := app.deposit_resource_snapshot(p_deposit_id) || jsonb_build_object(
                'deposit_receipt_id',p_receipt_id,'payment_id',p_payment_id,
                'amount_usd_cents',p_amount_usd_cents,'occurred_at',v_at,
                'payment_available_usd_cents',app.payment_available_value(p_payment_id));
            PERFORM app.record_deposit_command(p_property_id,p_actor_id,'deposit.receipt.record',
                p_idempotency_key,p_request_digest,p_deposit_id,p_reason,p_authorization_reference,
                v_result);
            RETURN v_result;
        END;
    $$;
"""

GRANTED = ("app.record_lease_deposit_receipt(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,text,text)",)


def upgrade() -> None:
    op.execute(SQL)
    for function in GRANTED:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Lease Deposit receipt writer migration is forward-only")
