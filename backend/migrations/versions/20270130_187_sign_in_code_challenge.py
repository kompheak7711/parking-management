"""Store the sign-in code challenge and the session's MFA proof (login slice sub-slice L3c-2a).

DL-056, SEC-013, API-096, DB-AUTH-003, DB-AUTH-004. A password-checked sign-in of an account that
needs MFA writes one challenge row that keeps only the sha256 digest of the pre-authentication
token, the digest of the password verifier that was checked, the keyed wrong-try digests and,
for a `challenge`, the sign-in code it was made for; it lasts 5 minutes by the database clock and
is completed once. Each TOTP time step of an enrollment
is used once and only after the last used step, so a code cannot be used twice. A session made
by a completed challenge gets one MFA proof row; a session of an account that needs MFA counts as
live only with it. Three new relations, append-only except the one completion of a challenge;
the runtime role gets column privileges only. A used step and a proof name their enrollment and
session without a foreign key, checked by their insert guards instead, so the existing
truncate refusals of `app.totp_mfa_enrollments` and `app.browser_sessions` stay as they are
(neither table's rows can be deleted). A purely additive change.
"""

from alembic import op

revision = "20270130_187"
down_revision = "20270129_186"
branch_labels = None
depends_on = None

APPEND_ONLY = "app.reject_sign_in_code_history_change()"
COMPLETE_ONCE = "app.protect_sign_in_mfa_challenge_completion()"
STEP_AFTER_LAST = "app.check_totp_used_step()"
PROOF_OF_CHALLENGE = "app.check_browser_session_mfa_proof()"
CHALLENGE_OF_CODE = "app.check_sign_in_mfa_challenge()"
TABLES = ("sign_in_mfa_challenges", "totp_used_steps", "browser_session_mfa_proofs")


