"""Sign in with a recovery code (login slice sub-slice L3c-2c-2).

DL-058, API-096, API-098, TEST-129, DB-AUTH-003, DB-AUTH-004. A sign-in code challenge can be
completed with one of the account's recovery codes instead of the sign-in code; the code is
consumed through `app.perform_account_recovery` (mode `recovery_code`, audited, every other
session of the account revoked) and the session gets a `recovery_code` proof. The proof now names
the consumed recovery code (a new column, unique and with a foreign key, so one code proves one
session; insert and select privileges for the runtime role), and the proof guard checks it (the
L3c-2a binding): a `recovery_code` proof needs a `challenge` (not an `enrollment`) and a recovery
code of a live set of the challenge's own account, made no earlier than the sign-in code the
challenge was made for, consumed by that account since the challenge was made. The replaced guard
keeps every earlier condition. A purely additive change: the new column is empty for every `totp`
proof, and no `recovery_code` proof was written before this sub-slice.
"""

from alembic import op

revision = "20270202_190"
down_revision = "20270201_189"
branch_labels = None
depends_on = None

PROOF_OF_CHALLENGE = "app.check_browser_session_mfa_proof()"


def upgrade() -> None:
    """Add the proof's recovery code, its check, the grants, and widen the proof guard."""
    op.execute(
        """
        ALTER TABLE app.browser_session_mfa_proofs
        ADD COLUMN recovery_code_id uuid UNIQUE
            REFERENCES app.recovery_codes (code_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
        """
    )
    op.execute(
        """
        ALTER TABLE app.browser_session_mfa_proofs
        ADD CONSTRAINT browser_session_mfa_proofs_recovery_code_of_method
        CHECK ((method = 'recovery_code') = (recovery_code_id IS NOT NULL))
        """
    )
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
            -- A `recovery_code` proof (login sub-slice L3c-2c-2): a `challenge`, and a recovery
            -- code of a live set of its own account, made no earlier than the sign-in code the
            -- challenge was made for (review round 2), consumed by that account since the
            -- challenge was made.
            IF NEW.method = 'recovery_code' AND NOT EXISTS (
                SELECT 1
                FROM app.sign_in_mfa_challenges AS challenge
                JOIN app.recovery_code_sets AS recovery_set
                  ON recovery_set.actor_id = challenge.actor_id
                JOIN app.recovery_codes AS recovery_code
                  ON recovery_code.set_id = recovery_set.set_id
                JOIN app.totp_mfa_enrollments AS enrollment
                  ON enrollment.enrollment_id = challenge.enrollment_id
                WHERE challenge.challenge_id = NEW.challenge_id
                  AND challenge.purpose = 'challenge'
                  AND recovery_code.code_id = NEW.recovery_code_id
                  AND recovery_set.invalidated_at IS NULL
                  AND recovery_set.created_at >= enrollment.created_at
                  AND recovery_code.consumed_by_actor_id = challenge.actor_id
                  AND recovery_code.consumed_at >= challenge.created_at
            ) THEN
                RAISE EXCEPTION 'a recovery-code proof names a code used since the challenge'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {PROOF_OF_CHALLENGE} FROM PUBLIC")
    op.execute(
        "GRANT INSERT (recovery_code_id) ON app.browser_session_mfa_proofs TO prm_runtime"
    )
    # The session read checks that the proof's recovery code's set is still live (review
    # round 2).
    op.execute(
        "GRANT SELECT (recovery_code_id) ON app.browser_session_mfa_proofs TO prm_runtime"
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("recovery-code sign-in migration is forward-only")
