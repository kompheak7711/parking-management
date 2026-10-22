"""Hidden characters and spaces in names (login slice sub-slice L2c).

DL-081 (Q-2026-10-22-169 (a), owner, 2026-10-22), DB-AUTH-007, DB-AUTH-010: an account name
(username, display name, audit name) and a role bundle name also refuse U+034F, the Hangul
fillers (U+115F, U+1160, U+3164, U+FFA0), the invisible Khmer vowels U+17B4 and U+17B5, the line
and paragraph separators U+2028 and U+2029, and (review round 1, security) the Mongolian
variation selectors U+180B to U+180F, the blank braille pattern U+2800, the variation selectors
U+FE00 to U+FE0F and U+E0100 to U+E01EF (in U+E0080 to U+E0FFF), U+FFF0 to U+FFF8, U+1BCA0 to
U+1BCA3 and U+1D173 to U+1D17A; a space other than U+0020 and two U+0020 in a row (the API
folds both into one space, so no other writer can save a look-alike); and a name that is not
NFC. The API removes U+200B before saving a name; the database keeps refusing it.
`app.assert_account_names` is replaced with the same signature, owner, privileges, attributes
and message; `app.role_bundles` gains one check constraint and keeps its L1b-2 check. The
upgrade refuses to run while a stored username is not NFC or holds U+200B, because the sign-in
lookup now looks a username up in that form (review round 1, security). A tightening approved
by the owner; nothing else changes.
"""

from alembic import op

revision = "20270126_183"
down_revision = "20270125_182"
branch_labels = None
depends_on = None

NEW_HIDDEN = (
    "'[\\u034f\\u115f\\u1160\\u17b4\\u17b5\\u180b-\\u180f\\u2028\\u2029'\n"
    "                                   '\\u2800\\u3164\\ufe00-\\ufe0f\\uffa0\\ufff0-\\ufff8'\n"
    "                                   '\\U0001bca0-\\U0001bca3\\U0001d173-\\U0001d17a'\n"
    "                                   '\\U000e0080-\\U000e0fff'\n"
    "                                   '\\u00a0\\u1680\\u2000-\\u200a\\u202f\\u205f\\u3000]'"
)


def upgrade() -> None:
    """Check the stored usernames, then replace the account name check and add the bundle
    name check."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM app.user_accounts
                WHERE normalized_username IS NOT NFC NORMALIZED
                   OR pg_catalog.strpos(normalized_username, U&'\\200B') > 0
            ) THEN
                RAISE EXCEPTION
                    'a stored username is not NFC or holds U+200B'
                    USING ERRCODE = 'check_violation';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION app.assert_account_names(p_names text[])
        RETURNS void
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_name text;
        BEGIN
            -- Review round 1 of L2a: the bundle name rule of sub-slice L1b-2, so two accounts or
            -- an audit name cannot look like another on screen or in the audit history. L2c
            -- (Q-2026-10-22-169 (a)): also the remaining invisible characters, the spaces the
            -- API folds into one U+0020, and NFC.
            FOREACH v_name IN ARRAY p_names LOOP
                IF v_name IS NOT NULL AND (
                       v_name <> pg_catalog.btrim(v_name)
                       OR pg_catalog.length(v_name) NOT BETWEEN 1 AND 128
                       OR v_name ~ '[[:cntrl:]\\u0001-\\u001f\\u007f-\\u009f\\u00ad'
                                   '\\u061c\\u180e\\u200b-\\u200f\\u202a-\\u202e'
                                   '\\u2060-\\u206f\\ufeff\\ufff9-\\ufffb'
                                   '\\U000e0000-\\U000e007f]'
                       OR v_name ~ {NEW_HIDDEN}
                       OR pg_catalog.strpos(v_name, '  ') > 0
                       OR v_name IS NOT NFC NORMALIZED
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
        f"""
        ALTER TABLE app.role_bundles
            ADD CONSTRAINT role_bundles_name_visible_check
            CHECK (
                name !~ {NEW_HIDDEN}
                AND strpos(name, '  ') = 0
                AND name IS NFC NORMALIZED
            )
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("name hidden characters migration is forward-only")
