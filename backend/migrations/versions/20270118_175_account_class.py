"""Add the account class of a local human account (login slice sub-slice L1a).

DL-056, DL-058, DL-059, DL-074 answer 2, DL-081 (owner answer (a) to Q-2026-10-21-152): an
account has one class, `owner`, `manager` or `staff`, that ties the Owner-only rights to the
account class and not to a role name (SEC-021). The class is a separate append-only relation
(DB-AUTH-001: assignments are separate relations), so this migration takes no lock on
`app.user_accounts` that conflicts with a reader or a foreign-key check: a whole-chain upgrade
that holds the V1-042 validation gate cannot deadlock with a waiting writer. Exactly one Owner
account (the bootstrapped one); an Owner or Manager account requires MFA; a class, once given,
never changes or goes away. Old accounts keep no class and can never sign in (fail closed); only
the bootstrapped Owner is classed by this migration. The bootstrap function writes `owner`
through one exact-text change (checked to match once); same signature, settings and privileges.
"""

from alembic import op
from sqlalchemy import text

revision = "20270118_175"
down_revision = "20270117_174"
branch_labels = None
depends_on = None

BOOTSTRAP = (
    "app.establish_initial_owner_bootstrap(uuid,uuid,uuid,uuid,text,text,text,text,text,jsonb,"
    "bytea,bytea,text,uuid[],text[],text,jsonb)"
)

BOOTSTRAP_REPLACEMENTS = (
    (
        "            INSERT INTO app.password_credentials (\n",
        "            INSERT INTO app.user_account_classes (\n"
        "                actor_id, account_class, provenance\n"
        "            ) VALUES (\n"
        "                p_actor_id, 'owner', 'protected-initial-owner-bootstrap'\n"
        "            );\n"
        "            INSERT INTO app.password_credentials (\n",
    ),
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Account class bootstrap contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    """Add the class relation, its guards, the Owner backfill and the bootstrap class write."""
    op.execute(
        """
        CREATE TABLE app.user_account_classes (
            actor_id uuid PRIMARY KEY
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            account_class text NOT NULL
                CHECK (account_class IN ('owner', 'manager', 'staff')),
            classified_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            provenance text NOT NULL CHECK (length(btrim(provenance)) > 0)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX user_account_classes_single_owner
        ON app.user_account_classes (account_class)
        WHERE account_class = 'owner'
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_user_account_class_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'user account class is immutable'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER user_account_classes_are_immutable
        BEFORE UPDATE OR DELETE ON app.user_account_classes
        FOR EACH ROW
        EXECUTE FUNCTION app.reject_user_account_class_change()
        """
    )
    op.execute(
        """
        CREATE TRIGGER user_account_classes_reject_truncate
        BEFORE TRUNCATE ON app.user_account_classes
        FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_user_account_class_change()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.require_user_account_class_mfa()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_mfa_policy_class text;
        BEGIN
            -- At READ COMMITTED the share lock waits for, and then sees, a concurrent MFA policy
            -- change; at REPEATABLE READ or SERIALIZABLE such a change after the snapshot fails
            -- the lock with a serialization failure.
            SELECT account.mfa_policy_class
            INTO v_mfa_policy_class
            FROM app.user_accounts AS account
            WHERE account.actor_id = NEW.actor_id
            FOR SHARE;
            IF NEW.account_class IN ('owner', 'manager')
               AND v_mfa_policy_class IS DISTINCT FROM 'required' THEN
                RAISE EXCEPTION 'an Owner or Manager account requires MFA'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER user_account_classes_require_mfa
        BEFORE INSERT ON app.user_account_classes
        FOR EACH ROW
        EXECUTE FUNCTION app.require_user_account_class_mfa()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_privileged_account_optional_mfa()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            -- Under REPEATABLE READ or SERIALIZABLE the class check below could read a snapshot
            -- older than a class given meanwhile, so an MFA policy is lowered only at READ
            -- COMMITTED (fail closed; review round 1 of login sub-slice L1a).
            IF NEW.mfa_policy_class IS DISTINCT FROM OLD.mfa_policy_class
               AND pg_catalog.current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'an MFA policy can be lowered only at READ COMMITTED'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            IF EXISTS (
                   SELECT 1
                   FROM app.user_account_classes AS classification
                   WHERE classification.actor_id = OLD.actor_id
                     AND classification.account_class IN ('owner', 'manager')
               ) THEN
                RAISE EXCEPTION 'an Owner or Manager account requires MFA'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER user_accounts_privileged_class_requires_mfa
        AFTER UPDATE ON app.user_accounts
        FOR EACH ROW
        WHEN (NEW.mfa_policy_class IS DISTINCT FROM 'required')
        EXECUTE FUNCTION app.reject_privileged_account_optional_mfa()
        """
    )
    for function in (
        "app.reject_user_account_class_change()",
        "app.require_user_account_class_mfa()",
        "app.reject_privileged_account_optional_mfa()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    op.execute(
        """
        INSERT INTO app.user_account_classes (actor_id, account_class, provenance)
        SELECT closure.established_actor_id, 'owner', 'login-slice-account-class-backfill'
        FROM app.initial_owner_bootstrap_closure AS closure
        WHERE closure.singleton
        """
    )
    op.execute("REVOKE ALL ON app.user_account_classes FROM PUBLIC")
    op.execute("GRANT SELECT ON app.user_account_classes TO prm_runtime")
    _patch(BOOTSTRAP, BOOTSTRAP_REPLACEMENTS)


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("account class migration is forward-only")
