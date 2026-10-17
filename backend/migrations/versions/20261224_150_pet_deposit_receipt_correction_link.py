# ruff: noqa: E501
"""A Pet Deposit receipt after closure needs its correction's link (V1-056 sub-slice 10e-2b-3).

BR-SETTLE-012, BR-SETTLE-013; DB-DEP-002, DB-SETTLE-005; owner answer 2 to Q-2026-10-12-89 (an
approved tightening: the receipt table, not only its single internal writer, holds owner rule 3 of
Q-2026-10-12-87) and answer (a) to Q-2026-10-12-90 (the rule applies once the Lease's Final
Settlement is closed; before closure nothing changes).

- app.validate_deposit_receipt: once the Lease's Final Settlement is closed, a Pet Deposit receipt
  of that Lease is refused (P5S01, the message of the 8e-1 refusal) unless a correction of that
  Settlement, confirmed in the current transaction, links it (DB-SETTLE-005 deposit_receipt_id,
  through app.settlement_correction_linked). It is the first check of the Pet Deposit branch,
  after the Payment source trigger, the Deposit row lock and the one-active-receipt check, so the
  closed Settlement is the reason given for every other receipt. The Deposit row is locked first
  (by the earlier balance trigger's app.serialize_deposit_state and again by this function), so
  at READ COMMITTED a closure committed while the receipt waited is read by the check's own
  statement; a REPEATABLE READ or SERIALIZABLE writer whose snapshot is older than the closure
  fails on the Deposit's serialization guard instead (40001). A receipt that holds the lock first
  and commits makes the waiting Final Settlement confirm stale (P5S02).
- The only Pet Deposit receipt writer, app.write_correction_deposit_receipt, links its receipt
  before it inserts it, so it passes. Security Deposit receipts do not change.

One exact-text patch of an existing trigger function (an approved tightening); no new function,
table, trigger, constraint or grant.
"""

from alembic import op
from sqlalchemy import text

revision = "20261224_150"
down_revision = "20261223_149"
branch_labels = None
depends_on = None

RECEIPT = "app.validate_deposit_receipt()"
RECEIPT_REPLACEMENTS = (
    (
        "            ELSE\n"
        "                SELECT approval.approved_at INTO v_accepted_at\n",
        "            ELSE\n"
        "                -- Sub-slice 10e-2b-3 (owner answer 2 to Q-2026-10-12-89 and answer (a) to\n"
        "                -- Q-2026-10-12-90; an approved tightening): once the Lease's Final Settlement\n"
        "                -- is closed, a Pet Deposit receipt of that Lease is written only when a\n"
        "                -- correction of that Settlement, confirmed in this transaction, links it. The\n"
        "                -- Deposit row lock taken above and by the earlier balance trigger comes first,\n"
        "                -- so at READ COMMITTED a closure committed while this receipt waited is read\n"
        "                -- here; a REPEATABLE READ or SERIALIZABLE writer fails on the Deposit's\n"
        "                -- serialization guard instead.\n"
        "                IF EXISTS(SELECT 1 FROM app.final_settlements AS settlement\n"
        "                    WHERE settlement.lease_id=v_deposit.lease_id\n"
        "                      AND settlement.closed_at IS NOT NULL)\n"
        "                    AND app.settlement_correction_linked((SELECT settlement.id\n"
        "                        FROM app.final_settlements AS settlement\n"
        "                        WHERE settlement.lease_id=v_deposit.lease_id\n"
        "                          AND settlement.closed_at IS NOT NULL),'deposit_receipts',NEW.id)\n"
        "                        IS NOT TRUE\n"
        "                THEN RAISE EXCEPTION 'A closed Final Settlement changes only through a post-settlement correction'\n"
        "                    USING ERRCODE='P5S01'; END IF;\n"
        "                SELECT approval.approved_at INTO v_accepted_at\n",
    ),
)

PATCHES = ((RECEIPT, RECEIPT_REPLACEMENTS),)


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
            raise RuntimeError(f"Pet Deposit receipt link contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Pet Deposit receipt link migration is forward-only")
