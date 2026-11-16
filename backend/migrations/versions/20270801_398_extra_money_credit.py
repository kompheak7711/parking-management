"""Extra money becomes Customer Credit at once at Receive payment (D5, DL-235).

Owner (12 Nov 2026, DL-226, D5). Before, money above everything the payer owed waited on the
Receipt until the payer chose Customer Credit or a Refund (BR-PAY-030, BR-CREDIT-002). Now it
becomes the payer's Customer Credit at once; the Customer may ask for a Refund of that Credit
any day (BR-CREDIT-011).

What changes:

- ``app.receive_payment``: after the money pays what was ticked, any money still free on the
  Payment becomes the payer's Customer Credit in the same step, through
  ``app.recognize_customer_credit`` with a key derived from the command's key (so a replay
  never makes it twice). The answer adds ``customer_credit`` (the Credit, or null) and
  ``credit_usd_cents``; ``left_usd_cents`` is what still waits on the Payment.
- When "nothing is owed" cannot be checked at this moment (another person is changing
  Invoices, so the check's short table lock is not free, or a new Invoice arrived after the
  ticks were read), the Payment is still saved and the money waits on the Receipt as before;
  staff keep it as Credit or refund it by hand.

Money waiting on Receipts made before stays as it is. A Payment recorded by another path (the
two-step confirm and allocate commands, another person's money for a named Invoice or Lease)
is not changed. No row is changed or deleted. This migration is forward-only.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule; the rule is the owner's.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270801_398"
down_revision: str | None = "20270731_397"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECEIVE = "app.receive_payment(uuid, uuid, uuid, text, jsonb, jsonb, jsonb)"
RECEIVE_CREDIT = (
    (
        "DECLARE v_post jsonb; v_allocations jsonb; v_seen uuid[]:='{}'; v_id uuid;",
        "DECLARE v_post jsonb; v_allocations jsonb; v_seen uuid[]:='{}'; v_id uuid;\n"
        "        DECLARE v_credit jsonb; v_free bigint;",
        1,
    ),
    (
        "            SELECT COALESCE(jsonb_agg(jsonb_build_object('allocation_id',allocation.id,",
        """            -- D5 (DL-235, BR-PAY-030): money above everything the payer owes becomes
            -- the payer's Customer Credit in the same step, with no question to the payer.
            -- If that cannot be checked now (a short table lock is not free, or something
            -- new is owed), the money waits on the Receipt as before.
            v_free:=app.payment_available_value(v_payment.id);
            IF v_free>0 THEN
                BEGIN
                    v_credit:=app.recognize_customer_credit(p_property_id,v_payment.id,
                        p_actor_id,md5('receive-payment:credit:'||v_scope)::uuid,v_free,
                        'Kept as Customer Credit at once by the rule (BR-PAY-030, DL-235)',
                        'Money above everything owed at Receive payment.');
                EXCEPTION WHEN lock_not_available OR check_violation THEN
                    v_credit:=NULL;
                END;
            END IF;
            SELECT COALESCE(jsonb_agg(jsonb_build_object('allocation_id',allocation.id,""",
        1,
    ),
    (
        "'left_usd_cents',app.payment_available_value(v_payment.id));",
        """'left_usd_cents',app.payment_available_value(v_payment.id),
                'customer_credit',CASE WHEN v_credit IS NOT NULL THEN jsonb_build_object(
                    'id',v_credit->'credit'->'id',
                    'customer_id',v_credit->'credit'->'customer_id',
                    'amount_usd_cents',v_credit->'credit'->'recognized_usd_cents') END,
                'credit_usd_cents',
                    COALESCE((v_credit->'credit'->>'recognized_usd_cents')::bigint,0));""",
        1,
    ),
)


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _changed(signature: str, replacements: tuple[tuple[str, str, int], ...]) -> str:
    definition = _definition(signature)
    for before, after, count in replacements:
        if definition.count(before) != count:
            raise RuntimeError(f"Extra money Credit source contract changed: {signature}: {before}")
        definition = definition.replace(before, after)
    return definition


def _run(sql: str) -> None:
    op.execute(text(sql.replace(":", "\\:")))


def upgrade() -> None:
    _run(_changed(RECEIVE, RECEIVE_CREDIT))


def downgrade() -> None:
    raise RuntimeError("the extra money Credit migration is forward-only")
