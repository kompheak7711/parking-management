# ruff: noqa: E501
"""Add an occupant to a draft or a running Lease (V1-060 B6; DL-102).

Revision ID: 20270327_246
Revises: 20270326_245
Create Date: 2026-10-28

The owner asked on 2026-10-28 how to add a friend who starts living in the Unit after the Lease was
signed and the tenant moved in alone. The owner-approved Lease page design (DESIGN.md 0.15) has
"Add occupant" on a draft or a running Lease:

- Before the move-in (a draft, or a signed Lease nobody has moved in under yet) the person is
  planned: they move in with the Lease, and Record move-in ticks them and records their date.
- After the move-in the person gets their own Occupancy from their own actual move-in date, between
  the Lease's first move-in date and its End Date and never after today (BR-OCC-004).

An occupant signs nothing and owes nothing (BR-OCC-006). Each addition is one append-only row of
app.lease_occupant_additions, written only by app.add_lease_occupant (SECURITY DEFINER, EXECUTE to
prm_runtime, the move-in permission `reservations.complete`), and the Lease History shows it.
Refused: a cancelled or terminated Lease; a deactivated Customer; a renewal with no move-in of its
own (its occupants stay with the earlier Lease); the Primary Tenant after the move-in (their
Occupancy decides who pays the Utilities); someone already planned or living there; a 21st person.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270327_246"
down_revision: str | None = "20270326_245"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "app.add_lease_occupant(uuid,uuid,text,uuid,uuid,integer,uuid,uuid,date,text,text,uuid)"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.lease_occupant_additions (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL
                CHECK (idempotency_key <> '00000000-0000-0000-0000-000000000000'::uuid),
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            occupancy_id uuid UNIQUE REFERENCES app.occupancies(id) ON DELETE RESTRICT,
            move_in_date date CHECK (isfinite(move_in_date)),
            reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
            authorization_reference text NOT NULL
                CHECK (authorization_reference = 'reservations.complete'),
            result_snapshot jsonb NOT NULL CHECK (jsonb_typeof(result_snapshot) = 'object'),
            occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
            CONSTRAINT lease_occupant_additions_idempotency_unique
                UNIQUE (property_id, actor_id, idempotency_key),
            CONSTRAINT lease_occupant_additions_shape
                CHECK ((occupancy_id IS NULL) = (move_in_date IS NULL))
        );
        CREATE UNIQUE INDEX lease_occupant_additions_planned_once
            ON app.lease_occupant_additions(lease_id, customer_id) WHERE occupancy_id IS NULL;
        CREATE INDEX lease_occupant_additions_lease_idx
            ON app.lease_occupant_additions(lease_id, occurred_at, id);
        COMMENT ON TABLE app.lease_occupant_additions IS
            'Add occupant (DL-102): a planned person before the move-in, or an Occupancy with its own move-in date after it';

        CREATE FUNCTION app.add_lease_occupant(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text, p_event_id uuid,
            p_lease_id uuid, p_expected_lease_version integer, p_customer_id uuid,
            p_occupancy_id uuid, p_move_in_date date, p_reason text,
            p_authorization_reference text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_prior app.lease_occupant_additions%ROWTYPE; v_lease app.leases%ROWTYPE;
            v_business_date date; v_first_move_in date; v_planned uuid[]; v_result jsonb;
        BEGIN
            IF p_property_id IS NULL OR p_idempotency_key IS NULL OR p_event_id IS NULL
                OR p_lease_id IS NULL OR p_customer_id IS NULL OR p_actor_id IS NULL
                OR p_expected_lease_version IS NULL OR p_expected_lease_version < 1
                OR p_idempotency_key = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_event_id = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_customer_id = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_occupancy_id IS NOT DISTINCT FROM '00000000-0000-0000-0000-000000000000'::uuid
                OR (p_occupancy_id IS NULL) <> (p_move_in_date IS NULL)
                OR (p_move_in_date IS NOT NULL AND NOT isfinite(p_move_in_date))
                OR p_request_digest IS NULL OR p_request_digest !~ '^[0-9a-f]{64}$'
                OR p_authorization_reference IS DISTINCT FROM 'reservations.complete'
                OR p_reason IS NULL OR p_reason = '' OR p_reason <> btrim(p_reason)
                OR length(p_reason) > 500
            THEN RAISE EXCEPTION 'Occupant addition evidence is invalid' USING ERRCODE = '22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                p_property_id::text || '|' || p_actor_id::text || '|lease-occupant|'
                    || p_idempotency_key::text, 0));
            SELECT * INTO v_prior FROM app.lease_occupant_additions AS addition
            WHERE addition.property_id = p_property_id AND addition.actor_id = p_actor_id
              AND addition.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_prior.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Occupant addition idempotency key was reused' USING ERRCODE = '23505';
                END IF;
                RETURN v_prior.result_snapshot;
            END IF;
            SELECT lease.* INTO v_lease FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            -- The same order as the move-in: the Lease, then its Unit.
            PERFORM 1 FROM app.units WHERE id = v_lease.unit_id FOR UPDATE;
            IF v_lease.version <> p_expected_lease_version THEN
                RAISE EXCEPTION 'Occupant addition version is stale' USING ERRCODE = '40001'; END IF;
            SELECT timezone(property.timezone_name, statement_timestamp())::date INTO STRICT v_business_date
            FROM app.properties AS property WHERE property.id = p_property_id;
            SELECT min(occupancy.move_in_date) INTO v_first_move_in
            FROM app.occupancies AS occupancy WHERE occupancy.lease_id = v_lease.id;
            IF v_lease.status NOT IN ('DRAFTED', 'SIGNED')
                OR NOT EXISTS (SELECT 1 FROM app.customers AS customer
                    WHERE customer.id = p_customer_id AND customer.deactivated_at IS NULL)
                -- A renewal records no move-in of its own: its occupants stay with the earlier Lease.
                OR (v_first_move_in IS NULL AND v_lease.predecessor_lease_id IS NOT NULL)
            THEN RAISE EXCEPTION 'Occupant addition is not allowed on this Lease' USING ERRCODE = '23514'; END IF;
            IF v_first_move_in IS NULL THEN
                -- Before the move-in: the person is planned and moves in with the Lease.
                v_planned := ARRAY(
                    SELECT DISTINCT planned.customer_id FROM (
                        SELECT (element.value #>> '{}')::uuid AS customer_id
                        FROM (SELECT command.result_snapshot FROM app.lease_commands AS command
                              WHERE command.lease_id = v_lease.id AND command.action = 'lease.draft'
                              ORDER BY command.occurred_at, command.event_id LIMIT 1) AS draft,
                             jsonb_array_elements(CASE
                                 WHEN jsonb_typeof(draft.result_snapshot->'planned_occupant_customer_ids') = 'array'
                                 THEN draft.result_snapshot->'planned_occupant_customer_ids'
                                 ELSE '[]'::jsonb END) AS element(value)
                        UNION ALL
                        SELECT addition.customer_id FROM app.lease_occupant_additions AS addition
                        WHERE addition.lease_id = v_lease.id AND addition.occupancy_id IS NULL
                    ) AS planned);
                IF p_occupancy_id IS NOT NULL OR p_customer_id = ANY(v_planned)
                    OR cardinality(v_planned) >= 20
                THEN RAISE EXCEPTION 'Occupant addition before the move-in is not allowed'
                    USING ERRCODE = '23514'; END IF;
            ELSE
                -- After the move-in: the person's own Occupancy from their own move-in date.
                IF p_occupancy_id IS NULL OR v_lease.status <> 'SIGNED'
                    OR p_customer_id = v_lease.primary_tenant_id
                    OR p_move_in_date < v_first_move_in OR p_move_in_date > v_lease.end_date
                    OR p_move_in_date > v_business_date
                    OR NOT EXISTS (SELECT 1 FROM app.occupancies AS occupancy
                        WHERE occupancy.lease_id = v_lease.id AND occupancy.move_out_date IS NULL)
                    OR EXISTS (SELECT 1 FROM app.occupancies AS occupancy
                        WHERE occupancy.lease_id = v_lease.id AND occupancy.customer_id = p_customer_id
                          AND occupancy.move_out_date IS NULL)
                    OR (SELECT count(*) FROM app.occupancies AS occupancy
                        WHERE occupancy.lease_id = v_lease.id AND occupancy.move_out_date IS NULL) >= 20
                THEN RAISE EXCEPTION 'Occupant addition after the move-in is not allowed'
                    USING ERRCODE = '23514'; END IF;
                INSERT INTO app.occupancies(id, lease_id, customer_id, move_in_date, created_by, updated_by)
                VALUES (p_occupancy_id, v_lease.id, p_customer_id, p_move_in_date, p_actor_id, p_actor_id);
            END IF;
            UPDATE app.leases SET version = version + 1, updated_at = statement_timestamp(),
                updated_by = p_actor_id WHERE id = v_lease.id;
            v_result := jsonb_build_object('event_id', p_event_id, 'property_id', p_property_id,
                'lease_id', v_lease.id, 'lease_version', v_lease.version + 1,
                'customer_id', p_customer_id, 'occupancy_id', p_occupancy_id,
                'move_in_date', p_move_in_date);
            INSERT INTO app.lease_occupant_additions(id, property_id, actor_id, idempotency_key,
                request_digest, lease_id, customer_id, occupancy_id, move_in_date, reason,
                authorization_reference, result_snapshot, occurred_at)
            VALUES (p_event_id, p_property_id, p_actor_id, p_idempotency_key, p_request_digest,
                v_lease.id, p_customer_id, p_occupancy_id, p_move_in_date, p_reason,
                p_authorization_reference, v_result, statement_timestamp());
            SET CONSTRAINTS ALL IMMEDIATE;
            RETURN v_result;
        END $$;
    """)
    op.execute(
        "CREATE TRIGGER lease_occupant_additions_reject_mutation BEFORE UPDATE OR DELETE "
        "ON app.lease_occupant_additions "
        "FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation()"
    )
    op.execute(
        "CREATE TRIGGER lease_occupant_additions_reject_truncate BEFORE TRUNCATE "
        "ON app.lease_occupant_additions "
        "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate()"
    )
    op.execute(
        "REVOKE ALL ON TABLE app.lease_occupant_additions "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute("GRANT SELECT ON TABLE app.lease_occupant_additions TO prm_runtime")
    op.execute(
        f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("V1-060 Add occupant migration is forward-only")
