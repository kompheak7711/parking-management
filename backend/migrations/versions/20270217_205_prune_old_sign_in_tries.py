"""An Owner-run removal of wrong sign-in tries older than 30 days (V1-056 slice 12c).

Owner answer (a) to Q-2026-10-23-175 (DL-081): the wrong-try rows (`app.sign_in_wrong_tries`,
their ended waits and the clears) older than 30 days can be removed by the Owner with an
additive, reviewed procedure. A wait never lasts longer than 15 minutes, so an old wait changes
nothing.

1. `app.reject_sign_in_try_history_change` (the guard of the three relations) still refuses
   every UPDATE and TRUNCATE, and refuses a DELETE unless the transaction-local setting
   `prm.sign_in_prune` is on (the prune function sets it) and the row is older than 30 days by
   database time (a try by `tried_at`, a wait by `ends_at`, a clear by `cleared_at`). No
   application role has a privilege on the relations, so only the table owner can delete at all.
2. `app.prune_sign_in_wrong_tries(after, limit)` (new; no application role may run it) removes
   the waits that ended more than 30 days ago, then, for the next `limit` usernames after
   `after` (digest order) that have an old try or an old clear, each under the username lock of
   the sign-in functions: the old clears except a username's latest clear while a try it covers
   is recent or named by a wait, and the old tries that no remaining wait or clear names. It runs
   only at READ COMMITTED (the command sets it). It returns the three
   counts and the last username digest of the batch (NULL when there is none); the command runs
   it until that is NULL. A count of a username never grows: a remaining try is never older
   than a removed clear's tries.
3. Indexes on the two foreign keys to the tries, so each removed try is checked by index.

A username's wrong tries older than 30 days no longer count toward a wait once removed (decided
by Claude under the owner's 2026-10-23 22:30 rule, DL-092).
"""

from alembic import op

revision = "20270217_205"
down_revision = "20270216_204"
branch_labels = None
depends_on = None

APPEND_ONLY = "app.reject_sign_in_try_history_change()"
PRUNE = "app.prune_sign_in_wrong_tries(bytea,integer)"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.reject_sign_in_try_history_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_at text;
        BEGIN
            -- V1-056 slice 12c: only the prune function removes rows, and only rows older
            -- than 30 days.
            IF TG_OP = 'DELETE'
               AND pg_catalog.current_setting('prm.sign_in_prune', true) = 'on' THEN
                v_at := pg_catalog.to_jsonb(OLD) ->> CASE TG_TABLE_NAME
                    WHEN 'sign_in_wrong_tries' THEN 'tried_at'
                    WHEN 'sign_in_waits' THEN 'ends_at'
                    WHEN 'sign_in_try_clears' THEN 'cleared_at'
                END;
                IF v_at IS NOT NULL
                   AND v_at::timestamptz
                       < pg_catalog.statement_timestamp() - interval '30 days' THEN
                    RETURN OLD;
                END IF;
            END IF;
            RAISE EXCEPTION 'sign-in try history is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE INDEX sign_in_waits_wrong_try_idx ON app.sign_in_waits (wrong_try_no);
        CREATE INDEX sign_in_try_clears_try_idx ON app.sign_in_try_clears (covers_through_try_no);
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.prune_sign_in_wrong_tries(p_after bytea, p_limit integer)
        RETURNS TABLE(wrong_tries bigint, waits bigint, clears bigint, last_username_digest bytea)
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_cutoff timestamptz := pg_catalog.statement_timestamp() - interval '30 days';
            v_usernames bytea[];
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 1000
               OR (p_after IS NOT NULL AND pg_catalog.length(p_after) <> 32) THEN
                RAISE EXCEPTION 'prune bounds are invalid'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF pg_catalog.current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'sign-in tries are removed only at READ COMMITTED'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            -- An ended wait changes nothing (a wait lasts at most 15 minutes); removed first,
            -- before any username lock is held. Its guard needs the flag.
            PERFORM pg_catalog.set_config('prm.sign_in_prune', 'on', true);
            DELETE FROM app.sign_in_waits AS wait WHERE wait.ends_at < v_cutoff;
            GET DIAGNOSTICS waits = ROW_COUNT;
            -- The next usernames (in digest order) with an old try or an old clear, each under
            -- the username lock the sign-in functions take, so a correct sign-in never clears
            -- through a try that is being removed. Only username locks: no cycle with the
            -- functions, which take one username lock and then a source lock.
            SELECT pg_catalog.array_agg(digest ORDER BY digest)
            INTO v_usernames
            FROM (
                SELECT old.digest FROM (
                    SELECT wrong.username_digest AS digest FROM app.sign_in_wrong_tries AS wrong
                    WHERE wrong.tried_at < v_cutoff
                    UNION
                    SELECT clear.username_digest FROM app.sign_in_try_clears AS clear
                    WHERE clear.cleared_at < v_cutoff
                ) AS old
                WHERE p_after IS NULL OR old.digest > p_after
                ORDER BY old.digest
                LIMIT p_limit
            ) AS batch;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'sign-in-username:' || pg_catalog.encode(locked.digest, 'hex'), 0
                )
            )
            FROM pg_catalog.unnest(COALESCE(v_usernames, '{}'::bytea[])) AS locked(digest)
            ORDER BY locked.digest;
            -- An old clear goes unless it is its username's latest clear and a try it covers
            -- stays (not old, or named by a wait that has not been removed): the count of a
            -- username is its tries after its latest clear, so removing a clear never brings a
            -- try back.
            DELETE FROM app.sign_in_try_clears AS clear
            WHERE clear.username_digest = ANY(COALESCE(v_usernames, '{}'::bytea[]))
              AND clear.cleared_at < v_cutoff
              AND (EXISTS (SELECT 1 FROM app.sign_in_try_clears AS newer
                      WHERE newer.username_digest = clear.username_digest
                        AND newer.covers_through_try_no > clear.covers_through_try_no)
                   OR NOT EXISTS (SELECT 1 FROM app.sign_in_wrong_tries AS covered
                      WHERE covered.username_digest = clear.username_digest
                        AND covered.try_no <= clear.covers_through_try_no
                        AND (covered.tried_at >= v_cutoff
                             OR EXISTS (SELECT 1 FROM app.sign_in_waits AS wait
                                 WHERE wait.wrong_try_no = covered.try_no))));
            GET DIAGNOSTICS clears = ROW_COUNT;
            DELETE FROM app.sign_in_wrong_tries AS wrong
            WHERE wrong.username_digest = ANY(COALESCE(v_usernames, '{}'::bytea[]))
              AND wrong.tried_at < v_cutoff
              AND NOT EXISTS (SELECT 1 FROM app.sign_in_waits AS wait
                  WHERE wait.wrong_try_no = wrong.try_no)
              AND NOT EXISTS (SELECT 1 FROM app.sign_in_try_clears AS clear
                  WHERE clear.covers_through_try_no = wrong.try_no);
            GET DIAGNOSTICS wrong_tries = ROW_COUNT;
            PERFORM pg_catalog.set_config('prm.sign_in_prune', 'off', true);
            last_username_digest := v_usernames[pg_catalog.array_length(v_usernames, 1)];
            RETURN NEXT;
        END;
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {PRUNE} FROM PUBLIC")


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("sign-in try prune migration is forward-only")
