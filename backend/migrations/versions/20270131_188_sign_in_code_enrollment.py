"""Set up a sign-in code at sign-in (login slice sub-slice L3c-2b).

DL-056, SEC-013, API-096, UI-110, DB-AUTH-003, DB-AUTH-004. An account that needs MFA and has no
sign-in code gets an `enrollment` challenge at sign-in (migration `20270130_187`). Beginning the
enrollment writes a `pending` sign-in code of the account and one start row that ties it to that
challenge; the start's insert guard checks that the challenge is open and the account still needs
a sign-in code (MFA policy `required`, active, classified, no active sign-in code), so an
`enrollment` challenge left for an account whose MFA was turned off in the meantime starts
nothing. Confirming it with the right code activates the sign-in code, uses its time step and
writes the session with a `totp` proof: the proof guard now also accepts, for an `enrollment`
challenge, the sign-in code started by that challenge, with a step used since the challenge. One
new relation, append-only; the runtime role gets column privileges only. The start names its
sign-in code without a foreign key, checked by its insert guard instead, so the existing truncate
refusal of `app.totp_mfa_enrollments` stays as it is. A purely additive change: the replaced
proof guard keeps every earlier condition and accepts one more case.
"""

from alembic import op

revision = "20270131_188"
down_revision = "20270130_187"
branch_labels = None
depends_on = None

APPEND_ONLY = "app.reject_sign_in_code_history_change()"
START_OF_CHALLENGE = "app.check_sign_in_code_enrollment_start()"
PROOF_OF_CHALLENGE = "app.check_browser_session_mfa_proof()"


def upgrade() -> None:
    """Create the enrollment start relation, its guards and grants, and widen the proof guard."""
    op.execute(
        """
        CREATE TABLE app.sign_in_code_enrollment_starts (
            challenge_id uuid PRIMARY KEY
                REFERENCES app.sign_in_mfa_challenges (challenge_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            enrollment_id uuid NOT NULL UNIQUE,
            started_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(started_at))
        )
        """
    )
    # One start per open `enrollment` challenge, for a `pending` sign-in code of the challenge's
    # own account made since the challenge, while the account still needs a sign-in code (the
    # L3c-2a binding: a sign-in code turned off between the sign-in lookup and the challenge
    # write can leave an `enrollment` challenge for an account with MFA `optional`).
    op.execute(
        f"""
        CREATE FUNCTION {START_OF_CHALLENGE}
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM app.sign_in_mfa_challenges AS challenge
                JOIN app.user_accounts AS account ON account.actor_id = challenge.actor_id
                JOIN app.user_account_classes AS classification
                  ON classification.actor_id = challenge.actor_id
                WHERE challenge.challenge_id = NEW.challenge_id
                  AND challenge.actor_id = NEW.actor_id
                  AND challenge.purpose = 'enrollment'
                  AND challenge.completed_at IS NULL
                  AND pg_catalog.statement_timestamp() < challenge.expires_at
                  AND account.lifecycle_state = 'active'
                  AND account.mfa_policy_class = 'required'
            ) THEN
                RAISE EXCEPTION 'a sign-in code is started by an open enrollment challenge'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM app.totp_mfa_enrollments AS enrollment
                WHERE enrollment.actor_id = NEW.actor_id
                  AND enrollment.enrollment_state = 'active'
            ) THEN
                RAISE EXCEPTION 'a sign-in code is started only for an account without one'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM app.totp_mfa_enrollments AS enrollment
                JOIN app.sign_in_mfa_challenges AS challenge
                  ON challenge.challenge_id = NEW.challenge_id
                WHERE enrollment.enrollment_id = NEW.enrollment_id
                  AND enrollment.actor_id = NEW.actor_id
                  AND enrollment.enrollment_state = 'pending'
                  AND enrollment.created_at >= challenge.created_at
            ) THEN
                RAISE EXCEPTION 'a started sign-in code is a new pending code of the account'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            NEW.started_at := pg_catalog.statement_timestamp();
            RETURN NEW;
        END;
        $$
        """
    )
    # The proof guard of migration 20270130_187 with one more accepted case: a `totp` proof of an
    # `enrollment` challenge names the sign-in code that challenge started (login sub-slice
    # L3c-2b; the L3c-2a binding), with a step of it used since the challenge was made.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {PROOF_OF_CHALLENGE}
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
            ) AND NOT EXISTS (
                SELECT 1
                FROM app.sign_in_mfa_challenges AS challenge
                JOIN app.sign_in_code_enrollment_starts AS start
                  ON start.challenge_id = challenge.challenge_id
                 AND start.actor_id = challenge.actor_id
                JOIN app.totp_mfa_enrollments AS enrollment
                  ON enrollment.enrollment_id = start.enrollment_id
                 AND enrollment.actor_id = challenge.actor_id
                JOIN app.totp_used_steps AS used
                  ON used.enrollment_id = start.enrollment_id
                WHERE challenge.challenge_id = NEW.challenge_id
                  AND challenge.purpose = 'enrollment'
                  AND start.enrollment_id = NEW.enrollment_id
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
    op.execute(
        f"""
        CREATE TRIGGER sign_in_code_enrollment_starts_of_challenge
        BEFORE INSERT ON app.sign_in_code_enrollment_starts
        FOR EACH ROW
        EXECUTE FUNCTION {START_OF_CHALLENGE}
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER sign_in_code_enrollment_starts_are_append_only
        BEFORE UPDATE OR DELETE ON app.sign_in_code_enrollment_starts
        FOR EACH ROW
        EXECUTE FUNCTION {APPEND_ONLY}
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER sign_in_code_enrollment_starts_reject_truncate
        BEFORE TRUNCATE ON app.sign_in_code_enrollment_starts
        FOR EACH STATEMENT
        EXECUTE FUNCTION {APPEND_ONLY}
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {START_OF_CHALLENGE} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON FUNCTION {PROOF_OF_CHALLENGE} FROM PUBLIC")
    op.execute("REVOKE ALL ON app.sign_in_code_enrollment_starts FROM PUBLIC, prm_runtime")
    op.execute(
        """
        GRANT SELECT (challenge_id, actor_id, enrollment_id, started_at)
        ON app.sign_in_code_enrollment_starts TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT INSERT (challenge_id, actor_id, enrollment_id)
        ON app.sign_in_code_enrollment_starts TO prm_runtime
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("sign-in code enrollment migration is forward-only")
