"""A Unit with no Meter needs no final Utility Invoice before its Settlement (V1-058 R7b-7).

Revision ID: 20270319_238
Revises: 20270318_237
Create Date: 2026-10-26

Owner decision 2026-10-26 (decision card "How should a Lease with no electricity or water
work?", answer "Meters decide"): electricity and water are billed from the Meters on the Unit; a
Unit with no Meter (a store room with no electricity or water) gets no Utility Invoice. Until now
the Final Settlement preview asked for final Utility inputs whenever the Primary Tenant had moved
in, but those inputs must name every Meter on the hand-back day (migration 63), so a Unit with no
Meter could never close its Final Settlement. The preview now skips FINAL_UTILITY_NOT_ISSUED when
no final inputs exist and the Unit has no Meter installed and not taken out on the hand-back day,
the same Meter list the final inputs check. UTILITY_PERIOD_NOT_BILLED still blocks any earlier
Utility period with consumption on no Invoice.

The Home "Refund due by" to-do (migration 222, DL-073 item 4) waited for a final Utility Invoice
too; for such a Unit it now counts from the final inspection alone (GREATEST skips the missing
Invoice date).

Both functions are patched in place, as migrations 168, 174 and 206 did: CREATE OR REPLACE keeps
their identity, owner and privileges.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270319_238"
down_revision: str | None = "20270318_237"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"
HOME = "app.home_page(uuid,uuid,uuid[],text[])"

BEFORE = """                    IF v_final.id IS NULL THEN
                        v_issues:=v_issues||jsonb_build_object('code','FINAL_UTILITY_NOT_ISSUED',
                            'reason','FINAL_INPUTS_NOT_RECORDED');
"""
AFTER = """                    IF v_final.id IS NULL AND NOT EXISTS(SELECT 1
                        FROM app.utility_meters meter WHERE meter.unit_id=v_move_out.unit_id
                          AND meter.installed_date<=v_move_out.actual_move_out_date
                          AND (meter.deactivated_date IS NULL
                            OR meter.deactivated_date>=v_move_out.actual_move_out_date)) THEN
                        -- V1-058 R7b-7: no Meter on the hand-back day, nothing to read or bill.
                        NULL;
                    ELSIF v_final.id IS NULL THEN
                        v_issues:=v_issues||jsonb_build_object('code','FINAL_UTILITY_NOT_ISSUED',
                            'reason','FINAL_INPUTS_NOT_RECORDED');
"""

HOME_BEFORE = """                        WHERE command.lease_id=lease.id AND command.action='FINAL'
                          AND invoice.status NOT IN ('DRAFT','VOID')) AS final_billed
"""
HOME_AFTER = """                        WHERE command.lease_id=lease.id AND command.action='FINAL'
                          AND invoice.status NOT IN ('DRAFT','VOID'))
                    -- V1-058 R7b-7: no Meter at all on the hand-back day, nothing to bill.
                    OR EXISTS(SELECT 1 FROM app.physical_move_out_events move_out
                        WHERE move_out.lease_id=lease.id AND NOT EXISTS(
                            SELECT 1 FROM app.physical_move_out_events later
                            WHERE later.supersedes_event_id=move_out.id)
                          AND NOT EXISTS(SELECT 1 FROM app.utility_meters meter
                            WHERE meter.unit_id=move_out.unit_id
                              AND meter.installed_date<=move_out.actual_move_out_date
                              AND (meter.deactivated_date IS NULL
                                OR meter.deactivated_date>=move_out.actual_move_out_date)))
                        AS final_billed
"""


def _patch(signature: str, before: str, after: str) -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    if definition.count(before) != 1:
        raise RuntimeError(f"{signature} source contract changed")
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition.replace(before, after))


def upgrade() -> None:
    _patch(PREVIEW, BEFORE, AFTER)
    _patch(HOME, HOME_BEFORE, HOME_AFTER)


def downgrade() -> None:
    raise RuntimeError("V1-058 no-Meter final Utility migration is forward-only")
