"""Account and role bundle administration in the database (login slice sub-slice L2a).

API-079, API-080, DL-057, DL-074 answers 1 and 2, DL-081 (Q-2026-10-21-152 (a), Q-156 (a),
Q-165 (a) and the owner rule that Settings access needs the sign-in code), SEC-014, SEC-017,
SEC-021, SEC-075, DB-AUTH-010: only the active Owner account class administers accounts, role
bundles, assignments and Settings access, through definer functions that the runtime role may
execute. Each function runs at READ COMMITTED only; each write function writes one immutable
audit event in the same transaction. Disabling an account, a role bundle that loses a capability,
a removed assignment and a Staff account whose MFA policy is raised revoke the applicable
sessions in the same step; a Staff account whose MFA is turned off loses its sign-in code, its
sessions and its Settings access in the same step, the last as a recorded removal. An
account's version is 1 plus its number of recorded changes.
Nothing existing is altered.
"""

from alembic import op

revision = "20270124_181"
down_revision = "20270123_180"
branch_labels = None
depends_on = None

DEFINERS = (
    "app.admin_create_account(uuid,text,text,text,text,uuid)",
    "app.admin_update_account(uuid,uuid,integer,text,text,boolean,text,uuid)",
    "app.admin_revoke_account_sessions(uuid,uuid,uuid)",
    "app.admin_create_role_bundle(uuid,uuid,text,text[],uuid)",
    "app.admin_update_role_bundle(uuid,uuid,integer,text,text[],uuid)",
    "app.admin_assign_role_bundle(uuid,uuid,uuid,uuid)",
    "app.admin_remove_role_assignment(uuid,uuid,uuid,text,uuid)",
    "app.admin_give_settings_access(uuid,uuid,text,uuid)",
    "app.admin_remove_settings_access(uuid,uuid,text,uuid)",
    "app.admin_accounts(uuid)",
    "app.admin_role_bundles(uuid)",
)
INTERNAL = (
    "app.reject_account_change_history_change()",
    "app.assert_access_administrator(uuid)",
    "app.administered_property()",
    "app.user_account_version(uuid)",
    "app.revoke_live_sessions(uuid,uuid,text,text)",
    "app.bundle_capability_set(text[])",
    "app.assert_account_names(text[])",
    "app.record_access_administration(uuid,text,text,uuid,text,jsonb,jsonb,uuid)",
)


