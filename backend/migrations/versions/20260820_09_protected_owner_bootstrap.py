"""Add the atomic least-privilege protected initial Owner bootstrap operation."""

from alembic import op

revision = "20260820_09"
down_revision = "20260819_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Publish preflight/audit and one-time atomic bootstrap functions only."""
    op.execute(
        """
        DO $$
        DECLARE
            bootstrap_role pg_catalog.pg_roles%ROWTYPE;
            has_large_object_authority boolean;
        BEGIN
            SELECT *
            INTO bootstrap_role
            FROM pg_catalog.pg_roles
            WHERE rolname = 'prm_bootstrap';

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'prm_bootstrap role must exist before migration';
            END IF;

            BEGIN
                IF pg_catalog.current_setting(
                    'prm.test_force_large_object_authority_query_error', true
                ) = 'force-query-error' THEN
                    RAISE EXCEPTION 'forced large-object authority query error';
                END IF;

                SELECT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_largeobject_metadata AS large_object
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        COALESCE(
                            large_object.lomacl,
                            pg_catalog.acldefault('L', large_object.lomowner)
                        )
                    ) AS privilege
                    WHERE large_object.lomowner = bootstrap_role.oid
                       OR pg_catalog.pg_has_role(
                           bootstrap_role.oid, large_object.lomowner, 'USAGE'
                       )
                       OR pg_catalog.pg_has_role(
                           bootstrap_role.oid, large_object.lomowner, 'MEMBER'
                       )
                       OR CASE
                           WHEN privilege.grantee = 0 THEN true
                           ELSE pg_catalog.pg_has_role(
                               bootstrap_role.oid, privilege.grantee, 'USAGE'
                           ) OR pg_catalog.pg_has_role(
                               bootstrap_role.oid, privilege.grantee, 'MEMBER'
                           )
                       END
                ) INTO STRICT has_large_object_authority;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION
                    'prm_bootstrap large-object authority state could not be proven safe'
                    USING ERRCODE = 'P0001';
            END;

            IF NOT bootstrap_role.rolcanlogin
               OR bootstrap_role.rolinherit
               OR bootstrap_role.rolsuper
               OR bootstrap_role.rolcreatedb
               OR bootstrap_role.rolcreaterole
               OR bootstrap_role.rolreplication
               OR bootstrap_role.rolbypassrls
               OR bootstrap_role.rolconnlimit <> 1
               OR has_large_object_authority
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_auth_members
                   WHERE roleid = bootstrap_role.oid OR member = bootstrap_role.oid
               )
               OR NOT pg_catalog.has_database_privilege(
                   bootstrap_role.oid, pg_catalog.current_database(), 'CONNECT'
               )
               OR pg_catalog.has_database_privilege(
                   bootstrap_role.oid, pg_catalog.current_database(), 'CREATE'
               )
               OR pg_catalog.has_database_privilege(
                   bootstrap_role.oid, pg_catalog.current_database(), 'TEMP'
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_namespace AS namespace
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(
                           namespace.nspacl,
                           pg_catalog.acldefault('n', namespace.nspowner)
                       )
                   ) AS privilege
                   WHERE privilege.grantee = bootstrap_role.oid
                      OR (
                          privilege.grantee = 0
                          AND privilege.privilege_type = 'CREATE'
                          AND namespace.nspname <> 'pg_catalog'
                          AND namespace.nspname <> 'information_schema'
                          AND namespace.nspname NOT LIKE 'pg_toast%'
                      )
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_class AS relation
                   JOIN pg_catalog.pg_namespace AS namespace
                     ON namespace.oid = relation.relnamespace
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(
                           relation.relacl,
                           pg_catalog.acldefault(
                               CASE WHEN relation.relkind = 'S' THEN 'S'::"char" ELSE 'r'::"char" END,
                               relation.relowner
                           )
                       )
                   ) AS privilege
                   WHERE privilege.grantee = bootstrap_role.oid
                      OR (
                          privilege.grantee = 0
                          AND namespace.nspname <> 'pg_catalog'
                          AND namespace.nspname <> 'information_schema'
                          AND namespace.nspname NOT LIKE 'pg_toast%'
                      )
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_attribute AS attribute
                   JOIN pg_catalog.pg_class AS relation
                     ON relation.oid = attribute.attrelid
                   JOIN pg_catalog.pg_namespace AS namespace
                     ON namespace.oid = relation.relnamespace
                   CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS privilege
                   WHERE attribute.attacl IS NOT NULL
                     AND (
                         privilege.grantee = bootstrap_role.oid
                         OR (
                             privilege.grantee = 0
                             AND namespace.nspname <> 'pg_catalog'
                             AND namespace.nspname <> 'information_schema'
                             AND namespace.nspname NOT LIKE 'pg_toast%'
                         )
                     )
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_proc AS procedure
                   JOIN pg_catalog.pg_namespace AS namespace
                     ON namespace.oid = procedure.pronamespace
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(
                           procedure.proacl,
                           pg_catalog.acldefault('f', procedure.proowner)
                       )
                   ) AS privilege
                   WHERE privilege.grantee = bootstrap_role.oid
                      OR (
                          privilege.grantee = 0
                          AND namespace.nspname <> 'pg_catalog'
                          AND namespace.nspname <> 'information_schema'
                          AND namespace.nspname NOT LIKE 'pg_toast%'
                      )
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_type AS type_definition
                   JOIN pg_catalog.pg_namespace AS namespace
                     ON namespace.oid = type_definition.typnamespace
                   CROSS JOIN LATERAL pg_catalog.aclexplode(
                       COALESCE(
                           type_definition.typacl,
                           pg_catalog.acldefault('T', type_definition.typowner)
                       )
                   ) AS privilege
                   WHERE privilege.grantee = bootstrap_role.oid
                      OR (
                          type_definition.typacl IS NOT NULL
                          AND privilege.grantee = 0
                          AND namespace.nspname <> 'pg_catalog'
                          AND namespace.nspname <> 'information_schema'
                          AND namespace.nspname NOT LIKE 'pg_toast%'
                      )
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_default_acl AS default_acl
                   CROSS JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl) AS privilege
                   WHERE default_acl.defaclrole = bootstrap_role.oid
                      OR privilege.grantee = bootstrap_role.oid
                      OR privilege.grantee = 0
               )
               OR EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_shdepend AS dependency
                   JOIN pg_catalog.pg_database AS target_database
                     ON target_database.datname = pg_catalog.current_database()
                   WHERE dependency.refclassid = 'pg_catalog.pg_authid'::regclass
                     AND dependency.refobjid = bootstrap_role.oid
                     AND dependency.dbid = target_database.oid
                     AND dependency.deptype = 'o'
               )
               OR EXISTS (
                   SELECT 1 FROM pg_catalog.pg_database
                   WHERE datname = pg_catalog.current_database()
                     AND datdba = bootstrap_role.oid
                   UNION ALL
                   SELECT 1 FROM pg_catalog.pg_namespace
                   WHERE nspowner = bootstrap_role.oid
                   UNION ALL
                   SELECT 1 FROM pg_catalog.pg_class
                   WHERE relowner = bootstrap_role.oid
                   UNION ALL
                   SELECT 1 FROM pg_catalog.pg_proc
                   WHERE proowner = bootstrap_role.oid
                   UNION ALL
                   SELECT 1 FROM pg_catalog.pg_type
                   WHERE typowner = bootstrap_role.oid
               ) THEN
                RAISE EXCEPTION
                    'prm_bootstrap role must have safe attributes and only bounded CONNECT authority in the target database before migration';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.begin_initial_owner_bootstrap_attempt(
            p_target_actor_id uuid,
            p_correlation_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            existing_actor_id uuid;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(120120059);
            SELECT established_actor_id
            INTO existing_actor_id
            FROM app.initial_owner_bootstrap_closure
            WHERE singleton;

            IF existing_actor_id IS NOT NULL THEN
                INSERT INTO app.initial_owner_bootstrap_audit_events (
                    target_actor_id, procedure_identity, correlation_id, outcome, reason,
                    previous_state, resulting_state, established_actor_id
                ) VALUES (
                    p_target_actor_id, 'protected_initial_owner_bootstrap', p_correlation_id,
                    'rejected', 'bootstrap_closed', 'closed', 'closed', existing_actor_id
                );
                RETURN false;
            END IF;
            IF EXISTS (SELECT 1 FROM app.user_accounts) THEN
                RAISE EXCEPTION 'initial Owner bootstrap rejected' USING ERRCODE = 'P0001';
            END IF;
            RETURN true;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.establish_initial_owner_bootstrap(
            p_actor_id uuid,
            p_correlation_id uuid,
            p_enrollment_id uuid,
            p_recovery_set_id uuid,
            p_normalized_username text,
            p_display_name text,
            p_audit_name text,
            p_password_verifier text,
            p_password_algorithm text,
            p_password_work_factors jsonb,
            p_totp_ciphertext bytea,
            p_totp_nonce bytea,
            p_totp_key_identifier text,
            p_recovery_code_ids uuid[],
            p_recovery_verifiers text[],
            p_recovery_algorithm text,
            p_recovery_work_factors jsonb
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            closure_established boolean;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(120120059);
            IF EXISTS (SELECT 1 FROM app.initial_owner_bootstrap_closure)
               OR EXISTS (SELECT 1 FROM app.user_accounts)
               OR pg_catalog.cardinality(p_recovery_code_ids) <> 10
               OR pg_catalog.cardinality(p_recovery_verifiers) <> 10
               OR EXISTS (
                   SELECT 1 FROM pg_catalog.unnest(p_recovery_code_ids) AS item(value)
                   WHERE value IS NULL
               )
               OR EXISTS (
                   SELECT 1 FROM pg_catalog.unnest(p_recovery_verifiers) AS item(value)
                   WHERE value IS NULL OR length(value) = 0
               )
               OR (
                   SELECT count(DISTINCT value)
                   FROM pg_catalog.unnest(p_recovery_code_ids) item(value)
               ) <> 10
               OR (
                   SELECT count(DISTINCT value)
                   FROM pg_catalog.unnest(p_recovery_verifiers) item(value)
               ) <> 10 THEN
                RAISE EXCEPTION 'initial Owner bootstrap rejected' USING ERRCODE = 'P0001';
            END IF;

            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, created_by_actor_id, provenance
            ) VALUES (
                p_actor_id, p_normalized_username, p_display_name, p_audit_name,
                'active', 'required', p_actor_id, 'protected-initial-owner-bootstrap'
            );
            INSERT INTO app.password_credentials (
                actor_id, verifier_encoding, algorithm, work_factor_metadata,
                changed_by_actor_id, provenance
            ) VALUES (
                p_actor_id, p_password_verifier, p_password_algorithm,
                p_password_work_factors, p_actor_id, 'protected-initial-owner-bootstrap'
            );
            INSERT INTO app.totp_mfa_enrollments (
                enrollment_id, actor_id, secret_ciphertext, secret_nonce, key_identifier,
                protection_algorithm, totp_algorithm, digits, period_seconds,
                enrollment_state, created_by_actor_id, provenance, activated_at,
                activated_by_actor_id, activation_provenance
            ) VALUES (
                p_enrollment_id, p_actor_id, p_totp_ciphertext, p_totp_nonce,
                p_totp_key_identifier, 'aes-256-gcm', 'sha1', 6, 30, 'active', p_actor_id,
                'protected-initial-owner-bootstrap', statement_timestamp(), p_actor_id,
                'protected-initial-owner-bootstrap-confirmed'
            );
            INSERT INTO app.recovery_code_sets (
                set_id, actor_id, created_by_actor_id, provenance
            ) VALUES (
                p_recovery_set_id, p_actor_id, p_actor_id,
                'protected-initial-owner-bootstrap'
            );
            INSERT INTO app.recovery_codes (
                code_id, set_id, verifier_encoding, algorithm,
                work_factor_metadata, provenance
            )
            SELECT
                code_id.value, p_recovery_set_id, verifier.value, p_recovery_algorithm,
                p_recovery_work_factors, 'protected-initial-owner-bootstrap'
            FROM pg_catalog.unnest(p_recovery_code_ids)
                WITH ORDINALITY AS code_id(value, position)
            JOIN pg_catalog.unnest(p_recovery_verifiers)
                WITH ORDINALITY AS verifier(value, position)
              USING (position);

            SELECT established
            INTO closure_established
            FROM app.attempt_initial_owner_bootstrap_closure(p_actor_id, p_correlation_id);
            IF closure_established IS DISTINCT FROM true THEN
                RAISE EXCEPTION 'initial Owner bootstrap rejected' USING ERRCODE = 'P0001';
            END IF;

            EXECUTE 'REVOKE EXECUTE ON FUNCTION app.establish_initial_owner_bootstrap('
                'uuid, uuid, uuid, uuid, text, text, text, text, text, jsonb, bytea, bytea, '
                'text, uuid[], text[], text, jsonb) FROM prm_bootstrap';
            RETURN true;
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.begin_initial_owner_bootstrap_attempt(uuid, uuid) "
        "FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute(
        """
        REVOKE ALL ON FUNCTION app.establish_initial_owner_bootstrap(
            uuid, uuid, uuid, uuid, text, text, text, text, text, jsonb,
            bytea, bytea, text, uuid[], text[], text, jsonb
        ) FROM PUBLIC, prm_runtime, prm_bootstrap
        """
    )
    op.execute("GRANT USAGE ON SCHEMA app TO prm_bootstrap")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.begin_initial_owner_bootstrap_attempt(uuid, uuid) "
        "TO prm_bootstrap"
    )
    op.execute(
        """
        GRANT EXECUTE ON FUNCTION app.establish_initial_owner_bootstrap(
            uuid, uuid, uuid, uuid, text, text, text, text, text, jsonb,
            bytea, bytea, text, uuid[], text[], text, jsonb
        ) TO prm_bootstrap
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("protected initial Owner bootstrap migration is forward-only")
