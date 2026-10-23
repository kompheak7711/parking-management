"""The wrong-try clear no longer compares a keyed digest it cannot make (login slice L3c-1).

DL-081, owner answer (a) to Q-2026-10-23-175, DB-AUTH-011. From sub-slice L3c-1 the application
keys the wrong-try digests with HMAC-SHA256 under a key derived from the protected key file; the
database has no key, so `app.clear_sign_in_wrong_tries` can no longer check that the digest is the
signed-in account's own username (review round 2 of L3b). The function is replaced with the same
signature, owner, privileges and attributes; the only change is that this comparison is gone. It
still clears only for an active account, still answers an active wait without clearing, and still
takes the username lock and then the source lock. A relaxing change.
"""

from alembic import op

revision = "20270129_186"
down_revision = "20270128_185"
branch_labels = None
depends_on = None

# The fragments of migration 20270128_185, unchanged.
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

LAST_CLEARED = """
            SELECT COALESCE(pg_catalog.max(cleared.covers_through_try_no), 0)
            INTO v_cleared_through
            FROM app.sign_in_try_clears AS cleared
            WHERE cleared.username_digest = p_username_digest;
"""


def upgrade() -> None:
    """Replace the clear function without the digest comparison."""
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION app.clear_sign_in_wrong_tries(
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

            -- Only an active account clears; a session write for any other account is refused
            -- later in the same transaction, which then rolls back. The digest is keyed by the
            -- application (login sub-slice L3c-1), so it is not compared with the username here.
            IF NOT EXISTS (
                   SELECT 1
                   FROM app.user_accounts AS account
                   WHERE account.actor_id = p_actor_id
                     AND account.lifecycle_state = 'active'
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


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("sign-in clear migration is forward-only")