def upgrade() -> None:
    """Create the challenge, used-step and proof relations, their guards and the grants."""
    op.execute(
        """
        CREATE TABLE app.sign_in_mfa_challenges (
            challenge_id uuid PRIMARY KEY,
            actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            token_verifier bytea NOT NULL UNIQUE CHECK (length(token_verifier) = 32),
            purpose text NOT NULL CHECK (purpose IN ('challenge', 'enrollment')),
            -- The active sign-in code a `challenge` was made for (review round 1, security), so
            -- a challenge from before a sign-in code reset never completes with a later code.
            enrollment_id uuid,
            password_verifier_digest bytea NOT NULL
                CHECK (length(password_verifier_digest) = 32),
            username_digest bytea NOT NULL CHECK (length(username_digest) = 32),
            source_digest bytea NOT NULL CHECK (length(source_digest) = 32),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(created_at)),
            expires_at timestamptz NOT NULL DEFAULT statement_timestamp() + interval '5 minutes',
            completed_at timestamptz,
            CHECK (expires_at = created_at + interval '5 minutes'),
            CHECK ((purpose = 'challenge') = (enrollment_id IS NOT NULL)),
            CHECK (
                completed_at IS NULL
                OR (completed_at >= created_at AND completed_at < expires_at)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX sign_in_mfa_challenges_actor_idx
        ON app.sign_in_mfa_challenges (actor_id, created_at)
        """
    )
    op.execute(
        """
        CREATE TABLE app.totp_used_steps (
            enrollment_id uuid NOT NULL,
            time_step bigint NOT NULL CHECK (time_step > 0),
            used_at timestamptz NOT NULL DEFAULT statement_timestamp() CHECK (isfinite(used_at)),
            PRIMARY KEY (enrollment_id, time_step)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.browser_session_mfa_proofs (
            session_id uuid PRIMARY KEY,
            challenge_id uuid NOT NULL UNIQUE
                REFERENCES app.sign_in_mfa_challenges (challenge_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            method text NOT NULL CHECK (method IN ('totp', 'recovery_code')),
            enrollment_id uuid,
            proven_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(proven_at)),
            CHECK ((method = 'totp') = (enrollment_id IS NOT NULL))
        )
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {APPEND_ONLY}
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'sign-in code history is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    # A challenge changes once: its completion, before it expires; the time is the database
    # clock's.
    op.execute(
        f"""
        CREATE FUNCTION {COMPLETE_ONCE}
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.challenge_id IS DISTINCT FROM OLD.challenge_id
               OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
               OR NEW.token_verifier IS DISTINCT FROM OLD.token_verifier
               OR NEW.purpose IS DISTINCT FROM OLD.purpose
               OR NEW.enrollment_id IS DISTINCT FROM OLD.enrollment_id
               OR NEW.password_verifier_digest IS DISTINCT FROM OLD.password_verifier_digest
               OR NEW.username_digest IS DISTINCT FROM OLD.username_digest
               OR NEW.source_digest IS DISTINCT FROM OLD.source_digest
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
                RAISE EXCEPTION 'a sign-in code challenge is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.completed_at IS NOT NULL THEN
                RAISE EXCEPTION 'a sign-in code challenge is completed once'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.completed_at IS NULL THEN
                RAISE EXCEPTION 'a sign-in code challenge changes only by its completion'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF pg_catalog.statement_timestamp() >= OLD.expires_at THEN
                RAISE EXCEPTION 'an expired sign-in code challenge is not completed'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            NEW.completed_at := pg_catalog.statement_timestamp();
            RETURN NEW;
        END;
        $$
        """
    )
    # One use per time step, after the last used step, never after the current step of the
    # database clock, and only for an active enrollment. The enrollment row is locked first, so
    # two parallel steps, or a step and a disable, wait for each other (review round 1).
    op.execute(
        f"""
        CREATE FUNCTION {STEP_AFTER_LAST}
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            PERFORM 1
            FROM app.totp_mfa_enrollments AS enrollment
            WHERE enrollment.enrollment_id = NEW.enrollment_id
              AND enrollment.enrollment_state = 'active'
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'a sign-in code step is used only for an active enrollment'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.time_step > pg_catalog.floor(
                   EXTRACT(EPOCH FROM pg_catalog.statement_timestamp()) / 30
               ) THEN
                RAISE EXCEPTION 'a sign-in code step is never after the current step'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM app.totp_used_steps AS used
                WHERE used.enrollment_id = NEW.enrollment_id
                  AND used.time_step >= NEW.time_step
            ) THEN
                RAISE EXCEPTION 'a sign-in code step is used once and after the last used step'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    # A proof belongs to a live session made after the challenge and to a completed challenge of
    # the session's own account; a `totp` proof names the challenge's own enrollment and a step
    # of it used since the challenge was made (review round 1, security).
    op.execute(
        f"""
        CREATE FUNCTION {PROOF_OF_CHALLENGE}
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM app.browser_sessions AS browser
                JOIN app.sign_in_mfa_challenges AS challenge
                  ON challenge.actor_id = browser.actor_id
                WHERE browser.session_id = NEW.session_id
                  AND browser.revoked_at IS NULL
                  AND browser.created_at >= challenge.created_at
                  AND challenge.challenge_id = NEW.challenge_id
                  AND challenge.completed_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'an MFA proof needs a completed challenge of the session account'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.method = 'totp' AND NOT EXISTS (
                SELECT 1
                FROM app.sign_in_mfa_challenges AS challenge
                JOIN app.totp_mfa_enrollments AS enrollment
                  ON enrollment.enrollment_id = challenge.enrollment_id
                 AND enrollment.actor_id = challenge.actor_id
                JOIN app.totp_used_steps AS used
                  ON used.enrollment_id = challenge.enrollment_id
                WHERE challenge.challenge_id = NEW.challenge_id
                  AND challenge.enrollment_id = NEW.enrollment_id
                  AND used.used_at >= challenge.created_at
            ) THEN
                RAISE EXCEPTION 'an MFA proof names the challenge sign-in code and a step it used'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    # A `challenge` names an active sign-in code of its own account (review round 2).
    op.execute(
        f"""
        CREATE FUNCTION {CHALLENGE_OF_CODE}
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.purpose = 'challenge' AND NOT EXISTS (
                SELECT 1
                FROM app.totp_mfa_enrollments AS enrollment
                WHERE enrollment.enrollment_id = NEW.enrollment_id
                  AND enrollment.actor_id = NEW.actor_id
                  AND enrollment.enrollment_state = 'active'
            ) THEN
                RAISE EXCEPTION 'a challenge names an active sign-in code of its account'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER sign_in_mfa_challenges_of_a_sign_in_code
        BEFORE INSERT ON app.sign_in_mfa_challenges
        FOR EACH ROW
        EXECUTE FUNCTION {CHALLENGE_OF_CODE}
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER sign_in_mfa_challenges_complete_once
        BEFORE UPDATE ON app.sign_in_mfa_challenges
        FOR EACH ROW
        EXECUTE FUNCTION {COMPLETE_ONCE}
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER sign_in_mfa_challenges_reject_delete
        BEFORE DELETE ON app.sign_in_mfa_challenges
        FOR EACH ROW
        EXECUTE FUNCTION {APPEND_ONLY}
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER totp_used_steps_after_last
        BEFORE INSERT ON app.totp_used_steps
        FOR EACH ROW
        EXECUTE FUNCTION {STEP_AFTER_LAST}
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER browser_session_mfa_proofs_of_challenge
        BEFORE INSERT ON app.browser_session_mfa_proofs
        FOR EACH ROW
        EXECUTE FUNCTION {PROOF_OF_CHALLENGE}
        """
    )
    for table in TABLES[1:]:
        op.execute(
            f"""
            CREATE TRIGGER {table}_are_append_only
            BEFORE UPDATE OR DELETE ON app.{table}
            FOR EACH ROW
            EXECUTE FUNCTION {APPEND_ONLY}
            """
        )
    for table in TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_truncate
            BEFORE TRUNCATE ON app.{table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION {APPEND_ONLY}
            """
        )
    for function in (
        APPEND_ONLY,
        COMPLETE_ONCE,
        STEP_AFTER_LAST,
        PROOF_OF_CHALLENGE,
        CHALLENGE_OF_CODE,
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for table in TABLES:
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC, prm_runtime")
    op.execute(
        """
        GRANT SELECT (
            challenge_id, actor_id, token_verifier, purpose, enrollment_id,
            password_verifier_digest, username_digest, source_digest, created_at, expires_at,
            completed_at
        ) ON app.sign_in_mfa_challenges TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT INSERT (
            challenge_id, actor_id, token_verifier, purpose, enrollment_id,
            password_verifier_digest, username_digest, source_digest
        ) ON app.sign_in_mfa_challenges TO prm_runtime
        """
    )
    op.execute("GRANT UPDATE (completed_at) ON app.sign_in_mfa_challenges TO prm_runtime")
    op.execute(
        "GRANT SELECT (enrollment_id, time_step, used_at) ON app.totp_used_steps TO prm_runtime"
    )
    op.execute("GRANT INSERT (enrollment_id, time_step) ON app.totp_used_steps TO prm_runtime")
    op.execute(
        """
        GRANT SELECT (session_id, challenge_id, method, enrollment_id, proven_at)
        ON app.browser_session_mfa_proofs TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT INSERT (session_id, challenge_id, method, enrollment_id)
        ON app.browser_session_mfa_proofs TO prm_runtime
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("sign-in code challenge migration is forward-only")
