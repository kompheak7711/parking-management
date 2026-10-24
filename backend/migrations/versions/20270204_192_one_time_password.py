"""The Owner's reset with a one-time password and the forced change (login sub-slice L4a).

DL-058, DL-080 item 10, DL-081 (owner answers (a) to Q-2026-10-21-153, Q-2026-10-21-165 and
Q-2026-10-23-180), API-099, SEC-011, SEC-014, SEC-075, DB-AUTH-002, DB-AUTH-005; technical points
in Q-2026-10-24-185 (decided by Claude under the owner's 2026-10-23 22:30 rule).

- `app.one_time_passwords`: one append-only row per one-time password the Owner gives a Manager
  or Staff account: who, by whom, why, when, and its end (24 hours later, database clock). The
  password itself is never stored; its Argon2id verifier replaces the account's password.
- `app.password_credentials.one_time_password_id`: set while the account's password is a
  one-time password that has not been changed yet; the forced change clears it.
- `app.password_change_challenges`: the pre-authentication state of a sign-in with a one-time
  password (no session, no actor): the digest of the pre-authentication token, 10 minutes.
- `app.password_changes`: one append-only row per forced change.
- `app.issue_one_time_password`: the Owner's reset (and a new account's first password), with
  "also reset MFA", which also ends the live recovery codes and the Settings access in the same
  step; every live session of the account ends.
- `app.change_one_time_password`: the forced change; every live session of the account ends.
- `app.perform_account_recovery` (same signature): the administrative mode is refused (the
  Owner's reset is `app.issue_one_time_password`, so it always leaves a one-time password that
  must be changed); the emergency mode always needs a new password (review round 1: stricter
  than Q-2026-10-24-185, which asks for one only with an MFA reset) and ends the live recovery
  codes when it resets MFA.

Every replacement that can end a sign-in code or the recovery codes (the reset, the emergency
recovery) takes the blocking transaction lock on `recovery-codes:` and then on
`password-credential:` before anything else; the forced change, which touches neither, takes
only `password-credential:`. Every session write takes `password-credential:` shared as its
first statement (Python), so a session made with an old password or code cannot commit after
the replacement (bindings from L3a-1 and L3d-1). New tables, a new column and two new
functions; the replaced `app.perform_account_recovery` refuses what it accepted before (the
administrative mode, an emergency recovery without a new password).
"""

from alembic import op

revision = "20270204_192"
down_revision = "20270203_191"
branch_labels = None
depends_on = None

