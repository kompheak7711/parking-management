# ruff: noqa: E501
"""Keep returned pay-back money out of every Lease Deposit forfeiture (V1-056 sub-slice 10c-2b-6).

BR-DEP-022, DL-032; owner answer (a) to Q-2026-10-10-73 and owner answer 4 of 2026-10-12 to the
sub-slice 10c-2b-5 report (an approved tightening):

- Returned Pet Refund-review money is the Customer's (pay back), so no path may forfeit it,
  including the owner-only one-call Lease Deposit disposition. Since sub-slice 10c-2b-5 the
  forfeiture draft's source takes only the held money beyond the pay-back value; the Lease
  Deposit disposition insert check now enforces the same limit for every writer.
- The held-value check and its message stay first and unchanged; the new check refuses (23514) an
  amount above the held value less `app.lease_deposit_payback_value(deposit)`.

Only the disposition insert check is patched in place; no new function, table or trigger.
"""

from alembic import op
from sqlalchemy import text

revision = "20261125_121"
down_revision = "20261124_120"
branch_labels = None
depends_on = None

DISPOSITION_CHECK = "app.validate_lease_deposit_disposition()"
DISPOSITION_CHECK_REPLACEMENTS = (
    (
        "            IF NEW.amount_usd_cents > v_held THEN\n"
        "                RAISE EXCEPTION 'Lease Deposit disposition exceeds held refundable value'\n"
        "                    USING ERRCODE = '23514';\n"
        "            END IF;\n",
        "            IF NEW.amount_usd_cents > v_held THEN\n"
        "                RAISE EXCEPTION 'Lease Deposit disposition exceeds held refundable value'\n"
        "                    USING ERRCODE = '23514';\n"
        "            END IF;\n"
        "            -- Sub-slice 10c-2b-6 (owner answer (a) to Q-2026-10-10-73 and owner answer 4 of\n"
        "            -- 2026-10-12, approved tightening): returned Pet Refund-review money is the\n"
        "            -- Customer's, so no forfeiture, the owner's one-call disposition included, takes it;\n"
        "            -- at most the held money beyond the pay-back value is forfeited, as the forfeiture\n"
        "            -- draft's source already says.\n"
        "            IF NEW.amount_usd_cents > v_held - app.lease_deposit_payback_value(NEW.deposit_id) THEN\n"
        "                RAISE EXCEPTION 'Lease Deposit disposition would forfeit returned pay-back money'\n"
        "                    USING ERRCODE = '23514';\n"
        "            END IF;\n",
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
            raise RuntimeError(f"Pet Deposit pay-back limit contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    _patch(DISPOSITION_CHECK, DISPOSITION_CHECK_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("Pet Deposit pay-back limit migration is forward-only")
