"""DL-227 (owner 13 Nov 2026): the Payment Method for ABA QR payments is chosen in Settings.

Before this migration the office jobs found the Payment Method that an ABA QR payment is
recorded with by a code written in the operations file (``aba_payway.payment_method_code``,
DL-180). Changing it meant editing a file on the office computer. The owner asked that this
be a choice in the app, also for other businesses that use the app later.

1. ``app.payment_methods`` gets ``aba_qr`` (false for every method today). At most one method
   has it, and only a method that is on (accepted). Turning a method off takes the mark away.
2. ``app.replace_property_payment_methods(...)`` (the Settings save) reads an optional
   ``aba_qr`` true/false on each method. When no method in the list carries the key, the mark
   stays as it was (a screen that does not show the choice cannot clear it by saving). When
   the key is present, the method marked true gets the mark and every other method loses it.
   Two marked methods, or a marked method that is off, are refused.
3. ``app.aba_payment_method(property, code, actor)`` returns the marked method first; when no
   method is marked it still uses the code from the operations file, so a computer set up
   before this change keeps working.

The function signatures and grants stay the same. No data is changed: no method is marked.
Forward-only. Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270723_392"
down_revision: str | None = "20270717_340"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMN = """
    ALTER TABLE app.payment_methods
        ADD COLUMN aba_qr boolean NOT NULL DEFAULT false,
        ADD CONSTRAINT payment_methods_aba_qr_is_on CHECK (NOT aba_qr OR accepted);
    CREATE UNIQUE INDEX payment_methods_one_aba_qr ON app.payment_methods ((true)) WHERE aba_qr;
"""

REPLACE_METHODS = """
    CREATE OR REPLACE FUNCTION app.replace_property_payment_methods(
        p_property_id uuid,
        p_methods jsonb,
        p_expected_version integer,
        p_actor_id uuid
    )
    RETURNS TABLE(
        property_id uuid,
        name text,
        address_text text,
        timezone_name text,
        version integer
    )
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog
    AS $$
    DECLARE
        v_aba_given boolean;
        v_aba_code text;
    BEGIN
        IF jsonb_typeof(p_methods) <> 'array'
            OR EXISTS (
                SELECT 1
                FROM jsonb_array_elements(p_methods) AS method
                WHERE jsonb_typeof(method) <> 'object'
                   OR NULLIF(btrim(method->>'id'), '') IS NULL
                   OR NULLIF(btrim(method->>'code'), '') IS NULL
                   OR NULLIF(btrim(method->>'display_name'), '') IS NULL
                   OR jsonb_typeof(method->'accepted') <> 'boolean'
                   OR (method ? 'aba_qr' AND jsonb_typeof(method->'aba_qr') <> 'boolean')
                   OR (method->>'aba_qr' = 'true' AND method->>'accepted' <> 'true')
            )
            OR EXISTS (
                SELECT 1
                FROM jsonb_array_elements(p_methods) AS method
                GROUP BY btrim(method->>'code')
                HAVING count(*) > 1
            )
            OR (
                SELECT count(*)
                FROM jsonb_array_elements(p_methods) AS method
                WHERE method->>'aba_qr' = 'true'
            ) > 1
        THEN
            RAISE EXCEPTION 'Payment Method configuration is invalid'
                USING ERRCODE = '22023';
        END IF;

        v_aba_given := EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_methods) AS method WHERE method ? 'aba_qr'
        );
        SELECT btrim(method->>'code') INTO v_aba_code
        FROM jsonb_array_elements(p_methods) AS method
        WHERE method->>'aba_qr' = 'true';

        PERFORM 1
        FROM app.property_configuration AS configuration
        WHERE configuration.property_id = p_property_id
          AND configuration.version = p_expected_version
        FOR UPDATE;
        IF NOT FOUND THEN
            RETURN;
        END IF;

        -- A method that is turned off (or left out) loses the ABA mark first, so the one-mark
        -- index and the "mark only on a method that is on" check hold at every step.
        UPDATE app.payment_methods AS existing
        SET aba_qr = false,
            updated_at = statement_timestamp(),
            updated_by = p_actor_id
        WHERE existing.aba_qr
          AND (
              (v_aba_given AND existing.code IS DISTINCT FROM v_aba_code)
              OR NOT EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(p_methods) AS method
                  WHERE btrim(method->>'code') = existing.code
                    AND method->>'accepted' = 'true'
              )
          );

        UPDATE app.payment_methods AS existing
        SET accepted = false,
            updated_at = statement_timestamp(),
            updated_by = p_actor_id
        WHERE existing.accepted
          AND NOT EXISTS (
              SELECT 1
              FROM jsonb_array_elements(p_methods) AS method
              WHERE btrim(method->>'code') = existing.code
          );

        INSERT INTO app.payment_methods AS existing (
            id,
            code,
            display_name,
            accepted,
            created_by,
            updated_by
        )
        SELECT
            (method->>'id')::uuid,
            btrim(method->>'code'),
            btrim(method->>'display_name'),
            (method->>'accepted')::boolean,
            p_actor_id,
            p_actor_id
        FROM jsonb_array_elements(p_methods) AS method
        ON CONFLICT (code) DO UPDATE
        SET display_name = EXCLUDED.display_name,
            accepted = EXCLUDED.accepted,
            updated_at = statement_timestamp(),
            updated_by = p_actor_id;

        IF v_aba_code IS NOT NULL THEN
            UPDATE app.payment_methods AS existing
            SET aba_qr = true,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE existing.code = v_aba_code
              AND NOT existing.aba_qr;
        END IF;

        RETURN QUERY
        UPDATE app.property_configuration AS configuration
        SET updated_at = statement_timestamp(),
            updated_by = p_actor_id,
            version = configuration.version + 1
        WHERE configuration.property_id = p_property_id
        RETURNING
            configuration.property_id,
            configuration.name,
            configuration.address_text,
            configuration.timezone_name,
            configuration.version;
    END;
    $$;
"""

ABA_METHOD = """
    CREATE OR REPLACE FUNCTION app.aba_payment_method(p_property uuid, p_code text, p_actor uuid)
    RETURNS uuid LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        RETURN COALESCE(
            (SELECT method.id FROM app.payment_methods AS method
             WHERE method.aba_qr AND method.accepted),
            (SELECT method.id FROM app.payment_methods AS method
             WHERE method.code = p_code AND method.accepted)
        );
    END $$;
"""


def upgrade() -> None:
    op.execute(COLUMN)
    op.execute(REPLACE_METHODS)
    op.execute(ABA_METHOD)


def downgrade() -> None:
    raise RuntimeError("The ABA QR Payment Method migration is forward-only")
