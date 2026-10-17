# ruff: noqa: E501
"""A recovery counts as returned money only while its charge stands (V1-056 sub-slice 10e-2b-4b-1).

BR-SETTLE-013, BR-DEP-022, DL-032, DL-053, BR-INV-044; DB-DEP-004, DB-REFUND-002; owner answer (a)
to Q-2026-10-17-125: a recovery counts as money that came back only while its charge stands. If
the charge is later forgiven by a CHARGE_REDUCTION, a credit Adjustment or a VOID, it stops
counting.

- A RECOVERED_BY_CHARGE row names an authorized Miscellaneous obligation of exactly its amount,
  billed on an issued Invoice line before the row is written. What still stands of that charge at a
  time is the least of the recovered amount and the adjusted obligation, never below 0, of each of
  its lines on an Invoice issued by then and not VOID by then (an obligation has at most one Invoice
  that is not VOID at a time, and after a VOID it can be billed again on a later Invoice). A VOID
  Invoice with no void event counts as VOID at every time (fail closed). Paid or unpaid, a charge
  that stands counts. A later credit forgives a DEBIT Adjustment of the line first (the least of
  the recovered amount and the line). New internal app.refund_recovery_standing_at.
- The Pet Refund-review part of the pay-back count (sub-slice 10e-2b-4a) counts each such recovery
  at its own time by what still stands of its charge now; another Refund's payout (sub-slice
  10e-2d) is undone by its recovery only as far as the charge stands now, from the Refund's time.
  One rule for both, as the answer says ("alike"): a forgiven recovery counts as if it had been
  that much smaller, and a restored charge (an Adjustment reversal, a later Invoice of the same
  obligation) counts again exactly as before, whatever was paid out in between. (Review round 1,
  both reviewers: placing a forgiveness and a restoration at their own times let the count's
  floor at 0 swallow a forgiveness after a payout and then add the restoration in full, and let a
  forgiveness after payouts take later returned money; the first build did that.)

One exact-text patch of the internal app.lease_deposit_payback_count_as (two replacements) and one
new internal function with no grant. A forgiven recovery charge lowers the count (a forfeiture can
then take more), which is the owner's answer; with every recovery charge standing whole every
result stays as built. The pay-back value, the Deposit path, the forfeiture source and insert
check, the returned-Refund check, the receipt correction's targets and plan check read the count
and follow it unchanged.
"""

from alembic import op
from sqlalchemy import text

revision = "20261226_152"
down_revision = "20261225_151"
branch_labels = None
depends_on = None

SQL = r"""
    -- DB-REFUND-002 (owner answer (a) to Q-2026-10-17-125): what still stands of a recovery's
    -- charge at a time. The least of the recovered amount and the adjusted obligation (never below
    -- 0) of each line of the charge on an Invoice issued by then and not VOID by then; a VOID
    -- Invoice with no void event counts as VOID at every time (fail closed).
    CREATE FUNCTION app.refund_recovery_standing_at(p_recovery uuid, p_as_of timestamptz)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT LEAST(recovery.source_balance_effect_usd_cents,
            COALESCE((SELECT sum(GREATEST(0,app.invoice_adjusted_line_obligation_at(line.id,p_as_of)))
                FROM app.invoice_lines line
                JOIN app.invoices invoice ON invoice.id=line.invoice_id
                WHERE line.authorized_obligation_id=recovery.recovery_obligation_id
                  AND invoice.issued_at<=p_as_of
                  AND NOT (invoice.status='VOID'
                      AND COALESCE((SELECT min(void_event.occurred_at)
                          FROM app.invoice_void_events void_event
                          WHERE void_event.invoice_id=invoice.id),'-infinity')<=p_as_of)),0))::bigint
        FROM app.refund_corrections recovery
        WHERE recovery.id=p_recovery AND recovery.correction_kind='RECOVERED_BY_CHARGE'
    $$;

"""

INTERNAL = ("app.refund_recovery_standing_at(uuid,timestamp with time zone)",)

COUNT = "app.lease_deposit_payback_count_as(uuid,uuid,bigint,boolean)"
COUNT_REPLACEMENTS = (
    (
        "            SELECT correction.occurred_at,0,correction.id,correction.source_balance_effect_usd_cents\n",
        "            SELECT correction.occurred_at,0,correction.id,\n"
        "                -- Sub-slice 10e-2b-4b-1 (owner answer (a) to Q-2026-10-17-125): a recovery\n"
        "                -- counts, at its own time, only what still stands of its charge now, alike\n"
        "                -- for the recovery that undoes another Refund's payout below.\n"
        "                CASE WHEN correction.correction_kind='RECOVERED_BY_CHARGE'\n"
        "                    THEN app.refund_recovery_standing_at(correction.id,'infinity')\n"
        "                    ELSE correction.source_balance_effect_usd_cents END\n",
    ),
    (
        "                    -COALESCE((SELECT sum(correction.source_balance_effect_usd_cents)\n",
        "                    -COALESCE((SELECT sum(CASE WHEN correction.correction_kind='RECOVERED_BY_CHARGE'\n"
        "                            -- Sub-slice 10e-2b-4b-1 (owner answer (a) to Q-2026-10-17-125):\n"
        "                            -- a recovery undoes the payout only as far as its charge stands.\n"
        "                            THEN app.refund_recovery_standing_at(correction.id,'infinity')\n"
        "                            ELSE correction.source_balance_effect_usd_cents END)\n",
    ),
)

PATCHES = ((COUNT, COUNT_REPLACEMENTS),)


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
            raise RuntimeError(f"Pet pay-back recovery standing contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SQL)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Pet pay-back recovery standing migration is forward-only")