PERFORM_ACCOUNT_RECOVERY = """
        CREATE OR REPLACE FUNCTION app.perform_account_recovery(
            p_actor_id uuid,
            p_target_actor_id uuid,
            p_correlation_id uuid,
            p_recovery_mode text,
            p_procedure_identity text,
            p_reason text,
            p_verifier_encoding text,
            p_algorithm text,
            p_work_factor_metadata jsonb,
            p_reset_mfa boolean,
            p_recovery_code_id uuid
        ) RETURNS TABLE (
            password_changed boolean,
            mfa_disabled boolean,
            recovery_code_consumed boolean,
            sessions_revoked integer
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            operation_actor_id uuid := COALESCE(p_actor_id, p_target_actor_id);
            password_present_before boolean;
            active_mfa_before integer;
            active_sessions_before integer;
            code_available_before boolean := false;
            recovery_codes_invalidated boolean := false;
            mutation_provenance text;
            previous_state_document jsonb;
            resulting_state_document jsonb;
        BEGIN
            -- Login sub-slice L4a: the Owner's reset is `app.issue_one_time_password`, which
            -- always leaves a one-time password that must be changed at the next sign-in.
            IF p_recovery_mode IS NULL OR p_recovery_mode = 'administrative' THEN
                RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
            END IF;
            IF p_recovery_mode = 'emergency' THEN
                -- The replacement locks first, in the order of every other replacement
                -- (Q-2026-10-24-185), so a session write that checked the old password or code
                -- either commits first (and its session is revoked below) or waits and is
                -- refused.
                PERFORM pg_advisory_xact_lock(
                    hashtextextended('recovery-codes:' || p_target_actor_id::text, 0)
                );
                PERFORM pg_advisory_xact_lock(
                    hashtextextended('password-credential:' || p_target_actor_id::text, 0)
                );
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM app.user_accounts
                WHERE actor_id = p_target_actor_id AND lifecycle_state = 'active'
            ) THEN
                RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
            END IF;
            IF p_recovery_mode = 'recovery_code' THEN
                IF p_actor_id IS DISTINCT FROM p_target_actor_id
                   OR p_procedure_identity IS NOT NULL
                   OR p_reason <> 'mfa_recovery'
                   OR p_verifier_encoding IS NOT NULL OR p_reset_mfa
                   OR p_recovery_code_id IS NULL THEN
                    RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
                END IF;
            ELSIF p_recovery_mode = 'emergency' THEN
                -- Q-2026-10-23-180 (a): a sign-in code reset also replaces the password.
                IF p_actor_id IS NOT NULL
                   OR p_procedure_identity IS NULL
                   OR p_procedure_identity !~ '^[a-z][a-z0-9_-]{0,63}$'
                   OR p_reason <> 'documented_emergency_recovery'
                   OR p_verifier_encoding IS NULL
                   OR p_reset_mfa IS NULL
                   OR p_recovery_code_id IS NOT NULL THEN
                    RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
                END IF;
                PERFORM 1 FROM app.user_accounts
                WHERE actor_id = p_target_actor_id
                FOR NO KEY UPDATE;
            ELSE
                RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
            END IF;
            IF p_verifier_encoding IS NOT NULL AND (
                p_algorithm IS NULL OR p_work_factor_metadata IS NULL
                OR NOT app.valid_password_work_factor_metadata(p_work_factor_metadata)
            ) THEN
                RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
            END IF;

            SELECT EXISTS (
                SELECT 1 FROM app.password_credentials WHERE actor_id = p_target_actor_id
            ) INTO password_present_before;
            SELECT count(*)::integer INTO active_mfa_before
            FROM app.totp_mfa_enrollments
            WHERE actor_id = p_target_actor_id AND enrollment_state IN ('pending', 'active');
            SELECT count(*)::integer INTO active_sessions_before
            FROM app.browser_sessions
            WHERE actor_id = p_target_actor_id AND revoked_at IS NULL
              AND idle_expires_at > statement_timestamp()
              AND absolute_expires_at > statement_timestamp();

            IF p_recovery_mode = 'recovery_code' THEN
                SELECT true INTO code_available_before
                FROM app.recovery_codes AS recovery_code
                JOIN app.recovery_code_sets AS recovery_set USING (set_id)
                WHERE recovery_code.code_id = p_recovery_code_id
                  AND recovery_set.actor_id = p_target_actor_id
                  AND recovery_code.consumed_at IS NULL
                  AND recovery_code.invalidated_at IS NULL
                  AND recovery_set.invalidated_at IS NULL
                FOR UPDATE OF recovery_code, recovery_set;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
                END IF;
            END IF;

            previous_state_document := jsonb_build_object(
                'password_credential_present', password_present_before,
                'active_mfa_enrollments', active_mfa_before,
                'active_sessions', active_sessions_before,
                'recovery_code_available', code_available_before
            );
            mutation_provenance := jsonb_build_object(
                'action', 'account_recovery',
                'correlation_id', p_correlation_id,
                'mode', p_recovery_mode,
                'procedure_identity', p_procedure_identity,
                'reason', p_reason
            )::text;

            password_changed := false;
            IF p_verifier_encoding IS NOT NULL THEN
                UPDATE app.password_credentials
                SET verifier_encoding = p_verifier_encoding,
                    algorithm = p_algorithm,
                    work_factor_metadata = p_work_factor_metadata,
                    changed_by_actor_id = operation_actor_id,
                    provenance = mutation_provenance,
                    one_time_password_id = NULL
                WHERE actor_id = p_target_actor_id;
                password_changed := FOUND;
                IF NOT password_changed THEN
                    RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
                END IF;
            END IF;

            mfa_disabled := false;
            IF p_reset_mfa THEN
                UPDATE app.totp_mfa_enrollments
                SET enrollment_state = 'disabled',
                    disabled_by_actor_id = operation_actor_id,
                    disablement_provenance = mutation_provenance
                WHERE actor_id = p_target_actor_id
                  AND enrollment_state IN ('pending', 'active');
                mfa_disabled := FOUND;
                -- L2a review round 2 and the L4 binding: the live recovery codes end with the
                -- sign-in code.
                UPDATE app.recovery_code_sets
                SET invalidated_at = statement_timestamp(),
                    invalidated_by_actor_id = operation_actor_id,
                    invalidation_provenance = mutation_provenance
                WHERE actor_id = p_target_actor_id
                  AND invalidated_at IS NULL;
                recovery_codes_invalidated := FOUND;
            END IF;

            recovery_code_consumed := false;
            IF p_recovery_code_id IS NOT NULL THEN
                UPDATE app.recovery_codes
                SET consumed_at = statement_timestamp(),
                    consumed_by_actor_id = operation_actor_id,
                    consumption_provenance = mutation_provenance
                WHERE code_id = p_recovery_code_id
                  AND consumed_at IS NULL AND invalidated_at IS NULL;
                recovery_code_consumed := FOUND;
                IF NOT recovery_code_consumed THEN
                    RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
                END IF;
            END IF;

            IF p_recovery_mode <> 'recovery_code' AND NOT (password_changed OR mfa_disabled) THEN
                RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
            END IF;

            UPDATE app.browser_sessions
            SET revoked_by_actor_id = operation_actor_id,
                revocation_reason = CASE
                    WHEN p_recovery_mode = 'recovery_code' THEN 'mfa_recovery'
                    WHEN password_changed THEN 'password_reset'
                    ELSE 'mfa_reset'
                END,
                revocation_provenance = mutation_provenance
            WHERE actor_id = p_target_actor_id
              AND revoked_at IS NULL
              AND idle_expires_at > statement_timestamp()
              AND absolute_expires_at > statement_timestamp();
            GET DIAGNOSTICS sessions_revoked = ROW_COUNT;

            resulting_state_document := jsonb_build_object(
                'password_changed', password_changed,
                'active_mfa_enrollments',
                    active_mfa_before
                    - CASE WHEN mfa_disabled THEN active_mfa_before ELSE 0 END,
                'active_sessions', active_sessions_before - sessions_revoked,
                'recovery_code_consumed', recovery_code_consumed,
                'recovery_codes_invalidated', recovery_codes_invalidated
            );
            INSERT INTO app.account_recovery_audit_events (
                actor_id, target_actor_id, correlation_id, recovery_mode,
                procedure_identity, reason, outcome, previous_state,
                resulting_state, password_changed, mfa_disabled,
                recovery_code_consumed, sessions_revoked
            ) VALUES (
                p_actor_id, p_target_actor_id, p_correlation_id, p_recovery_mode,
                p_procedure_identity, p_reason, 'completed', previous_state_document,
                resulting_state_document, password_changed, mfa_disabled,
                recovery_code_consumed, sessions_revoked
            );
            RETURN NEXT;
        END;
        $$
"""


