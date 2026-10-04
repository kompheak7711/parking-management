# ruff: noqa: E501
"""Reservation Deposit Refunds and forfeitures as drafts (BR-AUTH-010, BR-RES-016, BR-RES-021, BR-RES-022; V1-056 slice 3b).

Owner answers of 2026-10-04 to Q-2026-10-03-2 (docs/010):

- Staff cancellation cancels the Reservation at once and releases the Unit. The Security
  Deposit stays held until a ``financial.approve`` holder confirms the Refund or forfeiture
  draft.
- The expiry worker still expires the Reservation and releases the Unit, but never forfeits.
- Reservation outcome corrections are drafts too.
- Reservation Refunds always go to the Reservation Customer.

Relaxing and additive, with the owner-approved privilege changes (answer to plan Q6): the
outcome-complete check also accepts a cancelled Reservation whose Deposit has no outcome
record yet; new cancel and expire functions record only the lifecycle event; new draft
record and confirm functions; a bounded per-Property read list of Reservations waiting for a
Deposit decision. The financial role loses direct EXECUTE on the atomic cancel, expire and
outcome correction functions, which stay unchanged in the database. No earlier row is read
for change or changed.
"""

from alembic import op

revision = "20261015_80"
down_revision = "20261014_79"
branch_labels = None
depends_on = None

FINANCIAL = (
    "app.cancel_reservation_v3(uuid,uuid,text,uuid,uuid,integer,text,text,boolean,text,text,text,uuid)",
    "app.expire_reservation_v3(uuid,uuid,text,uuid,uuid,integer,boolean,text,uuid)",
    "app.record_reservation_deposit_draft(uuid,uuid,uuid,uuid,text,uuid,text,text,uuid,text,text)",
    "app.record_reservation_deposit_correction_draft(uuid,uuid,uuid,uuid,text,uuid,uuid,uuid,text,text,text,uuid,text,text,text)",
    "app.confirm_reservation_deposit_draft(uuid,uuid,uuid,uuid,text)",
    "app.reject_reservation_deposit_draft(uuid,uuid,uuid,uuid,text,text)",
    "app.withdraw_reservation_deposit_draft(uuid,uuid,uuid,uuid,text,text)",
)
RUNTIME = (
    "app.list_reservations_awaiting_deposit_decision(uuid,uuid,integer,timestamp with time zone,uuid)",
)
INTERNAL = (
    "app.reservation_deposit_has_outcome(uuid)",
    "app.reservation_deposit_draft_scope(uuid,uuid,uuid)",
    "app.reservation_deposit_draft_source(uuid,uuid,text)",
    "app.reservation_deposit_held_cents(uuid)",
)
RETIRED = (
    "app.cancel_reservation_v2(uuid,uuid,text,uuid,uuid,text,uuid,integer,text,text,boolean,text,text,text,text,uuid)",
    "app.expire_reservation_v2(uuid,uuid,text,uuid,uuid,uuid,integer,boolean,text,text,uuid)",
    "app.correct_reservation_deposit_outcome(uuid,uuid,text,uuid,uuid,uuid,text,uuid,integer,text,text,text,text,uuid)",
    "app.correct_reservation_deposit_disposition_v2(uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,integer,text,text,text,text)",
)

LIFECYCLE_RESULT = """
    reservation_id uuid,
    unit_id uuid,
    status text,
    cancellation_reason_code text,
    cancellation_responsibility text,
    effective_expiration_date date,
    version integer,
    unit_status text,
    unit_version integer,
    deposit_id uuid,
    deposit_received_usd_cents bigint,
    deposit_outcome_state text,
    outcome_id uuid,
    refund_number text
"""


