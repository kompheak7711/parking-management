"""Add transactional Reservation cancellation Deposit outcomes."""

from alembic import op

revision = "20260825_21"
down_revision = "20260825_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the bounded V1-031 financial outcome and correction boundary."""
    op.execute(
        """
        DO $$
        DECLARE
            financial_role pg_catalog.pg_roles%ROWTYPE;
            unsafe_public_function text;
        BEGIN
            SELECT * INTO financial_role
            FROM pg_catalog.pg_roles
            WHERE rolname = 'prm_financial';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'prm_financial role must exist before V1-031 migration';
            END IF;

            SELECT procedure.oid::regprocedure::text
            INTO unsafe_public_function
            FROM pg_catalog.pg_proc AS procedure
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    procedure.proacl,
                    pg_catalog.acldefault('f', procedure.proowner)
                )
            ) AS privilege
            WHERE privilege.grantee = 0
              AND procedure.prorettype <> 'pg_catalog.trigger'::regtype
              AND namespace.nspname <> 'pg_catalog'
              AND namespace.nspname <> 'information_schema'
              AND namespace.nspname NOT LIKE 'pg_toast%'
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS dependency
                  WHERE dependency.classid = 'pg_catalog.pg_proc'::regclass
                    AND dependency.objid = procedure.oid
                    AND dependency.deptype = 'e'
              )
            ORDER BY procedure.oid
            LIMIT 1;
            IF unsafe_public_function IS NOT NULL THEN
                RAISE EXCEPTION
                    'prm_financial role must have safe attributes and only bounded CONNECT authority before V1-031 migration: PUBLIC can execute %',
                    unsafe_public_function;
            END IF;

            IF NOT financial_role.rolcanlogin
               OR financial_role.rolinherit
               OR financial_role.rolsuper
               OR financial_role.rolcreatedb
               OR financial_role.rolcreaterole
               OR financial_role.rolreplication
               OR financial_role.rolbypassrls
               OR EXISTS (
                   SELECT 1 FROM pg_catalog.pg_auth_members
                   WHERE roleid = financial_role.oid OR member = financial_role.oid
               )
               OR NOT pg_catalog.has_database_privilege(
                   financial_role.oid, pg_catalog.current_database(), 'CONNECT'
               )
               OR pg_catalog.has_database_privilege(
                   financial_role.oid, pg_catalog.current_database(), 'CREATE'
               )
               OR pg_catalog.has_database_privilege(
                   financial_role.oid, pg_catalog.current_database(), 'TEMP'
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_namespace AS namespace
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(
                           namespace.nspacl,
                           pg_catalog.acldefault('n', namespace.nspowner)
                       )
                   ) AS privilege
                   WHERE privilege.grantee = financial_role.oid
                      OR (
                          privilege.grantee = 0
                          AND privilege.privilege_type = 'CREATE'
                          AND namespace.nspname <> 'pg_catalog'
                          AND namespace.nspname <> 'information_schema'
                          AND namespace.nspname NOT LIKE 'pg_toast%'
                      )
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_class AS relation
                   JOIN pg_catalog.pg_namespace AS namespace
                     ON namespace.oid = relation.relnamespace
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(
                           relation.relacl,
                           pg_catalog.acldefault(
                               CASE WHEN relation.relkind = 'S' THEN 'S'::"char" ELSE 'r'::"char" END,
                               relation.relowner
                           )
                       )
                   ) AS privilege
                   WHERE privilege.grantee = financial_role.oid
                      OR (
                          privilege.grantee = 0
                          AND namespace.nspname <> 'pg_catalog'
                          AND namespace.nspname <> 'information_schema'
                          AND namespace.nspname NOT LIKE 'pg_toast%'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM pg_catalog.pg_depend AS dependency
                              WHERE dependency.classid = 'pg_catalog.pg_class'::regclass
                                AND dependency.objid = relation.oid
                                AND dependency.deptype = 'e'
                          )
                      )
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_attribute AS attribute
                   JOIN pg_catalog.pg_class AS relation
                     ON relation.oid = attribute.attrelid
                   JOIN pg_catalog.pg_namespace AS namespace
                     ON namespace.oid = relation.relnamespace
                   CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS privilege
                   WHERE attribute.attacl IS NOT NULL
                     AND (
                         privilege.grantee = financial_role.oid
                         OR (
                             privilege.grantee = 0
                             AND namespace.nspname <> 'pg_catalog'
                             AND namespace.nspname <> 'information_schema'
                             AND namespace.nspname NOT LIKE 'pg_toast%'
                             AND NOT EXISTS (
                                 SELECT 1
                                 FROM pg_catalog.pg_depend AS dependency
                                 WHERE dependency.classid = 'pg_catalog.pg_class'::regclass
                                   AND dependency.objid = relation.oid
                                   AND dependency.deptype = 'e'
                             )
                         )
                     )
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_proc AS procedure
                   JOIN pg_catalog.pg_namespace AS namespace
                     ON namespace.oid = procedure.pronamespace
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(
                           procedure.proacl,
                           pg_catalog.acldefault('f', procedure.proowner)
                       )
                   ) AS privilege
                   WHERE privilege.grantee = financial_role.oid
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_type AS type_definition
                   JOIN pg_catalog.pg_namespace AS namespace
                     ON namespace.oid = type_definition.typnamespace
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(
                           type_definition.typacl,
                           pg_catalog.acldefault('T', type_definition.typowner)
                       )
                   ) AS privilege
                   WHERE privilege.grantee = financial_role.oid
                      OR (
                          type_definition.typacl IS NOT NULL
                          AND privilege.grantee = 0
                          AND namespace.nspname <> 'pg_catalog'
                          AND namespace.nspname <> 'information_schema'
                          AND namespace.nspname NOT LIKE 'pg_toast%'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM pg_catalog.pg_depend AS dependency
                              WHERE dependency.classid = 'pg_catalog.pg_type'::regclass
                                AND dependency.objid = type_definition.oid
                                AND dependency.deptype = 'e'
                          )
                      )
               )
               OR EXISTS (
                   SELECT 1 FROM pg_catalog.pg_default_acl AS default_acl
                   CROSS JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl) AS privilege
                   WHERE default_acl.defaclrole = financial_role.oid
                      OR privilege.grantee = financial_role.oid
                      OR privilege.grantee = 0
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_largeobject_metadata AS large_object
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(
                           large_object.lomacl,
                           pg_catalog.acldefault('L', large_object.lomowner)
                       )
                   ) AS privilege
                   WHERE large_object.lomowner = financial_role.oid
                      OR privilege.grantee = financial_role.oid
                      OR privilege.grantee = 0
               )
               OR EXISTS (
                   SELECT 1 FROM pg_catalog.pg_database AS database
                   WHERE database.datname = pg_catalog.current_database()
                     AND database.datdba = financial_role.oid
                   UNION ALL
                   SELECT 1 FROM pg_catalog.pg_namespace
                   WHERE nspowner = financial_role.oid
                   UNION ALL
                   SELECT 1 FROM pg_catalog.pg_class
                   WHERE relowner = financial_role.oid
                   UNION ALL
                   SELECT 1 FROM pg_catalog.pg_proc
                   WHERE proowner = financial_role.oid
                   UNION ALL
                   SELECT 1 FROM pg_catalog.pg_type
                   WHERE typowner = financial_role.oid
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_shdepend AS dependency
                   JOIN pg_catalog.pg_database AS target_database
                     ON target_database.datname = pg_catalog.current_database()
                   WHERE dependency.refclassid = 'pg_catalog.pg_authid'::regclass
                     AND dependency.refobjid = financial_role.oid
                     AND dependency.dbid = target_database.oid
                     AND dependency.deptype = 'o'
               )
            THEN
                RAISE EXCEPTION
                    'prm_financial role must have safe attributes and only bounded CONNECT authority before V1-031 migration';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TABLE app.deposit_dispositions (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            deposit_id uuid NOT NULL REFERENCES app.deposits(id) ON DELETE RESTRICT,
            amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
            governing_reservation_id uuid NOT NULL
                REFERENCES app.reservations(id) ON DELETE RESTRICT,
            source_lifecycle_event_id uuid NOT NULL
                REFERENCES app.reservation_lifecycle_events(id) ON DELETE RESTRICT,
            effective_date date NOT NULL,
            reason text NOT NULL,
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            authorization_reference text NOT NULL,
            CONSTRAINT reservation_deposit_disposition_text_normalized CHECK (
                length(btrim(reason)) > 0 AND reason = btrim(reason)
                AND length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX deposit_dispositions_source_history_idx "
        "ON app.deposit_dispositions(deposit_id, occurred_at, id)"
    )
    op.execute(
        "CREATE INDEX deposit_dispositions_reservation_history_idx "
        "ON app.deposit_dispositions(governing_reservation_id, occurred_at, id)"
    )
    op.execute(
        """
        CREATE TABLE app.deposit_disposition_reversals (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            deposit_disposition_id uuid NOT NULL UNIQUE
                REFERENCES app.deposit_dispositions(id) ON DELETE RESTRICT,
            reason text NOT NULL,
            evidence_reference text NOT NULL,
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            authorization_reference text NOT NULL,
            CONSTRAINT reservation_deposit_disposition_reversal_text_normalized CHECK (
                length(btrim(reason)) > 0 AND reason = btrim(reason)
                AND length(btrim(evidence_reference)) > 0
                AND evidence_reference = btrim(evidence_reference)
                AND length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.refunds (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            refund_number text NOT NULL UNIQUE,
            recipient_customer_id uuid NOT NULL
                REFERENCES app.customers(id) ON DELETE RESTRICT,
            source_deposit_id uuid NOT NULL
                REFERENCES app.deposits(id) ON DELETE RESTRICT,
            source_lifecycle_event_id uuid NOT NULL
                REFERENCES app.reservation_lifecycle_events(id) ON DELETE RESTRICT,
            usd_accounting_value_cents bigint NOT NULL
                CHECK (usd_accounting_value_cents > 0),
            refund_currency text NOT NULL CHECK (refund_currency = 'USD'),
            refund_amount_minor bigint NOT NULL CHECK (refund_amount_minor > 0),
            reason text NOT NULL,
            processed_at timestamptz NOT NULL,
            processed_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            authorization_reference text NOT NULL,
            CONSTRAINT reservation_refund_usd_value_exact CHECK (
                refund_amount_minor = usd_accounting_value_cents
            ),
            CONSTRAINT reservation_refund_text_normalized CHECK (
                length(btrim(refund_number)) > 0
                AND refund_number = btrim(refund_number)
                AND length(refund_number) <= 128
                AND length(btrim(reason)) > 0 AND reason = btrim(reason)
                AND length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX reservation_refunds_source_history_idx "
        "ON app.refunds(source_deposit_id, processed_at, id)"
    )
    op.execute(
        """
        CREATE TABLE app.refund_corrections (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            refund_id uuid NOT NULL REFERENCES app.refunds(id) ON DELETE RESTRICT,
            correction_kind text NOT NULL
                CHECK (correction_kind IN ('VALUE_CORRECTION', 'CORRECTION_REVERSAL')),
            reverses_correction_id uuid UNIQUE
                REFERENCES app.refund_corrections(id) ON DELETE RESTRICT,
            source_balance_effect_usd_cents bigint NOT NULL
                CHECK (source_balance_effect_usd_cents <> 0),
            previous_net_refund_usd_cents bigint NOT NULL
                CHECK (previous_net_refund_usd_cents >= 0),
            resulting_net_refund_usd_cents bigint NOT NULL
                CHECK (resulting_net_refund_usd_cents >= 0),
            reason text NOT NULL,
            evidence_reference text NOT NULL,
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            authorization_reference text NOT NULL,
            CONSTRAINT reservation_refund_correction_shape CHECK (
                (
                    correction_kind = 'VALUE_CORRECTION'
                    AND reverses_correction_id IS NULL
                    AND source_balance_effect_usd_cents > 0
                ) OR (
                    correction_kind = 'CORRECTION_REVERSAL'
                    AND reverses_correction_id IS NOT NULL
                    AND source_balance_effect_usd_cents < 0
                )
            ),
            CONSTRAINT reservation_refund_correction_arithmetic CHECK (
                resulting_net_refund_usd_cents
                    = previous_net_refund_usd_cents - source_balance_effect_usd_cents
            ),
            CONSTRAINT reservation_refund_correction_text_normalized CHECK (
                length(btrim(reason)) > 0 AND reason = btrim(reason)
                AND length(btrim(evidence_reference)) > 0
                AND evidence_reference = btrim(evidence_reference)
                AND length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX reservation_refund_corrections_history_idx "
        "ON app.refund_corrections(refund_id, occurred_at, id)"
    )
    op.execute(
        """
        ALTER TABLE app.reservation_commands
        DROP CONSTRAINT reservation_commands_action_check
        """
    )
    op.execute(
        """
        ALTER TABLE app.reservation_commands
        ADD CONSTRAINT reservation_commands_action_check CHECK (
            action IN (
                'reservation.create',
                'reservation.extend',
                'reservation.expire',
                'reservation.cancel',
                'reservation.cancel.outcome',
                'reservation.expire.outcome',
                'reservation.outcome.complete',
                'reservation.outcome.correct'
            )
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_reservation_financial_history_loss()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'Reservation financial history is append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table in (
        "deposit_dispositions",
        "deposit_disposition_reversals",
        "refunds",
        "refund_corrections",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_update_or_delete
            BEFORE UPDATE OR DELETE ON app.{table}
            FOR EACH ROW EXECUTE FUNCTION app.reject_reservation_financial_history_loss()
            """
        )

    op.execute(
        """
        CREATE FUNCTION app.validate_reservation_financial_outcome()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_customer_id uuid;
            v_responsibility text;
            v_business_date date;
            v_received bigint;
            v_disposed bigint;
            v_refunded bigint;
            v_amount bigint;
            v_deposit_id uuid;
        BEGIN
            IF TG_TABLE_NAME = 'deposit_dispositions' THEN
                SELECT reservation.customer_id,
                       reservation.cancellation_responsibility,
                       event.business_date
                INTO v_customer_id, v_responsibility, v_business_date
                FROM app.reservation_lifecycle_events AS event
                JOIN app.reservations AS reservation
                  ON reservation.id = event.reservation_id
                JOIN app.deposits AS deposit
                  ON deposit.reservation_id = reservation.id
                WHERE event.id = NEW.source_lifecycle_event_id
                  AND reservation.id = NEW.governing_reservation_id
                  AND deposit.id = NEW.deposit_id
                  AND reservation.status = 'CANCELLED'
                FOR UPDATE OF deposit;
                IF NOT FOUND OR v_responsibility <> 'CUSTOMER'
                    OR NEW.effective_date <> v_business_date
                THEN
                    RAISE EXCEPTION 'Deposit disposition source is not an eligible Customer-caused cancellation'
                        USING ERRCODE = '23514';
                END IF;
                v_amount := NEW.amount_usd_cents;
                v_deposit_id := NEW.deposit_id;
            ELSE
                SELECT reservation.customer_id,
                       reservation.cancellation_responsibility,
                       event.business_date
                INTO v_customer_id, v_responsibility, v_business_date
                FROM app.reservation_lifecycle_events AS event
                JOIN app.reservations AS reservation
                  ON reservation.id = event.reservation_id
                JOIN app.deposits AS deposit
                  ON deposit.reservation_id = reservation.id
                WHERE event.id = NEW.source_lifecycle_event_id
                  AND deposit.id = NEW.source_deposit_id
                  AND reservation.status = 'CANCELLED'
                FOR UPDATE OF deposit;
                IF NOT FOUND OR v_responsibility <> 'PROPERTY'
                    OR NEW.recipient_customer_id <> v_customer_id
                THEN
                    RAISE EXCEPTION 'Refund source is not an eligible Property-caused cancellation'
                        USING ERRCODE = '23514';
                END IF;
                v_amount := NEW.usd_accounting_value_cents;
                v_deposit_id := NEW.source_deposit_id;
            END IF;

            SELECT COALESCE(sum(receipt.amount_usd_cents), 0)::bigint
            INTO v_received
            FROM app.deposit_receipts AS receipt
            WHERE receipt.deposit_id = v_deposit_id;

            SELECT COALESCE(sum(disposition.amount_usd_cents), 0)::bigint
            INTO v_disposed
            FROM app.deposit_dispositions AS disposition
            WHERE disposition.deposit_id = v_deposit_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM app.deposit_disposition_reversals AS reversal
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

            IF v_amount > v_received - v_disposed - v_refunded THEN
                RAISE EXCEPTION 'Reservation Deposit outcome exceeds held refundable value'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER deposit_dispositions_validate_source
        BEFORE INSERT ON app.deposit_dispositions
        FOR EACH ROW EXECUTE FUNCTION app.validate_reservation_financial_outcome()
        """
    )
    op.execute(
        """
        CREATE TRIGGER refunds_validate_source
        BEFORE INSERT ON app.refunds
        FOR EACH ROW EXECUTE FUNCTION app.validate_reservation_financial_outcome()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.validate_refund_correction()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_original bigint;
            v_current bigint;
            v_reversed app.refund_corrections%ROWTYPE;
        BEGIN
            SELECT refund.usd_accounting_value_cents
            INTO STRICT v_original
            FROM app.refunds AS refund
            JOIN app.deposits AS deposit ON deposit.id = refund.source_deposit_id
            WHERE refund.id = NEW.refund_id
            FOR UPDATE OF refund, deposit;

            SELECT v_original - COALESCE(sum(correction.source_balance_effect_usd_cents), 0)
            INTO v_current
            FROM app.refund_corrections AS correction
            WHERE correction.refund_id = NEW.refund_id;

            IF NEW.previous_net_refund_usd_cents <> v_current
                OR NEW.resulting_net_refund_usd_cents > v_original
            THEN
                RAISE EXCEPTION 'Refund correction does not continue the current immutable history'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.correction_kind = 'VALUE_CORRECTION' THEN
                IF NEW.source_balance_effect_usd_cents > v_current THEN
                    RAISE EXCEPTION 'Refund correction exceeds current net Refund value'
                        USING ERRCODE = '23514';
                END IF;
            ELSE
                SELECT correction.* INTO v_reversed
                FROM app.refund_corrections AS correction
                WHERE correction.id = NEW.reverses_correction_id
                  AND correction.refund_id = NEW.refund_id
                  AND correction.correction_kind = 'VALUE_CORRECTION';
                IF NOT FOUND
                    OR NEW.source_balance_effect_usd_cents
                        <> -v_reversed.source_balance_effect_usd_cents
                    OR EXISTS (
                        SELECT 1 FROM app.refund_corrections AS prior_reversal
                        WHERE prior_reversal.reverses_correction_id = v_reversed.id
                    )
                THEN
                    RAISE EXCEPTION 'Refund correction reversal is not valid'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER refund_corrections_validate_history
        BEFORE INSERT ON app.refund_corrections
        FOR EACH ROW EXECUTE FUNCTION app.validate_refund_correction()
        """
    )

    op.execute(
        """
        CREATE FUNCTION app.assert_reservation_financial_outcome_complete()
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
                IF NEW.status <> 'CANCELLED' THEN
                    RETURN NULL;
                END IF;
            ELSIF TG_TABLE_NAME = 'deposit_dispositions' THEN
                v_reservation_id := NEW.governing_reservation_id;
            ELSIF TG_TABLE_NAME = 'deposit_disposition_reversals' THEN
                SELECT disposition.governing_reservation_id
                INTO STRICT v_reservation_id
                FROM app.deposit_dispositions AS disposition
                WHERE disposition.id = NEW.deposit_disposition_id;
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
            WHERE receipt.deposit_id = v_deposit_id;

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
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER reservations_financial_outcome_complete
        AFTER UPDATE OF status ON app.reservations
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION app.assert_reservation_financial_outcome_complete()
        """
    )
    for table in (
        "deposit_dispositions",
        "deposit_disposition_reversals",
        "refunds",
        "refund_corrections",
    ):
        op.execute(
            f"""
            CREATE CONSTRAINT TRIGGER {table}_reservation_outcome_complete
            AFTER INSERT ON app.{table}
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.assert_reservation_financial_outcome_complete()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_truncate
            BEFORE TRUNCATE ON app.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_reservation_financial_history_loss()
            """
        )

    op.execute(
        """
        CREATE FUNCTION app.create_reservation_deposit_outcome(
            p_outcome_id uuid,
            p_refund_number text,
            p_reservation_id uuid,
            p_reason text,
            p_authorization_reference text,
            p_actor_id uuid,
            p_audit_source text,
            p_correlation_id uuid
        )
        RETURNS TABLE(
            lifecycle_event_id uuid,
            deposit_id uuid,
            outcome_kind text,
            outcome_id uuid,
            amount_usd_cents bigint,
            refund_number text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_reservation app.reservations%ROWTYPE;
            v_event app.reservation_lifecycle_events%ROWTYPE;
            v_deposit_id uuid;
            v_received bigint;
            v_property_id uuid;
        BEGIN
            IF p_outcome_id = '00000000-0000-0000-0000-000000000000'::uuid
                OR COALESCE(btrim(p_reason), '') = ''
                OR COALESCE(btrim(p_authorization_reference), '') = ''
            THEN
                RAISE EXCEPTION 'Reservation Deposit outcome evidence is invalid'
                    USING ERRCODE = '23514';
            END IF;
            SELECT reservation.* INTO STRICT v_reservation
            FROM app.reservations AS reservation
            WHERE reservation.id = p_reservation_id
              AND reservation.status = 'CANCELLED'
            FOR UPDATE;
            SELECT event.* INTO STRICT v_event
            FROM app.reservation_lifecycle_events AS event
            WHERE event.reservation_id = p_reservation_id
              AND event.resulting_version = v_reservation.version;
            SELECT deposit.id, unit.property_id
            INTO STRICT v_deposit_id, v_property_id
            FROM app.deposits AS deposit
            JOIN app.units AS unit ON unit.id = v_reservation.unit_id
            WHERE deposit.reservation_id = p_reservation_id
            FOR UPDATE OF deposit;
            SELECT COALESCE(sum(receipt.amount_usd_cents), 0)::bigint
            INTO v_received
            FROM app.deposit_receipts AS receipt
            WHERE receipt.deposit_id = v_deposit_id;
            IF v_received <= 0 THEN
                RAISE EXCEPTION 'Reservation Deposit has no received value to classify'
                    USING ERRCODE = '23514';
            END IF;

            IF v_reservation.cancellation_responsibility = 'CUSTOMER' THEN
                IF p_refund_number IS NOT NULL
                    OR p_authorization_reference <> 'reservation_deposits.dispose'
                THEN
                    RAISE EXCEPTION 'Customer-caused cancellation cannot create a Refund'
                        USING ERRCODE = '23514';
                END IF;
                INSERT INTO app.deposit_dispositions (
                    id, deposit_id, amount_usd_cents, governing_reservation_id,
                    source_lifecycle_event_id, effective_date, reason, occurred_at,
                    actor_id, authorization_reference
                ) VALUES (
                    p_outcome_id, v_deposit_id, v_received, p_reservation_id,
                    v_event.id, v_event.business_date, btrim(p_reason),
                    statement_timestamp(), p_actor_id, btrim(p_authorization_reference)
                );
                outcome_kind := 'NON_REFUNDABLE_DISPOSITION';
                refund_number := NULL;
            ELSIF v_reservation.cancellation_responsibility = 'PROPERTY' THEN
                IF COALESCE(btrim(p_refund_number), '') = ''
                    OR p_refund_number <> btrim(p_refund_number)
                    OR p_authorization_reference <> 'reservation_deposits.refund'
                THEN
                    RAISE EXCEPTION 'Property-caused cancellation requires a normalized Refund number'
                        USING ERRCODE = '23514';
                END IF;
                INSERT INTO app.refunds (
                    id, refund_number, recipient_customer_id, source_deposit_id,
                    source_lifecycle_event_id, usd_accounting_value_cents,
                    refund_currency, refund_amount_minor, reason, processed_at,
                    processed_by, authorization_reference
                ) VALUES (
                    p_outcome_id, p_refund_number, v_reservation.customer_id,
                    v_deposit_id, v_event.id, v_received, 'USD', v_received,
                    btrim(p_reason), statement_timestamp(), p_actor_id,
                    btrim(p_authorization_reference)
                );
                outcome_kind := 'REFUND';
                refund_number := p_refund_number;
            ELSE
                RAISE EXCEPTION 'Reservation cancellation responsibility is not classified'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type,
                entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                customer_id, unit_id
            ) VALUES (
                p_outcome_id, statement_timestamp(), v_event.business_date, p_actor_id,
                CASE WHEN outcome_kind = 'REFUND'
                    THEN 'reservation.deposit.refunded'
                    ELSE 'reservation.deposit.forfeited' END,
                CASE WHEN outcome_kind = 'REFUND' THEN 'refund'
                    ELSE 'deposit_disposition' END,
                p_outcome_id, btrim(p_reason), btrim(p_authorization_reference),
                v_property_id,
                jsonb_build_object(
                    'reservation_id', p_reservation_id,
                    'deposit_id', v_deposit_id,
                    'deposit_received_usd_cents', v_received,
                    'outcome_state', 'UNCLASSIFIED'
                ),
                jsonb_build_object(
                    'reservation_id', p_reservation_id,
                    'deposit_id', v_deposit_id,
                    'lifecycle_event_id', v_event.id,
                    'outcome_kind', outcome_kind,
                    'amount_usd_cents', v_received,
                    'refund_number', refund_number
                ),
                p_correlation_id, p_audit_source, 'SUCCEEDED',
                v_reservation.customer_id, v_reservation.unit_id
            );
            lifecycle_event_id := v_event.id;
            deposit_id := v_deposit_id;
            outcome_id := p_outcome_id;
            amount_usd_cents := v_received;
            RETURN NEXT;
        END;
        $$
        """
    )

    lifecycle_result = """
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
    op.execute(
        f"""
        CREATE FUNCTION app.cancel_reservation_v2(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_event_id uuid,
            p_outcome_id uuid,
            p_refund_number text,
            p_reservation_id uuid,
            p_expected_version integer,
            p_reason_code text,
            p_responsibility text,
            p_property_could_provide_unit boolean,
            p_reason_memo text,
            p_coordination_reference text,
            p_lifecycle_authorization_reference text,
            p_outcome_authorization_reference text,
            p_actor_id uuid
        )
        RETURNS TABLE({lifecycle_result})
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_command app.reservation_commands%ROWTYPE;
            v_lifecycle record;
            v_outcome record;
        BEGIN
            IF p_lifecycle_authorization_reference <> 'reservations.cancel' THEN
                RAISE EXCEPTION 'Reservation cancellation authorization is invalid'
                    USING ERRCODE = '23514';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'reservation-command/' || p_actor_id::text || '/'
                    || p_property_id::text || '/reservation.cancel.outcome/'
                    || p_idempotency_key::text, 0
                )
            );
            SELECT command.* INTO v_command
            FROM app.reservation_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'reservation.cancel.outcome'
              AND command.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_command.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Reservation idempotency key was reused'
                        USING ERRCODE = 'P0001';
                END IF;
                RETURN QUERY SELECT
                    (v_command.result_snapshot ->> 'reservation_id')::uuid,
                    (v_command.result_snapshot ->> 'unit_id')::uuid,
                    v_command.result_snapshot ->> 'status',
                    v_command.result_snapshot ->> 'cancellation_reason_code',
                    v_command.result_snapshot ->> 'cancellation_responsibility',
                    (v_command.result_snapshot ->> 'effective_expiration_date')::date,
                    (v_command.result_snapshot ->> 'version')::integer,
                    v_command.result_snapshot ->> 'unit_status',
                    (v_command.result_snapshot ->> 'unit_version')::integer,
                    (v_command.result_snapshot ->> 'deposit_id')::uuid,
                    (v_command.result_snapshot ->> 'deposit_received_usd_cents')::bigint,
                    v_command.result_snapshot ->> 'deposit_outcome_state',
                    (v_command.result_snapshot ->> 'outcome_id')::uuid,
                    v_command.result_snapshot ->> 'refund_number';
                RETURN;
            END IF;
            SELECT * INTO STRICT v_lifecycle
            FROM app.cancel_reservation(
                p_property_id, p_idempotency_key, p_request_digest, p_event_id,
                p_reservation_id, p_expected_version, p_reason_code, p_responsibility,
                p_property_could_provide_unit, p_reason_memo,
                p_coordination_reference, p_lifecycle_authorization_reference,
                p_actor_id
            );
            SELECT * INTO STRICT v_outcome
            FROM app.create_reservation_deposit_outcome(
                p_outcome_id, p_refund_number, p_reservation_id,
                COALESCE(nullif(btrim(p_reason_memo), ''), p_reason_code),
                p_outcome_authorization_reference, p_actor_id, 'API',
                p_idempotency_key
            );
            INSERT INTO app.reservation_commands (
                actor_id, property_id, action, idempotency_key, request_digest,
                result_id, result_snapshot
            ) VALUES (
                p_actor_id, p_property_id, 'reservation.cancel.outcome',
                p_idempotency_key, p_request_digest, p_outcome_id,
                jsonb_build_object(
                    'reservation_id', v_lifecycle.reservation_id,
                    'unit_id', v_lifecycle.unit_id, 'status', v_lifecycle.status,
                    'cancellation_reason_code', v_lifecycle.cancellation_reason_code,
                    'cancellation_responsibility', v_lifecycle.cancellation_responsibility,
                    'effective_expiration_date', v_lifecycle.effective_expiration_date,
                    'version', v_lifecycle.version, 'unit_status', v_lifecycle.unit_status,
                    'unit_version', v_lifecycle.unit_version,
                    'deposit_id', v_outcome.deposit_id,
                    'deposit_received_usd_cents', v_outcome.amount_usd_cents,
                    'deposit_outcome_state', v_outcome.outcome_kind,
                    'outcome_id', v_outcome.outcome_id,
                    'refund_number', v_outcome.refund_number
                )
            );
            RETURN QUERY SELECT
                v_lifecycle.reservation_id, v_lifecycle.unit_id, v_lifecycle.status,
                v_lifecycle.cancellation_reason_code,
                v_lifecycle.cancellation_responsibility,
                v_lifecycle.effective_expiration_date, v_lifecycle.version,
                v_lifecycle.unit_status, v_lifecycle.unit_version,
                v_outcome.deposit_id, v_outcome.amount_usd_cents,
                v_outcome.outcome_kind, v_outcome.outcome_id,
                v_outcome.refund_number;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION app.expire_reservation_v2(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_event_id uuid,
            p_outcome_id uuid,
            p_reservation_id uuid,
            p_expected_version integer,
            p_property_could_provide_unit boolean,
            p_lifecycle_authorization_reference text,
            p_outcome_authorization_reference text,
            p_actor_id uuid
        )
        RETURNS TABLE({lifecycle_result})
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_command app.reservation_commands%ROWTYPE;
            v_lifecycle record;
            v_outcome record;
        BEGIN
            IF p_lifecycle_authorization_reference <> 'reservations.cancel'
                OR p_outcome_authorization_reference <> 'reservation_deposits.dispose'
            THEN
                RAISE EXCEPTION 'Reservation expiration authorization is invalid'
                    USING ERRCODE = '23514';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'reservation-command/' || p_actor_id::text || '/'
                    || p_property_id::text || '/reservation.expire.outcome/'
                    || p_idempotency_key::text, 0
                )
            );
            SELECT command.* INTO v_command
            FROM app.reservation_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'reservation.expire.outcome'
              AND command.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_command.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Reservation idempotency key was reused'
                        USING ERRCODE = 'P0001';
                END IF;
                RETURN QUERY SELECT
                    (v_command.result_snapshot ->> 'reservation_id')::uuid,
                    (v_command.result_snapshot ->> 'unit_id')::uuid,
                    v_command.result_snapshot ->> 'status',
                    v_command.result_snapshot ->> 'cancellation_reason_code',
                    v_command.result_snapshot ->> 'cancellation_responsibility',
                    (v_command.result_snapshot ->> 'effective_expiration_date')::date,
                    (v_command.result_snapshot ->> 'version')::integer,
                    v_command.result_snapshot ->> 'unit_status',
                    (v_command.result_snapshot ->> 'unit_version')::integer,
                    (v_command.result_snapshot ->> 'deposit_id')::uuid,
                    (v_command.result_snapshot ->> 'deposit_received_usd_cents')::bigint,
                    v_command.result_snapshot ->> 'deposit_outcome_state',
                    (v_command.result_snapshot ->> 'outcome_id')::uuid,
                    v_command.result_snapshot ->> 'refund_number';
                RETURN;
            END IF;
            SELECT * INTO STRICT v_lifecycle
            FROM app.expire_reservation(
                p_property_id, p_idempotency_key, p_request_digest, p_event_id,
                p_reservation_id, p_expected_version,
                p_property_could_provide_unit,
                p_lifecycle_authorization_reference, p_actor_id
            );
            SELECT * INTO STRICT v_outcome
            FROM app.create_reservation_deposit_outcome(
                p_outcome_id, NULL, p_reservation_id,
                'Reservation expired while the Property could provide the Unit',
                p_outcome_authorization_reference, p_actor_id, 'SCHEDULED',
                p_idempotency_key
            );
            INSERT INTO app.reservation_commands (
                actor_id, property_id, action, idempotency_key, request_digest,
                result_id, result_snapshot
            ) VALUES (
                p_actor_id, p_property_id, 'reservation.expire.outcome',
                p_idempotency_key, p_request_digest, p_outcome_id,
                jsonb_build_object(
                    'reservation_id', v_lifecycle.reservation_id,
                    'unit_id', v_lifecycle.unit_id, 'status', v_lifecycle.status,
                    'cancellation_reason_code', v_lifecycle.cancellation_reason_code,
                    'cancellation_responsibility', v_lifecycle.cancellation_responsibility,
                    'effective_expiration_date', v_lifecycle.effective_expiration_date,
                    'version', v_lifecycle.version, 'unit_status', v_lifecycle.unit_status,
                    'unit_version', v_lifecycle.unit_version,
                    'deposit_id', v_outcome.deposit_id,
                    'deposit_received_usd_cents', v_outcome.amount_usd_cents,
                    'deposit_outcome_state', v_outcome.outcome_kind,
                    'outcome_id', v_outcome.outcome_id, 'refund_number', NULL
                )
            );
            RETURN QUERY SELECT
                v_lifecycle.reservation_id, v_lifecycle.unit_id, v_lifecycle.status,
                v_lifecycle.cancellation_reason_code,
                v_lifecycle.cancellation_responsibility,
                v_lifecycle.effective_expiration_date, v_lifecycle.version,
                v_lifecycle.unit_status, v_lifecycle.unit_version,
                v_outcome.deposit_id, v_outcome.amount_usd_cents,
                v_outcome.outcome_kind, v_outcome.outcome_id, NULL::text;
        END;
        $$
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION app.complete_reservation_deposit_outcome(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_outcome_id uuid,
            p_refund_number text,
            p_reservation_id uuid,
            p_expected_version integer,
            p_reason text,
            p_outcome_authorization_reference text,
            p_actor_id uuid
        )
        RETURNS TABLE({lifecycle_result})
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_command app.reservation_commands%ROWTYPE;
            v_reservation app.reservations%ROWTYPE;
            v_unit app.units%ROWTYPE;
            v_outcome record;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'reservation-command/' || p_actor_id::text || '/'
                    || p_property_id::text || '/reservation.outcome.complete/'
                    || p_idempotency_key::text, 0
                )
            );
            SELECT command.* INTO v_command
            FROM app.reservation_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'reservation.outcome.complete'
              AND command.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_command.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Reservation idempotency key was reused'
                        USING ERRCODE = 'P0001';
                END IF;
                RETURN QUERY SELECT
                    (v_command.result_snapshot ->> 'reservation_id')::uuid,
                    (v_command.result_snapshot ->> 'unit_id')::uuid,
                    v_command.result_snapshot ->> 'status',
                    v_command.result_snapshot ->> 'cancellation_reason_code',
                    v_command.result_snapshot ->> 'cancellation_responsibility',
                    (v_command.result_snapshot ->> 'effective_expiration_date')::date,
                    (v_command.result_snapshot ->> 'version')::integer,
                    v_command.result_snapshot ->> 'unit_status',
                    (v_command.result_snapshot ->> 'unit_version')::integer,
                    (v_command.result_snapshot ->> 'deposit_id')::uuid,
                    (v_command.result_snapshot ->> 'deposit_received_usd_cents')::bigint,
                    v_command.result_snapshot ->> 'deposit_outcome_state',
                    (v_command.result_snapshot ->> 'outcome_id')::uuid,
                    v_command.result_snapshot ->> 'refund_number';
                RETURN;
            END IF;
            SELECT reservation.* INTO v_reservation
            FROM app.reservations AS reservation
            JOIN app.units AS unit ON unit.id = reservation.unit_id
            WHERE reservation.id = p_reservation_id
              AND unit.property_id = p_property_id
            FOR UPDATE OF reservation;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Reservation was not found in the Property'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_reservation.status <> 'CANCELLED'
                OR v_reservation.version <> p_expected_version
            THEN
                RAISE EXCEPTION 'Reservation outcome completion version is invalid'
                    USING ERRCODE = '40001';
            END IF;
            IF EXISTS (
                SELECT 1 FROM app.deposit_dispositions AS disposition
                WHERE disposition.governing_reservation_id = p_reservation_id
            ) OR EXISTS (
                SELECT 1 FROM app.refunds AS refund
                JOIN app.reservation_lifecycle_events AS event
                  ON event.id = refund.source_lifecycle_event_id
                WHERE event.reservation_id = p_reservation_id
            ) THEN
                RAISE EXCEPTION 'Reservation Deposit outcome is already classified'
                    USING ERRCODE = 'P0001';
            END IF;
            SELECT unit.* INTO STRICT v_unit
            FROM app.units AS unit WHERE unit.id = v_reservation.unit_id;
            SELECT * INTO STRICT v_outcome
            FROM app.create_reservation_deposit_outcome(
                p_outcome_id, p_refund_number, p_reservation_id, p_reason,
                p_outcome_authorization_reference, p_actor_id, 'ADMINISTRATIVE',
                p_idempotency_key
            );
            INSERT INTO app.reservation_commands (
                actor_id, property_id, action, idempotency_key, request_digest,
                result_id, result_snapshot
            ) VALUES (
                p_actor_id, p_property_id, 'reservation.outcome.complete',
                p_idempotency_key, p_request_digest, p_outcome_id,
                jsonb_build_object(
                    'reservation_id', v_reservation.id,
                    'unit_id', v_reservation.unit_id, 'status', v_reservation.status,
                    'cancellation_reason_code', v_reservation.cancellation_reason_code,
                    'cancellation_responsibility', v_reservation.cancellation_responsibility,
                    'effective_expiration_date', v_reservation.effective_expiration_date,
                    'version', v_reservation.version, 'unit_status', v_unit.status,
                    'unit_version', v_unit.version, 'deposit_id', v_outcome.deposit_id,
                    'deposit_received_usd_cents', v_outcome.amount_usd_cents,
                    'deposit_outcome_state', v_outcome.outcome_kind,
                    'outcome_id', v_outcome.outcome_id,
                    'refund_number', v_outcome.refund_number
                )
            );
            RETURN QUERY SELECT
                v_reservation.id, v_reservation.unit_id, v_reservation.status,
                v_reservation.cancellation_reason_code,
                v_reservation.cancellation_responsibility,
                v_reservation.effective_expiration_date, v_reservation.version,
                v_unit.status, v_unit.version, v_outcome.deposit_id,
                v_outcome.amount_usd_cents, v_outcome.outcome_kind,
                v_outcome.outcome_id, v_outcome.refund_number;
        END;
        $$
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION app.correct_reservation_deposit_outcome(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_correction_id uuid,
            p_expected_outcome_id uuid,
            p_replacement_outcome_id uuid,
            p_replacement_refund_number text,
            p_reservation_id uuid,
            p_expected_version integer,
            p_reason text,
            p_evidence_reference text,
            p_correction_authorization_reference text,
            p_replacement_authorization_reference text,
            p_actor_id uuid
        )
        RETURNS TABLE({lifecycle_result})
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_command app.reservation_commands%ROWTYPE;
            v_reservation app.reservations%ROWTYPE;
            v_unit app.units%ROWTYPE;
            v_event app.reservation_lifecycle_events%ROWTYPE;
            v_deposit_id uuid;
            v_received bigint;
            v_original_outcome_id uuid;
            v_original_refund bigint;
            v_outcome record;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'reservation-command/' || p_actor_id::text || '/'
                    || p_property_id::text || '/reservation.outcome.correct/'
                    || p_idempotency_key::text, 0
                )
            );
            SELECT command.* INTO v_command
            FROM app.reservation_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'reservation.outcome.correct'
              AND command.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_command.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Reservation idempotency key was reused'
                        USING ERRCODE = 'P0001';
                END IF;
                RETURN QUERY SELECT
                    (v_command.result_snapshot ->> 'reservation_id')::uuid,
                    (v_command.result_snapshot ->> 'unit_id')::uuid,
                    v_command.result_snapshot ->> 'status',
                    v_command.result_snapshot ->> 'cancellation_reason_code',
                    v_command.result_snapshot ->> 'cancellation_responsibility',
                    (v_command.result_snapshot ->> 'effective_expiration_date')::date,
                    (v_command.result_snapshot ->> 'version')::integer,
                    v_command.result_snapshot ->> 'unit_status',
                    (v_command.result_snapshot ->> 'unit_version')::integer,
                    (v_command.result_snapshot ->> 'deposit_id')::uuid,
                    (v_command.result_snapshot ->> 'deposit_received_usd_cents')::bigint,
                    v_command.result_snapshot ->> 'deposit_outcome_state',
                    (v_command.result_snapshot ->> 'outcome_id')::uuid,
                    v_command.result_snapshot ->> 'refund_number';
                RETURN;
            END IF;
            IF p_expected_outcome_id = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_correction_id = p_replacement_outcome_id
                OR COALESCE(btrim(p_reason), '') = ''
                OR COALESCE(btrim(p_evidence_reference), '') = ''
                OR p_correction_authorization_reference <> 'reservation_deposits.correct'
            THEN
                RAISE EXCEPTION 'Reservation outcome correction evidence is invalid'
                    USING ERRCODE = '23514';
            END IF;
            SELECT reservation.* INTO v_reservation
            FROM app.reservations AS reservation
            JOIN app.units AS unit ON unit.id = reservation.unit_id
            WHERE reservation.id = p_reservation_id
              AND unit.property_id = p_property_id
            FOR UPDATE OF reservation;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Reservation was not found in the Property'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_reservation.status <> 'CANCELLED'
                OR v_reservation.version <> p_expected_version
            THEN
                RAISE EXCEPTION 'Reservation outcome correction version is invalid'
                    USING ERRCODE = '40001';
            END IF;
            SELECT unit.* INTO STRICT v_unit
            FROM app.units AS unit WHERE unit.id = v_reservation.unit_id;
            SELECT event.* INTO STRICT v_event
            FROM app.reservation_lifecycle_events AS event
            WHERE event.reservation_id = p_reservation_id
              AND event.resulting_version = v_reservation.version;
            SELECT deposit.id INTO STRICT v_deposit_id
            FROM app.deposits AS deposit
            WHERE deposit.reservation_id = p_reservation_id
            FOR UPDATE OF deposit;
            SELECT COALESCE(sum(receipt.amount_usd_cents), 0)::bigint
            INTO v_received
            FROM app.deposit_receipts AS receipt
            WHERE receipt.deposit_id = v_deposit_id;

            IF v_reservation.cancellation_responsibility = 'CUSTOMER' THEN
                SELECT disposition.id INTO STRICT v_original_outcome_id
                FROM app.deposit_dispositions AS disposition
                WHERE disposition.deposit_id = v_deposit_id
                  AND NOT EXISTS (
                      SELECT 1 FROM app.deposit_disposition_reversals AS reversal
                      WHERE reversal.deposit_disposition_id = disposition.id
                  )
                FOR UPDATE OF disposition;
                IF v_original_outcome_id <> p_expected_outcome_id THEN
                    RAISE EXCEPTION 'Reservation Deposit outcome precondition was not met'
                        USING ERRCODE = '40001';
                END IF;
                INSERT INTO app.deposit_disposition_reversals (
                    id, deposit_disposition_id, reason, evidence_reference,
                    occurred_at, actor_id, authorization_reference
                ) VALUES (
                    p_correction_id, v_original_outcome_id, btrim(p_reason),
                    btrim(p_evidence_reference), statement_timestamp(), p_actor_id,
                    btrim(p_correction_authorization_reference)
                );
            ELSE
                SELECT refund.id,
                       refund.usd_accounting_value_cents - COALESCE((
                           SELECT sum(correction.source_balance_effect_usd_cents)
                           FROM app.refund_corrections AS correction
                           WHERE correction.refund_id = refund.id
                       ), 0)::bigint
                INTO STRICT v_original_outcome_id, v_original_refund
                FROM app.refunds AS refund
                WHERE refund.source_deposit_id = v_deposit_id
                  AND refund.usd_accounting_value_cents - COALESCE((
                      SELECT sum(correction.source_balance_effect_usd_cents)
                      FROM app.refund_corrections AS correction
                      WHERE correction.refund_id = refund.id
                  ), 0)::bigint > 0
                FOR UPDATE OF refund;
                IF v_original_outcome_id <> p_expected_outcome_id THEN
                    RAISE EXCEPTION 'Reservation Deposit outcome precondition was not met'
                        USING ERRCODE = '40001';
                END IF;
                INSERT INTO app.refund_corrections (
                    id, refund_id, correction_kind, reverses_correction_id,
                    source_balance_effect_usd_cents,
                    previous_net_refund_usd_cents, resulting_net_refund_usd_cents,
                    reason, evidence_reference, occurred_at, actor_id,
                    authorization_reference
                ) VALUES (
                    p_correction_id, v_original_outcome_id, 'VALUE_CORRECTION', NULL,
                    v_original_refund, v_original_refund, 0, btrim(p_reason),
                    btrim(p_evidence_reference), statement_timestamp(), p_actor_id,
                    btrim(p_correction_authorization_reference)
                );
            END IF;
            SELECT * INTO STRICT v_outcome
            FROM app.create_reservation_deposit_outcome(
                p_replacement_outcome_id, p_replacement_refund_number,
                p_reservation_id, p_reason, p_replacement_authorization_reference,
                p_actor_id, 'API', p_idempotency_key
            );
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type,
                entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                customer_id, unit_id
            ) VALUES (
                p_correction_id, statement_timestamp(), v_event.business_date,
                p_actor_id, 'reservation.deposit.outcome.corrected',
                'reservation', p_reservation_id, btrim(p_reason),
                btrim(p_correction_authorization_reference), p_property_id,
                jsonb_build_object('outcome_id', v_original_outcome_id),
                jsonb_build_object(
                    'replacement_outcome_id', p_replacement_outcome_id,
                    'evidence_reference', btrim(p_evidence_reference),
                    'outcome_kind', v_outcome.outcome_kind
                ),
                p_idempotency_key, 'API', 'SUCCEEDED',
                v_reservation.customer_id, v_reservation.unit_id
            );
            INSERT INTO app.reservation_commands (
                actor_id, property_id, action, idempotency_key, request_digest,
                result_id, result_snapshot
            ) VALUES (
                p_actor_id, p_property_id, 'reservation.outcome.correct',
                p_idempotency_key, p_request_digest, p_correction_id,
                jsonb_build_object(
                    'reservation_id', v_reservation.id,
                    'unit_id', v_reservation.unit_id, 'status', v_reservation.status,
                    'cancellation_reason_code', v_reservation.cancellation_reason_code,
                    'cancellation_responsibility', v_reservation.cancellation_responsibility,
                    'effective_expiration_date', v_reservation.effective_expiration_date,
                    'version', v_reservation.version, 'unit_status', v_unit.status,
                    'unit_version', v_unit.version, 'deposit_id', v_outcome.deposit_id,
                    'deposit_received_usd_cents', v_outcome.amount_usd_cents,
                    'deposit_outcome_state', v_outcome.outcome_kind,
                    'outcome_id', v_outcome.outcome_id,
                    'refund_number', v_outcome.refund_number
                )
            );
            RETURN QUERY SELECT
                v_reservation.id, v_reservation.unit_id, v_reservation.status,
                v_reservation.cancellation_reason_code,
                v_reservation.cancellation_responsibility,
                v_reservation.effective_expiration_date, v_reservation.version,
                v_unit.status, v_unit.version, v_outcome.deposit_id,
                v_outcome.amount_usd_cents, v_outcome.outcome_kind,
                v_outcome.outcome_id, v_outcome.refund_number;
        END;
        $$
        """
    )

    # V1-030's deferred lifecycle assertions run at COMMIT after the invoking
    # SECURITY DEFINER command has returned. Keep those checks owner-scoped so
    # the dedicated financial role needs no direct lifecycle-table grants.
    for function in (
        "app.assert_reservation_cancellation_event()",
        "app.assert_lifecycle_event_applied()",
        "app.assert_reservation_unit_summary()",
    ):
        op.execute(f"ALTER FUNCTION {function} SECURITY DEFINER")

    functions = (
        "app.reject_reservation_financial_history_loss()",
        "app.validate_reservation_financial_outcome()",
        "app.validate_refund_correction()",
        "app.assert_reservation_financial_outcome_complete()",
        "app.create_reservation_deposit_outcome(uuid,text,uuid,text,text,uuid,text,uuid)",
        "app.cancel_reservation_v2(uuid,uuid,text,uuid,uuid,text,uuid,integer,text,text,boolean,text,text,text,text,uuid)",
        "app.expire_reservation_v2(uuid,uuid,text,uuid,uuid,uuid,integer,boolean,text,text,uuid)",
        "app.complete_reservation_deposit_outcome(uuid,uuid,text,uuid,text,uuid,integer,text,text,uuid)",
        "app.correct_reservation_deposit_outcome(uuid,uuid,text,uuid,uuid,uuid,text,uuid,integer,text,text,text,text,uuid)",
    )
    for function in functions:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_bootstrap")
    for table in (
        "deposit_dispositions",
        "deposit_disposition_reversals",
        "refunds",
        "refund_corrections",
    ):
        op.execute(
            f"REVOKE ALL ON TABLE app.{table} "
            "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT SELECT ON TABLE app.{table} TO prm_runtime, prm_financial")
    op.execute("GRANT USAGE ON SCHEMA app TO prm_financial")
    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "app.cancel_reservation(uuid,uuid,text,uuid,uuid,integer,text,text,boolean,text,text,text,uuid) "
        "FROM prm_runtime, prm_financial"
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "app.expire_reservation(uuid,uuid,text,uuid,uuid,integer,boolean,text,uuid) "
        "FROM prm_runtime, prm_financial"
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "app.cancel_reservation_v2(uuid,uuid,text,uuid,uuid,text,uuid,integer,text,text,boolean,text,text,text,text,uuid) "
        "FROM prm_runtime"
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "app.expire_reservation_v2(uuid,uuid,text,uuid,uuid,uuid,integer,boolean,text,text,uuid) "
        "FROM prm_runtime"
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "app.complete_reservation_deposit_outcome(uuid,uuid,text,uuid,text,uuid,integer,text,text,uuid) "
        "FROM prm_runtime, prm_financial"
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "app.correct_reservation_deposit_outcome(uuid,uuid,text,uuid,uuid,uuid,text,uuid,integer,text,text,text,text,uuid) "
        "FROM prm_runtime"
    )
    for function in (
        "app.cancel_reservation_v2(uuid,uuid,text,uuid,uuid,text,uuid,integer,text,text,boolean,text,text,text,text,uuid)",
        "app.expire_reservation_v2(uuid,uuid,text,uuid,uuid,uuid,integer,boolean,text,text,uuid)",
        "app.correct_reservation_deposit_outcome(uuid,uuid,text,uuid,uuid,uuid,text,uuid,integer,text,text,text,text,uuid)",
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    """Refuse rollback that could erase Reservation financial history."""
    raise RuntimeError("Reservation Deposit outcome migration is forward-only")
