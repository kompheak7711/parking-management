# ruff: noqa: E501
"""Sign Lease refuses a draft whose Reservation ended (V1-060 B7 second review; DL-109).

Revision ID: 20270331_250
Revises: 20270330_249
Create Date: 2026-10-28

The second review of DL-108 (2026-10-28) found that a draft Lease made from a Reservation that
later ended (cancelled, or expired, which DL-004 turns into cancelled) was still signed by
app.sign_lease_with_payment: as a walk-in, with no Security Deposit, while the command changed the
ended Reservation's Security Deposit. DL-100 says a Lease from a Reservation keeps the
Reservation's Security Deposit; DL-009 keeps an ended Reservation's Security Deposit for its own
outcome (forfeit or refund).

app.sign_lease_with_payment (same signature) now, before any money:
- locks the Unit, then the Primary Tenant's active Reservation of the Unit and the Security Deposit
  the draft names, in the order the Lease commands lock them (the Lease, the Unit, the
  Reservation, the Deposit), so the amount due is read from locked rows;
- refuses ('Reservation cannot be completed by this signing') a draft that is not a renewal when
  the Security Deposit it names is not held for that active Reservation: the Reservation ended or
  changed (for example a new Reservation of the same Unit). Nothing is saved.
And at the end:
- the planned amount is applied only to the Security Deposit the command charged;
- a Lease that is not a renewal must end with exactly one Security Deposit, received in full;
  otherwise nothing is saved.

Whether such a draft could instead be signed as a walk-in Lease with a new Security Deposit is an
owner decision; until then it is refused. No money rule changes.

Forward-only: one function replaced with the same signature; no table change.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270331_250"
down_revision: str | None = "20270330_249"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIGN = "app.sign_lease_with_payment(uuid,uuid,uuid,text,uuid,integer,uuid[],text,jsonb,boolean)"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION app.sign_lease_with_payment(
            p_property_id uuid, p_actor_id uuid, p_key uuid, p_digest text,
            p_lease_id uuid, p_expected_version integer, p_signer_ids uuid[], p_reason text,
            p_request jsonb, p_may_create_deposit boolean
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog SET timezone = 'UTC' AS $$
        DECLARE
            v_scope text := p_property_id::text || ':' || p_actor_id::text || ':' || p_key::text;
            v_command app.lease_signing_payment_commands%ROWTYPE;
            v_lease app.leases%ROWTYPE;
            v_timezone text;
            v_today date;
            v_unsigned uuid[];
            v_ticked uuid[];
            v_preview jsonb;
            v_initial jsonb;
            v_rent bigint;
            v_planned bigint;
            v_reservation uuid;
            v_held uuid;
            v_held_deposit app.deposits%ROWTYPE;
            v_snapshot jsonb;
            v_required bigint;
            v_received bigint;
            v_deposit bigint := 0;
            v_total bigint;
            v_request jsonb;
            v_confirm jsonb;
            v_payment app.payments%ROWTYPE;
            v_signer uuid;
            v_version integer;
            v_signed_at timestamptz := statement_timestamp();
            v_start date;
            v_invoice jsonb;
            v_invoice_id uuid;
            v_line record;
            v_left bigint;
            v_take bigint;
            v_details jsonb := '[]'::jsonb;
            v_deposit_id uuid;
            v_deposit_receipt uuid;
            v_result jsonb;
        BEGIN
            v_timezone := app.require_invoice_command_actor(p_property_id, p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id, p_property_id);
            IF p_key IS NULL OR p_key = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_digest IS NULL OR p_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Sign Lease command identity is invalid' USING ERRCODE = 'P5302';
            END IF;
            -- Held until the money, the signing, the Invoice, the Security Deposit and the
            -- response commit.
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-sign-payment:' || v_scope, 0));
            SELECT * INTO v_command FROM app.lease_signing_payment_commands
            WHERE property_id = p_property_id AND actor_id = p_actor_id AND idempotency_key = p_key;
            IF FOUND THEN
                IF v_command.request_digest <> p_digest THEN
                    RAISE EXCEPTION 'Sign Lease key reused' USING ERRCODE = 'P5305';
                END IF;
                RETURN v_command.response;
            END IF;
            IF p_lease_id IS NULL OR p_expected_version IS NULL OR p_expected_version < 1
                OR p_signer_ids IS NULL OR cardinality(p_signer_ids) > 100
                OR array_position(p_signer_ids, NULL) IS NOT NULL
                OR (SELECT count(DISTINCT signer) FROM unnest(p_signer_ids) AS signer)
                    <> cardinality(p_signer_ids)
                OR p_reason IS NULL OR p_reason <> btrim(p_reason)
                OR length(p_reason) NOT BETWEEN 1 AND 500
                OR p_may_create_deposit IS NULL
                OR p_request IS NULL OR jsonb_typeof(p_request) <> 'object'
                OR p_request - ARRAY['payment_method_id', 'received_amount_minor', 'received_at',
                    'evidence_reference', 'payer_intent_memo', 'channel_transaction_reference']
                    <> '{}'::jsonb
                OR jsonb_typeof(p_request -> 'received_amount_minor') IS DISTINCT FROM 'number'
            THEN
                RAISE EXCEPTION 'Sign Lease input is invalid' USING ERRCODE = '22023';
            END IF;

            -- The Lease at the version the screen showed, locked until the end.
            SELECT lease.* INTO v_lease FROM app.leases AS lease
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id
            FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            IF v_lease.version <> p_expected_version THEN
                RAISE EXCEPTION 'Lease version is stale' USING ERRCODE = '40001';
            END IF;
            IF v_lease.status <> 'DRAFTED' THEN
                RAISE EXCEPTION 'Only a drafted Lease may be signed' USING ERRCODE = '55000';
            END IF;
            -- The Unit, then the Reservation and its Security Deposit, are locked before anything
            -- is read for the money, in the order the Lease commands lock them: the Lease, the
            -- Unit, the Reservation, the Deposit.
            PERFORM 1 FROM app.units AS unit WHERE unit.id = v_lease.unit_id FOR UPDATE;
            v_today := timezone(v_timezone, clock_timestamp())::date;

            -- The screen's ticks are exactly the Lease's Signers who have not signed yet.
            SELECT coalesce(array_agg(signer.id ORDER BY signer.id), '{}'::uuid[]) INTO v_unsigned
            FROM app.lease_signers AS signer
            WHERE signer.lease_id = p_lease_id AND signer.signed_at IS NULL;
            SELECT coalesce(array_agg(signer ORDER BY signer), '{}'::uuid[]) INTO v_ticked
            FROM unnest(p_signer_ids) AS signer;
            IF v_unsigned <> v_ticked THEN
                RAISE EXCEPTION 'Every Lease signer, including the Primary Tenant, must sign'
                    USING ERRCODE = '23514';
            END IF;

            -- What is due at signing (DL-100): the Initial Rent Invoice as the generator will
            -- make it, then the Security Deposit (DL-101).
            v_preview := app.lease_signing_preview(p_property_id, p_lease_id);
            v_initial := v_preview -> 'initial';
            IF v_initial IS NULL OR jsonb_typeof(v_initial) <> 'object' THEN
                RAISE EXCEPTION 'Lease terms are incomplete' USING ERRCODE = '23514';
            END IF;
            IF v_initial ->> 'problem' IS NOT NULL THEN
                RAISE EXCEPTION 'An Initial Rent Service covers only part of a month or has no rate'
                    USING ERRCODE = '23514';
            END IF;
            IF (v_initial ->> 'due_date')::date < v_today THEN
                RAISE EXCEPTION 'Initial Rent Due Date precedes the issue date; record an authorized Due Date'
                    USING ERRCODE = '22023';
            END IF;
            v_rent := (v_initial ->> 'total_usd_cents')::bigint;
            v_start := (v_initial ->> 'period_start')::date;
            v_planned := app.lease_planned_security_deposit(p_lease_id);
            -- Signing completes the Primary Tenant's active Reservation of the Unit (DL-064).
            SELECT reservation.id INTO v_reservation FROM app.reservations AS reservation
            WHERE reservation.unit_id = v_lease.unit_id
              AND reservation.customer_id = v_lease.primary_tenant_id
              AND reservation.status = 'ACTIVE'
            ORDER BY reservation.id LIMIT 1
            FOR UPDATE OF reservation;
            v_held := app.lease_held_security_deposit_id(p_lease_id);
            IF v_held IS NULL AND v_reservation IS NOT NULL THEN
                SELECT deposit.id INTO v_held FROM app.deposits AS deposit
                WHERE deposit.reservation_id = v_reservation AND deposit.deposit_type = 'SECURITY'
                  AND deposit.lease_id IS NULL
                ORDER BY deposit.id LIMIT 1;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'The Reservation has no Security Deposit' USING ERRCODE = '55000';
                END IF;
            END IF;
            -- A Lease from a Reservation takes that Reservation's Security Deposit (DL-100). The
            -- Security Deposit the draft names must still be held for the Primary Tenant's active
            -- Reservation of this Unit. A Reservation that ended (cancelled, or expired, which
            -- DL-004 cancels) or changed keeps its Security Deposit for its own outcome (DL-009):
            -- the draft is not signed and nothing is saved.
            IF v_lease.predecessor_lease_id IS NULL AND v_held IS NOT NULL THEN
                SELECT deposit.* INTO v_held_deposit FROM app.deposits AS deposit
                WHERE deposit.id = v_held FOR UPDATE;
                IF NOT FOUND OR v_reservation IS NULL
                    OR v_held_deposit.reservation_id IS DISTINCT FROM v_reservation
                    OR v_held_deposit.deposit_type <> 'SECURITY'
                    OR v_held_deposit.lease_id IS NOT NULL
                THEN
                    RAISE EXCEPTION 'Reservation cannot be completed by this signing'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            IF v_lease.predecessor_lease_id IS NOT NULL THEN
                -- A renewal keeps the Security Deposit it carries (DL-066).
                v_deposit := 0;
            ELSIF v_held IS NOT NULL THEN
                v_snapshot := app.deposit_snapshot(v_held);
                v_received := (v_snapshot ->> 'received_usd_cents')::bigint;
                v_required := coalesce(v_planned, (v_snapshot ->> 'required_usd_cents')::bigint);
                IF v_required < v_received THEN
                    RAISE EXCEPTION 'The Security Deposit cannot be less than the money already received'
                        USING ERRCODE = '23514';
                END IF;
                v_deposit := v_required - v_received;
            ELSE
                IF v_planned IS NULL THEN
                    RAISE EXCEPTION 'Record the Security Deposit on the draft first'
                        USING ERRCODE = '55000';
                END IF;
                IF NOT p_may_create_deposit THEN
                    RAISE EXCEPTION 'A walk-in Lease''s Security Deposit needs deposits.manage'
                        USING ERRCODE = '42501';
                END IF;
                v_deposit := v_planned;
            END IF;
            v_total := v_rent + v_deposit;
            IF p_request -> 'received_amount_minor' IS DISTINCT FROM to_jsonb(v_total) THEN
                RAISE EXCEPTION 'The money due at signing changed' USING ERRCODE = 'P4904';
            END IF;

            -- 1. The money: the Primary Tenant's own Payment with its Receipt, nothing named on it.
            -- Its key is derived from this command's key, so it never replays another Payment.
            v_request := p_request || jsonb_build_object(
                'received_currency', 'USD',
                'payer_customer_id', v_lease.primary_tenant_id::text,
                'payment_scope_kind', 'NORMAL_CUSTOMER',
                'lease_id', NULL,
                'identified_invoice_id', NULL,
                'identified_late_payment_charge_id', NULL);
            IF NOT (v_request ? 'payer_intent_memo') THEN
                v_request := v_request || jsonb_build_object('payer_intent_memo', NULL);
            END IF;
            IF NOT (v_request ? 'channel_transaction_reference') THEN
                v_request := v_request || jsonb_build_object('channel_transaction_reference', NULL);
            END IF;
            v_confirm := app.confirm_usd_payment(p_property_id, p_actor_id,
                md5('lease-sign-payment:confirm:' || v_scope)::uuid, v_request);
            SELECT * INTO STRICT v_payment FROM app.payments
            WHERE id = (v_confirm -> 'payment' ->> 'id')::uuid;
            -- Defensive: the derived key is new, so an older Payment can only mean key reuse.
            IF v_payment.confirmed_at < transaction_timestamp() THEN
                RAISE EXCEPTION 'Sign Lease key reused' USING ERRCODE = 'P5305';
            END IF;

            -- 2. The signatures and the signing, with the Lease commands' own checks. Each step
            -- below was written as its own transaction, with the database's deferred checks
            -- waiting until the step's end; app.confirm_usd_payment ended by checking all of them,
            -- so each step starts with them deferred again and checks them all before it returns.
            SET CONSTRAINTS ALL DEFERRED;
            v_version := v_lease.version;
            FOREACH v_signer IN ARRAY v_unsigned LOOP
                v_snapshot := app.record_lease_signature(p_property_id,
                    md5('lease-sign-payment:signer:' || v_signer::text || ':' || v_scope)::uuid,
                    encode(sha256(convert_to('lease-sign-payment:signer:' || v_signer::text || ':'
                        || p_digest, 'UTF8')), 'hex'),
                    gen_random_uuid(), p_lease_id, v_signer, v_version, v_signed_at, p_reason,
                    p_actor_id);
                v_version := (v_snapshot ->> 'version')::integer;
            END LOOP;
            v_snapshot := app.sign_lease_with_reservation(p_property_id,
                md5('lease-sign-payment:sign:' || v_scope)::uuid,
                encode(sha256(convert_to('lease-sign-payment:sign:' || p_digest, 'UTF8')), 'hex'),
                gen_random_uuid(), p_lease_id, v_version, v_signed_at, p_reason, p_actor_id,
                v_reservation);

            -- 3. DL-101: the draft's amount becomes the Reservation deposit's required amount.
            IF v_lease.predecessor_lease_id IS NULL AND v_held IS NOT NULL AND v_planned IS NOT NULL
            THEN
                -- It changes the Security Deposit this command charged, and no other.
                IF app.lease_held_security_deposit_id(p_lease_id) IS DISTINCT FROM v_held THEN
                    RAISE EXCEPTION 'The money due at signing changed' USING ERRCODE = 'P4904';
                END IF;
                SET CONSTRAINTS ALL DEFERRED;
                PERFORM app.apply_lease_planned_security_deposit(p_property_id, p_lease_id,
                    gen_random_uuid(), p_actor_id, 'leases.sign');
            END IF;

            -- 4. The Initial Rent Invoice, made as billing makes every Rent Invoice.
            SET CONSTRAINTS ALL DEFERRED;
            v_invoice := app.generate_rent_service_invoice(p_property_id,
                md5('lease-sign-payment:invoice:' || v_scope)::uuid,
                encode(sha256(convert_to('lease-sign-payment:invoice:' || p_digest, 'UTF8')), 'hex'),
                gen_random_uuid(),
                'RENT-I-' || to_char(v_start, 'YYYYMM') || '-'
                    || left(replace(p_lease_id::text, '-', ''), 12),
                p_lease_id, NULL, 'INITIAL', v_start, clock_timestamp(), p_actor_id, NULL);
            v_invoice_id := (v_invoice ->> 'invoice_id')::uuid;
            IF (v_invoice ->> 'total_usd_cents')::bigint IS DISTINCT FROM v_rent THEN
                RAISE EXCEPTION 'The money due at signing changed' USING ERRCODE = 'P4904';
            END IF;

            -- 5. The money pays the Initial Rent Invoice by name, line by line in the proposal's
            -- line order: Rent, then Services, then the other lines.
            v_left := v_rent;
            FOR v_line IN
                SELECT line.id, app.invoice_line_outstanding(line.id) AS outstanding
                FROM app.invoice_lines AS line WHERE line.invoice_id = v_invoice_id
                ORDER BY CASE line.category WHEN 'RENT' THEN 0 WHEN 'SERVICE_CHARGES' THEN 1 ELSE 2 END,
                    line.line_sequence, line.id
            LOOP
                EXIT WHEN v_left = 0;
                CONTINUE WHEN v_line.outstanding <= 0;
                v_take := LEAST(v_left, v_line.outstanding);
                v_details := v_details || jsonb_build_array(jsonb_build_object(
                    'invoice_line_id', v_line.id, 'amount_usd_cents', v_take));
                v_left := v_left - v_take;
            END LOOP;
            IF v_left > 0 THEN
                RAISE EXCEPTION 'The money due at signing changed' USING ERRCODE = 'P4904';
            END IF;
            PERFORM app.post_payment_allocations(p_property_id, v_payment.id, p_actor_id,
                md5('lease-sign-payment:allocate:' || v_scope)::uuid, p_digest,
                jsonb_build_object('mode', 'DESIGNATED',
                    'designation_reference', 'Sign Lease: the Initial Rent Invoice (DL-100)',
                    'targets', jsonb_build_array(jsonb_build_object('invoice_id', v_invoice_id,
                        'amount_usd_cents', v_rent, 'details', v_details))));

            -- 6. The rest of the money goes into the Security Deposit: a walk-in Lease's is made
            -- at the draft's amount; a Reservation's continues.
            IF v_deposit > 0 THEN
                SET CONSTRAINTS ALL DEFERRED;
                IF v_held IS NULL THEN
                    v_deposit_id := gen_random_uuid();
                    PERFORM app.create_lease_security_deposit(p_property_id, p_actor_id,
                        md5('lease-sign-payment:deposit:' || v_scope)::uuid,
                        encode(sha256(convert_to('lease-sign-payment:deposit:' || p_digest, 'UTF8')), 'hex'),
                        v_deposit_id, p_lease_id, v_deposit,
                        'Security Deposit agreed on the draft Lease, received at signing.',
                        'deposits.manage');
                ELSE
                    v_deposit_id := v_held;
                END IF;
                v_deposit_receipt := gen_random_uuid();
                PERFORM app.record_lease_deposit_receipt(p_property_id, p_actor_id,
                    md5('lease-sign-payment:receipt:' || v_scope)::uuid,
                    encode(sha256(convert_to('lease-sign-payment:receipt:' || p_digest, 'UTF8')), 'hex'),
                    v_deposit_receipt, v_deposit_id, v_payment.id, v_deposit,
                    'Security Deposit received at signing.', 'payments.allocate');
            END IF;
            SET CONSTRAINTS ALL IMMEDIATE;
            -- Nothing waits on the Payment: it paid exactly what was due at signing.
            IF app.payment_available_value(v_payment.id) <> 0 THEN
                RAISE EXCEPTION 'The money due at signing changed' USING ERRCODE = 'P4904';
            END IF;
            -- A Lease that is not a renewal ends with exactly one Security Deposit, received in
            -- full (DL-100).
            IF v_lease.predecessor_lease_id IS NULL AND (
                SELECT count(*) <> 1 OR coalesce(bool_or(
                    (app.deposit_snapshot(deposit.id) ->> 'received_usd_cents')::bigint
                    <> (app.deposit_snapshot(deposit.id) ->> 'required_usd_cents')::bigint), true)
                FROM app.deposits AS deposit
                WHERE deposit.lease_id = p_lease_id AND deposit.deposit_type = 'SECURITY')
            THEN
                RAISE EXCEPTION 'The money due at signing changed' USING ERRCODE = 'P4904';
            END IF;

            v_result := jsonb_build_object(
                'lease_id', p_lease_id,
                'lease_version', (app.lease_snapshot(p_lease_id) ->> 'version')::integer,
                'signed_at', v_signed_at,
                'reservation_id', v_reservation,
                'payment_id', v_payment.id,
                'receipt_id', v_confirm -> 'receipt' ->> 'id',
                'receipt_number', v_confirm -> 'receipt' ->> 'receipt_number',
                'invoice_id', v_invoice_id,
                'invoice_number', (SELECT invoice.invoice_number FROM app.invoices AS invoice
                    WHERE invoice.id = v_invoice_id),
                'rent_usd_cents', v_rent,
                'deposit_usd_cents', v_deposit,
                'total_usd_cents', v_total,
                'deposit_id', v_deposit_id,
                'deposit_receipt_id', v_deposit_receipt);
            INSERT INTO app.lease_signing_payment_commands(property_id, actor_id, idempotency_key,
                request_digest, lease_id, payment_id, invoice_id, response, recorded_at)
            VALUES (p_property_id, p_actor_id, p_key, p_digest, p_lease_id, v_payment.id,
                v_invoice_id, v_result, clock_timestamp());
            RETURN v_result;
        END $$;
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {SIGN} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGN} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("V1-060 Sign Lease reservation check migration is forward-only")
