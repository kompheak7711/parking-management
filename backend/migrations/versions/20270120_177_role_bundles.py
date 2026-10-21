"""Add role bundles, their assignments and the grant reader (login slice sub-slice L1b-2).

SEC-001 to SEC-003, SEC-020 to SEC-022, API-080, DB-AUTH-001, DB-AUTH-007, DL-074 answer 1,
DL-081 (owner answers (a) to Q-2026-10-21-161 and (b) to Q-2026-10-21-162): a role bundle is
configurable data of one Property and gives capabilities only from the catalog's `bundle` grant
path; every version of a bundle and its complete capability set is kept for good; an assignment
of a bundle to an account is never changed, only removed once by a new record. The definer
function `app.actor_capability_grants` returns the effective capabilities of an active, classified
account with their Property: its assigned bundles' current capabilities, and
`identity.manage_access` for the Owner account class only. New relations, functions and triggers
only; the new foreign keys take SHARE ROW EXCLUSIVE on the tables they refer to, which does not
conflict with a reader or a foreign-key check.
"""

from alembic import op

revision = "20270120_177"
down_revision = "20270119_176"
branch_labels = None
depends_on = None

APPEND_ONLY = "app.reject_role_bundle_history_change()"
TRIGGER_FUNCTIONS = (
    APPEND_ONLY,
    "app.guard_role_bundle_change()",
    "app.record_role_bundle_version()",
    "app.require_role_bundle_version_of_bundle()",
    "app.require_role_bundle_capability_version()",
    "app.require_single_active_role_assignment()",
)
READER = "app.actor_capability_grants(uuid)"


