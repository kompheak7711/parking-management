"""Record a session's recent reauthentication (login slice sub-slice L3d-1).

SEC-018, API-097, UI-111, TEST-132, DB-AUTH-004, owner answer (a) to Q-2026-10-21-157. A signed-in
person gives the password again, and the sign-in code when the account needs MFA; each success
writes one row of `app.browser_session_reauthentications` (append-only). Its insert guard checks
that the session is live and of the row's account, that a `totp` reauthentication names the
account's active sign-in code with a step of it used since its transaction began (one row per
step), and that a
`password` reauthentication is only for an account that needs no MFA. The session's
`reauthenticated_at` is the time of its latest row. The row names its session without a foreign
key, checked by the insert guard instead, so the existing truncate refusal of
`app.browser_sessions` stays as it is. A purely additive change.
"""

from alembic import op

revision = "20270203_191"
down_revision = "20270202_190"
branch_labels = None
depends_on = None

APPEND_ONLY = "app.reject_sign_in_code_history_change()"
REAUTHENTICATION_OF_SESSION = "app.check_browser_session_reauthentication()"


def upgrade() -> None:
    """Create the reauthentication relation, its guards and the grants."""
    op.execute(
        """
        CREATE TABLE app.browser_session_reauthentications (
            reauthentication_id uuid PRIMARY KEY,
            session_id uuid NOT NULL,
            actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            method text NOT NULL CHECK (method IN ('password', 'totp')),
            enrollment_id uuid,
            time_step bigint,
            reauthenticated_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(reauthenticated_at)),
            CHECK (
                (method = 'totp') = (enrollment_id IS NOT NULL AND time_step IS NOT NULL)
                AND (method = 'password') = (enrollment_id IS NULL AND time_step IS NULL)
            )
        )
        """
    )
    # One reauthentication per time step of a sign-in code (review round 1).
    op.execute(
        """
        CREATE UNIQUE INDEX browser_session_reauthentications_one_per_step
        ON app.browser_session_reauthentications (enrollment_id, time_step)
        WHERE method = 'totp'
        """
    )
    op.execute(
        """
        CREATE INDEX browser_session_reauthentications_session_idx
        ON app.browser_session_reauthentications (session_id, reauthenticated_at)
        """
    )
    # A reauthentication belongs to a live session of its own account; a `totp` one names the
    # account's active sign-in code and a step of it used since its transaction began; a `password`
    # one is only for an account that needs no MFA (MFA policy `optional`, no active code).
    op.execute(
        f"""
        CREATE FUNCTION {REAUTHENTICATION_OF_SESSION}
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM app.browser_sessions AS browser
                JOIN app.user_accounts AS account ON account.actor_id = browser.actor_id
                WHERE browser.session_id = NEW.session_id
                  AND browser.actor_id = NEW.actor_id
                  AND browser.revoked_at IS NULL
                  AND pg_catalog.statement_timestamp() < browser.idle_expires_at
                  AND pg_catalog.statement_timestamp() < browser.absolute_expires_at
                  AND account.lifecycle_state = 'active'
            ) THEN
                RAISE EXCEPTION 'a reauthentication needs a live session of its account'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.method = 'totp' AND NOT EXISTS (
                SELECT 1
                FROM app.totp_mfa_enrollments AS enrollment
                JOIN app.totp_used_steps AS used
                  ON used.enrollment_id = enrollment.enrollment_id
                WHERE enrollment.enrollment_id = NEW.enrollment_id
                  AND enrollment.actor_id = NEW.actor_id
                  AND enrollment.enrollment_state = 'active'
                  AND used.time_step = NEW.time_step
                  AND used.used_at >= pg_catalog.transaction_timestamp()
            ) THEN
                RAISE EXCEPTION 'a reauthentication names a step of its active sign-in code'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.method = 'password' AND EXISTS (
                SELECT 1
                FROM app.user_accounts AS account
                WHERE account.actor_id = NEW.actor_id
                  AND (
                      account.mfa_policy_class <> 'optional'
                      OR EXISTS (
                          SELECT 1
                          FROM app.totp_mfa_enrollments AS enrollment
                          WHERE enrollment.actor_id = account.actor_id
                            AND enrollment.enrollment_state = 'active'
                      )
                  )
            ) THEN
                RAISE EXCEPTION 'an account that needs MFA reauthenticates with its sign-in code'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            NEW.reauthenticated_at := pg_catalog.statement_timestamp();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER browser_session_reauthentications_of_session
        BEFORE INSERT ON app.browser_session_reauthentications
        FOR EACH ROW
        EXECUTE FUNCTION {REAUTHENTICATION_OF_SESSION}
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER browser_session_reauthentications_are_append_only
        BEFORE UPDATE OR DELETE ON app.browser_session_reauthentications
        FOR EACH ROW
        EXECUTE FUNCTION {APPEND_ONLY}
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER browser_session_reauthentications_reject_truncate
        BEFORE TRUNCATE ON app.browser_session_reauthentications
        FOR EACH STATEMENT
        EXECUTE FUNCTION {APPEND_ONLY}
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {REAUTHENTICATION_OF_SESSION} FROM PUBLIC")
    op.execute("REVOKE ALL ON app.browser_session_reauthentications FROM PUBLIC, prm_runtime")
    op.execute(
        """
        GRANT SELECT (
            reauthentication_id, session_id, actor_id, method, enrollment_id, time_step,
            reauthenticated_at
        ) ON app.browser_session_reauthentications TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT INSERT (reauthentication_id, session_id, actor_id, method, enrollment_id, time_step)
        ON app.browser_session_reauthentications TO prm_runtime
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("session reauthentication migration is forward-only")
