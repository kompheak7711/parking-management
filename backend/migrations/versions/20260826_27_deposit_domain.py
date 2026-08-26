# ruff: noqa: E501
"""Add protected Security and Pet Deposit domain persistence."""

from alembic import op

revision = "20260826_27"
down_revision = "20260826_26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install the bounded V1-037 Deposit aggregate and command boundary."""
    op.execute(
        """
        ALTER TABLE app.deposits
            DROP CONSTRAINT deposits_reservation_security_shape,
            DROP CONSTRAINT deposits_deposit_type_check,
            ALTER COLUMN reservation_id DROP NOT NULL,
            ADD CONSTRAINT deposits_type_check
                CHECK (deposit_type IN ('SECURITY', 'PET')),
            ADD CONSTRAINT deposits_source_shape CHECK (
                (deposit_type = 'SECURITY' AND reservation_id IS NOT NULL
                    AND pet_approval_id IS NULL)
                OR
                (deposit_type = 'PET' AND reservation_id IS NULL
                    AND lease_id IS NOT NULL AND pet_approval_id IS NOT NULL)
            ),
            ADD CONSTRAINT deposits_pet_approval_fkey
                FOREIGN KEY (pet_approval_id)
                REFERENCES app.lease_pet_approvals(id) ON DELETE RESTRICT
                DEFERRABLE INITIALLY DEFERRED;

        CREATE UNIQUE INDEX deposits_security_reservation_unique
            ON app.deposits(reservation_id) WHERE deposit_type = 'SECURITY';
        CREATE UNIQUE INDEX deposits_pet_lease_unique
            ON app.deposits(lease_id) WHERE deposit_type = 'PET';
        CREATE UNIQUE INDEX deposits_pet_approval_unique
            ON app.deposits(pet_approval_id) WHERE deposit_type = 'PET';
        CREATE INDEX deposits_lease_history_idx
            ON app.deposits(lease_id, required_effective_date, id)
            WHERE lease_id IS NOT NULL;

        CREATE OR REPLACE FUNCTION app.validate_reservation_security_deposit()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_reservation app.reservations%ROWTYPE; v_accepted bigint;
        BEGIN
            IF NEW.deposit_type = 'PET' THEN RETURN NEW; END IF;
            SELECT reservation.* INTO v_reservation FROM app.reservations AS reservation
            WHERE reservation.id = NEW.reservation_id;
            SELECT acceptance.accepted_required_amount_usd_cents INTO v_accepted
            FROM app.reservation_deposit_acceptances AS acceptance
            WHERE acceptance.reservation_id = NEW.reservation_id;
            IF v_reservation.id IS NULL OR v_accepted IS NULL
                OR NEW.customer_id <> v_reservation.customer_id
                OR NEW.required_effective_date <> v_reservation.reservation_date
                OR NEW.required_usd_cents < v_accepted
            THEN RAISE EXCEPTION 'Reservation Security Deposit continuity is invalid'
                USING ERRCODE = '23514'; END IF;
            RETURN NEW;
        END;
        $$;

        ALTER TABLE app.deposit_dispositions
            ALTER COLUMN governing_reservation_id DROP NOT NULL,
            ALTER COLUMN source_lifecycle_event_id DROP NOT NULL,
            ADD COLUMN governing_lease_id uuid
                REFERENCES app.leases(id) ON DELETE RESTRICT,
            ADD CONSTRAINT deposit_dispositions_governing_source_shape CHECK (
                (governing_reservation_id IS NOT NULL
                    AND source_lifecycle_event_id IS NOT NULL
                    AND governing_lease_id IS NULL)
                OR
                (governing_reservation_id IS NULL
                    AND source_lifecycle_event_id IS NULL
                    AND governing_lease_id IS NOT NULL)
            );
        CREATE INDEX deposit_dispositions_lease_history_idx
            ON app.deposit_dispositions(governing_lease_id, occurred_at, id)
            WHERE governing_lease_id IS NOT NULL;
        """
    )
    op.execute(
        """
        CREATE TABLE app.deposit_required_amount_adjustments (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            deposit_id uuid NOT NULL REFERENCES app.deposits(id) ON DELETE RESTRICT,
            adjustment_type text NOT NULL CHECK (adjustment_type IN ('INCREASE','DECREASE')),
            amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
            effective_date date NOT NULL,
            reason text NOT NULL CHECK (length(btrim(reason)) > 0 AND reason = btrim(reason)),
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            )
        );
        CREATE INDEX deposit_required_adjustments_history_idx
            ON app.deposit_required_amount_adjustments(deposit_id, effective_date, occurred_at, id);

        CREATE TABLE app.deposit_receipt_reversals (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            deposit_receipt_id uuid NOT NULL UNIQUE
                REFERENCES app.deposit_receipts(id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK (length(btrim(reason)) > 0 AND reason = btrim(reason)),
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            )
        );

        CREATE TABLE app.deposit_commands (
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            action text NOT NULL CHECK (action IN (
                'deposit.pet.create', 'deposit.required.adjust', 'deposit.receipt.reverse',
                'deposit.disposition.record', 'deposit.disposition.reverse',
                'deposit.pet_refund.qualify'
            )),
            idempotency_key uuid NOT NULL,
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            deposit_id uuid NOT NULL REFERENCES app.deposits(id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK (length(btrim(reason)) > 0 AND reason = btrim(reason)),
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            ),
            result_snapshot jsonb NOT NULL CHECK (jsonb_typeof(result_snapshot) = 'object'),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (actor_id, property_id, action, idempotency_key)
        );
        CREATE INDEX deposit_commands_deposit_history_idx
            ON app.deposit_commands(deposit_id, created_at, action, idempotency_key);
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.deposit_property_id(p_deposit_id uuid)
        RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT unit.property_id
            FROM app.deposits AS deposit
            LEFT JOIN app.reservations AS reservation ON reservation.id = deposit.reservation_id
            LEFT JOIN app.leases AS lease ON lease.id = deposit.lease_id
            JOIN app.units AS unit ON unit.id = COALESCE(reservation.unit_id, lease.unit_id)
            WHERE deposit.id = p_deposit_id
        $$;

        CREATE FUNCTION app.deposit_snapshot(p_deposit_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object(
                'deposit_id', deposit.id,
                'property_id', app.deposit_property_id(deposit.id),
                'deposit_type', deposit.deposit_type,
                'customer_id', deposit.customer_id,
                'reservation_id', deposit.reservation_id,
                'lease_id', deposit.lease_id,
                'pet_approval_id', deposit.pet_approval_id,
                'required_usd_cents', deposit.required_usd_cents + COALESCE((
                    SELECT sum(CASE adjustment.adjustment_type
                        WHEN 'INCREASE' THEN adjustment.amount_usd_cents
                        ELSE -adjustment.amount_usd_cents END)
                    FROM app.deposit_required_amount_adjustments AS adjustment
                    WHERE adjustment.deposit_id = deposit.id
                ), 0),
                'received_usd_cents', COALESCE((
                    SELECT sum(receipt.amount_usd_cents)
                    FROM app.deposit_receipts AS receipt
                    WHERE receipt.deposit_id = deposit.id
                      AND NOT EXISTS (
                          SELECT 1 FROM app.deposit_receipt_reversals AS reversal
                          WHERE reversal.deposit_receipt_id = receipt.id
                      )
                ), 0),
                'held_refundable_usd_cents', GREATEST(0,
                    COALESCE((SELECT sum(receipt.amount_usd_cents)
                        FROM app.deposit_receipts AS receipt
                        WHERE receipt.deposit_id = deposit.id
                          AND NOT EXISTS (SELECT 1 FROM app.deposit_receipt_reversals AS reversal
                              WHERE reversal.deposit_receipt_id = receipt.id)), 0)
                    - COALESCE((SELECT sum(disposition.amount_usd_cents)
                        FROM app.deposit_dispositions AS disposition
                        WHERE disposition.deposit_id = deposit.id
                          AND NOT EXISTS (SELECT 1 FROM app.deposit_disposition_reversals AS reversal
                              WHERE reversal.deposit_disposition_id = disposition.id)), 0)
                    - COALESCE((SELECT sum(refund.usd_accounting_value_cents
                            - COALESCE((SELECT sum(correction.source_balance_effect_usd_cents)
                                FROM app.refund_corrections AS correction
                                WHERE correction.refund_id = refund.id), 0))
                        FROM app.refunds AS refund WHERE refund.source_deposit_id = deposit.id), 0)
                ),
                'outstanding_required_usd_cents', GREATEST(0,
                    deposit.required_usd_cents + COALESCE((SELECT sum(
                        CASE adjustment.adjustment_type WHEN 'INCREASE'
                            THEN adjustment.amount_usd_cents ELSE -adjustment.amount_usd_cents END)
                        FROM app.deposit_required_amount_adjustments AS adjustment
                        WHERE adjustment.deposit_id = deposit.id), 0)
                    - COALESCE((SELECT sum(receipt.amount_usd_cents)
                        FROM app.deposit_receipts AS receipt
                        WHERE receipt.deposit_id = deposit.id
                          AND NOT EXISTS (SELECT 1 FROM app.deposit_receipt_reversals AS reversal
                              WHERE reversal.deposit_receipt_id = receipt.id)), 0)
                ),
                'version', deposit.version
            )
            FROM app.deposits AS deposit WHERE deposit.id = p_deposit_id
        $$;

        CREATE OR REPLACE FUNCTION app.validate_deposit_receipt()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_deposit app.deposits%ROWTYPE; v_received bigint;
            v_accepted bigint; v_accepted_at timestamptz; v_required bigint;
        BEGIN
            SELECT deposit.* INTO v_deposit FROM app.deposits AS deposit
            WHERE deposit.id = NEW.deposit_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Deposit was not found' USING ERRCODE='23503'; END IF;
            SELECT COALESCE(sum(receipt.amount_usd_cents),0) INTO v_received
            FROM app.deposit_receipts AS receipt WHERE receipt.deposit_id=NEW.deposit_id
              AND NOT EXISTS (SELECT 1 FROM app.deposit_receipt_reversals AS reversal
                  WHERE reversal.deposit_receipt_id=receipt.id);
            v_required := (app.deposit_snapshot(NEW.deposit_id)->>'required_usd_cents')::bigint;
            IF v_deposit.deposit_type = 'SECURITY' THEN
                SELECT acceptance.accepted_required_amount_usd_cents,acceptance.accepted_at
                INTO v_accepted,v_accepted_at FROM app.reservation_deposit_acceptances AS acceptance
                WHERE acceptance.reservation_id=v_deposit.reservation_id;
                IF NEW.occurred_at > clock_timestamp()+interval '5 seconds'
                    OR NEW.occurred_at < v_accepted_at
                    OR (v_received=0 AND NEW.amount_usd_cents<>v_accepted)
                    OR v_received+NEW.amount_usd_cents>v_required
                THEN RAISE EXCEPTION 'Deposit receipt does not preserve the accepted or required amount'
                    USING ERRCODE='23514'; END IF;
            ELSE
                SELECT approval.approved_at INTO v_accepted_at
                FROM app.lease_pet_approvals AS approval WHERE approval.id=v_deposit.pet_approval_id;
                IF NEW.occurred_at > clock_timestamp()+interval '5 seconds'
                    OR NEW.occurred_at < v_accepted_at
                    OR v_received+NEW.amount_usd_cents>v_required
                THEN RAISE EXCEPTION 'Pet Deposit receipt exceeds its approved liability'
                    USING ERRCODE='23514'; END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.validate_deposit_source()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF NEW.deposit_type = 'SECURITY' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM app.reservations AS reservation
                    LEFT JOIN app.leases AS lease ON lease.id = NEW.lease_id
                    WHERE reservation.id = NEW.reservation_id
                      AND reservation.customer_id = NEW.customer_id
                      AND (NEW.lease_id IS NULL OR (
                          reservation.resulting_lease_id = NEW.lease_id
                          AND lease.primary_tenant_id = NEW.customer_id
                      ))
                ) THEN
                    RAISE EXCEPTION 'Security Deposit sources do not match'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF NOT EXISTS (
                SELECT 1 FROM app.lease_pet_approvals AS approval
                JOIN app.leases AS lease ON lease.id = approval.lease_id
                WHERE approval.id = NEW.pet_approval_id
                  AND lease.id = NEW.lease_id
                  AND lease.primary_tenant_id = NEW.customer_id
                  AND lease.status = 'SIGNED'
                  AND approval.deposit_required_by_signed_terms
                  AND NEW.required_effective_date >= approval.approved_date
            ) THEN
                RAISE EXCEPTION 'Pet Deposit requires matching approved signed Lease terms'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$;
        CREATE CONSTRAINT TRIGGER deposits_validate_source
            AFTER INSERT OR UPDATE OF lease_id ON app.deposits
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.validate_deposit_source();

        CREATE FUNCTION app.reject_deposit_domain_history_loss()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Deposit domain history is append-only' USING ERRCODE = '55000';
        END;
        $$;

        CREATE FUNCTION app.validate_deposit_required_adjustment()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_required bigint;
        BEGIN
            PERFORM 1 FROM app.deposits WHERE id = NEW.deposit_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Deposit was not found' USING ERRCODE = '23503';
            END IF;
            SELECT deposit.required_usd_cents + COALESCE(sum(
                CASE adjustment.adjustment_type WHEN 'INCREASE'
                    THEN adjustment.amount_usd_cents ELSE -adjustment.amount_usd_cents END
            ), 0)
            INTO v_required
            FROM app.deposits AS deposit
            LEFT JOIN app.deposit_required_amount_adjustments AS adjustment
                ON adjustment.deposit_id = deposit.id
            WHERE deposit.id = NEW.deposit_id
            GROUP BY deposit.required_usd_cents;
            IF NEW.adjustment_type = 'DECREASE' AND NEW.amount_usd_cents > v_required THEN
                RAISE EXCEPTION 'Deposit required amount cannot become negative'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER deposit_required_adjustments_validate_balance
            BEFORE INSERT ON app.deposit_required_amount_adjustments
            FOR EACH ROW EXECUTE FUNCTION app.validate_deposit_required_adjustment();

        CREATE FUNCTION app.validate_deposit_receipt_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_deposit_id uuid;
        BEGIN
            SELECT receipt.deposit_id INTO v_deposit_id
            FROM app.deposit_receipts AS receipt
            WHERE receipt.id = NEW.deposit_receipt_id
            FOR UPDATE OF receipt;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Deposit receipt was not found' USING ERRCODE = '23503';
            END IF;
            PERFORM 1 FROM app.deposits WHERE id = v_deposit_id FOR UPDATE;
            IF EXISTS (
                SELECT 1 FROM app.deposit_dispositions AS disposition
                WHERE disposition.deposit_id = v_deposit_id
                  AND NOT EXISTS (
                      SELECT 1 FROM app.deposit_disposition_reversals AS reversal
                      WHERE reversal.deposit_disposition_id = disposition.id
                  )
            ) OR EXISTS (
                SELECT 1 FROM app.refunds AS refund
                WHERE refund.source_deposit_id = v_deposit_id
            ) THEN
                RAISE EXCEPTION 'Deposit receipt has active dependent financial history'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER deposit_receipt_reversals_validate_dependencies
            BEFORE INSERT ON app.deposit_receipt_reversals
            FOR EACH ROW EXECUTE FUNCTION app.validate_deposit_receipt_reversal();

        CREATE FUNCTION app.validate_lease_deposit_disposition()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_termination_date date; v_held bigint;
        BEGIN
            SELECT lease.actual_termination_date
            INTO v_termination_date
            FROM app.deposits AS deposit
            JOIN app.leases AS lease ON lease.id = deposit.lease_id
            WHERE deposit.id = NEW.deposit_id
              AND lease.id = NEW.governing_lease_id
              AND lease.status = 'TERMINATED'
            FOR UPDATE OF deposit;
            IF NOT FOUND OR NEW.effective_date <> v_termination_date THEN
                RAISE EXCEPTION 'Lease Deposit disposition source is invalid'
                    USING ERRCODE = '23514';
            END IF;
            v_held := (app.deposit_snapshot(NEW.deposit_id)
                ->> 'held_refundable_usd_cents')::bigint;
            IF NEW.amount_usd_cents > v_held THEN
                RAISE EXCEPTION 'Lease Deposit disposition exceeds held refundable value'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        DROP TRIGGER deposit_dispositions_validate_source ON app.deposit_dispositions;
        CREATE TRIGGER deposit_dispositions_validate_reservation_source
            BEFORE INSERT ON app.deposit_dispositions
            FOR EACH ROW WHEN (NEW.governing_reservation_id IS NOT NULL)
            EXECUTE FUNCTION app.validate_reservation_financial_outcome();
        CREATE TRIGGER deposit_dispositions_validate_lease_source
            BEFORE INSERT ON app.deposit_dispositions
            FOR EACH ROW WHEN (NEW.governing_lease_id IS NOT NULL)
            EXECUTE FUNCTION app.validate_lease_deposit_disposition();
        """
    )
    for table in (
        "deposit_required_amount_adjustments",
        "deposit_receipt_reversals",
        "deposit_commands",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_reject_mutation BEFORE UPDATE OR DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_deposit_domain_history_loss()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON app.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_deposit_domain_history_loss()"
        )
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.replay_deposit_command(
            p_property_id uuid, p_actor_id uuid, p_action text,
            p_idempotency_key uuid, p_request_digest text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_command app.deposit_commands%ROWTYPE;
        BEGIN
            SELECT * INTO v_command FROM app.deposit_commands
            WHERE actor_id = p_actor_id AND property_id = p_property_id
              AND action = p_action AND idempotency_key = p_idempotency_key;
            IF NOT FOUND THEN RETURN NULL; END IF;
            IF v_command.request_digest <> p_request_digest THEN
                RAISE EXCEPTION 'Deposit idempotency key conflicts with another request'
                    USING ERRCODE = '23505';
            END IF;
            RETURN v_command.result_snapshot;
        END;
        $$;

        CREATE FUNCTION app.record_deposit_command(
            p_property_id uuid, p_actor_id uuid, p_action text,
            p_idempotency_key uuid, p_request_digest text, p_deposit_id uuid,
            p_reason text, p_authorization_reference text, p_result jsonb
        ) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
            INSERT INTO app.deposit_commands(
                actor_id,property_id,action,idempotency_key,request_digest,deposit_id,
                reason,authorization_reference,result_snapshot
            ) VALUES (p_actor_id,p_property_id,p_action,p_idempotency_key,p_request_digest,
                p_deposit_id,btrim(p_reason),btrim(p_authorization_reference),p_result)
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.create_pet_deposit(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_deposit_id uuid, p_lease_id uuid,
            p_pet_approval_id uuid, p_required_usd_cents bigint,
            p_required_effective_date date, p_reason text,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb; v_customer_id uuid;
        BEGIN
            v_result := app.replay_deposit_command(p_property_id,p_actor_id,
                'deposit.pet.create',p_idempotency_key,p_request_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_authorization_reference <> 'deposits.manage'
                OR p_required_usd_cents <= 0 OR COALESCE(btrim(p_reason),'') = ''
            THEN RAISE EXCEPTION 'Pet Deposit evidence is invalid' USING ERRCODE='22023'; END IF;
            SELECT lease.primary_tenant_id INTO v_customer_id
            FROM app.leases AS lease JOIN app.units AS unit ON unit.id=lease.unit_id
            WHERE lease.id=p_lease_id AND unit.property_id=p_property_id
              AND lease.status='SIGNED' FOR SHARE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Signed Lease was not found' USING ERRCODE='P0002'; END IF;
            INSERT INTO app.deposits(id,deposit_type,customer_id,reservation_id,lease_id,
                pet_approval_id,required_usd_cents,required_effective_date,created_by,updated_by)
            VALUES(p_deposit_id,'PET',v_customer_id,NULL,p_lease_id,p_pet_approval_id,
                p_required_usd_cents,p_required_effective_date,p_actor_id,p_actor_id);
            SET CONSTRAINTS app.deposits_validate_source IMMEDIATE;
            v_result := app.deposit_snapshot(p_deposit_id);
            PERFORM app.record_deposit_command(p_property_id,p_actor_id,'deposit.pet.create',
                p_idempotency_key,p_request_digest,p_deposit_id,p_reason,
                p_authorization_reference,v_result);
            RETURN v_result;
        END;
        $$;

        CREATE FUNCTION app.adjust_deposit_required_amount(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_adjustment_id uuid, p_deposit_id uuid,
            p_adjustment_type text, p_amount_usd_cents bigint, p_effective_date date,
            p_reason text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb; v_required bigint;
        BEGIN
            v_result := app.replay_deposit_command(p_property_id,p_actor_id,
                'deposit.required.adjust',p_idempotency_key,p_request_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_authorization_reference <> 'deposits.manage'
                OR p_adjustment_type NOT IN ('INCREASE','DECREASE')
                OR p_amount_usd_cents <= 0 OR COALESCE(btrim(p_reason),'') = ''
            THEN RAISE EXCEPTION 'Deposit adjustment evidence is invalid' USING ERRCODE='22023'; END IF;
            PERFORM 1 FROM app.deposits WHERE id=p_deposit_id FOR UPDATE;
            IF NOT FOUND OR app.deposit_property_id(p_deposit_id) <> p_property_id
            THEN RAISE EXCEPTION 'Deposit was not found' USING ERRCODE='P0002'; END IF;
            v_required := (app.deposit_snapshot(p_deposit_id)->>'required_usd_cents')::bigint;
            IF p_adjustment_type='DECREASE' AND p_amount_usd_cents > v_required
            THEN RAISE EXCEPTION 'Deposit required amount cannot become negative' USING ERRCODE='23514'; END IF;
            INSERT INTO app.deposit_required_amount_adjustments(id,deposit_id,adjustment_type,
                amount_usd_cents,effective_date,reason,occurred_at,actor_id,authorization_reference)
            VALUES(p_adjustment_id,p_deposit_id,p_adjustment_type,p_amount_usd_cents,
                p_effective_date,btrim(p_reason),statement_timestamp(),p_actor_id,p_authorization_reference);
            v_result := app.deposit_snapshot(p_deposit_id);
            PERFORM app.record_deposit_command(p_property_id,p_actor_id,'deposit.required.adjust',
                p_idempotency_key,p_request_digest,p_deposit_id,p_reason,p_authorization_reference,v_result);
            RETURN v_result;
        END;
        $$;

        CREATE FUNCTION app.reverse_deposit_receipt(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_reversal_id uuid, p_receipt_id uuid,
            p_reason text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb; v_deposit_id uuid;
        BEGIN
            v_result := app.replay_deposit_command(p_property_id,p_actor_id,
                'deposit.receipt.reverse',p_idempotency_key,p_request_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_authorization_reference <> 'deposits.correct' OR COALESCE(btrim(p_reason),'') = ''
            THEN RAISE EXCEPTION 'Deposit receipt reversal evidence is invalid' USING ERRCODE='22023'; END IF;
            SELECT receipt.deposit_id INTO v_deposit_id FROM app.deposit_receipts AS receipt
            WHERE receipt.id=p_receipt_id FOR UPDATE OF receipt;
            IF NOT FOUND OR app.deposit_property_id(v_deposit_id) <> p_property_id
            THEN RAISE EXCEPTION 'Deposit receipt was not found' USING ERRCODE='P0002'; END IF;
            PERFORM 1 FROM app.deposits WHERE id=v_deposit_id FOR UPDATE;
            IF EXISTS(SELECT 1 FROM app.deposit_dispositions d WHERE d.deposit_id=v_deposit_id
                    AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals r WHERE r.deposit_disposition_id=d.id))
                OR EXISTS(SELECT 1 FROM app.refunds r WHERE r.source_deposit_id=v_deposit_id)
            THEN RAISE EXCEPTION 'Deposit receipt has active dependent financial history' USING ERRCODE='55000'; END IF;
            INSERT INTO app.deposit_receipt_reversals(id,deposit_receipt_id,reason,occurred_at,
                actor_id,authorization_reference) VALUES(p_reversal_id,p_receipt_id,btrim(p_reason),
                statement_timestamp(),p_actor_id,p_authorization_reference);
            v_result := app.deposit_snapshot(v_deposit_id);
            PERFORM app.record_deposit_command(p_property_id,p_actor_id,'deposit.receipt.reverse',
                p_idempotency_key,p_request_digest,v_deposit_id,p_reason,p_authorization_reference,v_result);
            RETURN v_result;
        END;
        $$;

        CREATE FUNCTION app.record_lease_deposit_disposition(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_disposition_id uuid, p_deposit_id uuid,
            p_governing_lease_id uuid, p_amount_usd_cents bigint,
            p_effective_date date, p_reason text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb;
        BEGIN
            v_result := app.replay_deposit_command(p_property_id,p_actor_id,
                'deposit.disposition.record',p_idempotency_key,p_request_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_authorization_reference <> 'deposits.dispose'
                OR p_amount_usd_cents <= 0 OR p_effective_date IS NULL
                OR COALESCE(btrim(p_reason),'') = ''
            THEN RAISE EXCEPTION 'Deposit disposition evidence is invalid'
                USING ERRCODE='22023'; END IF;
            PERFORM 1 FROM app.deposits WHERE id=p_deposit_id FOR UPDATE;
            IF NOT FOUND OR app.deposit_property_id(p_deposit_id) <> p_property_id
            THEN RAISE EXCEPTION 'Deposit was not found' USING ERRCODE='P0002'; END IF;
            INSERT INTO app.deposit_dispositions(
                id,deposit_id,amount_usd_cents,governing_reservation_id,
                source_lifecycle_event_id,governing_lease_id,effective_date,reason,
                occurred_at,actor_id,authorization_reference
            ) VALUES (
                p_disposition_id,p_deposit_id,p_amount_usd_cents,NULL,NULL,
                p_governing_lease_id,p_effective_date,btrim(p_reason),
                statement_timestamp(),p_actor_id,p_authorization_reference
            );
            v_result := app.deposit_snapshot(p_deposit_id)
                || jsonb_build_object('deposit_disposition_id',p_disposition_id);
            PERFORM app.record_deposit_command(p_property_id,p_actor_id,
                'deposit.disposition.record',p_idempotency_key,p_request_digest,
                p_deposit_id,p_reason,p_authorization_reference,v_result);
            RETURN v_result;
        END;
        $$;

        CREATE FUNCTION app.reverse_deposit_disposition(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_reversal_id uuid, p_disposition_id uuid,
            p_reason text, p_evidence_reference text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb; v_deposit_id uuid;
        BEGIN
            v_result := app.replay_deposit_command(p_property_id,p_actor_id,
                'deposit.disposition.reverse',p_idempotency_key,p_request_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_authorization_reference <> 'deposits.correct'
                OR COALESCE(btrim(p_reason),'') = ''
                OR COALESCE(btrim(p_evidence_reference),'') = ''
            THEN RAISE EXCEPTION 'Deposit disposition reversal evidence is invalid'
                USING ERRCODE='22023'; END IF;
            SELECT disposition.deposit_id INTO v_deposit_id
            FROM app.deposit_dispositions AS disposition
            WHERE disposition.id=p_disposition_id
              AND disposition.governing_lease_id IS NOT NULL
            FOR UPDATE OF disposition;
            IF NOT FOUND OR app.deposit_property_id(v_deposit_id) <> p_property_id
            THEN RAISE EXCEPTION 'Lease Deposit disposition was not found'
                USING ERRCODE='P0002'; END IF;
            PERFORM 1 FROM app.deposits WHERE id=v_deposit_id FOR UPDATE;
            INSERT INTO app.deposit_disposition_reversals(
                id,deposit_disposition_id,reason,evidence_reference,occurred_at,
                actor_id,authorization_reference
            ) VALUES (
                p_reversal_id,p_disposition_id,btrim(p_reason),
                btrim(p_evidence_reference),statement_timestamp(),p_actor_id,
                p_authorization_reference
            );
            v_result := app.deposit_snapshot(v_deposit_id)
                || jsonb_build_object('deposit_disposition_reversal_id',p_reversal_id);
            PERFORM app.record_deposit_command(p_property_id,p_actor_id,
                'deposit.disposition.reverse',p_idempotency_key,p_request_digest,
                v_deposit_id,p_reason,p_authorization_reference,v_result);
            RETURN v_result;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.qualify_active_lease_pet_refund(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_departure_id uuid, p_review_id uuid,
            p_deposit_id uuid, p_permanently_left_date date,
            p_obligations_reviewed_usd_cents bigint, p_review_findings text,
            p_resolution_reference text, p_reason text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_result jsonb; v_lease_id uuid; v_approval_id uuid;
            v_approved_date date; v_lease_start_date date; v_business_date date;
        BEGIN
            v_result := app.replay_deposit_command(p_property_id,p_actor_id,
                'deposit.pet_refund.qualify',p_idempotency_key,p_request_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_authorization_reference <> 'deposits.refund.qualify'
                OR p_obligations_reviewed_usd_cents < 0
                OR COALESCE(btrim(p_review_findings),'') = ''
                OR COALESCE(btrim(p_resolution_reference),'') = ''
                OR COALESCE(btrim(p_reason),'') = ''
            THEN RAISE EXCEPTION 'Pet Deposit Refund qualification is invalid' USING ERRCODE='22023'; END IF;
            SELECT deposit.lease_id,deposit.pet_approval_id,approval.approved_date,
                   lease.start_date,
                   timezone(property.timezone_name,statement_timestamp())::date
            INTO v_lease_id,v_approval_id,v_approved_date,v_lease_start_date,v_business_date
            FROM app.deposits AS deposit JOIN app.leases AS lease ON lease.id=deposit.lease_id
            JOIN app.lease_pet_approvals AS approval ON approval.id=deposit.pet_approval_id
            JOIN app.units AS unit ON unit.id=lease.unit_id
            JOIN app.properties AS property ON property.id=unit.property_id
            WHERE deposit.id=p_deposit_id AND deposit.deposit_type='PET'
              AND lease.status='SIGNED' AND unit.property_id=p_property_id FOR UPDATE OF deposit;
            IF NOT FOUND THEN RAISE EXCEPTION 'Eligible Pet Deposit was not found' USING ERRCODE='P0002'; END IF;
            IF p_permanently_left_date < GREATEST(v_approved_date,v_lease_start_date)
                OR p_permanently_left_date > v_business_date
            THEN RAISE EXCEPTION 'Pet departure chronology is invalid' USING ERRCODE='23514'; END IF;
            IF (app.deposit_snapshot(p_deposit_id)->>'held_refundable_usd_cents')::bigint <= 0
            THEN RAISE EXCEPTION 'Pet Deposit has no refundable held balance' USING ERRCODE='23514'; END IF;
            INSERT INTO app.lease_pet_departures(id,pet_approval_id,lease_id,permanently_left_date,
                reason,occurred_at,actor_id) VALUES(p_departure_id,v_approval_id,v_lease_id,
                p_permanently_left_date,btrim(p_reason),statement_timestamp(),p_actor_id);
            INSERT INTO app.pet_deposit_refund_reviews(id,pet_departure_id,pet_deposit_id,
                obligations_reviewed_usd_cents,review_findings,all_pet_obligations_resolved,
                resolution_reference,reason,reviewed_at,reviewed_by,authorization_reference)
            VALUES(p_review_id,p_departure_id,p_deposit_id,p_obligations_reviewed_usd_cents,
                btrim(p_review_findings),true,btrim(p_resolution_reference),btrim(p_reason),
                statement_timestamp(),p_actor_id,p_authorization_reference);
            SET CONSTRAINTS app.lease_pet_departures_validate,
                app.pet_deposit_refund_reviews_validate IMMEDIATE;
            v_result := app.deposit_snapshot(p_deposit_id)
                || jsonb_build_object('pet_departure_id',p_departure_id,
                    'pet_refund_review_id',p_review_id,'refund_qualified',true);
            PERFORM app.record_deposit_command(p_property_id,p_actor_id,'deposit.pet_refund.qualify',
                p_idempotency_key,p_request_digest,p_deposit_id,p_reason,p_authorization_reference,v_result);
            RETURN v_result;
        END;
        $$;
        """
    )
    tables = (
        "deposit_required_amount_adjustments",
        "deposit_receipt_reversals",
        "deposit_commands",
    )
    for table in tables:
        op.execute(
            f"REVOKE ALL ON TABLE app.{table} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT SELECT ON TABLE app.{table} TO prm_runtime, prm_financial")
    functions = (
        "app.deposit_property_id(uuid)",
        "app.deposit_snapshot(uuid)",
        "app.validate_deposit_source()",
        "app.reject_deposit_domain_history_loss()",
        "app.validate_deposit_required_adjustment()",
        "app.validate_deposit_receipt_reversal()",
        "app.validate_lease_deposit_disposition()",
        "app.replay_deposit_command(uuid,uuid,text,uuid,text)",
        "app.record_deposit_command(uuid,uuid,text,uuid,text,uuid,text,text,jsonb)",
        "app.create_pet_deposit(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text)",
        "app.adjust_deposit_required_amount(uuid,uuid,uuid,text,uuid,uuid,text,bigint,date,text,text)",
        "app.reverse_deposit_receipt(uuid,uuid,uuid,text,uuid,uuid,text,text)",
        "app.record_lease_deposit_disposition(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text)",
        "app.reverse_deposit_disposition(uuid,uuid,uuid,text,uuid,uuid,text,text,text)",
        "app.qualify_active_lease_pet_refund(uuid,uuid,uuid,text,uuid,uuid,uuid,date,bigint,text,text,text,text)",
    )
    for function in functions:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute("GRANT EXECUTE ON FUNCTION app.deposit_snapshot(uuid) TO prm_runtime, prm_financial")
    for function in functions[9:]:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    """Refuse rollback that could erase Deposit liability history."""
    raise RuntimeError("Deposit domain migration is forward-only")