def upgrade() -> None:
    """Create the account change history and the administration functions."""
    op.execute(
        """
        CREATE TABLE app.user_account_changes (
            actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            version integer NOT NULL CHECK (version >= 2),
            changed_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(changed_at)),
            changed_by_actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            previous_state jsonb NOT NULL,
            resulting_state jsonb NOT NULL,
            provenance text NOT NULL
                CHECK (length(btrim(provenance)) > 0 AND length(provenance) <= 500),
            PRIMARY KEY (actor_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_account_change_history_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'account change history is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER user_account_changes_are_append_only
        BEFORE UPDATE OR DELETE ON app.user_account_changes
        FOR EACH ROW
        EXECUTE FUNCTION app.reject_account_change_history_change()
        """
    )
    op.execute(
        """
        CREATE TRIGGER user_account_changes_are_never_truncated
        BEFORE TRUNCATE ON app.user_account_changes
        FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_account_change_history_change()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.assert_access_administrator(p_owner_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog
        AS $$
        BEGIN
            -- As in sub-slices L1a to L1d: the checks below read committed rows, so an older
            -- snapshot could miss a change committed meanwhile (fail closed).
            IF pg_catalog.current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'account administration runs only at READ COMMITTED'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            IF NOT EXISTS (
                   SELECT 1
                   FROM app.user_accounts AS account
                   JOIN app.user_account_classes AS classification
                     ON classification.actor_id = account.actor_id
                   WHERE account.actor_id = p_owner_id
                     AND account.lifecycle_state = 'active'
                     AND classification.account_class = 'owner'
               ) THEN
                RAISE EXCEPTION 'only the Owner administers accounts and role bundles'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.administered_property()
        RETURNS uuid
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_property_id uuid;
        BEGIN
            SELECT property.id INTO v_property_id FROM app.properties AS property;
            IF v_property_id IS NULL THEN
                RAISE EXCEPTION 'the Property is not set up'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            RETURN v_property_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.user_account_version(p_actor_id uuid)
        RETURNS integer
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $$
            SELECT 1 + pg_catalog.count(*)::integer
            FROM app.user_account_changes AS change
            WHERE change.actor_id = p_actor_id
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.revoke_live_sessions(
            p_actor_id uuid,
            p_revoked_by uuid,
            p_reason text,
            p_provenance text
        )
        RETURNS integer
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_count integer;
        BEGIN
            UPDATE app.browser_sessions
            SET revoked_by_actor_id = p_revoked_by,
                revocation_reason = p_reason,
                revocation_provenance = p_provenance
            WHERE actor_id = p_actor_id
              AND revoked_at IS NULL
              AND idle_expires_at > pg_catalog.statement_timestamp()
              AND absolute_expires_at > pg_catalog.statement_timestamp();
            GET DIAGNOSTICS v_count = ROW_COUNT;
            RETURN v_count;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.bundle_capability_set(p_capabilities text[])
        RETURNS text[]
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_set text[];
        BEGIN
            IF p_capabilities IS NULL
               OR pg_catalog.array_position(p_capabilities, NULL) IS NOT NULL THEN
                RAISE EXCEPTION 'only bundle capabilities can be in a role bundle'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            SELECT COALESCE(pg_catalog.array_agg(DISTINCT given ORDER BY given), '{}')
            INTO v_set
            FROM pg_catalog.unnest(p_capabilities) AS given;
            IF EXISTS (
                   SELECT 1
                   FROM pg_catalog.unnest(v_set) AS given
                   WHERE NOT EXISTS (
                       SELECT 1
                       FROM app.capabilities AS catalog
                       WHERE catalog.capability_id = given
                         AND catalog.grant_path = 'bundle'
                   )
               ) THEN
                RAISE EXCEPTION 'only bundle capabilities can be in a role bundle'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            RETURN v_set;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.assert_account_names(p_names text[])
        RETURNS void
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_name text;
        BEGIN
            -- Review round 1: the bundle name rule of sub-slice L1b-2, so two accounts or an
            -- audit name cannot look like another on screen or in the audit history.
            FOREACH v_name IN ARRAY p_names LOOP
                IF v_name IS NOT NULL AND (
                       v_name <> pg_catalog.btrim(v_name)
                       OR pg_catalog.length(v_name) NOT BETWEEN 1 AND 128
                       OR v_name ~ '[[:cntrl:]\\u0001-\\u001f\\u007f-\\u009f\\u00ad'
                                   '\\u061c\\u180e\\u200b-\\u200f\\u202a-\\u202e'
                                   '\\u2060-\\u206f\\ufeff\\ufff9-\\ufffb'
                                   '\\U000e0000-\\U000e007f]'
                   ) THEN
                    RAISE EXCEPTION
                        'an account name is 1 to 128 visible characters with no space at either end'
                        USING ERRCODE = 'invalid_parameter_value';
                END IF;
            END LOOP;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.record_access_administration(
            p_owner_id uuid,
            p_action text,
            p_entity_type text,
            p_entity_id uuid,
            p_reason text,
            p_previous_state jsonb,
            p_resulting_state jsonb,
            p_correlation_id uuid
        )
        RETURNS void
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_at timestamptz := pg_catalog.statement_timestamp();
            v_property_id uuid;
            v_timezone text;
        BEGIN
            IF p_correlation_id IS NULL THEN
                RAISE EXCEPTION 'an administration action needs a correlation id'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            SELECT property.id, property.timezone_name
            INTO v_property_id, v_timezone
            FROM app.properties AS property;
            IF v_property_id IS NULL THEN
                RAISE EXCEPTION 'the Property is not set up'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type, entity_id,
                reason, authorization_reference, property_id, previous_state, resulting_state,
                correlation_id, source, outcome
            ) VALUES (
                pg_catalog.gen_random_uuid(), v_at, pg_catalog.timezone(v_timezone, v_at)::date,
                p_owner_id, p_action, p_entity_type, p_entity_id, p_reason,
                'identity.manage_access', v_property_id, p_previous_state, p_resulting_state,
                p_correlation_id, 'API', 'SUCCEEDED'
            );
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.admin_create_account(
            p_owner_id uuid,
            p_username text,
            p_display_name text,
            p_audit_name text,
            p_account_class text,
            p_correlation_id uuid
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_actor_id uuid := pg_catalog.gen_random_uuid();
            v_property_id uuid;
            v_bundle_id uuid;
            v_mfa_policy text;
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            -- Q-2026-10-21-152 (a): exactly one Owner; the Owner creates Manager or Staff
            -- accounts only, and the class sets the MFA policy and the default bundle.
            IF p_account_class IS NULL OR p_account_class NOT IN ('manager', 'staff') THEN
                RAISE EXCEPTION 'the Owner creates Manager or Staff accounts only'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            PERFORM app.assert_account_names(
                ARRAY[pg_catalog.lower(pg_catalog.btrim(p_username)), p_display_name, p_audit_name]
            );
            v_property_id := app.administered_property();
            SELECT CASE p_account_class
                       WHEN 'manager' THEN defaults.manager_bundle_id
                       ELSE defaults.staff_bundle_id
                   END
            INTO v_bundle_id
            FROM app.default_role_bundles AS defaults
            WHERE defaults.property_id = v_property_id;
            IF v_bundle_id IS NULL THEN
                RAISE EXCEPTION 'the Property has no default role bundles'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            v_mfa_policy := CASE p_account_class WHEN 'manager' THEN 'required' ELSE 'optional' END;
            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name, lifecycle_state,
                mfa_policy_class, created_by_actor_id, provenance
            ) VALUES (
                v_actor_id, pg_catalog.lower(pg_catalog.btrim(p_username)), p_display_name,
                p_audit_name, 'active', v_mfa_policy, p_owner_id, 'owner-account-create'
            );
            INSERT INTO app.user_account_classes (actor_id, account_class, provenance)
            VALUES (v_actor_id, p_account_class, 'owner-account-create');
            INSERT INTO app.user_role_assignments (
                assignment_id, actor_id, role_bundle_id, property_id, assigned_by_actor_id,
                provenance
            ) VALUES (
                pg_catalog.gen_random_uuid(), v_actor_id, v_bundle_id, v_property_id,
                p_owner_id, 'owner-account-create'
            );
            PERFORM app.record_access_administration(
                p_owner_id, 'identity.account.created', 'user_account', v_actor_id,
                'Owner created the account', NULL,
                pg_catalog.jsonb_build_object(
                    'username', pg_catalog.lower(pg_catalog.btrim(p_username)),
                    'display_name', p_display_name,
                    'audit_name', p_audit_name,
                    'account_class', p_account_class,
                    'lifecycle_state', 'active',
                    'mfa_policy_class', v_mfa_policy,
                    'default_role_bundle_id', v_bundle_id,
                    'version', 1
                ),
                p_correlation_id
            );
            RETURN v_actor_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.admin_update_account(
            p_owner_id uuid,
            p_actor_id uuid,
            p_expected_version integer,
            p_display_name text,
            p_audit_name text,
            p_disable boolean,
            p_mfa_policy text,
            p_correlation_id uuid
        )
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_account app.user_accounts%ROWTYPE;
            v_class text;
            v_version integer;
            v_disable boolean := COALESCE(p_disable, false);
            v_previous jsonb;
            v_resulting jsonb;
            v_revoked integer := 0;
            v_settings_removed uuid;
            v_mfa_disabled boolean := false;
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            SELECT account.* INTO v_account
            FROM app.user_accounts AS account
            WHERE account.actor_id = p_actor_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the account does not exist' USING ERRCODE = 'no_data_found';
            END IF;
            SELECT classification.account_class INTO v_class
            FROM app.user_account_classes AS classification
            WHERE classification.actor_id = p_actor_id;
            IF v_class = 'owner' THEN
                RAISE EXCEPTION 'the Owner account is not changed by account administration'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF NOT v_disable AND p_display_name IS NULL AND p_audit_name IS NULL
               AND p_mfa_policy IS NULL THEN
                RAISE EXCEPTION 'at least one account change is required'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            -- Q-2026-10-21-152 (a): an old account without a class is never classified; the
            -- Owner only disables it and creates a new account.
            IF v_class IS NULL AND (
                   NOT v_disable OR p_display_name IS NOT NULL OR p_audit_name IS NOT NULL
                   OR p_mfa_policy IS NOT NULL
               ) THEN
                RAISE EXCEPTION 'an account without a class can only be disabled'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF p_mfa_policy IS NOT NULL AND p_mfa_policy NOT IN ('required', 'optional') THEN
                RAISE EXCEPTION 'an MFA policy is required or optional'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            PERFORM app.assert_account_names(ARRAY[p_display_name, p_audit_name]);
            IF v_account.lifecycle_state <> 'active' THEN
                RAISE EXCEPTION 'a disabled account is not changed'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            v_version := app.user_account_version(p_actor_id);
            IF p_expected_version IS DISTINCT FROM v_version THEN
                RAISE EXCEPTION 'the account changed since it was read'
                    USING ERRCODE = 'serialization_failure';
            END IF;
            v_previous := pg_catalog.jsonb_build_object(
                'display_name', v_account.display_name,
                'audit_name', v_account.audit_name,
                'lifecycle_state', v_account.lifecycle_state,
                'mfa_policy_class', v_account.mfa_policy_class,
                'version', v_version
            );
            UPDATE app.user_accounts
            SET display_name = COALESCE(p_display_name, display_name),
                audit_name = COALESCE(p_audit_name, audit_name),
                lifecycle_state = CASE WHEN v_disable THEN 'disabled' ELSE lifecycle_state END,
                mfa_policy_class = COALESCE(p_mfa_policy, mfa_policy_class)
            WHERE actor_id = p_actor_id;
            IF v_disable THEN
                v_revoked := app.revoke_live_sessions(
                    p_actor_id, p_owner_id, 'account_disabled', 'access-admin-account-disabled'
                );
            ELSIF v_class = 'staff' AND p_mfa_policy = 'required'
                  AND v_account.mfa_policy_class = 'optional' THEN
                -- Sub-slice L1e: the grant reader checks the account, not the session, so a
                -- Staff session started without the sign-in code ends when MFA is required.
                v_revoked := app.revoke_live_sessions(
                    p_actor_id, p_owner_id, 'material_privilege_reduction',
                    'access-admin-mfa-required'
                );
            END IF;
            IF v_class = 'staff' AND p_mfa_policy = 'optional' THEN
                -- Q-2026-10-21-156 (a): MFA off is a reset with "also reset MFA", so the sign-in
                -- code ends and a new one is set up if MFA is required again (review round 1).
                UPDATE app.totp_mfa_enrollments
                SET enrollment_state = 'disabled',
                    disabled_by_actor_id = p_owner_id,
                    disablement_provenance = 'access-admin-mfa-off'
                WHERE actor_id = p_actor_id
                  AND enrollment_state IN ('pending', 'active');
                v_mfa_disabled := FOUND;
                IF v_mfa_disabled AND NOT v_disable THEN
                    v_revoked := app.revoke_live_sessions(
                        p_actor_id, p_owner_id, 'mfa_reset', 'access-admin-mfa-off'
                    );
                END IF;
                -- Q-2026-10-21-165 (a): MFA off removes the account's Settings access in the
                -- same step, as a recorded removal; the Owner gives it again after the new code.
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
                    v_settings_removed := app.remove_settings_access(
                        p_owner_id, p_actor_id, 'sign-in code turned off'
                    );
                END IF;
            END IF;
            SELECT pg_catalog.jsonb_build_object(
                       'display_name', account.display_name,
                       'audit_name', account.audit_name,
                       'lifecycle_state', account.lifecycle_state,
                       'mfa_policy_class', account.mfa_policy_class,
                       'version', v_version + 1
                   )
            INTO v_resulting
            FROM app.user_accounts AS account
            WHERE account.actor_id = p_actor_id;
            INSERT INTO app.user_account_changes (
                actor_id, version, changed_by_actor_id, previous_state, resulting_state,
                provenance
            ) VALUES (
                p_actor_id, v_version + 1, p_owner_id, v_previous, v_resulting,
                'owner-account-update'
            );
            PERFORM app.record_access_administration(
                p_owner_id,
                CASE WHEN v_disable THEN 'identity.account.disabled'
                     ELSE 'identity.account.updated' END,
                'user_account', p_actor_id, 'Owner changed the account', v_previous,
                v_resulting || pg_catalog.jsonb_build_object(
                    'sessions_revoked', v_revoked,
                    'mfa_disabled', v_mfa_disabled,
                    'settings_access_removed', v_settings_removed IS NOT NULL,
                    'settings_access_removed_grant_id', v_settings_removed
                ),
                p_correlation_id
            );
            RETURN v_version + 1;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.admin_revoke_account_sessions(
            p_owner_id uuid,
            p_actor_id uuid,
            p_correlation_id uuid
        )
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_class text;
            v_revoked integer;
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            IF NOT EXISTS (
                   SELECT 1 FROM app.user_accounts AS account
                   WHERE account.actor_id = p_actor_id
               ) THEN
                RAISE EXCEPTION 'the account does not exist' USING ERRCODE = 'no_data_found';
            END IF;
            SELECT classification.account_class INTO v_class
            FROM app.user_account_classes AS classification
            WHERE classification.actor_id = p_actor_id;
            IF v_class IS NULL OR v_class NOT IN ('manager', 'staff') THEN
                RAISE EXCEPTION 'sessions are revoked here only for a Manager or Staff account'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            v_revoked := app.revoke_live_sessions(
                p_actor_id, p_owner_id, 'material_privilege_reduction',
                'access-admin-revoke-sessions'
            );
            PERFORM app.record_access_administration(
                p_owner_id, 'identity.account.sessions_revoked', 'user_account', p_actor_id,
                'Owner revoked the sessions', NULL,
                pg_catalog.jsonb_build_object('sessions_revoked', v_revoked),
                p_correlation_id
            );
            RETURN v_revoked;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.admin_create_role_bundle(
            p_owner_id uuid,
            p_property_id uuid,
            p_name text,
            p_capabilities text[],
            p_correlation_id uuid
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_bundle_id uuid := pg_catalog.gen_random_uuid();
            v_set text[];
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            IF p_property_id IS DISTINCT FROM app.administered_property() THEN
                RAISE EXCEPTION 'the Property does not exist' USING ERRCODE = 'no_data_found';
            END IF;
            v_set := app.bundle_capability_set(p_capabilities);
            INSERT INTO app.role_bundles (role_bundle_id, property_id, name, version, provenance)
            VALUES (v_bundle_id, p_property_id, p_name, 1, 'owner-role-bundle-create');
            INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
            SELECT v_bundle_id, 1, given FROM pg_catalog.unnest(v_set) AS given;
            PERFORM app.record_access_administration(
                p_owner_id, 'identity.role_bundle.created', 'role_bundle', v_bundle_id,
                'Owner created the role bundle', NULL,
                pg_catalog.jsonb_build_object(
                    'name', p_name, 'version', 1,
                    'capability_ids', pg_catalog.to_jsonb(v_set)
                ),
                p_correlation_id
            );
            RETURN v_bundle_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.admin_update_role_bundle(
            p_owner_id uuid,
            p_role_bundle_id uuid,
            p_expected_version integer,
            p_name text,
            p_capabilities text[],
            p_correlation_id uuid
        )
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_bundle app.role_bundles%ROWTYPE;
            v_old text[];
            v_new text[];
            v_holder uuid;
            v_revoked integer := 0;
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            SELECT bundle.* INTO v_bundle
            FROM app.role_bundles AS bundle
            WHERE bundle.role_bundle_id = p_role_bundle_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the role bundle does not exist' USING ERRCODE = 'no_data_found';
            END IF;
            IF p_name IS NULL AND p_capabilities IS NULL THEN
                RAISE EXCEPTION 'at least one role bundle change is required'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF p_expected_version IS DISTINCT FROM v_bundle.version THEN
                RAISE EXCEPTION 'the role bundle changed since it was read'
                    USING ERRCODE = 'serialization_failure';
            END IF;
            SELECT COALESCE(
                       pg_catalog.array_agg(held.capability_id ORDER BY held.capability_id),
                       '{}'
                   )
            INTO v_old
            FROM app.role_bundle_capabilities AS held
            WHERE held.role_bundle_id = p_role_bundle_id
              AND held.version = v_bundle.version;
            v_new := CASE WHEN p_capabilities IS NULL THEN v_old
                          ELSE app.bundle_capability_set(p_capabilities) END;
            UPDATE app.role_bundles
            SET name = COALESCE(p_name, name),
                version = version + 1
            WHERE role_bundle_id = p_role_bundle_id;
            INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
            SELECT p_role_bundle_id, v_bundle.version + 1, given
            FROM pg_catalog.unnest(v_new) AS given;
            -- DL-057, SEC-017: a material privilege reduction revokes the applicable sessions.
            IF EXISTS (
                   SELECT 1 FROM pg_catalog.unnest(v_old) AS given
                   WHERE NOT given = ANY (v_new)
               ) THEN
                FOR v_holder IN
                    SELECT DISTINCT assignment.actor_id
                    FROM app.user_role_assignments AS assignment
                    WHERE assignment.role_bundle_id = p_role_bundle_id
                      AND NOT EXISTS (
                          SELECT 1
                          FROM app.user_role_assignment_removals AS removal
                          WHERE removal.assignment_id = assignment.assignment_id
                      )
                    ORDER BY assignment.actor_id
                LOOP
                    v_revoked := v_revoked + app.revoke_live_sessions(
                        v_holder, p_owner_id, 'material_privilege_reduction',
                        'access-admin-role-bundle-reduced'
                    );
                END LOOP;
            END IF;
            PERFORM app.record_access_administration(
                p_owner_id, 'identity.role_bundle.updated', 'role_bundle', p_role_bundle_id,
                'Owner changed the role bundle',
                pg_catalog.jsonb_build_object(
                    'name', v_bundle.name, 'version', v_bundle.version,
                    'capability_ids', pg_catalog.to_jsonb(v_old)
                ),
                pg_catalog.jsonb_build_object(
                    'name', COALESCE(p_name, v_bundle.name), 'version', v_bundle.version + 1,
                    'capability_ids', pg_catalog.to_jsonb(v_new),
                    'sessions_revoked', v_revoked
                ),
                p_correlation_id
            );
            RETURN v_bundle.version + 1;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.admin_assign_role_bundle(
            p_owner_id uuid,
            p_actor_id uuid,
            p_role_bundle_id uuid,
            p_correlation_id uuid
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_assignment_id uuid := pg_catalog.gen_random_uuid();
            v_property_id uuid;
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            IF NOT EXISTS (
                   SELECT 1 FROM app.user_accounts AS account
                   WHERE account.actor_id = p_actor_id
               ) THEN
                RAISE EXCEPTION 'the account does not exist' USING ERRCODE = 'no_data_found';
            END IF;
            SELECT bundle.property_id INTO v_property_id
            FROM app.role_bundles AS bundle
            WHERE bundle.role_bundle_id = p_role_bundle_id;
            IF v_property_id IS NULL THEN
                RAISE EXCEPTION 'the role bundle does not exist' USING ERRCODE = 'no_data_found';
            END IF;
            -- The Owner may assign a bundle to itself too (sub-slice L1c, note 2).
            PERFORM 1
            FROM app.user_accounts AS account
            JOIN app.user_account_classes AS classification
              ON classification.actor_id = account.actor_id
            WHERE account.actor_id = p_actor_id
              AND account.lifecycle_state = 'active'
            FOR SHARE OF account;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'a role bundle is assigned only to an active account with a class'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            INSERT INTO app.user_role_assignments (
                assignment_id, actor_id, role_bundle_id, property_id, assigned_by_actor_id,
                provenance
            ) VALUES (
                v_assignment_id, p_actor_id, p_role_bundle_id, v_property_id, p_owner_id,
                'owner-role-assignment'
            );
            PERFORM app.record_access_administration(
                p_owner_id, 'identity.role_assignment.created', 'user_account', p_actor_id,
                'Owner assigned the role bundle', NULL,
                pg_catalog.jsonb_build_object(
                    'assignment_id', v_assignment_id, 'role_bundle_id', p_role_bundle_id
                ),
                p_correlation_id
            );
            RETURN v_assignment_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.admin_remove_role_assignment(
            p_owner_id uuid,
            p_actor_id uuid,
            p_role_bundle_id uuid,
            p_reason text,
            p_correlation_id uuid
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_assignment_id uuid;
            v_revoked integer;
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            SELECT assignment.assignment_id INTO v_assignment_id
            FROM app.user_role_assignments AS assignment
            WHERE assignment.actor_id = p_actor_id
              AND assignment.role_bundle_id = p_role_bundle_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM app.user_role_assignment_removals AS removal
                  WHERE removal.assignment_id = assignment.assignment_id
              );
            IF v_assignment_id IS NULL THEN
                RAISE EXCEPTION 'this account does not have that role bundle'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            INSERT INTO app.user_role_assignment_removals (
                assignment_id, removed_by_actor_id, reason, provenance
            ) VALUES (
                v_assignment_id, p_owner_id, p_reason, 'owner-role-assignment-removal'
            );
            v_revoked := app.revoke_live_sessions(
                p_actor_id, p_owner_id, 'material_privilege_reduction',
                'access-admin-role-assignment-removed'
            );
            PERFORM app.record_access_administration(
                p_owner_id, 'identity.role_assignment.removed', 'user_account', p_actor_id,
                p_reason,
                pg_catalog.jsonb_build_object(
                    'assignment_id', v_assignment_id, 'role_bundle_id', p_role_bundle_id
                ),
                pg_catalog.jsonb_build_object('sessions_revoked', v_revoked),
                p_correlation_id
            );
            RETURN v_assignment_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.admin_give_settings_access(
            p_owner_id uuid,
            p_actor_id uuid,
            p_reason text,
            p_correlation_id uuid
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_grant_id uuid;
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            -- Sub-slice L1d review round 2: a disable committed at the same moment waits, so
            -- no grant is given to an account that is being disabled.
            PERFORM 1 FROM app.user_accounts AS account
            WHERE account.actor_id = p_actor_id
            FOR SHARE;
            v_grant_id := app.give_settings_access(p_owner_id, p_actor_id, p_reason);
            PERFORM app.record_access_administration(
                p_owner_id, 'identity.settings_access.given', 'user_account', p_actor_id,
                p_reason, NULL, pg_catalog.jsonb_build_object('grant_id', v_grant_id),
                p_correlation_id
            );
            RETURN v_grant_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.admin_remove_settings_access(
            p_owner_id uuid,
            p_actor_id uuid,
            p_reason text,
            p_correlation_id uuid
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_grant_id uuid;
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            v_grant_id := app.remove_settings_access(p_owner_id, p_actor_id, p_reason);
            PERFORM app.record_access_administration(
                p_owner_id, 'identity.settings_access.removed', 'user_account', p_actor_id,
                p_reason, pg_catalog.jsonb_build_object('grant_id', v_grant_id), '{}'::jsonb,
                p_correlation_id
            );
            RETURN v_grant_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.admin_accounts(p_owner_id uuid)
        RETURNS TABLE (
            actor_id uuid,
            username text,
            display_name text,
            audit_name text,
            lifecycle_state text,
            mfa_policy_class text,
            account_class text,
            settings_access boolean,
            version integer
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            -- `settings_access` is the recorded grant, as the user list shows it (Q-165 (a));
            -- whether it works now is the grant reader's answer (sub-slice L1e).
            RETURN QUERY
            SELECT account.actor_id, account.normalized_username, account.display_name,
                   account.audit_name, account.lifecycle_state, account.mfa_policy_class,
                   classification.account_class,
                   classification.account_class IS NOT DISTINCT FROM 'owner' OR EXISTS (
                       SELECT 1
                       FROM app.user_capability_grants AS given
                       WHERE given.actor_id = account.actor_id
                         AND NOT EXISTS (
                             SELECT 1
                             FROM app.user_capability_grant_removals AS removal
                             WHERE removal.grant_id = given.grant_id
                         )
                   ),
                   app.user_account_version(account.actor_id)
            FROM app.user_accounts AS account
            LEFT JOIN app.user_account_classes AS classification
              ON classification.actor_id = account.actor_id
            ORDER BY account.actor_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.admin_role_bundles(p_owner_id uuid)
        RETURNS TABLE (
            role_bundle_id uuid,
            property_id uuid,
            name text,
            version integer,
            capability_ids text[]
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            RETURN QUERY
            SELECT bundle.role_bundle_id, bundle.property_id, bundle.name, bundle.version,
                   COALESCE(
                       (SELECT pg_catalog.array_agg(held.capability_id
                                                    ORDER BY held.capability_id)
                        FROM app.role_bundle_capabilities AS held
                        WHERE held.role_bundle_id = bundle.role_bundle_id
                          AND held.version = bundle.version),
                       '{}'
                   )
            FROM app.role_bundles AS bundle
            ORDER BY bundle.role_bundle_id;
        END;
        $$
        """
    )
    for function in DEFINERS + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for function in DEFINERS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")
    op.execute("REVOKE ALL ON app.user_account_changes FROM PUBLIC")


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("access administration migration is forward-only")
