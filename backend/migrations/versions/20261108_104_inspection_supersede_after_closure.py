# ruff: noqa: E501
"""Move-out inspection supersede refused after closure (V1-056 sub-slice 10c-2a-4).

BR-MOVEOUT-006, BR-SETTLE-012, BR-SETTLE-013; owner answer 2 to Q-2026-10-07-44 (approved
tightening) and the owner answer to Q-2026-10-08-49 (option (a)):

- Once a Lease's Final Settlement is closed, every supersede of a move-out inspection on that Lease
  is refused (P5S01, a conflict, as the other refusals after closure), before anything is written.
  The inspection the closed Settlement relied on never changes, so no line it paid changes its pet
  classification. A wrong finding on it is fixed only by a post-settlement correction.
- Damage found after closure is recorded as a new inspection that supersedes nothing; it is not
  checked here. Known limit: a mistake in such an inspection cannot be fixed by a supersede either;
  the wrong finding is simply not billed, because billing needs a confirmed correction.
- The inspection command and its insert trigger read the Lease's Final Settlement row FOR SHARE
  (as the 8e-1 refusal reads it) after the Lease row lock. The Settlement confirm, the only writer
  of closed_at, locks the Lease row FOR UPDATE before it closes the Settlement, so a supersede that
  waited while the Settlement closed reads the closure at READ COMMITTED.
- A supersede runs only at READ COMMITTED (55000 otherwise, before and after closure; owner answer
  to Q-2026-10-08-51), as the Settlement confirm and the correction confirms require: a REPEATABLE
  READ or SERIALIZABLE snapshot older than the Settlement's start would not see the Settlement row,
  and the Lease row lock raises nothing because the start and the confirm never change that row.
- The exact-repeat replay stays first: it writes nothing.
"""

from alembic import op
from sqlalchemy import text

revision = "20261108_104"
down_revision = "20261107_103"
branch_labels = None
depends_on = None

REFUSAL = (
    "                -- Sub-slice 10c-2a-4 (owner answer to Q-2026-10-08-51): a supersede runs only at\n"
    "                -- READ COMMITTED, before and after closure; an older snapshot could miss the\n"
    "                -- Settlement row and so its closure.\n"
    "                IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN\n"
    "                    RAISE EXCEPTION 'A move-out inspection is superseded only at READ COMMITTED'\n"
    "                        USING ERRCODE='55000'; END IF;\n"
    "                -- Sub-slice 10c-2a-4 (owner answer 2 to Q-2026-10-07-44, answer to\n"
    "                -- Q-2026-10-08-49): once the Lease's Final Settlement is closed, no inspection\n"
    "                -- on that Lease is superseded. The Settlement row is read FOR SHARE after the\n"
    "                -- Lease row lock; the confirm locks the Lease row before it closes the Settlement.\n"
    "                SELECT settlement.closed_at INTO v_closed FROM app.final_settlements settlement\n"
    "                WHERE settlement.lease_id={lease} FOR SHARE;\n"
    "                IF v_closed IS NOT NULL THEN\n"
    "                    RAISE EXCEPTION 'A move-out inspection of a Lease with a closed Final Settlement cannot be superseded'\n"
    "                        USING ERRCODE='P5S01'; END IF;\n"
)

COMMAND = "app.move_out_inspection_record(uuid,uuid,uuid,uuid,text,jsonb,text)"
COMMAND_REPLACEMENTS = (
    (
        "        DECLARE v_previous jsonb; v_result jsonb; v_response jsonb; v_audit uuid;\n",
        "        DECLARE v_previous jsonb; v_result jsonb; v_response jsonb; v_audit uuid; v_closed timestamptz;\n",
    ),
    (
        "                IF EXISTS(SELECT 1 FROM app.move_out_inspections WHERE supersedes_inspection_id=v_supersedes)\n"
        "                THEN RAISE EXCEPTION 'Inspection correction source changed' USING ERRCODE='P5M03'; END IF;\n"
        "            END IF;\n",
        "                IF EXISTS(SELECT 1 FROM app.move_out_inspections WHERE supersedes_inspection_id=v_supersedes)\n"
        "                THEN RAISE EXCEPTION 'Inspection correction source changed' USING ERRCODE='P5M03'; END IF;\n"
        + REFUSAL.format(lease="p_lease")
        + "            END IF;\n",
    ),
)

SOURCE = "app.validate_move_out_inspection_source()"
SOURCE_REPLACEMENTS = (
    (
        "        DECLARE v_lease app.leases%ROWTYPE; v_prior app.move_out_inspections%ROWTYPE; v_timezone text;\n",
        "        DECLARE v_lease app.leases%ROWTYPE; v_prior app.move_out_inspections%ROWTYPE; v_timezone text;\n"
        "        DECLARE v_closed timestamptz;\n",
    ),
    (
        "                THEN RAISE EXCEPTION 'Inspection correction source is invalid' USING ERRCODE='23514'; END IF;\n"
        "            END IF;\n",
        "                THEN RAISE EXCEPTION 'Inspection correction source is invalid' USING ERRCODE='23514'; END IF;\n"
        + REFUSAL.format(lease="NEW.lease_id")
        + "            END IF;\n",
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
            raise RuntimeError(f"Move-out inspection source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    _patch(COMMAND, COMMAND_REPLACEMENTS)
    _patch(SOURCE, SOURCE_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("Inspection supersede refusal after closure is forward-only")
