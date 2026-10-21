"""Settings access needs the sign-in code (login slice sub-slice L1e).

DL-081 (owner rule of 2026-10-21, amending DL-074 answer 2), SEC-013, SEC-021, DB-AUTH-008: an
account that holds Settings access must use the sign-in code at every sign-in. The Owner gives
Settings access to a Staff account only after it has set up its sign-in code (MFA policy
`required` and an `active` enrollment); otherwise the give is refused with a plain message. The
grant reader gives a Staff account's per-user Settings access only while that holds, so no path
leaves a Staff account able to change Settings without its sign-in code. Both functions are
replaced with the same signature, owner, privileges and attributes; nothing else changes.
"""

from alembic import op

revision = "20270123_180"
down_revision = "20270122_179"
branch_labels = None
depends_on = None

GIVE = "app.give_settings_access(uuid,uuid,text)"
READER = "app.actor_capability_grants(uuid)"


def upgrade() -> None:
    """Replace the give function and the grant reader with the sign-in code rule."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.give_settings_access(
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
            -- Owner rule of 2026-10-21 (DL-081): a Staff account first sets up its sign-in
            -- code. A Manager always needs the code at sign-in by its class (L1a).
            IF EXISTS (
                   SELECT 1
                   FROM app.user_account_classes AS classification
                   WHERE classification.actor_id = p_actor_id
                     AND classification.account_class = 'staff'
               )
               AND NOT app.staff_sign_in_code_is_set_up(p_actor_id) THEN
                RAISE EXCEPTION
                    'a Staff account gets Settings access only after it has set up its sign-in code'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
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
        CREATE FUNCTION app.staff_sign_in_code_is_set_up(p_actor_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM app.user_accounts AS account
                JOIN app.totp_mfa_enrollments AS enrollment
                  ON enrollment.actor_id = account.actor_id
                WHERE account.actor_id = p_actor_id
                  AND account.mfa_policy_class = 'required'
                  AND enrollment.enrollment_state = 'active'
            )
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
               OR (
                   EXISTS (
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
                   -- Owner rule of 2026-10-21 (DL-081): a Staff account's Settings access
                   -- works only while its sign-in code is set up, whatever path changed it.
                   AND (
                       account.account_class = 'manager'
                       OR (
                           account.account_class = 'staff'
                           AND app.staff_sign_in_code_is_set_up(p_actor_id)
                       )
                   )
               )
        $$
        """
    )
    for function in (GIVE, READER, "app.staff_sign_in_code_is_set_up(uuid)"):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for function in (GIVE, READER):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("settings access sign-in code migration is forward-only")
