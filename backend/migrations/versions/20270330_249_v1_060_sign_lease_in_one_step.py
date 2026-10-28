# ruff: noqa: E501
"""Sign Lease and its money in one database transaction (V1-060 B7; DL-108).

Revision ID: 20270330_249
Revises: 20270329_248
Create Date: 2026-10-28

Owner rules of 2026-10-27 (DL-100, DL-101): Sign Lease first receives the full money due at
signing, the rest of the Security Deposit and the Initial Rent Invoice; the Lease is signed only
after that money is saved; the Security Deposit amount is a Lease term recorded on the draft.
AGENTS.md: database transactions for multi-step financial operations. The final review of the
V1-060 test-session fixes (2026-10-28) found that the screen saved each step as its own request:
after a lost answer or a change by someone else, the money could be taken twice, or a Lease could
stay signed without its Initial Rent Invoice; and the money paid the Customer's oldest Invoices
first instead of the Initial Rent Invoice.

1. app.lease_signing_payment_commands: one append-only row per command (Property, actor, key) with
   the request digest, the Lease, the Payment, the Initial Rent Invoice and the exact response, so a
   retry with the same key gets the same answer and a different request with the same key is
   refused. A Lease is signed with its money at most once (lease_id UNIQUE).
2. app.sign_lease_with_payment(...), in one transaction, at the Lease version the screen showed:
   - works out the money due at signing: the Initial Rent Invoice as app.lease_signing_preview
     reads it, and the Security Deposit: the draft's amount (DL-101), or the Reservation's when the
     draft has none, less the money already received; nothing for a renewal, which keeps its
     Security Deposit (DL-066). Before anything is saved it refuses a walk-in draft without its
     Security Deposit, an amount below the money already received, a Service that covers only
     part of a month or has no rate, an Initial Rent Due Date that has passed, Signers other than
     the Lease's unsigned Signers, and a Payment amount that is not exactly the total;
   - confirms the Payment with its Receipt (app.confirm_usd_payment): the Primary Tenant's own
     money with nothing named on it;
   - records each Signer's signature and signs the Lease, completing the Primary Tenant's active
     Reservation of the Unit (app.record_lease_signature, app.sign_lease_with_reservation);
   - applies the draft's Security Deposit to the Reservation's (app.apply_lease_planned_security_deposit);
   - makes the Initial Rent Invoice as billing makes every Rent Invoice
     (app.generate_rent_service_invoice);
   - pays it with the Payment by name, line by line in the proposal's line order (Rent, then
     Services, then the rest) (app.post_payment_allocations, DESIGNATED);
   - makes a walk-in Lease's Security Deposit at the draft's amount and receives the rest of the
     money into the Security Deposit (app.create_lease_security_deposit,
     app.record_lease_deposit_receipt); nothing is left on the Payment.
   Every step keeps its own checks. Any refusal or failure saves nothing.
3. app.set_lease_planned_security_deposit (same signature): a save identity used again with
   another Lease, amount or reason is refused instead of answering the stored amount.

Additive only: one new table and one new function; one function replaced with the same signature.
SECURITY DEFINER functions with a fixed search_path; the new function is EXECUTE to prm_financial
only (the API checks leases.sign, payments.record and payments.allocate first, and deposits.manage
for a walk-in Lease's Security Deposit).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270330_249"
down_revision: str | None = "20270329_248"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIGN = "app.sign_lease_with_payment(uuid,uuid,uuid,text,uuid,integer,uuid[],text,jsonb,boolean)"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE app.lease_signing_payment_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL
                CHECK (idempotency_key <> '00000000-0000-0000-0000-000000000000'::uuid),
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            lease_id uuid NOT NULL UNIQUE REFERENCES app.leases(id) ON DELETE RESTRICT,
            payment_id uuid NOT NULL UNIQUE REFERENCES app.payments(id) ON DELETE RESTRICT,
            invoice_id uuid NOT NULL UNIQUE REFERENCES app.invoices(id) ON DELETE RESTRICT,
            response jsonb NOT NULL CHECK (jsonb_typeof(response) = 'object'),
            recorded_at timestamptz NOT NULL CHECK (isfinite(recorded_at)),
            PRIMARY KEY (property_id, actor_id, idempotency_key)
        );
        COMMENT ON TABLE app.lease_signing_payment_commands IS
            'V1-060 B7 (DL-108): one Sign Lease command (the money, the signatures, the signing, the Initial Rent Invoice and the Security Deposit in one transaction) and its exact response.';
        CREATE TRIGGER lease_signing_payment_commands_immutable
            BEFORE UPDATE OR DELETE ON app.lease_signing_payment_commands
            FOR EACH ROW EXECUTE FUNCTION app.reject_invoice_append_only_mutation();
        CREATE TRIGGER lease_signing_payment_commands_no_truncate
            BEFORE TRUNCATE ON app.lease_signing_payment_commands
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_invoice_append_only_mutation();
        REVOKE ALL ON app.lease_signing_payment_commands
            FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap;

        CREATE FUNCTION app.sign_lease_with_payment(
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
            ORDER BY reservation.id LIMIT 1;
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

        CREATE OR REPLACE FUNCTION app.set_lease_planned_security_deposit(
            p_property_id uuid, p_lease_id uuid, p_id uuid, p_actor_id uuid,
            p_required_usd_cents bigint, p_reason text, p_authorization_reference text
        ) RETURNS bigint
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_lease app.leases%ROWTYPE;
            v_saved app.lease_planned_security_deposits%ROWTYPE;
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
            -- The same identity again is a replay of a save already made, and only of the same
            -- save (review of 2026-10-28): another Lease, amount or reason is refused.
            SELECT planned.* INTO v_saved FROM app.lease_planned_security_deposits AS planned
            WHERE planned.id = p_id;
            IF FOUND THEN
                IF v_saved.property_id <> p_property_id OR v_saved.lease_id <> p_lease_id
                    OR v_saved.required_usd_cents <> p_required_usd_cents
                    OR v_saved.reason <> p_reason
                THEN
                    RAISE EXCEPTION 'This Security Deposit save was already used for another amount'
                        USING ERRCODE = '23505';
                END IF;
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
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {SIGN} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGN} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("V1-060 Sign Lease in one step migration is forward-only")
