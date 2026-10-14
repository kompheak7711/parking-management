# ruff: noqa: E501
"""A tie in the newest-first order of a correction's payments is broken by write order
(V1-056 sub-slice 10e-3d-2b-3).

BR-SETTLE-008, BR-SETTLE-013, BR-SETTLE-016, DL-032; DB-SETTLE-005; owner answer (a) to
Q-2026-10-14-111 (a financial correction must give the same result every time): within the
newest-first order of one correction's payments from a Credit or a Deposit, a tie in time is broken
by the order the correction wrote them, `app.settlement_correction_effects.effect_sequence` (given
at link time, before the write, the next number of the correction; the higher the newer), then by
the id as before. Every payment these orders rank is a linked effect of its correction (the rests a
Refund correction writes again are linked too, migration 100), so the sequence is always there. A
Deposit payment already ranks by `application_order` before the id; it gains the same tie-break
after `application_order`, so one rule holds for both forms.

Defence in depth: the database already refuses two payments of one source at one time. A Credit
application must be later than every earlier event of its Credit, its other applications included
(`app.validate_credit_application_source`, migration 41), and a Deposit application later than the
Deposit's latest balance event (`app.validate_deposit_application`, migration 86), whose
`application_order` is also unique per Final Settlement. So no stored result changes and no
waiting draft becomes stale in practice; the tie-break makes the order a rule instead of a
consequence of those checks (review round 1).

Relaxing exact-text patches (no refusal is added, no result changes where the times differ):

- `app.settlement_returned_value_placed` (migration 134): the order of a taking correction's
  payments from the source.
- `app.settlement_returned_value_follow` (migration 134): the order of a changing correction's
  payments from the source in the stream it paid out again.
- `app.settlement_return_reversal_source_state` (migrations 125 and 128): the order of the listed
  payments the reversal undoes (the own uses' and, since migration 130, other corrections'
  swept payments) and the newest-first walk that chooses, on the pooled own path, the payments
  reversed whole and the part applied again (sub-slice 10e-3c). A list can hold payments of two or
  more corrections; their effect sequences are compared only when the times tie, which the checks
  above prevent, and the id still decides any tie left.

No writer, lock, grant or table change. A `RETURN_REVERSAL` draft recorded before this migration
whose source now differs is stale at its confirm (P5S02); staff reject it and record it again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261209_135"
down_revision = "20261208_134"
branch_labels = None
depends_on = None

TIE_NOTE = """-- Sub-slice 10e-3d-2b-3 (owner answer (a) to Q-2026-10-14-111): a tie in time is
{indent}-- broken by the order the correction wrote them (its effect sequence), then by the id.
"""


def _note(indent: str) -> str:
    return indent + TIE_NOTE.format(indent=indent)


PLACED = "app.settlement_returned_value_placed(uuid,text,uuid,uuid,boolean)"
PLACED_REPLACEMENTS = (
    (
        """                    ORDER BY application.occurred_at DESC,application.id DESC)
""",
        _note("                    ")
        + """                    ORDER BY application.occurred_at DESC,effects.effect_sequence DESC,
                        application.id DESC)
""",
    ),
    (
        """                    ORDER BY application.occurred_at DESC,application.application_order DESC,
                        application.id DESC)
""",
        """                    ORDER BY application.occurred_at DESC,application.application_order DESC,
                        effects.effect_sequence DESC,application.id DESC)
""",
    ),
)

FOLLOW = "app.settlement_returned_value_follow(uuid,text,uuid,text,uuid,bigint,bigint,uuid)"
FOLLOW_REPLACEMENTS = (
    (
        """                            row_number() OVER (ORDER BY application.occurred_at DESC,application.id DESC)
""",
        _note("                            ")
        + """                            row_number() OVER (ORDER BY application.occurred_at DESC,
                                effect.effect_sequence DESC,application.id DESC)
""",
    ),
    (
        """                            row_number() OVER (ORDER BY application.occurred_at DESC,
                                application.application_order DESC,application.id DESC)
""",
        """                            row_number() OVER (ORDER BY application.occurred_at DESC,
                                application.application_order DESC,effect.effect_sequence DESC,
                                application.id DESC)
""",
    ),
)

CREDIT_SEQUENCE = """(SELECT written.effect_sequence
                            FROM app.settlement_correction_effects written
                            WHERE written.customer_credit_application_id=application.id) DESC"""
DEPOSIT_SEQUENCE = """(SELECT written.effect_sequence
                            FROM app.settlement_correction_effects written
                            WHERE written.deposit_application_id=application.id) DESC"""

SOURCE = "app.settlement_return_reversal_source_state(uuid,uuid)"
SOURCE_REPLACEMENTS = (
    (
        """                    ORDER BY application.occurred_at DESC,application.id DESC),'[]'::jsonb)
""",
        _note("                    ")
        + """                    ORDER BY application.occurred_at DESC,
                        """
        + CREDIT_SEQUENCE
        + """,
                        application.id DESC),'[]'::jsonb)
""",
    ),
    (
        """                    ORDER BY application.occurred_at DESC,application.application_order DESC,
                        application.id DESC),'[]'::jsonb)
""",
        """                    ORDER BY application.occurred_at DESC,application.application_order DESC,
                        """
        + DEPOSIT_SEQUENCE
        + """,
                        application.id DESC),'[]'::jsonb)
""",
    ),
    (
        """                    ORDER BY application.occurred_at DESC,application.id DESC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) AS before_it
""",
        _note("                    ")
        + """                    ORDER BY application.occurred_at DESC,
                        """
        + CREDIT_SEQUENCE
        + """,
                        application.id DESC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) AS before_it
""",
    ),
    (
        """                    ORDER BY application.occurred_at DESC,application.application_order DESC,
                        application.id DESC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)
""",
        """                    ORDER BY application.occurred_at DESC,application.application_order DESC,
                        """
        + DEPOSIT_SEQUENCE
        + """,
                        application.id DESC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)
""",
    ),
)

PATCHES = (
    (PLACED, PLACED_REPLACEMENTS),
    (FOLLOW, FOLLOW_REPLACEMENTS),
    (SOURCE, SOURCE_REPLACEMENTS),
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
            raise RuntimeError(f"Settlement returned value tie-break contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Settlement returned value tie-break migration is forward-only")
