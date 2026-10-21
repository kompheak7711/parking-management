"""Add per-user Settings access (login slice sub-slice L1d).

DL-074 answer 2, DL-075, DL-081 (owner answer (a) to Q-2026-10-21-151), SEC-014, SEC-021,
SEC-075, DB-AUTH-008: `settings.manage` is given to one Manager or Staff account at a time, only
by the Owner account class, and never through a bundle; the Owner always has it. Each grant and
its removal is an append-only record with who, when and why. The grant reader
`app.actor_capability_grants` is replaced so it also returns `settings.manage` to the Owner
account class and to an account with an active grant. New relations, functions and triggers,
and the reader replaced with the same signature, attributes and privileges.
"""

from alembic import op

revision = "20270121_178"
down_revision = "20270120_177"
branch_labels = None
depends_on = None

APPEND_ONLY = "app.reject_settings_access_history_change()"
SINGLE_ACTIVE = "app.require_single_active_capability_grant()"
GIVE = "app.give_settings_access(uuid,uuid,text)"
REMOVE = "app.remove_settings_access(uuid,uuid,text)"
READER = "app.actor_capability_grants(uuid)"


def upgrade() -> None:
    """Create the grant relations, their guards, the two definer functions and the reader."""
    op.execute(
        """
        CREATE TABLE app.user_capability_grants (
            grant_id uuid PRIMARY KEY,
            actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            capability_id text NOT NULL CHECK (capability_id = 'settings.manage'),
            grant_path text NOT NULL DEFAULT 'per_user' CHECK (grant_path = 'per_user'),
            given_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(given_at)),
            given_by_actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            reason text NOT NULL CHECK (length(btrim(reason)) > 0 AND length(reason) <= 500),
            provenance text NOT NULL
                CHECK (length(btrim(provenance)) > 0 AND length(provenance) <= 500),
            CONSTRAINT user_capability_grants_catalog_fkey
                FOREIGN KEY (capability_id, grant_path)
                REFERENCES app.capabilities (capability_id, grant_path)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE INDEX user_capability_grants_actor_idx
        ON app.user_capability_grants (actor_id, capability_id)
        """
    )
    op.execute(
        """
        CREATE TABLE app.user_capability_grant_removals (
            grant_id uuid PRIMARY KEY
                REFERENCES app.user_capability_grants (grant_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            removed_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(removed_at)),
            removed_by_actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            reason text NOT NULL CHECK (length(btrim(reason)) > 0 AND length(reason) <= 500),
            provenance text NOT NULL
                CHECK (length(btrim(provenance)) > 0 AND length(provenance) <= 500)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_settings_access_history_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'settings access history is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    for table in ("user_capability_grants", "user_capability_grant_removals"):
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
        """
        CREATE FUNCTION app.require_single_active_capability_grant()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            -- Under REPEATABLE READ or SERIALIZABLE the check below could read a snapshot older
            -- than a grant committed while this one waited for the lock (fail closed, as in
            -- login sub-slices L1a and L1b-2).
            IF pg_catalog.current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'Settings access is given only at READ COMMITTED'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('capability-grant:' || NEW.actor_id::text, 0)
            );
            IF EXISTS (
                   SELECT 1
                   FROM app.user_capability_grants AS given
                   WHERE given.actor_id = NEW.actor_id
                     AND given.capability_id = NEW.capability_id
                     AND NOT EXISTS (
                         SELECT 1
                         FROM app.user_capability_grant_removals AS removal
                         WHERE removal.grant_id = given.grant_id
                     )
               ) THEN
                RAISE EXCEPTION 'this account already has Settings access'
                    USING ERRCODE = 'unique_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER user_capability_grants_single_active
        BEFORE INSERT ON app.user_capability_grants
        FOR EACH ROW
        EXECUTE FUNCTION {SINGLE_ACTIVE}
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.give_settings_access(
            p_owner_id uuid,
            p_actor_id uuid,
            p_reason text
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_grant_id uuid := pg_catalog.gen_random_uuid();
        BEGIN
            PERFORM app.assert_settings_access_owner(p_owner_id);
            IF NOT EXISTS (
                   SELECT 1
                   FROM app.user_accounts AS account
                   JOIN app.user_account_classes AS classification
                     ON classification.actor_id = account.actor_id
                   WHERE account.actor_id = p_actor_id
                     AND account.lifecycle_state = 'active'
                     AND classification.account_class IN ('manager', 'staff')
               ) THEN
                RAISE EXCEPTION 'Settings access is given only to a Manager or Staff account'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            INSERT INTO app.user_capability_grants (
                grant_id, actor_id, capability_id, given_by_actor_id, reason, provenance
            ) VALUES (
                v_grant_id, p_actor_id, 'settings.manage', p_owner_id, p_reason,
                'owner-settings-access'
            );
            RETURN v_grant_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.remove_settings_access(
            p_owner_id uuid,
            p_actor_id uuid,
            p_reason text
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_grant_id uuid;
        BEGIN
            -- Review round 1: only the acting Owner is checked, so the Owner can also remove
            -- the Settings access of a disabled account (which then cannot come back with the
            -- account); an account with no active grant is refused below.
            PERFORM app.assert_settings_access_owner(p_owner_id);
            -- The same lock as a new grant, so a removal and a grant of one account wait for
            -- each other; READ COMMITTED as for a grant.
            IF pg_catalog.current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'Settings access is removed only at READ COMMITTED'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('capability-grant:' || p_actor_id::text, 0)
            );
            SELECT given.grant_id
            INTO v_grant_id
            FROM app.user_capability_grants AS given
            WHERE given.actor_id = p_actor_id
              AND given.capability_id = 'settings.manage'
              AND NOT EXISTS (
                  SELECT 1
                  FROM app.user_capability_grant_removals AS removal
                  WHERE removal.grant_id = given.grant_id
              );
            IF v_grant_id IS NULL THEN
                RAISE EXCEPTION 'this account has no Settings access'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            INSERT INTO app.user_capability_grant_removals (
                grant_id, removed_by_actor_id, reason, provenance
            ) VALUES (
                v_grant_id, p_owner_id, p_reason, 'owner-settings-access'
            );
            RETURN v_grant_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.assert_settings_access_owner(p_owner_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NOT EXISTS (
                   SELECT 1
                   FROM app.user_accounts AS account
                   JOIN app.user_account_classes AS classification
                     ON classification.actor_id = account.actor_id
                   WHERE account.actor_id = p_owner_id
                     AND account.lifecycle_state = 'active'
                     AND classification.account_class = 'owner'
               ) THEN
                RAISE EXCEPTION 'only the Owner gives or removes Settings access'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.actor_capability_grants(p_actor_id uuid)
        RETURNS TABLE (capability_id text, property_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
            WITH account AS (
                SELECT classification.account_class
                FROM app.user_accounts AS account
                JOIN app.user_account_classes AS classification
                  ON classification.actor_id = account.actor_id
                WHERE account.actor_id = p_actor_id
                  AND account.lifecycle_state = 'active'
            )
            SELECT bundle_capability.capability_id, bundle.property_id
            FROM account
            CROSS JOIN app.user_role_assignments AS assignment
            JOIN app.role_bundles AS bundle
              ON bundle.role_bundle_id = assignment.role_bundle_id
             AND bundle.property_id = assignment.property_id
            JOIN app.role_bundle_capabilities AS bundle_capability
              ON bundle_capability.role_bundle_id = bundle.role_bundle_id
             AND bundle_capability.version = bundle.version
            JOIN app.capabilities AS catalog
              ON catalog.capability_id = bundle_capability.capability_id
             AND catalog.grant_path = 'bundle'
            WHERE assignment.actor_id = p_actor_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM app.user_role_assignment_removals AS removal
                  WHERE removal.assignment_id = assignment.assignment_id
              )
            UNION
            SELECT catalog.capability_id, property.id
            FROM account
            CROSS JOIN app.properties AS property
            JOIN app.capabilities AS catalog
              ON catalog.capability_id = 'identity.manage_access'
             AND catalog.grant_path = 'owner_class'
            WHERE account.account_class = 'owner'
            UNION
            SELECT catalog.capability_id, property.id
            FROM account
            CROSS JOIN app.properties AS property
            JOIN app.capabilities AS catalog
              ON catalog.capability_id = 'settings.manage'
             AND catalog.grant_path = 'per_user'
            WHERE account.account_class = 'owner'
               OR EXISTS (
                   SELECT 1
                   FROM app.user_capability_grants AS given
                   WHERE given.actor_id = p_actor_id
                     AND given.capability_id = catalog.capability_id
                     AND NOT EXISTS (
                         SELECT 1
                         FROM app.user_capability_grant_removals AS removal
                         WHERE removal.grant_id = given.grant_id
                     )
               )
        $$
        """
    )
    for function in (
        APPEND_ONLY,
        SINGLE_ACTIVE,
        GIVE,
        REMOVE,
        "app.assert_settings_access_owner(uuid)",
        READER,
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for table in ("user_capability_grants", "user_capability_grant_removals"):
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC")
    for function in (GIVE, REMOVE, READER):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("settings access migration is forward-only")
