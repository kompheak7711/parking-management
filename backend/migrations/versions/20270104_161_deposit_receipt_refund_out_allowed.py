# ruff: noqa: E501
"""A receipt into a Deposit whose Refund is out is recorded again: the end of option (d) (V1-056 sub-slice 10e-2b-4e-2b-2b).

BR-DEP-002, BR-DEP-005, BR-DEP-009, DL-053; DB-DEP-002; owner answer to Q-2026-10-18-127: option
(a), and option (d) only until (a) is built. Option (a), a bounced Payment of a Deposit that
another Payment also funded charges back only its shortfall, is built in the return before
closure (sub-slices 10e-2b-4e-1 and 10e-2b-4e-2a), in the RETURNED_PAYMENT correction after
closure (10e-2b-4e-2a and 10e-2b-4e-2b-1) and in the receipt correction after closure
(10e-2b-4e-2b-2a), so option (d) ends.

app.record_lease_deposit_receipt: the option (d) refusal of sub-slice 10e-2b-4d (55000, "The
Deposit has a Refund that is not fully returned; this receipt is not recorded here") is removed;
a comment names its end. Every other check of the writer stays. app.deposit_has_unresolved_refund
stays (other checks read it).

One exact-text patch of an existing function (one replacement, checked to match once); no other
function, table, trigger, constraint or grant changes. A relaxing change.
"""

from alembic import op
from sqlalchemy import text

revision = "20270104_161"
down_revision = "20270103_160"
branch_labels = None
depends_on = None

WRITER = "app.record_lease_deposit_receipt(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,text,text)"
WRITER_REPLACEMENTS = (
    (
        "            -- Sub-slice 10e-2b-4d (owner answer (d) to Q-2026-10-18-127, until option (a) is\n"
        "            -- built): no receipt into a Deposit whose Refund is not fully returned, so a bounced\n"
        "            -- Payment of a Deposit funded by two Payments cannot be put out of reach on purpose.\n"
        "            IF app.deposit_has_unresolved_refund(p_deposit_id) THEN\n"
        "                RAISE EXCEPTION 'The Deposit has a Refund that is not fully returned; this receipt is not recorded here'\n"
        "                    USING ERRCODE='55000'; END IF;\n",
        "            -- Sub-slice 10e-2b-4e-2b-2b (owner answer (a) to Q-2026-10-18-127): the option (d)\n"
        "            -- refusal of a receipt into a Deposit whose Refund is not fully returned (sub-slice\n"
        "            -- 10e-2b-4d) has ended; a bounced Payment of a Deposit that another Payment also\n"
        "            -- funded charges back only its shortfall, before and after closure.\n",
    ),
)

PATCHES = ((WRITER, WRITER_REPLACEMENTS),)


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
            raise RuntimeError(f"Deposit receipt refund-out contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Deposit receipt refund-out migration is forward-only")