def upgrade() -> None:
    op.execute(
        """
        -- True once any outcome record (disposition or Refund) exists for the Deposit, even
        -- when it was later reversed or corrected: from then on the earlier rule applies.
        CREATE FUNCTION app.reservation_deposit_has_outcome(p_deposit_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.deposit_dispositions AS disposition
                WHERE disposition.deposit_id = p_deposit_id
            ) OR EXISTS (
                SELECT 1 FROM app.refunds AS refund
                WHERE refund.source_deposit_id = p_deposit_id
            )
        $$;

        -- The Deposit value still held: received receipts that were not reversed.
        CREATE FUNCTION app.reservation_deposit_held_cents(p_deposit_id uuid)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT COALESCE(sum(receipt.amount_usd_cents), 0)::bigint
            FROM app.deposit_receipts AS receipt
            WHERE receipt.deposit_id = p_deposit_id
              AND NOT EXISTS (
                  SELECT 1 FROM app.deposit_receipt_reversals AS reversal
                  WHERE reversal.deposit_receipt_id = receipt.id
              )
        $$;

        -- Relaxed (owner answer to Q-2026-10-03-2): a cancelled Reservation may wait for its
        -- Deposit decision with no outcome record at all. Once an outcome exists, the earlier
        -- complete-classified-outcome rule applies unchanged.
        CREATE OR REPLACE FUNCTION app.assert_reservation_financial_outcome_complete()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_reservation_id uuid;
            v_responsibility text;
            v_deposit_id uuid;
            v_received bigint;
            v_disposed bigint;
            v_refunded bigint;
        BEGIN
            -- Credit, Payment and Pet Deposit Refunds have no Reservation (revision 41 guard).
            IF TG_TABLE_NAME = 'refunds' THEN
                IF NEW.source_lifecycle_event_id IS NULL THEN RETURN NULL; END IF;
            ELSIF TG_TABLE_NAME = 'refund_corrections' THEN
                IF EXISTS(SELECT 1 FROM app.refunds WHERE id=NEW.refund_id AND source_lifecycle_event_id IS NULL)
                THEN RETURN NULL; END IF;
            END IF;
            IF TG_TABLE_NAME = 'reservations' THEN
                v_reservation_id := NEW.id;
                IF NEW.status <> 'CANCELLED' THEN RETURN NULL; END IF;
            ELSIF TG_TABLE_NAME = 'deposit_dispositions' THEN
                IF NEW.governing_reservation_id IS NULL THEN RETURN NULL; END IF;
                v_reservation_id := NEW.governing_reservation_id;
            ELSIF TG_TABLE_NAME = 'deposit_disposition_reversals' THEN
                SELECT disposition.governing_reservation_id
                INTO v_reservation_id
                FROM app.deposit_dispositions AS disposition
                WHERE disposition.id = NEW.deposit_disposition_id;
                IF v_reservation_id IS NULL THEN RETURN NULL; END IF;
            ELSIF TG_TABLE_NAME = 'refunds' THEN
                SELECT event.reservation_id INTO STRICT v_reservation_id
                FROM app.reservation_lifecycle_events AS event
                WHERE event.id = NEW.source_lifecycle_event_id;
            ELSE
                SELECT event.reservation_id INTO STRICT v_reservation_id
                FROM app.refund_corrections AS correction
                JOIN app.refunds AS refund ON refund.id = correction.refund_id
                JOIN app.reservation_lifecycle_events AS event
                  ON event.id = refund.source_lifecycle_event_id
                WHERE correction.id = NEW.id;
            END IF;

            SELECT reservation.cancellation_responsibility, deposit.id
            INTO STRICT v_responsibility, v_deposit_id
            FROM app.reservations AS reservation
            JOIN app.deposits AS deposit ON deposit.reservation_id = reservation.id
            WHERE reservation.id = v_reservation_id
              AND reservation.status = 'CANCELLED'
            FOR UPDATE OF deposit;

            IF NOT app.reservation_deposit_has_outcome(v_deposit_id) THEN
                RETURN NULL;
            END IF;

            SELECT COALESCE(sum(receipt.amount_usd_cents), 0)::bigint
            INTO v_received
            FROM app.deposit_receipts AS receipt
            WHERE receipt.deposit_id = v_deposit_id
              AND NOT EXISTS (
                  SELECT 1 FROM app.deposit_receipt_reversals AS reversal
                  WHERE reversal.deposit_receipt_id = receipt.id
              );

            SELECT COALESCE(sum(disposition.amount_usd_cents), 0)::bigint
            INTO v_disposed
            FROM app.deposit_dispositions AS disposition
            WHERE disposition.deposit_id = v_deposit_id
              AND NOT EXISTS (
                  SELECT 1 FROM app.deposit_disposition_reversals AS reversal
                  WHERE reversal.deposit_disposition_id = disposition.id
              );

            SELECT COALESCE(sum(
                refund.usd_accounting_value_cents - COALESCE((
                    SELECT sum(correction.source_balance_effect_usd_cents)
                    FROM app.refund_corrections AS correction
                    WHERE correction.refund_id = refund.id
                ), 0)
            ), 0)::bigint
            INTO v_refunded
            FROM app.refunds AS refund
            WHERE refund.source_deposit_id = v_deposit_id;

            IF (v_responsibility = 'CUSTOMER'
                    AND (v_disposed <> v_received OR v_refunded <> 0))
                OR (v_responsibility = 'PROPERTY'
                    AND (v_refunded <> v_received OR v_disposed <> 0))
            THEN
                RAISE EXCEPTION 'Reservation cancellation requires one complete classified Deposit outcome'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$;

        -- Owner answer of 2026-10-04 (Q-2026-10-04-5): a receipt reversal is refused only while
        -- a Reservation Deposit draft is pending, so a confirmed draft never classifies money
        -- that left. Otherwise it works as before. The body is revision 38's plus that check.
        CREATE OR REPLACE FUNCTION app.validate_deposit_receipt_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_deposit_id uuid;
        BEGIN
            SELECT receipt.deposit_id INTO v_deposit_id
            FROM app.deposit_receipts AS receipt WHERE receipt.id=NEW.deposit_receipt_id
            FOR UPDATE OF receipt;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Deposit receipt was not found' USING ERRCODE='23503';
            END IF;
            PERFORM 1 FROM app.deposits WHERE id=v_deposit_id FOR UPDATE;
            IF EXISTS (
                SELECT 1 FROM app.deposit_dispositions AS disposition
                WHERE disposition.deposit_id=v_deposit_id AND NOT EXISTS (
                    SELECT 1 FROM app.deposit_disposition_reversals AS reversal
                    WHERE reversal.deposit_disposition_id=disposition.id)
            ) OR app.deposit_has_unresolved_refund(v_deposit_id)
              OR EXISTS (
                SELECT 1 FROM app.deposits AS deposit
                JOIN app.financial_drafts AS draft
                  ON draft.payload->>'reservation_id' = deposit.reservation_id::text
                 AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE')
                WHERE deposit.id = v_deposit_id
                  AND NOT EXISTS (
                      SELECT 1 FROM app.financial_draft_decisions AS decision
                      WHERE decision.draft_id = draft.id
                  )
            ) THEN
                RAISE EXCEPTION 'Deposit receipt has active dependent financial history' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END $$;

        -- Finds the pending Deposit draft of a Reservation without scanning every draft.
        CREATE INDEX financial_drafts_reservation_deposit_idx
            ON app.financial_drafts ((payload->>'reservation_id'))
            WHERE kind IN ('REFUND','DEPOSIT_FORFEITURE');
        """
    )
    op.execute(
        f"""
        -- Staff cancellation: the lifecycle event and the Unit release only. The Deposit stays
        -- held until a financial.approve holder confirms its Refund or forfeiture draft.
        CREATE FUNCTION app.cancel_reservation_v3(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_event_id uuid,
            p_reservation_id uuid,
            p_expected_version integer,
            p_reason_code text,
            p_responsibility text,
            p_property_could_provide_unit boolean,
            p_reason_memo text,
            p_coordination_reference text,
            p_authorization_reference text,
            p_actor_id uuid
        )
        RETURNS TABLE({LIFECYCLE_RESULT})
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE v_lifecycle record;
        BEGIN
            IF p_authorization_reference IS DISTINCT FROM 'reservations.cancel' THEN
                RAISE EXCEPTION 'Reservation cancellation authorization is invalid'
                    USING ERRCODE = '23514';
            END IF;
            SELECT * INTO STRICT v_lifecycle
            FROM app.cancel_reservation(
                p_property_id, p_idempotency_key, p_request_digest, p_event_id,
                p_reservation_id, p_expected_version, p_reason_code, p_responsibility,
                p_property_could_provide_unit, p_reason_memo, p_coordination_reference,
                p_authorization_reference, p_actor_id
            );
            RETURN QUERY SELECT
                v_lifecycle.reservation_id, v_lifecycle.unit_id, v_lifecycle.status,
                v_lifecycle.cancellation_reason_code, v_lifecycle.cancellation_responsibility,
                v_lifecycle.effective_expiration_date, v_lifecycle.version,
                v_lifecycle.unit_status, v_lifecycle.unit_version, v_lifecycle.deposit_id,
                v_lifecycle.deposit_received_usd_cents,
                -- Only a Deposit that is really held waits for a decision (Q-2026-10-04-5).
                CASE WHEN app.reservation_deposit_held_cents(v_lifecycle.deposit_id) > 0
                    THEN 'AWAITING_DECISION' ELSE 'PENDING_V1_031' END,
                NULL::uuid, NULL::text;
        END;
        $$;

        -- Automatic expiration (BR-RES-016): expire and release the Unit; never forfeit.
        CREATE FUNCTION app.expire_reservation_v3(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_event_id uuid,
            p_reservation_id uuid,
            p_expected_version integer,
            p_property_could_provide_unit boolean,
            p_authorization_reference text,
            p_actor_id uuid
        )
        RETURNS TABLE({LIFECYCLE_RESULT})
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE v_lifecycle record;
        BEGIN
            IF p_authorization_reference IS DISTINCT FROM 'reservations.cancel' THEN
                RAISE EXCEPTION 'Reservation expiration authorization is invalid'
                    USING ERRCODE = '23514';
            END IF;
            SELECT * INTO STRICT v_lifecycle
            FROM app.expire_reservation(
                p_property_id, p_idempotency_key, p_request_digest, p_event_id,
                p_reservation_id, p_expected_version, p_property_could_provide_unit,
                p_authorization_reference, p_actor_id
            );
            RETURN QUERY SELECT
                v_lifecycle.reservation_id, v_lifecycle.unit_id, v_lifecycle.status,
                v_lifecycle.cancellation_reason_code, v_lifecycle.cancellation_responsibility,
                v_lifecycle.effective_expiration_date, v_lifecycle.version,
                v_lifecycle.unit_status, v_lifecycle.unit_version, v_lifecycle.deposit_id,
                v_lifecycle.deposit_received_usd_cents,
                -- Only a Deposit that is really held waits for a decision (Q-2026-10-04-5).
                CASE WHEN app.reservation_deposit_held_cents(v_lifecycle.deposit_id) > 0
                    THEN 'AWAITING_DECISION' ELSE 'PENDING_V1_031' END,
                NULL::uuid, NULL::text;
        END;
        $$;
        """
    )
    op.execute(
        """
        -- Locks the cancelled Reservation and its Deposit and returns the facts a Reservation
        -- Deposit draft is checked against. The draft kind must follow the cancellation
        -- responsibility: Customer-caused gives a forfeiture, Property-caused a Refund.
        CREATE FUNCTION app.reservation_deposit_draft_source(
            p_property_id uuid, p_reservation_id uuid, p_kind text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_reservation app.reservations%ROWTYPE;
            v_deposit_id uuid;
            v_received bigint;
        BEGIN
            SELECT reservation.* INTO v_reservation
            FROM app.reservations AS reservation
            JOIN app.units AS unit ON unit.id = reservation.unit_id
            WHERE reservation.id = p_reservation_id AND unit.property_id = p_property_id
            FOR UPDATE OF reservation;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Reservation was not found in the Property' USING ERRCODE = 'P0002';
            END IF;
            IF v_reservation.status <> 'CANCELLED' THEN
                RAISE EXCEPTION 'Reservation is not cancelled' USING ERRCODE = '23514';
            END IF;
            IF p_kind IS DISTINCT FROM (CASE v_reservation.cancellation_responsibility
                    WHEN 'CUSTOMER' THEN 'DEPOSIT_FORFEITURE'
                    WHEN 'PROPERTY' THEN 'REFUND' END)
            THEN
                RAISE EXCEPTION 'Reservation Deposit decision does not follow the cancellation responsibility'
                    USING ERRCODE = '23514';
            END IF;
            SELECT deposit.id INTO STRICT v_deposit_id
            FROM app.deposits AS deposit
            WHERE deposit.reservation_id = p_reservation_id
            FOR UPDATE OF deposit;
            -- The outcome functions classify every receipt; a corrected receipt has no rule yet.
            IF EXISTS (
                SELECT 1 FROM app.deposit_receipts AS receipt
                JOIN app.deposit_receipt_reversals AS reversal
                  ON reversal.deposit_receipt_id = receipt.id
                WHERE receipt.deposit_id = v_deposit_id
            ) THEN
                RAISE EXCEPTION 'Reservation Deposit has a reversed receipt'
                    USING ERRCODE = '23514';
            END IF;
            SELECT COALESCE(sum(receipt.amount_usd_cents), 0)::bigint INTO v_received
            FROM app.deposit_receipts AS receipt WHERE receipt.deposit_id = v_deposit_id;
            IF v_received <= 0 THEN
                RAISE EXCEPTION 'Reservation Deposit has no received value to classify'
                    USING ERRCODE = '23514';
            END IF;
            RETURN jsonb_build_object(
                'reservation_id', v_reservation.id,
                'reservation_version', v_reservation.version,
                'responsibility', v_reservation.cancellation_responsibility,
                'customer_id', v_reservation.customer_id,
                'deposit_id', v_deposit_id,
                'amount_usd_cents', v_received
            );
        END $$;

        -- A Staff draft of the Deposit decision of a cancelled or expired Reservation
        -- (BR-AUTH-010). Refund drafts carry the Refund number, method and reference note
        -- (BR-REFUND-014); the Refund always goes to the Reservation Customer.
        CREATE FUNCTION app.record_reservation_deposit_draft(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_reservation_id uuid,
            p_kind text, p_outcome_id uuid, p_reason text, p_refund_number text,
            p_refund_method_id uuid, p_reference_note text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_input jsonb; v_source jsonb; v_existing app.financial_drafts%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id, p_property_id);
            IF p_authorization_reference IS DISTINCT FROM (CASE p_kind
                    WHEN 'REFUND' THEN 'reservation_deposits.refund'
                    WHEN 'DEPOSIT_FORFEITURE' THEN 'reservation_deposits.dispose' END)
            THEN
                RAISE EXCEPTION 'Reservation Deposit draft authorization is invalid'
                    USING ERRCODE = '42501';
            END IF;
            IF p_draft_id IS NULL OR p_draft_id = '00000000-0000-0000-0000-000000000000'
                OR p_reservation_id IS NULL
                OR p_outcome_id IS NULL OR p_outcome_id = '00000000-0000-0000-0000-000000000000'
                OR p_outcome_id = p_draft_id
                OR p_reason IS NULL OR p_reason <> btrim(p_reason)
                OR length(p_reason) NOT BETWEEN 1 AND 1000
                OR (p_kind = 'REFUND' AND (
                    p_refund_number IS NULL OR p_refund_number <> btrim(p_refund_number)
                    OR length(p_refund_number) NOT BETWEEN 1 AND 128
                    OR p_refund_method_id IS NULL
                    OR p_reference_note IS NULL OR p_reference_note <> btrim(p_reference_note)
                    OR length(p_reference_note) NOT BETWEEN 1 AND 500))
                OR (p_kind = 'DEPOSIT_FORFEITURE' AND (
                    p_refund_number IS NOT NULL OR p_refund_method_id IS NOT NULL
                    OR p_reference_note IS NOT NULL))
            THEN
                RAISE EXCEPTION 'Reservation Deposit draft input is invalid' USING ERRCODE = '22023';
            END IF;
            v_input := jsonb_strip_nulls(jsonb_build_object(
                'variant', 'RESERVATION_OUTCOME', 'reservation_id', p_reservation_id,
                'outcome_id', p_outcome_id, 'reason', p_reason,
                'refund_number', p_refund_number, 'refund_method_id', p_refund_method_id,
                'reference_note', p_reference_note
            ));
            -- An exact repeat replays before any current-state check.
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft_id::text, 0));
            SELECT * INTO v_existing FROM app.financial_drafts WHERE id = p_draft_id;
            IF FOUND THEN
                IF v_existing.property_id = p_property_id AND v_existing.kind = p_kind
                    AND v_existing.prepared_by = p_actor_id
                    AND v_existing.payload - ARRAY[
                        'deposit_id','reservation_version','responsibility','customer_id',
                        'amount_usd_cents'
                    ] = v_input
                THEN RETURN app.financial_draft_json(v_existing); END IF;
                RAISE EXCEPTION 'Reservation Deposit draft identity was reused' USING ERRCODE = 'P5205';
            END IF;
            v_source := app.reservation_deposit_draft_source(p_property_id, p_reservation_id, p_kind);
            IF app.reservation_deposit_has_outcome((v_source->>'deposit_id')::uuid) THEN
                RAISE EXCEPTION 'Reservation Deposit decision is already recorded'
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                SELECT 1 FROM app.financial_drafts AS draft
                WHERE draft.property_id = p_property_id
                  AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE')
                  AND draft.payload->>'reservation_id' = p_reservation_id::text
                  AND NOT EXISTS (
                      SELECT 1 FROM app.financial_draft_decisions AS decision
                      WHERE decision.draft_id = draft.id
                  )
            ) THEN
                RAISE EXCEPTION 'A Deposit draft for this Reservation is already waiting'
                    USING ERRCODE = '55000';
            END IF;
            IF p_kind = 'REFUND' THEN
                PERFORM 1 FROM app.refund_methods WHERE id = p_refund_method_id AND active;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE = '22023';
                END IF;
                IF EXISTS (SELECT 1 FROM app.refunds WHERE refund_number = p_refund_number) THEN
                    RAISE EXCEPTION 'Refund number is already used' USING ERRCODE = '23505';
                END IF;
            END IF;
            RETURN app.insert_financial_draft(
                p_property_id, p_actor_id, p_draft_id, p_kind, p_authorization_reference,
                v_input || (v_source - 'reservation_id'),
                'deposit-received:' || (v_source->>'amount_usd_cents'), p_reason
            );
        END $$;

        -- A Staff draft that replaces the confirmed outcome of a cancelled Reservation with a
        -- new outcome of the same kind, keeping the original record (reservation_deposits.correct).
        CREATE FUNCTION app.record_reservation_deposit_correction_draft(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_reservation_id uuid,
            p_kind text, p_expected_outcome_id uuid, p_correction_id uuid,
            p_replacement_outcome_id uuid, p_reason text, p_evidence_reference text,
            p_refund_number text, p_refund_method_id uuid, p_reference_note text,
            p_correction_authorization_reference text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_input jsonb; v_source jsonb; v_existing app.financial_drafts%ROWTYPE;
            v_active uuid;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id, p_property_id);
            IF p_correction_authorization_reference IS DISTINCT FROM 'reservation_deposits.correct'
                OR p_authorization_reference IS DISTINCT FROM (CASE p_kind
                    WHEN 'REFUND' THEN 'reservation_deposits.refund'
                    WHEN 'DEPOSIT_FORFEITURE' THEN 'reservation_deposits.dispose' END)
            THEN
                RAISE EXCEPTION 'Reservation Deposit correction draft authorization is invalid'
                    USING ERRCODE = '42501';
            END IF;
            IF p_draft_id IS NULL OR p_draft_id = '00000000-0000-0000-0000-000000000000'
                OR p_reservation_id IS NULL
                OR p_expected_outcome_id IS NULL
                OR p_expected_outcome_id = '00000000-0000-0000-0000-000000000000'
                OR p_correction_id IS NULL
                OR p_correction_id = '00000000-0000-0000-0000-000000000000'
                OR p_replacement_outcome_id IS NULL
                OR p_replacement_outcome_id = '00000000-0000-0000-0000-000000000000'
                OR p_correction_id = p_replacement_outcome_id
                OR p_draft_id IN (p_correction_id, p_replacement_outcome_id)
                OR p_reason IS NULL OR p_reason <> btrim(p_reason)
                OR length(p_reason) NOT BETWEEN 1 AND 1000
                OR p_evidence_reference IS NULL
                OR p_evidence_reference <> btrim(p_evidence_reference)
                OR length(p_evidence_reference) NOT BETWEEN 1 AND 500
                OR (p_kind = 'REFUND' AND (
                    p_refund_number IS NULL OR p_refund_number <> btrim(p_refund_number)
                    OR length(p_refund_number) NOT BETWEEN 1 AND 128
                    OR p_refund_method_id IS NULL
                    OR p_reference_note IS NULL OR p_reference_note <> btrim(p_reference_note)
                    OR length(p_reference_note) NOT BETWEEN 1 AND 500))
                OR (p_kind = 'DEPOSIT_FORFEITURE' AND (
                    p_refund_number IS NOT NULL OR p_refund_method_id IS NOT NULL
                    OR p_reference_note IS NOT NULL))
            THEN
                RAISE EXCEPTION 'Reservation Deposit correction draft input is invalid'
                    USING ERRCODE = '22023';
            END IF;
            v_input := jsonb_strip_nulls(jsonb_build_object(
                'variant', 'RESERVATION_CORRECTION', 'reservation_id', p_reservation_id,
                'expected_outcome_id', p_expected_outcome_id, 'correction_id', p_correction_id,
                'outcome_id', p_replacement_outcome_id, 'reason', p_reason,
                'evidence_reference', p_evidence_reference,
                'refund_number', p_refund_number, 'refund_method_id', p_refund_method_id,
                'reference_note', p_reference_note
            ));
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft_id::text, 0));
            SELECT * INTO v_existing FROM app.financial_drafts WHERE id = p_draft_id;
            IF FOUND THEN
                IF v_existing.property_id = p_property_id AND v_existing.kind = p_kind
                    AND v_existing.prepared_by = p_actor_id
                    AND v_existing.payload - ARRAY[
                        'deposit_id','reservation_version','responsibility','customer_id',
                        'amount_usd_cents'
                    ] = v_input
                THEN RETURN app.financial_draft_json(v_existing); END IF;
                RAISE EXCEPTION 'Reservation Deposit draft identity was reused' USING ERRCODE = 'P5205';
            END IF;
            v_source := app.reservation_deposit_draft_source(p_property_id, p_reservation_id, p_kind);
            IF p_kind = 'DEPOSIT_FORFEITURE' THEN
                SELECT disposition.id INTO v_active
                FROM app.deposit_dispositions AS disposition
                WHERE disposition.deposit_id = (v_source->>'deposit_id')::uuid
                  AND NOT EXISTS (
                      SELECT 1 FROM app.deposit_disposition_reversals AS reversal
                      WHERE reversal.deposit_disposition_id = disposition.id
                  );
            ELSE
                SELECT refund.id INTO v_active
                FROM app.refunds AS refund
                WHERE refund.source_deposit_id = (v_source->>'deposit_id')::uuid
                  AND refund.usd_accounting_value_cents - COALESCE((
                      SELECT sum(correction.source_balance_effect_usd_cents)
                      FROM app.refund_corrections AS correction
                      WHERE correction.refund_id = refund.id
                  ), 0) > 0;
            END IF;
            IF v_active IS DISTINCT FROM p_expected_outcome_id THEN
                RAISE EXCEPTION 'Reservation Deposit outcome precondition was not met'
                    USING ERRCODE = '40001';
            END IF;
            IF EXISTS (
                SELECT 1 FROM app.financial_drafts AS draft
                WHERE draft.property_id = p_property_id
                  AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE')
                  AND draft.payload->>'reservation_id' = p_reservation_id::text
                  AND NOT EXISTS (
                      SELECT 1 FROM app.financial_draft_decisions AS decision
                      WHERE decision.draft_id = draft.id
                  )
            ) THEN
                RAISE EXCEPTION 'A Deposit draft for this Reservation is already waiting'
                    USING ERRCODE = '55000';
            END IF;
            IF p_kind = 'REFUND' THEN
                PERFORM 1 FROM app.refund_methods WHERE id = p_refund_method_id AND active;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE = '22023';
                END IF;
                IF EXISTS (SELECT 1 FROM app.refunds WHERE refund_number = p_refund_number) THEN
                    RAISE EXCEPTION 'Refund number is already used' USING ERRCODE = '23505';
                END IF;
            END IF;
            RETURN app.insert_financial_draft(
                p_property_id, p_actor_id, p_draft_id, p_kind, p_authorization_reference,
                v_input || (v_source - 'reservation_id'),
                'deposit-received:' || (v_source->>'amount_usd_cents'), p_reason
            );
        END $$;

        -- Only a financial.approve holder confirms. Confirmation runs the existing outcome
        -- functions with the approver as actor, so every earlier Reservation outcome rule
        -- still applies; a Refund also records its method and reference note.
        CREATE FUNCTION app.confirm_reservation_deposit_draft(
            p_property_id uuid, p_actor_id uuid, p_reservation_id uuid, p_draft_id uuid,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_draft app.financial_drafts%ROWTYPE;
            v_source jsonb;
            v_snapshot jsonb;
            v_digest text;
            v_action text;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id, p_property_id);
            IF p_authorization_reference IS DISTINCT FROM 'financial.approve' THEN
                RAISE EXCEPTION 'Only financial.approve may confirm a Reservation Deposit draft'
                    USING ERRCODE = '42501';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft_id::text, 0));
            SELECT draft.* INTO v_draft
            FROM app.financial_drafts AS draft
            JOIN app.financial_draft_decisions AS decision ON decision.draft_id = draft.id
            WHERE draft.id = p_draft_id AND draft.property_id = p_property_id
              AND decision.decision = 'CONFIRMED' AND decision.decided_by = p_actor_id
              AND draft.payload->>'variant' IN ('RESERVATION_OUTCOME','RESERVATION_CORRECTION')
              AND draft.payload->>'reservation_id' = p_reservation_id::text;
            IF FOUND THEN
                -- An exact replay returns the stored result of the first confirmation.
                SELECT command.result_snapshot INTO STRICT v_snapshot
                FROM app.reservation_commands AS command
                WHERE command.actor_id = p_actor_id AND command.property_id = p_property_id
                  AND command.action IN ('reservation.outcome.complete','reservation.outcome.correct')
                  AND command.idempotency_key = p_draft_id;
                RETURN jsonb_build_object(
                    'draft', app.financial_draft_json(v_draft), 'reservation', v_snapshot
                );
            END IF;
            v_draft := app.lock_pending_financial_draft(p_property_id, p_draft_id);
            IF v_draft.payload->>'reservation_id' IS DISTINCT FROM p_reservation_id::text THEN
                RAISE EXCEPTION 'Financial draft was not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_draft.kind NOT IN ('REFUND','DEPOSIT_FORFEITURE')
                OR v_draft.prepare_capability NOT IN (
                    'reservation_deposits.refund','reservation_deposits.dispose'
                )
                OR v_draft.payload->>'variant' IS NULL
                OR v_draft.payload->>'variant' NOT IN ('RESERVATION_OUTCOME','RESERVATION_CORRECTION')
            THEN
                RAISE EXCEPTION 'Financial draft is not a Reservation Deposit draft'
                    USING ERRCODE = '22023';
            END IF;
            v_action := CASE v_draft.payload->>'variant'
                WHEN 'RESERVATION_OUTCOME' THEN 'reservation.outcome.complete'
                ELSE 'reservation.outcome.correct' END;
            -- The draft id must not already be another outcome command key of this approver.
            IF EXISTS (
                SELECT 1 FROM app.reservation_commands AS command
                WHERE command.actor_id = p_actor_id AND command.property_id = p_property_id
                  AND command.action = v_action AND command.idempotency_key = p_draft_id
            ) THEN
                RAISE EXCEPTION 'Reservation Deposit draft identity was reused' USING ERRCODE = 'P5205';
            END IF;
            v_source := app.reservation_deposit_draft_source(
                p_property_id, (v_draft.payload->>'reservation_id')::uuid, v_draft.kind
            );
            -- Defensive: a draft is stale when the Reservation or its received Deposit changed.
            -- Receipts are recorded only at Reservation creation and their reversal is refused
            -- while a draft is pending, so this is not expected to fire.
            IF (v_source->>'reservation_version') IS DISTINCT FROM (v_draft.payload->>'reservation_version')
                OR (v_source->>'amount_usd_cents') IS DISTINCT FROM (v_draft.payload->>'amount_usd_cents')
                OR (v_source->>'deposit_id') IS DISTINCT FROM (v_draft.payload->>'deposit_id')
            THEN
                RAISE EXCEPTION 'Reservation Deposit draft is stale' USING ERRCODE = '23514';
            END IF;
            IF v_draft.kind = 'REFUND' THEN
                PERFORM 1 FROM app.refund_methods
                WHERE id = (v_draft.payload->>'refund_method_id')::uuid AND active FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE = '22023';
                END IF;
            END IF;
            v_digest := encode(sha256(convert_to(
                'reservation-deposit-draft:' || p_draft_id::text, 'UTF8'
            )), 'hex');
            IF v_draft.payload->>'variant' = 'RESERVATION_OUTCOME' THEN
                IF app.reservation_deposit_has_outcome((v_source->>'deposit_id')::uuid) THEN
                    RAISE EXCEPTION 'Reservation Deposit draft is stale' USING ERRCODE = '23514';
                END IF;
                PERFORM * FROM app.complete_reservation_deposit_outcome(
                    p_property_id, p_draft_id, v_digest, (v_draft.payload->>'outcome_id')::uuid,
                    v_draft.payload->>'refund_number', (v_draft.payload->>'reservation_id')::uuid,
                    (v_draft.payload->>'reservation_version')::integer, v_draft.payload->>'reason',
                    v_draft.prepare_capability, p_actor_id
                );
            ELSE
                PERFORM * FROM app.correct_reservation_deposit_outcome(
                    p_property_id, p_draft_id, v_digest, (v_draft.payload->>'correction_id')::uuid,
                    (v_draft.payload->>'expected_outcome_id')::uuid,
                    (v_draft.payload->>'outcome_id')::uuid, v_draft.payload->>'refund_number',
                    (v_draft.payload->>'reservation_id')::uuid,
                    (v_draft.payload->>'reservation_version')::integer, v_draft.payload->>'reason',
                    v_draft.payload->>'evidence_reference', 'reservation_deposits.correct',
                    v_draft.prepare_capability, p_actor_id
                );
            END IF;
            IF v_draft.kind = 'REFUND' THEN
                INSERT INTO app.refund_draft_details(
                    refund_id, draft_id, refund_method_id, reference_note, recorded_at
                ) VALUES (
                    (v_draft.payload->>'outcome_id')::uuid, p_draft_id,
                    (v_draft.payload->>'refund_method_id')::uuid,
                    v_draft.payload->>'reference_note', clock_timestamp()
                );
            END IF;
            SELECT command.result_snapshot INTO STRICT v_snapshot
            FROM app.reservation_commands AS command
            WHERE command.actor_id = p_actor_id AND command.property_id = p_property_id
              AND command.action = v_action AND command.idempotency_key = p_draft_id;
            PERFORM app.confirm_financial_draft_record(
                p_property_id, p_actor_id, p_draft_id, v_draft.kind,
                jsonb_strip_nulls(jsonb_build_object(
                    'reservation_id', v_draft.payload->>'reservation_id',
                    'outcome_id', v_draft.payload->>'outcome_id',
                    'correction_id', v_draft.payload->>'correction_id'
                )),
                'financial.approve'
            );
            RETURN jsonb_build_object('draft', app.financial_draft_json(v_draft), 'reservation', v_snapshot);
        END $$;

        -- Reject (financial.approve) and withdraw (the preparer, with the draft's prepare
        -- capability) for Reservation Deposit drafts only, brought forward from slice 11b
        -- (owner answer to Q-2026-10-04-5). They record a decision and never move money.
        CREATE FUNCTION app.reservation_deposit_draft_scope(
            p_property_id uuid, p_reservation_id uuid, p_draft_id uuid
        ) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM 1 FROM app.financial_drafts AS draft
            WHERE draft.id = p_draft_id AND draft.property_id = p_property_id
              AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE')
              AND draft.prepare_capability IN (
                  'reservation_deposits.refund','reservation_deposits.dispose'
              )
              AND draft.payload->>'variant' IN ('RESERVATION_OUTCOME','RESERVATION_CORRECTION')
              AND draft.payload->>'reservation_id' = p_reservation_id::text;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Financial draft was not found' USING ERRCODE = 'P0002';
            END IF;
        END $$;

        CREATE FUNCTION app.reject_reservation_deposit_draft(
            p_property_id uuid, p_actor_id uuid, p_reservation_id uuid, p_draft_id uuid,
            p_reason text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            IF p_authorization_reference IS DISTINCT FROM 'financial.approve' THEN
                RAISE EXCEPTION 'Only financial.approve may reject a draft' USING ERRCODE = '42501';
            END IF;
            PERFORM app.reservation_deposit_draft_scope(p_property_id, p_reservation_id, p_draft_id);
            RETURN app.reject_financial_draft(
                p_property_id, p_actor_id, p_draft_id, p_reason, p_authorization_reference
            );
        END $$;

        CREATE FUNCTION app.withdraw_reservation_deposit_draft(
            p_property_id uuid, p_actor_id uuid, p_reservation_id uuid, p_draft_id uuid,
            p_reason text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            IF p_authorization_reference IS NULL OR p_authorization_reference NOT IN (
                'reservation_deposits.refund','reservation_deposits.dispose'
            ) THEN
                RAISE EXCEPTION 'Only the preparer may withdraw a draft' USING ERRCODE = '42501';
            END IF;
            PERFORM app.reservation_deposit_draft_scope(p_property_id, p_reservation_id, p_draft_id);
            RETURN app.withdraw_financial_draft(
                p_property_id, p_actor_id, p_draft_id, p_reason, p_authorization_reference
            );
        END $$;

        -- Reservations waiting for a Deposit decision: cancelled or expired, Deposit received,
        -- and no outcome record yet. Oldest cancellation first; bounded keyset pages.
        CREATE FUNCTION app.list_reservations_awaiting_deposit_decision(
            p_property_id uuid, p_actor_id uuid, p_limit integer,
            p_after_cancelled_at timestamptz, p_after_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100
                OR (p_after_cancelled_at IS NULL) <> (p_after_id IS NULL)
            THEN
                RAISE EXCEPTION 'Reservation Deposit decision page is invalid' USING ERRCODE = '22023';
            END IF;
            WITH candidate AS (
                SELECT reservation.id, reservation.version, reservation.unit_id,
                       unit.unit_number, reservation.customer_id, customer.legal_name,
                       reservation.cancellation_reason_code,
                       reservation.cancellation_responsibility, reservation.cancelled_at,
                       deposit.id AS deposit_id,
                       (SELECT COALESCE(sum(receipt.amount_usd_cents), 0)::bigint
                        FROM app.deposit_receipts AS receipt
                        WHERE receipt.deposit_id = deposit.id
                          AND NOT EXISTS (
                              SELECT 1 FROM app.deposit_receipt_reversals AS reversal
                              WHERE reversal.deposit_receipt_id = receipt.id
                          )) AS held_usd_cents,
                       (SELECT draft.id FROM app.financial_drafts AS draft
                        WHERE draft.property_id = p_property_id
                          AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE')
                          AND draft.payload->>'reservation_id' = reservation.id::text
                          AND NOT EXISTS (
                              SELECT 1 FROM app.financial_draft_decisions AS decision
                              WHERE decision.draft_id = draft.id
                          )
                        ORDER BY draft.prepared_at DESC, draft.id DESC LIMIT 1) AS pending_draft_id
                FROM app.reservations AS reservation
                JOIN app.units AS unit ON unit.id = reservation.unit_id
                JOIN app.customers AS customer ON customer.id = reservation.customer_id
                JOIN app.deposits AS deposit ON deposit.reservation_id = reservation.id
                WHERE unit.property_id = p_property_id
                  AND reservation.status = 'CANCELLED'
                  AND NOT app.reservation_deposit_has_outcome(deposit.id)
                  AND (p_after_id IS NULL
                       OR (reservation.cancelled_at, reservation.id) > (p_after_cancelled_at, p_after_id))
                  AND EXISTS (
                      SELECT 1 FROM app.deposit_receipts AS receipt
                      WHERE receipt.deposit_id = deposit.id
                        AND NOT EXISTS (
                            SELECT 1 FROM app.deposit_receipt_reversals AS reversal
                            WHERE reversal.deposit_receipt_id = receipt.id
                        )
                  )
                ORDER BY reservation.cancelled_at, reservation.id
                LIMIT p_limit + 1
            ), page AS (
                SELECT candidate.*, row_number() OVER (
                    ORDER BY candidate.cancelled_at, candidate.id
                ) AS page_position
                FROM candidate
            )
            SELECT jsonb_build_object(
                'items', COALESCE(jsonb_agg(jsonb_build_object(
                    'reservation_id', page.id,
                    'reservation_version', page.version,
                    'unit_id', page.unit_id,
                    'unit_number', page.unit_number,
                    'customer_id', page.customer_id,
                    'customer_name', page.legal_name,
                    'cancellation_reason_code', page.cancellation_reason_code,
                    'cancellation_responsibility', page.cancellation_responsibility,
                    'cancelled_at', page.cancelled_at,
                    'deposit_id', page.deposit_id,
                    'held_usd_cents', page.held_usd_cents,
                    'decision_kind', CASE page.cancellation_responsibility
                        WHEN 'CUSTOMER' THEN 'DEPOSIT_FORFEITURE' ELSE 'REFUND' END,
                    'pending_draft_id', page.pending_draft_id
                ) ORDER BY page.page_position) FILTER (WHERE page.page_position <= p_limit), '[]'::jsonb),
                'next_after', CASE WHEN count(*) > p_limit THEN jsonb_build_object(
                    'cancelled_at', max(page.cancelled_at) FILTER (WHERE page.page_position = p_limit),
                    'reservation_id', (array_agg(page.id) FILTER (WHERE page.page_position = p_limit))[1]
                ) END
            ) INTO v_result
            FROM page;
            RETURN v_result;
        END $$;
        """
    )
    for function in (*FINANCIAL, *RUNTIME, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in FINANCIAL:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")
    for function in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")
    for function in RETIRED:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {function} FROM prm_financial")


def downgrade() -> None:
    raise RuntimeError("Reservation Deposit drafts are forward-only")
