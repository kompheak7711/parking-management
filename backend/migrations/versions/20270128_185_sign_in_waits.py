"""Count wrong sign-in tries and make the person wait (login slice sub-slice L3b).

DL-080 item 10 as amended by the owner (DL-081, 2026-10-23), Q-2026-10-21-154 (a), SEC-012,
UI-109, DB-AUTH-011. After 3 wrong tries in a row for one username the person waits 5 minutes;
after 5 in a row 15 minutes; after that every 2 more wrong tries start another 15-minute wait,
until a correct sign-in clears the count. Unknown usernames are counted the same way. A source
address that makes 20 wrong tries in 15 minutes waits 15 minutes. Tries during a wait are refused
by the application without checking the password and add nothing. The application passes only
sha256 digests of the username and of the source address, never the typed text. Three new
append-only relations and three definer functions, READ COMMITTED only; the runtime role may run
the functions and has no privilege on the relations. A purely additive change.
"""

from alembic import op

revision = "20270128_185"
down_revision = "20270127_184"
branch_labels = None
depends_on = None

APPEND_ONLY = "app.reject_sign_in_try_history_change()"
WAIT_SECONDS = "app.sign_in_wait_seconds(bytea,bytea)"
RECORD = "app.record_sign_in_wrong_try(bytea,bytea,text)"
CLEAR = "app.clear_sign_in_wrong_tries(bytea,bytea,uuid)"
TABLES = ("sign_in_wrong_tries", "sign_in_waits", "sign_in_try_clears")

# The seconds left of the longest active username or source wait at `v_now`, or NULL.
ACTIVE_WAIT = """
            SELECT pg_catalog.max(
                       pg_catalog.ceil(
                           EXTRACT(EPOCH FROM wait.ends_at - v_now)
                       )::integer
                   )
            INTO v_seconds
            FROM app.sign_in_waits AS wait
            WHERE wait.ends_at > v_now
              AND (
                  (wait.wait_scope = 'username' AND wait.key_digest = p_username_digest)
                  OR (wait.wait_scope = 'source' AND wait.key_digest = p_source_digest)
              );
"""
# Fail closed on anything but READ COMMITTED (a later snapshot would miss a parallel try) and on
# a key that is not a sha256 digest.
CHECK_CALL = """
            IF pg_catalog.current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'sign-in tries are counted only at READ COMMITTED'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            IF p_username_digest IS NULL OR pg_catalog.length(p_username_digest) <> 32
               OR p_source_digest IS NULL OR pg_catalog.length(p_source_digest) <> 32 THEN
                RAISE EXCEPTION 'a sign-in try key is a sha256 digest'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
"""
# The username lock first, then the source lock, in every function, so two tries never wait on
# each other in a cycle.
TAKE_LOCKS = """
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'sign-in-username:' || pg_catalog.encode(p_username_digest, 'hex'), 0
                )
            );
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'sign-in-source:' || pg_catalog.encode(p_source_digest, 'hex'), 0
                )
            );
            v_now := pg_catalog.clock_timestamp();
"""
# The last try a correct sign-in cleared for the username, or 0.
LAST_CLEARED = """
            SELECT COALESCE(pg_catalog.max(cleared.covers_through_try_no), 0)
            INTO v_cleared_through
            FROM app.sign_in_try_clears AS cleared
            WHERE cleared.username_digest = p_username_digest;
"""


