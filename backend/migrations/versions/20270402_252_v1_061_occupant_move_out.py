# ruff: noqa: E501
"""V1-061 (owner 2026-10-29, DL-111): move out one occupant of a running Lease.

Revision ID: 20270402_252
Revises: 20270401_251
Create Date: 2026-10-29

The owner asked on 2026-10-29 04:10 for a Move out button for each person on the Lease page:
"add move-out button for individual tenant. but Primary Tenant is not allowed to move-out", and
at 04:22: "If more than one signer, before move-out, other signer must acknowledge and agree. If
one signer or only signer left, do not allow to move-out until termination processing complete."

So one person's Occupancy of a signed Lease ends on their own move-out day:
- The Primary Tenant never moves out alone: they leave with the Lease (Termination and Move-out).
- A person who signs nothing needs only the day and a reason.
- A Joint Signer needs every other Signer of the Lease to agree; it is recorded with the names of
  the Signers who agreed. They stay a Signer of the Lease and keep its responsibility until it
  ends (the Signers of a signed Lease never change).
- The only Signer still living there is refused: the Lease is ended through Termination first.
- The day is on or after their move-in day, never after today and never after the End Date.

Each move-out is one append-only row of app.lease_occupant_move_outs, written only by
app.move_out_lease_occupant (SECURITY DEFINER, EXECUTE to prm_runtime, the move-in permission
`reservations.complete`, as Add occupant). The Lease History shows it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270402_252"
down_revision: str | None = "20270401_251"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = (
    "app.move_out_lease_occupant(uuid,uuid,text,uuid,uuid,integer,uuid,date,uuid[],text,text,uuid)"
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.lease_occupant_move_outs (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL
                CHECK (idempotency_key <> '00000000-0000-0000-0000-000000000000'::uuid),
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            occupancy_id uuid NOT NULL UNIQUE REFERENCES app.occupancies(id) ON DELETE RESTRICT,
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            move_out_date date NOT NULL CHECK (isfinite(move_out_date)),
            was_signer boolean NOT NULL,
            agreed_signer_customer_ids uuid[] NOT NULL,
            reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
            authorization_reference text NOT NULL
                CHECK (authorization_reference = 'reservations.complete'),
            result_snapshot jsonb NOT NULL CHECK (jsonb_typeof(result_snapshot) = 'object'),
            occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
            CONSTRAINT lease_occupant_move_outs_idempotency_unique
                UNIQUE (property_id, actor_id, idempotency_key),
            CONSTRAINT lease_occupant_move_outs_agreement
                CHECK (was_signer OR cardinality(agreed_signer_customer_ids) = 0)
        );
        CREATE INDEX lease_occupant_move_outs_lease_idx
            ON app.lease_occupant_move_outs(lease_id, occurred_at, id);
        COMMENT ON TABLE app.lease_occupant_move_outs IS
            'Move out one occupant (DL-111): never the Primary Tenant; a Joint Signer with every other Signer agreeing, never the last Signer living there';

        CREATE FUNCTION app.move_out_lease_occupant(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text, p_event_id uuid,
            p_lease_id uuid, p_expected_lease_version integer, p_occupancy_id uuid,
            p_move_out_date date, p_agreed_signer_customer_ids uuid[], p_reason text,
            p_authorization_reference text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_prior app.lease_occupant_move_outs%ROWTYPE; v_lease app.leases%ROWTYPE;
            v_occupancy app.occupancies%ROWTYPE; v_business_date date; v_signer boolean;
            v_others uuid[]; v_agreed uuid[]; v_result jsonb;
        BEGIN
            IF p_property_id IS NULL OR p_idempotency_key IS NULL OR p_event_id IS NULL
                OR p_lease_id IS NULL OR p_occupancy_id IS NULL OR p_actor_id IS NULL
                OR p_move_out_date IS NULL OR NOT isfinite(p_move_out_date)
                OR p_expected_lease_version IS NULL OR p_expected_lease_version < 1
                OR p_idempotency_key = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_event_id = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_agreed_signer_customer_ids IS NULL
                OR array_position(p_agreed_signer_customer_ids, NULL) IS NOT NULL
                OR cardinality(p_agreed_signer_customer_ids) > 100
                OR p_request_digest IS NULL OR p_request_digest !~ '^[0-9a-f]{64}$'
                OR p_authorization_reference IS DISTINCT FROM 'reservations.complete'
                OR p_reason IS NULL OR p_reason = '' OR p_reason <> btrim(p_reason)
                OR length(p_reason) > 500
            THEN RAISE EXCEPTION 'Occupant move-out evidence is invalid' USING ERRCODE = '22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                p_property_id::text || '|' || p_actor_id::text || '|lease-occupant-move-out|'
                    || p_idempotency_key::text, 0));
            SELECT * INTO v_prior FROM app.lease_occupant_move_outs AS move_out
            WHERE move_out.property_id = p_property_id AND move_out.actor_id = p_actor_id
              AND move_out.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_prior.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Occupant move-out idempotency key was reused' USING ERRCODE = '23505';
                END IF;
                RETURN v_prior.result_snapshot;
            END IF;
            SELECT lease.* INTO v_lease FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            -- The same order as the move-in and Add occupant: the Lease, then its Unit.
            PERFORM 1 FROM app.units WHERE id = v_lease.unit_id FOR UPDATE;
            IF v_lease.version <> p_expected_lease_version THEN
                RAISE EXCEPTION 'Occupant move-out version is stale' USING ERRCODE = '40001'; END IF;
            SELECT occupancy.* INTO v_occupancy FROM app.occupancies AS occupancy
            WHERE occupancy.id = p_occupancy_id AND occupancy.lease_id = v_lease.id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Occupancy was not found' USING ERRCODE = 'P0002'; END IF;
            SELECT timezone(property.timezone_name, statement_timestamp())::date INTO STRICT v_business_date
            FROM app.properties AS property WHERE property.id = p_property_id;
            IF v_lease.status <> 'SIGNED' OR v_occupancy.move_out_date IS NOT NULL THEN
                RAISE EXCEPTION 'Occupant move-out is not allowed on this Lease'
                    USING ERRCODE = '23514', HINT = 'NOT_LIVING_THERE'; END IF;
            IF v_occupancy.customer_id = v_lease.primary_tenant_id THEN
                RAISE EXCEPTION 'The Primary Tenant moves out only with the Lease'
                    USING ERRCODE = '23514', HINT = 'PRIMARY_TENANT'; END IF;
            IF p_move_out_date < v_occupancy.move_in_date OR p_move_out_date > v_business_date
                OR p_move_out_date > v_lease.end_date
            THEN RAISE EXCEPTION 'Occupant move-out date is not allowed'
                USING ERRCODE = '23514', HINT = 'DATE'; END IF;
            v_signer := EXISTS (SELECT 1 FROM app.lease_signers AS signer
                WHERE signer.lease_id = v_lease.id AND signer.customer_id = v_occupancy.customer_id);
            v_agreed := ARRAY(SELECT DISTINCT value FROM unnest(p_agreed_signer_customer_ids) AS value
                ORDER BY value);
            IF cardinality(v_agreed) <> cardinality(p_agreed_signer_customer_ids) THEN
                RAISE EXCEPTION 'Occupant move-out evidence is invalid' USING ERRCODE = '22023'; END IF;
            IF v_signer THEN
                -- The last Signer living there leaves only with the Lease (Termination first).
                IF NOT EXISTS (
                    SELECT 1 FROM app.occupancies AS occupancy
                    JOIN app.lease_signers AS signer
                      ON signer.lease_id = occupancy.lease_id AND signer.customer_id = occupancy.customer_id
                    WHERE occupancy.lease_id = v_lease.id AND occupancy.move_out_date IS NULL
                      AND occupancy.id <> v_occupancy.id
                ) THEN RAISE EXCEPTION 'The last Signer living there moves out only with the Lease'
                    USING ERRCODE = '23514', HINT = 'LAST_SIGNER'; END IF;
                v_others := ARRAY(SELECT signer.customer_id FROM app.lease_signers AS signer
                    WHERE signer.lease_id = v_lease.id AND signer.customer_id <> v_occupancy.customer_id
                    ORDER BY signer.customer_id);
                IF v_agreed IS DISTINCT FROM v_others THEN
                    RAISE EXCEPTION 'Every other Signer must agree to this move-out'
                        USING ERRCODE = '23514', HINT = 'SIGNERS_AGREE'; END IF;
            ELSIF cardinality(v_agreed) > 0 THEN
                RAISE EXCEPTION 'Occupant move-out evidence is invalid' USING ERRCODE = '22023';
            END IF;
            UPDATE app.occupancies SET move_out_date = p_move_out_date, version = version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE id = v_occupancy.id;
            UPDATE app.leases SET version = version + 1, updated_at = statement_timestamp(),
                updated_by = p_actor_id WHERE id = v_lease.id;
            v_result := jsonb_build_object('event_id', p_event_id, 'property_id', p_property_id,
                'lease_id', v_lease.id, 'lease_version', v_lease.version + 1,
                'occupancy_id', v_occupancy.id, 'customer_id', v_occupancy.customer_id,
                'move_out_date', p_move_out_date, 'was_signer', v_signer,
                'agreed_signer_customer_ids', to_jsonb(v_agreed));
            INSERT INTO app.lease_occupant_move_outs(id, property_id, actor_id, idempotency_key,
                request_digest, lease_id, occupancy_id, customer_id, move_out_date, was_signer,
                agreed_signer_customer_ids, reason, authorization_reference, result_snapshot,
                occurred_at)
            VALUES (p_event_id, p_property_id, p_actor_id, p_idempotency_key, p_request_digest,
                v_lease.id, v_occupancy.id, v_occupancy.customer_id, p_move_out_date, v_signer,
                v_agreed, p_reason, p_authorization_reference, v_result, statement_timestamp());
            SET CONSTRAINTS ALL IMMEDIATE;
            RETURN v_result;
        END $$;
    """)
    op.execute(
        "CREATE TRIGGER lease_occupant_move_outs_reject_mutation BEFORE UPDATE OR DELETE "
        "ON app.lease_occupant_move_outs "
        "FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation()"
    )
    op.execute(
        "CREATE TRIGGER lease_occupant_move_outs_reject_truncate BEFORE TRUNCATE "
        "ON app.lease_occupant_move_outs "
        "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate()"
    )
    op.execute(
        "REVOKE ALL ON TABLE app.lease_occupant_move_outs "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute("GRANT SELECT ON TABLE app.lease_occupant_move_outs TO prm_runtime")
    op.execute(
        f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("V1-061 occupant move-out migration is forward-only")