def upgrade() -> None:
    """Add the one-time password records, the two definer functions and the guards."""
    op.execute(
        """
        CREATE TABLE app.one_time_passwords (
            one_time_password_id uuid PRIMARY KEY,
            actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
            issued_by_actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
            issued_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            expires_at timestamptz NOT NULL,
            reason text NOT NULL CHECK (
                reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500
            ),
            correlation_id uuid NOT NULL,
            UNIQUE (one_time_password_id, actor_id),
            CHECK (expires_at = issued_at + interval '24 hours'),
            CHECK (issued_by_actor_id <> actor_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX one_time_passwords_actor_time
        ON app.one_time_passwords (actor_id, issued_at)
        """
    )
    op.execute(
        """
        ALTER TABLE app.password_credentials
        ADD COLUMN one_time_password_id uuid,
        ADD CONSTRAINT password_credentials_one_time_password_fkey
            FOREIGN KEY (one_time_password_id, actor_id)
            REFERENCES app.one_time_passwords (one_time_password_id, actor_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT
        """
    )
    op.execute(
        """
        CREATE TABLE app.password_change_challenges (
            challenge_id uuid PRIMARY KEY,
            actor_id uuid NOT NULL,
            one_time_password_id uuid NOT NULL,
            token_verifier bytea NOT NULL UNIQUE CHECK (octet_length(token_verifier) = 32),
            checked_verifier_digest bytea NOT NULL
                CHECK (octet_length(checked_verifier_digest) = 32),
            username_digest bytea NOT NULL CHECK (octet_length(username_digest) = 32),
            source_digest bytea NOT NULL CHECK (octet_length(source_digest) = 32),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            expires_at timestamptz NOT NULL
                DEFAULT statement_timestamp() + interval '10 minutes',
            completed_at timestamptz,
            CHECK (expires_at = created_at + interval '10 minutes'),
            CHECK (completed_at IS NULL OR completed_at >= created_at),
            FOREIGN KEY (one_time_password_id, actor_id)
                REFERENCES app.one_time_passwords (one_time_password_id, actor_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.password_changes (
            change_id uuid PRIMARY KEY,
            actor_id uuid NOT NULL,
            one_time_password_id uuid NOT NULL UNIQUE,
            changed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            correlation_id uuid NOT NULL,
            sessions_revoked integer NOT NULL CHECK (sessions_revoked >= 0),
            FOREIGN KEY (one_time_password_id, actor_id)
                REFERENCES app.one_time_passwords (one_time_password_id, actor_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_one_time_password_history_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            -- A challenge may only be completed once; nothing else of these records changes.
            -- Nested: the record of another table has no `completed_at`.
            IF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'password_change_challenges' THEN
                IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL
                   AND (NEW.challenge_id, NEW.actor_id, NEW.one_time_password_id,
                        NEW.token_verifier, NEW.checked_verifier_digest, NEW.username_digest,
                        NEW.source_digest, NEW.created_at, NEW.expires_at)
                       IS NOT DISTINCT FROM
                       (OLD.challenge_id, OLD.actor_id, OLD.one_time_password_id,
                        OLD.token_verifier, OLD.checked_verifier_digest, OLD.username_digest,
                        OLD.source_digest, OLD.created_at, OLD.expires_at) THEN
                    RETURN NEW;
                END IF;
            END IF;
            RAISE EXCEPTION 'one-time password history cannot be changed or destroyed'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.stamp_password_change_challenge()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            -- The database clock sets the 10 minutes of a new challenge, whatever was sent.
            NEW.created_at := statement_timestamp();
            NEW.expires_at := statement_timestamp() + interval '10 minutes';
            NEW.completed_at := NULL;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER password_change_challenges_stamp
        BEFORE INSERT ON app.password_change_challenges
        FOR EACH ROW
        EXECUTE FUNCTION app.stamp_password_change_challenge()
        """
    )
    for table in ("one_time_passwords", "password_change_challenges", "password_changes"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_change
            BEFORE UPDATE OR DELETE ON app.{table}
            FOR EACH ROW
            EXECUTE FUNCTION app.reject_one_time_password_history_change()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_truncate
            BEFORE TRUNCATE ON app.{table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_one_time_password_history_change()
            """
        )
    op.execute(
        """
        CREATE FUNCTION app.issue_one_time_password(
            p_owner_id uuid,
            p_actor_id uuid,
            p_correlation_id uuid,
            p_reason text,
            p_verifier_encoding text,
            p_algorithm text,
            p_work_factor_metadata jsonb,
            p_reset_mfa boolean
        ) RETURNS TABLE (
            issued_one_time_password_id uuid,
            issued_expires_at timestamptz,
            sign_in_code_reset boolean,
            recovery_codes_ended boolean,
            settings_access_ended boolean,
            sessions_ended integer
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_lifecycle text;
            v_class text;
            v_password_before boolean;
            v_mfa_before integer;
            v_sessions_before integer;
            v_one_time_id uuid := gen_random_uuid();
            v_expires_at timestamptz;
            v_provenance text;
            v_mfa_disabled boolean := false;
            v_codes_ended boolean := false;
            v_settings_grant uuid;
            v_revoked integer;
            v_resulting jsonb;
        BEGIN
            -- The replacement locks first (Q-2026-10-24-185): the recovery codes (L4 binding
            -- from L3c-2c-2), then the password and sign-in code of the account, which every
            -- session write takes shared as its first statement.
            PERFORM pg_advisory_xact_lock(
                hashtextextended('recovery-codes:' || p_actor_id::text, 0)
            );
            PERFORM pg_advisory_xact_lock(
                hashtextextended('password-credential:' || p_actor_id::text, 0)
            );
            PERFORM app.assert_access_administrator(p_owner_id);
            IF p_actor_id IS NULL OR p_correlation_id IS NULL OR p_reset_mfa IS NULL
               OR p_reason IS NULL OR p_reason <> btrim(p_reason)
               OR length(p_reason) NOT BETWEEN 1 AND 500
               OR p_verifier_encoding IS NULL OR p_algorithm IS NULL
               OR p_work_factor_metadata IS NULL
               OR NOT app.valid_password_work_factor_metadata(p_work_factor_metadata) THEN
                RAISE EXCEPTION 'a one-time password needs a reason and a verifier'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            -- The account row is held against a disable or a Settings grant meanwhile (both
            -- lock it), so a grant cannot slip in after the removal below.
            SELECT account.lifecycle_state, classification.account_class
            INTO v_lifecycle, v_class
            FROM app.user_accounts AS account
            LEFT JOIN app.user_account_classes AS classification
              ON classification.actor_id = account.actor_id
            WHERE account.actor_id = p_actor_id
            FOR NO KEY UPDATE OF account;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the account does not exist' USING ERRCODE = 'no_data_found';
            END IF;
            -- SEC-075 (decides the L1a note): only a Manager or Staff account, by its stored
            -- class; the Owner's own reset is the emergency procedure (DL-058).
            IF v_class IS NULL OR v_class NOT IN ('manager', 'staff') THEN
                RAISE EXCEPTION 'the Owner account is not changed by account administration'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF v_lifecycle <> 'active' THEN
                RAISE EXCEPTION 'a disabled account is not changed'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;

            SELECT EXISTS (
                SELECT 1 FROM app.password_credentials AS credential
                WHERE credential.actor_id = p_actor_id
            ) INTO v_password_before;
            SELECT count(*)::integer INTO v_mfa_before
            FROM app.totp_mfa_enrollments AS enrollment
            WHERE enrollment.actor_id = p_actor_id
              AND enrollment.enrollment_state IN ('pending', 'active');
            SELECT count(*)::integer INTO v_sessions_before
            FROM app.browser_sessions AS browser
            WHERE browser.actor_id = p_actor_id AND browser.revoked_at IS NULL
              AND browser.idle_expires_at > statement_timestamp()
              AND browser.absolute_expires_at > statement_timestamp();
            v_provenance := jsonb_build_object(
                'action', 'one_time_password',
                'correlation_id', p_correlation_id,
                'mode', 'administrative',
                'reason', 'authorized_account_recovery'
            )::text;

            INSERT INTO app.one_time_passwords AS issued (
                one_time_password_id, actor_id, issued_by_actor_id, issued_at, expires_at,
                reason, correlation_id
            ) VALUES (
                v_one_time_id, p_actor_id, p_owner_id, statement_timestamp(),
                statement_timestamp() + interval '24 hours', p_reason, p_correlation_id
            )
            RETURNING issued.expires_at INTO v_expires_at;
            -- Q-2026-10-21-153 (a): a new account gets its first password the same way.
            IF v_password_before THEN
                UPDATE app.password_credentials AS credential
                SET verifier_encoding = p_verifier_encoding,
                    algorithm = p_algorithm,
                    work_factor_metadata = p_work_factor_metadata,
                    changed_by_actor_id = p_owner_id,
                    provenance = v_provenance,
                    one_time_password_id = v_one_time_id
                WHERE credential.actor_id = p_actor_id;
            ELSE
                INSERT INTO app.password_credentials (
                    actor_id, verifier_encoding, algorithm, work_factor_metadata,
                    changed_by_actor_id, provenance, one_time_password_id
                ) VALUES (
                    p_actor_id, p_verifier_encoding, p_algorithm, p_work_factor_metadata,
                    p_owner_id, v_provenance, v_one_time_id
                );
            END IF;

            IF p_reset_mfa THEN
                UPDATE app.totp_mfa_enrollments AS enrollment
                SET enrollment_state = 'disabled',
                    disabled_by_actor_id = p_owner_id,
                    disablement_provenance = v_provenance
                WHERE enrollment.actor_id = p_actor_id
                  AND enrollment.enrollment_state IN ('pending', 'active');
                v_mfa_disabled := FOUND;
                UPDATE app.recovery_code_sets AS recovery_set
                SET invalidated_at = statement_timestamp(),
                    invalidated_by_actor_id = p_owner_id,
                    invalidation_provenance = v_provenance
                WHERE recovery_set.actor_id = p_actor_id
                  AND recovery_set.invalidated_at IS NULL;
                v_codes_ended := FOUND;
                -- Q-2026-10-21-165 (a): the reset of the sign-in code removes the account's
                -- Settings access in the same step, as a recorded removal.
                IF EXISTS (
                       SELECT 1
                       FROM app.user_capability_grants AS given
                       WHERE given.actor_id = p_actor_id
                         AND NOT EXISTS (
                             SELECT 1
                             FROM app.user_capability_grant_removals AS removal
                             WHERE removal.grant_id = given.grant_id
                         )
                   ) THEN
                    v_settings_grant := app.remove_settings_access(
                        p_owner_id, p_actor_id, 'sign-in code reset'
                    );
                END IF;
            END IF;

            v_revoked := app.revoke_live_sessions(
                p_actor_id, p_owner_id, 'password_reset', v_provenance
            );
            v_resulting := jsonb_build_object(
                'password_changed', true,
                'one_time_password', true,
                'active_mfa_enrollments',
                    CASE WHEN v_mfa_disabled THEN 0 ELSE v_mfa_before END,
                'active_sessions', v_sessions_before - v_revoked,
                'recovery_codes_invalidated', v_codes_ended,
                'settings_access_removed', v_settings_grant IS NOT NULL
            );
            INSERT INTO app.account_recovery_audit_events (
                actor_id, target_actor_id, correlation_id, recovery_mode,
                procedure_identity, reason, outcome, previous_state,
                resulting_state, password_changed, mfa_disabled,
                recovery_code_consumed, sessions_revoked
            ) VALUES (
                p_owner_id, p_actor_id, p_correlation_id, 'administrative',
                NULL, 'authorized_account_recovery', 'completed',
                jsonb_build_object(
                    'password_credential_present', v_password_before,
                    'active_mfa_enrollments', v_mfa_before,
                    'active_sessions', v_sessions_before,
                    'recovery_code_available', false
                ),
                v_resulting, true, v_mfa_disabled, false, v_revoked
            );
            PERFORM app.record_access_administration(
                p_owner_id, 'identity.account.one_time_password_given', 'user_account',
                p_actor_id, p_reason, NULL,
                v_resulting || jsonb_build_object(
                    'one_time_password_id', v_one_time_id,
                    'expires_at', v_expires_at,
                    'settings_access_removed_grant_id', v_settings_grant
                ),
                p_correlation_id
            );
            issued_one_time_password_id := v_one_time_id;
            issued_expires_at := v_expires_at;
            sign_in_code_reset := v_mfa_disabled;
            recovery_codes_ended := v_codes_ended;
            settings_access_ended := v_settings_grant IS NOT NULL;
            sessions_ended := v_revoked;
            RETURN NEXT;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.change_one_time_password(
            p_token_verifier bytea,
            p_verifier_encoding text,
            p_algorithm text,
            p_work_factor_metadata jsonb,
            p_correlation_id uuid
        ) RETURNS TABLE (
            changed_actor_id uuid,
            sessions_ended integer
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_actor_id uuid;
            v_challenge app.password_change_challenges%ROWTYPE;
            v_revoked integer;
            v_provenance text;
        BEGIN
            IF p_token_verifier IS NULL OR octet_length(p_token_verifier) <> 32
               OR p_verifier_encoding IS NULL OR p_algorithm IS NULL
               OR p_work_factor_metadata IS NULL
               OR NOT app.valid_password_work_factor_metadata(p_work_factor_metadata)
               OR p_correlation_id IS NULL THEN
                RAISE EXCEPTION 'password change rejected' USING ERRCODE = 'P0001';
            END IF;
            SELECT challenge.actor_id INTO v_actor_id
            FROM app.password_change_challenges AS challenge
            WHERE challenge.token_verifier = p_token_verifier;
            IF v_actor_id IS NULL THEN
                RAISE EXCEPTION 'password change rejected' USING ERRCODE = 'P0001';
            END IF;
            -- The replacement lock before any row lock, as every other replacement.
            PERFORM pg_advisory_xact_lock(
                hashtextextended('password-credential:' || v_actor_id::text, 0)
            );
            SELECT challenge.* INTO v_challenge
            FROM app.password_change_challenges AS challenge
            WHERE challenge.token_verifier = p_token_verifier
              AND challenge.completed_at IS NULL
              AND statement_timestamp() < challenge.expires_at
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'password change rejected' USING ERRCODE = 'P0001';
            END IF;
            PERFORM 1 FROM app.user_accounts AS account
            WHERE account.actor_id = v_actor_id AND account.lifecycle_state = 'active'
            FOR NO KEY UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'password change rejected' USING ERRCODE = 'P0001';
            END IF;
            -- The one-time password the sign-in checked is still the account's password, not
            -- changed and not past its 24 hours (database clock).
            PERFORM 1
            FROM app.password_credentials AS credential
            JOIN app.one_time_passwords AS issued
              ON issued.one_time_password_id = credential.one_time_password_id
            WHERE credential.actor_id = v_actor_id
              AND credential.one_time_password_id = v_challenge.one_time_password_id
              AND statement_timestamp() < issued.expires_at
              AND sha256(convert_to(credential.verifier_encoding, 'UTF8'))
                  = v_challenge.checked_verifier_digest
            FOR UPDATE OF credential;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'password change rejected' USING ERRCODE = 'P0001';
            END IF;
            v_provenance := jsonb_build_object(
                'action', 'one_time_password_change',
                'correlation_id', p_correlation_id
            )::text;
            UPDATE app.password_credentials AS credential
            SET verifier_encoding = p_verifier_encoding,
                algorithm = p_algorithm,
                work_factor_metadata = p_work_factor_metadata,
                changed_by_actor_id = v_actor_id,
                provenance = v_provenance,
                one_time_password_id = NULL
            WHERE credential.actor_id = v_actor_id;
            UPDATE app.password_change_challenges AS challenge
            SET completed_at = statement_timestamp()
            WHERE challenge.challenge_id = v_challenge.challenge_id;
            -- The L3d-1 binding: every write to the password ends the account's sessions in
            -- the same transaction.
            v_revoked := app.revoke_live_sessions(
                v_actor_id, v_actor_id, 'password_reset', v_provenance
            );
            INSERT INTO app.password_changes (
                change_id, actor_id, one_time_password_id, correlation_id, sessions_revoked
            ) VALUES (
                gen_random_uuid(), v_actor_id, v_challenge.one_time_password_id,
                p_correlation_id, v_revoked
            );
            changed_actor_id := v_actor_id;
            sessions_ended := v_revoked;
            RETURN NEXT;
        END;
        $$
        """
    )
    op.execute(PERFORM_ACCOUNT_RECOVERY)
    for trigger_function in (
        "app.reject_one_time_password_history_change()",
        "app.stamp_password_change_challenge()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {trigger_function} FROM PUBLIC")
    for signature in (
        "app.issue_one_time_password(uuid, uuid, uuid, text, text, text, jsonb, boolean)",
        "app.change_one_time_password(bytea, text, text, jsonb, uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    op.execute(
        "REVOKE ALL ON app.one_time_passwords, app.password_change_challenges, "
        "app.password_changes FROM PUBLIC, prm_runtime"
    )
    # The sign-in reads the end of a pending one-time password and writes the pre-authentication
    # state of the change; the change itself and every other write go through the functions.
    op.execute("GRANT SELECT ON app.one_time_passwords TO prm_runtime")
    op.execute("GRANT SELECT, INSERT ON app.password_change_challenges TO prm_runtime")
    # The runtime role reads the credential by column (DB-AUTH-002); the sign-in also reads which
    # one-time password, if any, the credential is.
    op.execute("GRANT SELECT (one_time_password_id) ON app.password_credentials TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("one-time password migration is forward-only")
