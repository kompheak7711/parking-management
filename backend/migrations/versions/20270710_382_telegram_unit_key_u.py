"""Telegram bots: "302" also finds Unit "U302" when a tenant links (DL-212).

The owner's Units are numbered "U302"; a tenant who types "302" in the Tenant bot was refused
(owner test, 8 Nov 2026). ``app.tenant_unit_key`` now also drops a leading "U" before a digit,
after "Unit", "Room", "No.", "#" and "បន្ទប់", so "U302", "u 302", "302", "Unit 302" and
"Room U302" are the same Unit. The relay's ``unitKey`` (relay/src/offline.ts) follows the same
rule. Forward-only.

Technical choice by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270710_382"
down_revision: str | None = "20270709_381"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
    -- "Unit 305", "305", "unit305" and "U305" are the same Unit.
    CREATE OR REPLACE FUNCTION app.tenant_unit_key(p_unit text) RETURNS text
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT regexp_replace(
            regexp_replace(upper(regexp_replace(COALESCE(p_unit, ''), '[[:space:]]+', '', 'g')),
                '^(UNIT|ROOM|NO\\.?|#|បន្ទប់)', ''),
            '^U([0-9])', '\\1')
    $$;
    """
    )


def downgrade() -> None:
    raise RuntimeError("the Unit key migration is forward-only")