def upgrade() -> None:
    """Create the bundle and assignment relations, their guards and the grant reader."""
    op.execute(
        """
        CREATE TABLE app.role_bundles (
            role_bundle_id uuid PRIMARY KEY,
            property_id uuid NOT NULL
                REFERENCES app.properties (id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            -- Review rounds 1 and 3: no control or invisible format characters, so one bundle
            -- name cannot look like another on screen; the ranges are listed, not taken from
            -- the locale.
            name text NOT NULL
                CHECK (
                    name = btrim(name)
                    AND length(name) BETWEEN 1 AND 128
                    AND name !~ '[[:cntrl:]\\u0001-\\u001f\\u007f-\\u009f\\u00ad'
                                '\\u061c\\u180e\\u200b-\\u200f\\u202a-\\u202e'
                                '\\u2060-\\u206f\\ufeff\\ufff9-\\ufffb'
                                '\\U000e0000-\\U000e007f]'
                ),
            version integer NOT NULL CHECK (version >= 1),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(created_at)),
            provenance text NOT NULL
                CHECK (length(btrim(provenance)) > 0 AND length(provenance) <= 500),
            CONSTRAINT role_bundles_bundle_property_key UNIQUE (role_bundle_id, property_id)
        )
        """
    )
    # Review round 1: a name is unique per Property whatever its capital letters.
    op.execute(
        """
        CREATE UNIQUE INDEX role_bundles_property_lower_name_key
        ON app.role_bundles (property_id, lower(name))
        """
    )
    op.execute(
        """
        CREATE TABLE app.role_bundle_versions (
            role_bundle_id uuid NOT NULL
                REFERENCES app.role_bundles (role_bundle_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            version integer NOT NULL CHECK (version >= 1),
            name text NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(recorded_at)),
            recorded_transaction xid8 NOT NULL DEFAULT pg_catalog.pg_current_xact_id(),
            -- Review round 1: with the transaction id, so a logical restore, whose new cluster
            -- may reuse an old transaction id, still cannot add to a recorded version.
            recorded_transaction_started_at timestamptz NOT NULL
                DEFAULT pg_catalog.transaction_timestamp(),
            PRIMARY KEY (role_bundle_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.role_bundle_capabilities (
            role_bundle_id uuid NOT NULL,
            version integer NOT NULL,
            capability_id text NOT NULL,
            grant_path text NOT NULL DEFAULT 'bundle' CHECK (grant_path = 'bundle'),
            PRIMARY KEY (role_bundle_id, version, capability_id),
            CONSTRAINT role_bundle_capabilities_version_fkey
                FOREIGN KEY (role_bundle_id, version)
                REFERENCES app.role_bundle_versions (role_bundle_id, version)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            CONSTRAINT role_bundle_capabilities_catalog_fkey
                FOREIGN KEY (capability_id, grant_path)
                REFERENCES app.capabilities (capability_id, grant_path)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.user_role_assignments (
            assignment_id uuid PRIMARY KEY,
            actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            role_bundle_id uuid NOT NULL,
            property_id uuid NOT NULL,
            assigned_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(assigned_at)),
            assigned_by_actor_id uuid
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            provenance text NOT NULL
                CHECK (length(btrim(provenance)) > 0 AND length(provenance) <= 500),
            CONSTRAINT user_role_assignments_bundle_fkey
                FOREIGN KEY (role_bundle_id, property_id)
                REFERENCES app.role_bundles (role_bundle_id, property_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE INDEX user_role_assignments_actor_idx
        ON app.user_role_assignments (actor_id, role_bundle_id)
        """
    )
    op.execute(
        """
        CREATE TABLE app.user_role_assignment_removals (
            assignment_id uuid PRIMARY KEY
                REFERENCES app.user_role_assignments (assignment_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            removed_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(removed_at)),
            removed_by_actor_id uuid
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
        CREATE FUNCTION app.reject_role_bundle_history_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'role bundle history is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    for table in (
        "role_bundle_versions",
        "role_bundle_capabilities",
        "user_role_assignments",
        "user_role_assignment_removals",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table}_are_append_only
            BEFORE UPDATE OR DELETE ON app.{table}
            FOR EACH ROW
            EXECUTE FUNCTION {APPEND_ONLY}
            """
        )
    for table in (
        "role_bundles",
        "role_bundle_versions",
        "role_bundle_capabilities",
        "user_role_assignments",
        "user_role_assignment_removals",
    ):
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
        CREATE TRIGGER role_bundles_are_never_deleted
        BEFORE DELETE ON app.role_bundles
        FOR EACH ROW
        EXECUTE FUNCTION {APPEND_ONLY}
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.guard_role_bundle_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.version <> 1 THEN
                    RAISE EXCEPTION 'a role bundle changes only its name and its next version'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            ELSIF NEW.role_bundle_id IS DISTINCT FROM OLD.role_bundle_id
               OR NEW.property_id IS DISTINCT FROM OLD.property_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.provenance IS DISTINCT FROM OLD.provenance
               OR NEW.version IS DISTINCT FROM OLD.version + 1 THEN
                RAISE EXCEPTION 'a role bundle changes only its name and its next version'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER role_bundles_change_by_version
        BEFORE INSERT OR UPDATE ON app.role_bundles
        FOR EACH ROW
        EXECUTE FUNCTION app.guard_role_bundle_change()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.record_role_bundle_version()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            INSERT INTO app.role_bundle_versions (role_bundle_id, version, name)
            VALUES (NEW.role_bundle_id, NEW.version, NEW.name);
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER role_bundles_record_version
        AFTER INSERT OR UPDATE ON app.role_bundles
        FOR EACH ROW
        EXECUTE FUNCTION app.record_role_bundle_version()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.require_role_bundle_version_of_bundle()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NOT EXISTS (
                   SELECT 1
                   FROM app.role_bundles AS bundle
                   WHERE bundle.role_bundle_id = NEW.role_bundle_id
                     AND bundle.version = NEW.version
                     AND bundle.name = NEW.name
               )
               OR NEW.recorded_transaction IS DISTINCT FROM pg_catalog.pg_current_xact_id()
               OR NEW.recorded_transaction_started_at
                  IS DISTINCT FROM pg_catalog.transaction_timestamp() THEN
                RAISE EXCEPTION 'a role bundle version is written only with its bundle'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER role_bundle_versions_follow_their_bundle
        BEFORE INSERT ON app.role_bundle_versions
        FOR EACH ROW
        EXECUTE FUNCTION app.require_role_bundle_version_of_bundle()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.require_role_bundle_capability_version()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            -- The transaction that wrote the version holds the bundle row's lock until it ends,
            -- so the bundle's version cannot move on while its capabilities are written.
            IF NOT EXISTS (
                   SELECT 1
                   FROM app.role_bundles AS bundle
                   JOIN app.role_bundle_versions AS recorded
                     ON recorded.role_bundle_id = bundle.role_bundle_id
                    AND recorded.version = bundle.version
                   WHERE bundle.role_bundle_id = NEW.role_bundle_id
                     AND bundle.version = NEW.version
                     AND recorded.recorded_transaction = pg_catalog.pg_current_xact_id()
                     AND recorded.recorded_transaction_started_at
                         = pg_catalog.transaction_timestamp()
               ) THEN
                RAISE EXCEPTION 'role bundle capabilities are written only with their version'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER role_bundle_capabilities_follow_their_version
        BEFORE INSERT ON app.role_bundle_capabilities
        FOR EACH ROW
        EXECUTE FUNCTION app.require_role_bundle_capability_version()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.require_single_active_role_assignment()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            -- Under REPEATABLE READ or SERIALIZABLE the check below could read a snapshot older
            -- than an assignment committed while this one waited for the lock (fail closed, as
            -- in login sub-slice L1a).
            IF pg_catalog.current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'a role bundle is assigned only at READ COMMITTED'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'role-assignment:' || NEW.actor_id::text || ':'
                        || NEW.role_bundle_id::text,
                    0
                )
            );
            IF EXISTS (
                   SELECT 1
                   FROM app.user_role_assignments AS assignment
                   WHERE assignment.actor_id = NEW.actor_id
                     AND assignment.role_bundle_id = NEW.role_bundle_id
                     AND NOT EXISTS (
                         SELECT 1
                         FROM app.user_role_assignment_removals AS removal
                         WHERE removal.assignment_id = assignment.assignment_id
                     )
               ) THEN
                RAISE EXCEPTION 'a role bundle is already assigned to this account'
                    USING ERRCODE = 'unique_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER user_role_assignments_single_active
        BEFORE INSERT ON app.user_role_assignments
        FOR EACH ROW
        EXECUTE FUNCTION app.require_single_active_role_assignment()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.actor_capability_grants(p_actor_id uuid)
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
        $$
        """
    )
    for function in (*TRIGGER_FUNCTIONS, READER):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for table in (
        "role_bundles",
        "role_bundle_versions",
        "role_bundle_capabilities",
        "user_role_assignments",
        "user_role_assignment_removals",
    ):
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {READER} TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("role bundle migration is forward-only")
