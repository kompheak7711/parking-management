# ruff: noqa: E501
"""Finishing a Billing Run attempt locks the run before the attempt (V1-060, DL-071 answer 13).

The flaky test `test_billing_run_migration.py::test_pending_future_basis_is_preserved_without_utility_invoice`
(about 1 run in 6, on the slice 12 list) is a real lock-order deadlock: two executions of the
same retryable run at once. `app.finish_scheduled_billing_attempt` locked the attempt row and
then updated the run row, while `app.start_scheduled_billing_run` (and both record-item
functions) lock the run row first and the attempt row second. Now the finish function locks the
run row first too, so the second execution waits for the first instead of a deadlock. Lock order
only: no rule, amount or answer changes. One exact-text replacement (checked to match once); same
signature, settings and privileges.
"""

from alembic import op
from sqlalchemy import text

revision = "20270220_208"
down_revision = "20270219_207"
branch_labels = None
depends_on = None

FINISH = "app.finish_scheduled_billing_attempt(uuid,uuid)"

FINISH_REPLACEMENTS = (
    (
        "        BEGIN\n"
        "            SELECT * INTO STRICT v_attempt FROM app.billing_run_attempts\n"
        "            WHERE id=p_attempt_id AND billing_run_id=p_run_id FOR UPDATE;\n",
        "        BEGIN\n"
        "            -- V1-060: the run row first, then the attempt row, as every other writer.\n"
        "            PERFORM 1 FROM app.billing_runs WHERE id=p_run_id FOR UPDATE;\n"
        "            SELECT * INTO STRICT v_attempt FROM app.billing_run_attempts\n"
        "            WHERE id=p_attempt_id AND billing_run_id=p_run_id FOR UPDATE;\n",
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
            raise RuntimeError(f"V1-060 billing lock order contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    _patch(FINISH, FINISH_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("V1-060 billing lock order migration is forward-only")