def upgrade() -> None:
    """Create the try, wait and clear relations, their guard and the three functions."""
    op.execute(
        """
        CREATE TABLE app.sign_in_wrong_tries (
            try_no bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            username_digest bytea NOT NULL CHECK (length(username_digest) = 32),
            source_digest bytea NOT NULL CHECK (length(source_digest) = 32),
            try_kind text NOT NULL
                CHECK (try_kind IN ('password', 'sign_in_code', 'recovery_code')),
            tried_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(tried_at))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX sign_in_wrong_tries_username_idx
        ON app.sign_in_wrong_tries (username_digest, try_no)
        """
    )
    op.execute(
        """
        CREATE INDEX sign_in_wrong_tries_source_idx
        ON app.sign_in_wrong_tries (source_digest, tried_at)
        """
    )
    op.execute(
        """
        CREATE TABLE app.sign_in_waits (
            wait_no bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            wait_scope text NOT NULL CHECK (wait_scope IN ('username', 'source')),
            key_digest bytea NOT NULL CHECK (length(key_digest) = 32),
            starts_at timestamptz NOT NULL CHECK (isfinite(starts_at)),
            ends_at timestamptz NOT NULL CHECK (isfinite(ends_at)),
            wrong_try_no bigint NOT NULL
                REFERENCES app.sign_in_wrong_tries (try_no)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            -- Only the waits of the owner's rule: 5 or 15 minutes for a username, 15 for a
            -- source (review round 1).
            CHECK (
                (wait_scope = 'username'
                 AND ends_at - starts_at IN (interval '5 minutes', interval '15 minutes'))
                OR (wait_scope = 'source' AND ends_at - starts_at = interval '15 minutes')
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX sign_in_waits_key_idx
        ON app.sign_in_waits (key_digest, ends_at)
        """
    )
    op.execute(
        """
        CREATE TABLE app.sign_in_try_clears (
            clear_no bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            username_digest bytea NOT NULL CHECK (length(username_digest) = 32),
            actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            covers_through_try_no bigint NOT NULL
                REFERENCES app.sign_in_wrong_tries (try_no)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            cleared_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(cleared_at))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX sign_in_try_clears_username_idx
        ON app.sign_in_try_clears (username_digest, covers_through_try_no)
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_sign_in_try_history_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'sign-in try history is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    for table in TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_are_append_only
            BEFORE UPDATE OR DELETE ON app.{table}
            FOR EACH ROW
            EXECUTE FUNCTION {APPEND_ONLY}
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_truncate
            BEFORE TRUNCATE ON app.{table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION {APPEND_ONLY}
            """
        )
    op.execute(
        f"""
        CREATE FUNCTION app.sign_in_wait_seconds(
            p_username_digest bytea,
            p_source_digest bytea
        )
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_now timestamptz;
            v_seconds integer;
        BEGIN
            {CHECK_CALL}
            -- Under the same locks as the count and the clear, so a wrong try that is being
            -- recorded is waited for (review round 1, security: the MFA step of sign-in asks
            -- again after the password check).
            {TAKE_LOCKS}
            {ACTIVE_WAIT}
            IF v_seconds IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN GREATEST(v_seconds, 1);
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION app.record_sign_in_wrong_try(
            p_username_digest bytea,
            p_source_digest bytea,
            p_try_kind text
        )
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_now timestamptz;
            v_seconds integer;
            v_cleared_through bigint;
            v_try_no bigint;
            v_username_tries bigint;
            v_source_tries bigint;
            v_minutes integer;
        BEGIN
            {CHECK_CALL}
            IF p_try_kind IS NULL
               OR p_try_kind NOT IN ('password', 'sign_in_code', 'recovery_code') THEN
                RAISE EXCEPTION 'unknown sign-in try kind'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            {TAKE_LOCKS}
            -- A wait that a parallel try started while this try was checked: this try adds
            -- nothing and gets the same wait.
            {ACTIVE_WAIT}
            IF v_seconds IS NOT NULL THEN
                RETURN GREATEST(v_seconds, 1);
            END IF;

            INSERT INTO app.sign_in_wrong_tries (
                username_digest, source_digest, try_kind, tried_at
            ) VALUES (
                p_username_digest, p_source_digest, p_try_kind, v_now
            )
            RETURNING try_no INTO v_try_no;

            {LAST_CLEARED}
            SELECT pg_catalog.count(*)
            INTO v_username_tries
            FROM app.sign_in_wrong_tries AS wrong
            WHERE wrong.username_digest = p_username_digest
              AND wrong.try_no > v_cleared_through;
            -- The owner's rule: 3 in a row wait 5 minutes; 5 in a row wait 15 minutes; every
            -- 2 more wait 15 minutes again.
            v_minutes := CASE
                WHEN v_username_tries = 3 THEN 5
                WHEN v_username_tries >= 5 AND (v_username_tries - 5) % 2 = 0 THEN 15
                ELSE NULL
            END;
            IF v_minutes IS NOT NULL THEN
                INSERT INTO app.sign_in_waits (
                    wait_scope, key_digest, starts_at, ends_at, wrong_try_no
                ) VALUES (
                    'username', p_username_digest, v_now,
                    v_now + pg_catalog.make_interval(mins => v_minutes), v_try_no
                );
                v_seconds := v_minutes * 60;
            END IF;

            SELECT pg_catalog.count(*)
            INTO v_source_tries
            FROM app.sign_in_wrong_tries AS wrong
            WHERE wrong.source_digest = p_source_digest
              AND wrong.tried_at > v_now - interval '15 minutes';
            IF v_source_tries >= 20 THEN
                INSERT INTO app.sign_in_waits (
                    wait_scope, key_digest, starts_at, ends_at, wrong_try_no
                ) VALUES (
                    'source', p_source_digest, v_now, v_now + interval '15 minutes', v_try_no
                );
                v_seconds := 15 * 60;
            END IF;
            RETURN v_seconds;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION app.clear_sign_in_wrong_tries(
            p_username_digest bytea,
            p_source_digest bytea,
            p_actor_id uuid
        )
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_now timestamptz;
            v_seconds integer;
            v_cleared_through bigint;
            v_last_try bigint;
        BEGIN
            {CHECK_CALL}
            {TAKE_LOCKS}
            -- A wait that a parallel wrong try started after this sign-in was checked wins
            -- (fail closed): nothing is cleared and the sign-in is refused.
            {ACTIVE_WAIT}
            IF v_seconds IS NOT NULL THEN
                RETURN GREATEST(v_seconds, 1);
            END IF;

            -- Only an active account clears, and only the count of its own username (review
            -- round 1); a session write for any other account is refused later in the same
            -- transaction, which then rolls back.
            IF NOT EXISTS (
                   SELECT 1
                   FROM app.user_accounts AS account
                   WHERE account.actor_id = p_actor_id
                     AND account.lifecycle_state = 'active'
                     AND pg_catalog.sha256(
                             pg_catalog.convert_to(
                                 'username:' || account.normalized_username, 'UTF8'
                             )
                         ) = p_username_digest
               ) THEN
                RETURN NULL;
            END IF;
            {LAST_CLEARED}
            SELECT pg_catalog.max(wrong.try_no)
            INTO v_last_try
            FROM app.sign_in_wrong_tries AS wrong
            WHERE wrong.username_digest = p_username_digest;
            IF v_last_try IS NOT NULL AND v_last_try > v_cleared_through THEN
                INSERT INTO app.sign_in_try_clears (
                    username_digest, actor_id, covers_through_try_no, cleared_at
                ) VALUES (
                    p_username_digest, p_actor_id, v_last_try, v_now
                );
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    for function in (APPEND_ONLY, WAIT_SECONDS, RECORD, CLEAR):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for table in TABLES:
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC")
    for function in (WAIT_SECONDS, RECORD, CLEAR):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("sign-in wait migration is forward-only")
