"""Add durable singleton Reservation expiration-run state."""

from alembic import op

revision = "20260826_22"
down_revision = "20260825_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create retry-safe scheduled-operation evidence without changing domain policy."""
    op.execute(
        """
        CREATE TABLE app.reservation_expiration_runs (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            business_date date NOT NULL,
            status text NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
            attempt_count integer NOT NULL CHECK (attempt_count > 0),
            candidate_count integer NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
            expired_count integer NOT NULL DEFAULT 0 CHECK (expired_count >= 0),
            started_at timestamptz NOT NULL,
            completed_at timestamptz,
            failure_code text,
            CONSTRAINT reservation_expiration_runs_one_logical_run
                UNIQUE (property_id, business_date),
            CONSTRAINT reservation_expiration_runs_terminal_shape CHECK (
                (status = 'RUNNING' AND completed_at IS NULL AND failure_code IS NULL)
                OR (status = 'SUCCEEDED' AND completed_at IS NOT NULL AND failure_code IS NULL)
                OR (status = 'FAILED' AND completed_at IS NOT NULL
                    AND length(btrim(failure_code)) > 0 AND failure_code = btrim(failure_code))
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.reservation_expiration_attempts (
            run_id uuid NOT NULL REFERENCES app.reservation_expiration_runs(id) ON DELETE RESTRICT,
            attempt_number integer NOT NULL CHECK (attempt_number > 0),
            status text NOT NULL CHECK (status IN ('RUNNING','SUCCEEDED','FAILED')),
            candidate_count integer NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
            expired_count integer NOT NULL DEFAULT 0 CHECK (expired_count >= 0),
            started_at timestamptz NOT NULL,
            completed_at timestamptz,
            failure_code text,
            PRIMARY KEY (run_id, attempt_number),
            CONSTRAINT reservation_expiration_attempt_terminal_shape CHECK (
                (status='RUNNING' AND completed_at IS NULL AND failure_code IS NULL)
                OR (status='SUCCEEDED' AND completed_at IS NOT NULL AND failure_code IS NULL)
                OR (status='FAILED' AND completed_at IS NOT NULL
                    AND length(btrim(failure_code)) > 0)
            )
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.list_due_reservations_as_of(
            p_property_id uuid, p_business_date date, p_limit integer
        ) RETURNS TABLE(reservation_id uuid, effective_expiration_date date, version integer)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            IF p_business_date IS NULL OR p_limit IS NULL OR p_limit < 1 OR p_limit > 100
            THEN RAISE EXCEPTION 'Due Reservation boundary is invalid' USING ERRCODE='22023'; END IF;
            RETURN QUERY SELECT reservation.id, reservation.effective_expiration_date,
                                reservation.version
            FROM app.reservations AS reservation
            JOIN app.units AS unit ON unit.id=reservation.unit_id
            WHERE unit.property_id=p_property_id AND reservation.status='ACTIVE'
              AND reservation.effective_expiration_date < p_business_date
            ORDER BY reservation.effective_expiration_date,reservation.id LIMIT p_limit;
        END; $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.start_reservation_expiration_run(
            p_run_id uuid, p_property_id uuid, p_business_date date
        ) RETURNS TABLE(run_id uuid, should_execute boolean, attempt_count integer)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_run app.reservation_expiration_runs%ROWTYPE;
            v_inserted integer;
        BEGIN
            IF p_run_id IS NULL OR p_run_id = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_business_date IS NULL
            THEN RAISE EXCEPTION 'Expiration run identity is invalid' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.reservation_expiration_runs(
                id, property_id, business_date, status, attempt_count, started_at
            ) VALUES (p_run_id, p_property_id, p_business_date, 'RUNNING', 1, statement_timestamp())
            ON CONFLICT (property_id, business_date) DO NOTHING;
            GET DIAGNOSTICS v_inserted = ROW_COUNT;
            SELECT * INTO STRICT v_run FROM app.reservation_expiration_runs
            WHERE property_id = p_property_id AND business_date = p_business_date FOR UPDATE;
            IF v_run.status = 'SUCCEEDED' THEN
                RETURN QUERY SELECT v_run.id, false, v_run.attempt_count;
                RETURN;
            END IF;
            IF v_run.id <> p_run_id THEN
                p_run_id := v_run.id;
            END IF;
            IF v_inserted = 0 THEN
                UPDATE app.reservation_expiration_attempts AS interrupted_attempt SET
                    status='FAILED', completed_at=statement_timestamp(),
                    failure_code='PROCESS_INTERRUPTED'
                WHERE interrupted_attempt.run_id=v_run.id
                  AND interrupted_attempt.attempt_number=v_run.attempt_count
                  AND interrupted_attempt.status='RUNNING';
                UPDATE app.reservation_expiration_runs AS retry_run SET
                    status = 'RUNNING', attempt_count = retry_run.attempt_count + 1,
                    candidate_count = 0, expired_count = 0,
                    started_at = statement_timestamp(), completed_at = NULL, failure_code = NULL
                WHERE retry_run.id = p_run_id RETURNING retry_run.* INTO v_run;
            END IF;
            INSERT INTO app.reservation_expiration_attempts(
                run_id, attempt_number, status, started_at
            ) VALUES (v_run.id, v_run.attempt_count, 'RUNNING', v_run.started_at);
            RETURN QUERY SELECT v_run.id, true, v_run.attempt_count;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.finish_reservation_expiration_run(
            p_run_id uuid, p_candidate_count integer, p_expired_count integer
        ) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            IF p_candidate_count < 0 OR p_expired_count < 0 OR p_expired_count > p_candidate_count
            THEN RAISE EXCEPTION 'Expiration counts are invalid' USING ERRCODE = '22023'; END IF;
            UPDATE app.reservation_expiration_runs SET
                status = 'SUCCEEDED', candidate_count = p_candidate_count,
                expired_count = p_expired_count, completed_at = statement_timestamp(),
                failure_code = NULL
            WHERE id = p_run_id AND status = 'RUNNING';
            IF NOT FOUND THEN RAISE EXCEPTION 'Expiration run is not active' USING ERRCODE = '55000'; END IF;
            UPDATE app.reservation_expiration_attempts AS attempt SET
                status='SUCCEEDED', candidate_count=p_candidate_count,
                expired_count=p_expired_count, completed_at=statement_timestamp()
            FROM app.reservation_expiration_runs AS run
            WHERE attempt.run_id=run.id AND attempt.attempt_number=run.attempt_count
              AND run.id=p_run_id AND attempt.status='RUNNING';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.fail_reservation_expiration_run(p_run_id uuid, p_failure_code text)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            IF p_failure_code IS NULL OR length(btrim(p_failure_code)) = 0
                OR p_failure_code <> btrim(p_failure_code) OR length(p_failure_code) > 100
            THEN RAISE EXCEPTION 'Expiration failure code is invalid' USING ERRCODE = '22023'; END IF;
            UPDATE app.reservation_expiration_runs SET
                status = 'FAILED', completed_at = statement_timestamp(), failure_code = p_failure_code
            WHERE id = p_run_id AND status = 'RUNNING';
            IF NOT FOUND THEN RAISE EXCEPTION 'Expiration run is not active' USING ERRCODE = '55000'; END IF;
            UPDATE app.reservation_expiration_attempts AS attempt SET
                status='FAILED', completed_at=statement_timestamp(), failure_code=p_failure_code
            FROM app.reservation_expiration_runs AS run
            WHERE attempt.run_id=run.id AND attempt.attempt_number=run.attempt_count
              AND run.id=p_run_id AND attempt.status='RUNNING';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_reservation_expiration_run_history_loss()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN RAISE EXCEPTION 'Reservation expiration-run history is permanent'
            USING ERRCODE = '55000'; END; $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER reservation_expiration_attempts_reject_delete
        BEFORE DELETE ON app.reservation_expiration_attempts FOR EACH ROW
        EXECUTE FUNCTION app.reject_reservation_expiration_run_history_loss()
        """
    )
    op.execute(
        """
        CREATE TRIGGER reservation_expiration_runs_reject_delete
        BEFORE DELETE ON app.reservation_expiration_runs FOR EACH ROW
        EXECUTE FUNCTION app.reject_reservation_expiration_run_history_loss()
        """
    )
    op.execute(
        """
        CREATE TRIGGER reservation_expiration_runs_reject_truncate
        BEFORE TRUNCATE ON app.reservation_expiration_runs FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_reservation_expiration_run_history_loss()
        """
    )
    for function in (
        "app.list_due_reservations_as_of(uuid,date,integer)",
        "app.start_reservation_expiration_run(uuid,uuid,date)",
        "app.finish_reservation_expiration_run(uuid,integer,integer)",
        "app.fail_reservation_expiration_run(uuid,text)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_bootstrap")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")
    op.execute(
        "REVOKE ALL ON TABLE app.reservation_expiration_runs "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute("GRANT SELECT ON TABLE app.reservation_expiration_runs TO prm_runtime")
    op.execute(
        "REVOKE ALL ON TABLE app.reservation_expiration_attempts "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute("GRANT SELECT ON TABLE app.reservation_expiration_attempts TO prm_runtime")


def downgrade() -> None:
    """Refuse rollback that could erase scheduled-operation evidence."""
    raise RuntimeError("Reservation expiration worker migration is forward-only")
