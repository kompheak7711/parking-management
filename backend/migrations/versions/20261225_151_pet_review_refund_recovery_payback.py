# ruff: noqa: E501
"""A Pet Refund-review Refund recovered by a charge counts as returned (V1-056 sub-slice 10e-2b-4a).

BR-SETTLE-013, BR-SETTLE-008, DL-032, BR-DEP-022, DL-053; DB-DEP-004, DB-REFUND-002; owner answer
(a) to Q-2026-10-17-123: when a Pet Refund-review Refund is recovered by a charge (a
RECOVERED_BY_CHARGE row), what is charged back counts like a verified return of that Refund and
adds to the pay-back count. The Customer must never both pay money back and lose the same money to
a forfeiture.

- The Pet Refund-review part of the running count (sub-slices 10c-2b-5 and 10e-2d) also adds each
  RECOVERED_BY_CHARGE row of such a Refund (the amount charged back; such a row is never reversed).
- The count without payouts (only the receipt correction's own corrected Deposit uses it) also
  adds, at the end, what is still to recover of each Pet Refund-review Refund of the Deposit: the
  receipt correction recovers by a charge every Refund of that Deposit that is not fully returned
  and writes those recoveries after every other event of the Deposit, so the count it records
  equals the count its forfeiture writer and step read after its writes.

- At the same moment and event order an addition to the count comes before a subtraction (the
  existing "returns come first" rule), so a charge-back written at the same instant as a return
  reversal (sub-slice 10e-3d-2c, migration 20261210_136) gives one result whatever the random row ids are; subtractions
  among themselves and additions among themselves give the same result in any order.

One exact-text patch of the internal app.lease_deposit_payback_count_as. For the Customer it is
relaxing (a higher count keeps more returned money as pay-back money; a forfeiture takes less),
and for the same reason the owner-confirmed refusal of a staff choice to forfeit again (owner answer
to Q-2026-10-17-122) applies up to the higher count. The pay-back value, the Deposit path, the
forfeiture source, the forfeiture insert check, the returned-Refund check, the receipt correction's
targets and plan check read the count and follow it unchanged.
"""

from alembic import op
from sqlalchemy import text

revision = "20261225_151"
down_revision = "20261224_150"
branch_labels = None
depends_on = None

COUNT = "app.lease_deposit_payback_count_as(uuid,uuid,bigint,boolean)"
COUNT_REPLACEMENTS = (
    (
        "                      AND returned.verified_return_amount_minor IS NOT NULL))\n",
        "                      AND returned.verified_return_amount_minor IS NOT NULL)\n"
        "                  -- Sub-slice 10e-2b-4a (owner answer (a) to Q-2026-10-17-123): what a charge\n"
        "                  -- recovers of a Pet Refund-review Refund counts like a verified return.\n"
        "                  OR correction.correction_kind='RECOVERED_BY_CHARGE')\n",
    ),
    (
        "            ORDER BY 1,2,3\n",
        "            UNION ALL\n"
        "            -- Sub-slice 10e-2b-4a: without payouts (the receipt correction's own corrected\n"
        "            -- Deposit), what is still to recover of each Pet Refund-review Refund, which that\n"
        "            -- correction charges back after every other event of the Deposit.\n"
        "            SELECT 'infinity'::timestamptz,1,refund.id,\n"
        "                GREATEST(0,app.refund_net_value_at(refund.id,'infinity')\n"
        "                    -CASE WHEN refund.id=p_returned_refund THEN v_returned ELSE 0 END)\n"
        "            FROM app.refunds refund\n"
        "            WHERE refund.source_deposit_id=p_deposit AND refund.pet_refund_review_id IS NOT NULL\n"
        "              AND NOT v_payouts\n"
        "            -- Sub-slice 10e-2b-4a (review round 1, security): at the same moment and order\n"
        "            -- an addition comes before a subtraction (returns come first), so a charge-back\n"
        "            -- written at the same instant as a return reversal never depends on row ids.\n"
        "            ORDER BY 1,2,4 DESC,3\n",
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
            raise RuntimeError(f"Pet Refund-review recovery pay-back contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Pet Refund-review recovery pay-back migration is forward-only")
