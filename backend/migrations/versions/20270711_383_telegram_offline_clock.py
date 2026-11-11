"""Telegram bots: the Property's clock for the relay while the office is away (DL-213).

Owner (11 Nov 2026): the Customer bot and the Staff bot answer by themselves while the office
app is closed, as the Tenant bot does (DL-210). The relay offers a customer the visit days and
move-in months from the Property's own date, so the office sends it the Property's time zone and
its distance from UTC with the bots' offline texts. ``app.telegram_offline_clock`` returns both
(the Telegram jobs' account, ``telegram.operate``). Forward-only.

Technical choice by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270711_383"
down_revision: str | None = "20270626_306"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = """
    CREATE FUNCTION app.telegram_offline_clock(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_zone text;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT property.timezone_name INTO v_zone FROM app.properties AS property
        WHERE property.id = p_property;
        IF v_zone IS NULL THEN
            RAISE EXCEPTION 'the property is not known' USING ERRCODE = '22023';
        END IF;
        RETURN jsonb_build_object(
            'timezone_name', v_zone,
            'utc_offset_minutes', round(extract(epoch FROM
                timezone(v_zone, statement_timestamp()) - timezone('UTC', statement_timestamp()))
                / 60)::integer);
    END $$;
"""

RUNTIME = ("app.telegram_offline_clock(uuid, uuid)",)


def upgrade() -> None:
    op.execute(FUNCTIONS)
    for signature in RUNTIME:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Telegram offline clock migration is forward-only")
