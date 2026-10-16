# ruff: noqa: E501
"""A charge reduction of the unpaid rest of a partly Deposit-paid obligation (V1-056 sub-slice 10c-3c-2).

BR-SETTLE-013, BR-SETTLE-012, BR-LATE-005, BR-AUTH-010, DL-032; DB-SETTLE-005, DB-DEP-005; owner
answer (a) to Q-2026-10-10-70 (after the allow-function hardening of sub-slice 10c-3c-1):

- A `CHARGE_REDUCTION` correction (the Invoice-line form of migration 20261103_99 and the
  Late-payment Charge form of migration 20261115_111) accepts an obligation that a Deposit
  application partly paid, within its unpaid rest: the current obligation less every active
  application, Deposit applications not reversed included. Nothing is released, no money moves and
  the Deposit application stays.
- `app.settlement_charge_reduction_plan` and `app.settlement_late_charge_reduction_plan` (exact-text
  patches): the Deposit refusal no longer applies while the obligation has an unpaid rest. An
  obligation that an active Deposit application paid and that has no unpaid rest keeps it (owner
  answer (a) to Q-2026-10-11-80: the 10c-3a refusal test of a Charge the Pet Deposit paid in full
  does not change). The unpaid-rest check that follows already counts every active Deposit
  application, so a reduction above the rest stays refused ("The charge reduction would release
  paid value"). The confirms run the patched plan again under their locks and write
  as before; their linked Adjustment or Charge correction passes the 8a-1 refusal only through the
  hardened allow functions (its reference or correlation names the correction, and the correction's
  draft names exactly that obligation).

No table, column, constraint, trigger, lock or grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20261218_144"
down_revision = "20261217_143"
branch_labels = None
depends_on = None

LINE_PLAN = "app.settlement_charge_reduction_plan(uuid,uuid,jsonb)"
LINE_PLAN_REPLACEMENTS = (
    (
        "        -- 8a-1: an Invoice that a Deposit application paid takes no Adjustment (until 10c-2).\n"
        "        IF EXISTS(SELECT 1 FROM app.deposit_applications application\n"
        "            WHERE application.invoice_id=v_invoice.id)\n"
        "        THEN RAISE EXCEPTION 'A Deposit application paid this obligation at Final Settlement'\n"
        "            USING ERRCODE='55000'; END IF;\n",
        "        -- Sub-slice 10c-3c-2 (owner answer (a) to Q-2026-10-10-70): a Deposit application on\n"
        "        -- the Invoice no longer refuses a reduction within the line's unpaid rest. The unpaid\n"
        "        -- rest below counts every active application, Deposit applications not reversed\n"
        "        -- included, so nothing is released and the Deposit application stays; the linked\n"
        "        -- Adjustment passes the 8a-1 refusal only through the hardened allow function\n"
        "        -- (sub-slice 10c-3c-1). A line that an active Deposit application paid and that has no\n"
        "        -- unpaid rest keeps this refusal (owner answer (a) to Q-2026-10-11-80).\n"
        "        IF app.invoice_line_deposit_value_at(v_line,'infinity'::timestamptz)>0\n"
        "            AND app.invoice_line_outstanding(v_line)<=0\n"
        "        THEN RAISE EXCEPTION 'A Deposit application paid this obligation at Final Settlement'\n"
        "            USING ERRCODE='55000'; END IF;\n",
        1,
    ),
)

CHARGE_PLAN = "app.settlement_late_charge_reduction_plan(uuid,uuid,jsonb)"
CHARGE_PLAN_REPLACEMENTS = (
    (
        "        -- 8a-1: a Charge that a Deposit application paid takes no correction, as the Invoice-line\n"
        "        -- form (the paid case is sub-slice 10c-3b).\n"
        "        IF (v_summary->>'deposit_total_usd_cents')::bigint>0 THEN\n"
        "            RAISE EXCEPTION 'A Deposit application paid this obligation at Final Settlement'\n"
        "                USING ERRCODE='55000'; END IF;\n",
        "        -- Sub-slice 10c-3c-2 (owner answer (a) to Q-2026-10-10-70): a Deposit application on\n"
        "        -- the Charge no longer refuses a reduction within its unpaid rest. The unpaid rest below\n"
        "        -- counts every active application, Deposit applications not reversed included, so\n"
        "        -- nothing is released and the Deposit application stays; the linked Charge correction\n"
        "        -- passes the 8a-1 refusal only through the hardened allow function (sub-slice\n"
        "        -- 10c-3c-1). A Charge that an active Deposit application paid and that has no unpaid\n"
        "        -- rest keeps this refusal (owner answer (a) to Q-2026-10-11-80).\n"
        "        IF (v_summary->>'deposit_total_usd_cents')::bigint>0\n"
        "            AND app.settlement_late_charge_obligation(v_charge.id)\n"
        "                <=(v_summary->>'active_total_usd_cents')::bigint THEN\n"
        "            RAISE EXCEPTION 'A Deposit application paid this obligation at Final Settlement'\n"
        "                USING ERRCODE='55000'; END IF;\n",
        1,
    ),
)

PATCHES = ((LINE_PLAN, LINE_PLAN_REPLACEMENTS), (CHARGE_PLAN, CHARGE_PLAN_REPLACEMENTS))


def _patch(signature: str, replacements: tuple[tuple[str, str, int], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after, count in replacements:
        if definition.count(before) != count:
            raise RuntimeError(f"Deposit-paid charge reduction contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Deposit-paid charge reduction migration is forward-only")
