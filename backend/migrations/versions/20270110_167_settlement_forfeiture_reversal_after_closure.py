# ruff: noqa: E501
"""The 6b forfeiture reversal after closure, and the 10h-1 triggers at READ COMMITTED only (V1-056 sub-slice 10h-2).

BR-SETTLE-012, BR-SETTLE-013, BR-DEP-019, BR-AUTH-010, DL-032; DB-SETTLE-005.

- Owner answer 4 to Q-2026-10-06-36 and answer 6 to Q-2026-10-10-69: after a Lease's Final
  Settlement closes, the reversal of a kept Deposit's forfeiture runs only inside a
  FORFEITURE_REVERSAL correction of that Settlement (sub-slice 10d), which follows DL-032. The 6b
  source app.lease_deposit_reversal_source refuses (P5S01) a forfeiture whose governing Lease or
  Deposit's Lease has a closed Final Settlement, so the 6b recorder and confirm refuse and a
  waiting draft stays pending (one exact-text replacement). A new BEFORE INSERT trigger on
  app.deposit_disposition_reversals (internal app.refuse_closed_settlement_forfeiture_reversal, no
  grant) locks the Deposit row, then those Settlement rows FOR SHARE, and refuses (P5S01) a
  reversal that a correction of each such closed Settlement, confirmed in this transaction, does
  not link. Every correction writer links the reversal before it writes it.
- Owner answer (a) to Q-2026-10-19-143: the two 10h-1 triggers refuse (55000) a reversal recorded
  at an isolation level other than READ COMMITTED, as the 8e-3 confirm does, so a snapshot taken
  before a Settlement started cannot miss it (one exact-text replacement each). No app path
  writes a reversal at a stricter level.

Fail-closed refusals the owner approved: one new internal function, one new trigger and three
exact-text replacements; signatures, settings and privileges are kept. No table, column,
constraint or grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20270110_167"
down_revision = "20270109_166"
branch_labels = None
depends_on = None

INTERNAL = ("app.refuse_closed_settlement_forfeiture_reversal()",)
SOURCE = "app.lease_deposit_reversal_source(uuid,uuid)"
ALLOCATION_TRIGGER = "app.refuse_relied_on_allocation_reversal()"
CREDIT_TRIGGER = "app.refuse_relied_on_credit_application_reversal()"

INTERNAL_SQL = """
    -- Owner answer 4 to Q-2026-10-06-36 and answer 6 to Q-2026-10-10-69: after closure a
    -- forfeiture of a Deposit of the Lease is reversed only through a correction of its Final
    -- Settlement confirmed in this transaction, for every writer.
    CREATE FUNCTION app.refuse_closed_settlement_forfeiture_reversal()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_disposition app.deposit_dispositions%ROWTYPE; v_deposit_lease uuid;
        v_settlement uuid;
    BEGIN
        SELECT * INTO v_disposition FROM app.deposit_dispositions
        WHERE id=NEW.deposit_disposition_id;
        -- An unknown forfeiture is refused by the foreign key.
        IF NOT FOUND THEN RETURN NEW; END IF;
        -- The Deposit row the writers already hold first. A Lease forfeiture's governing Lease is
        -- its Deposit's Lease, and the 8e-3 confirm takes each Deposit of the Lease (and its state
        -- guard) before it closes and re-checks its digest after that, so at READ COMMITTED this
        -- statement sees a closure committed during the wait, and a confirm that waits for this
        -- writer finds its draft stale. The closed Settlement rows are then held FOR SHARE (an
        -- open Settlement is not locked, so no deadlock with a running confirm); a REPEATABLE READ
        -- writer fails on the Deposit state guard (40001).
        SELECT deposit.lease_id INTO v_deposit_lease FROM app.deposits deposit
        WHERE deposit.id=v_disposition.deposit_id FOR UPDATE;
        FOR v_settlement IN SELECT settlement.id FROM app.final_settlements settlement
            WHERE settlement.lease_id IN (v_disposition.governing_lease_id,v_deposit_lease)
              AND settlement.closed_at IS NOT NULL
            ORDER BY settlement.id FOR SHARE
        LOOP
            IF app.settlement_correction_linked(v_settlement,'deposit_disposition_reversals',NEW.id)
                IS NOT TRUE
            THEN RAISE EXCEPTION 'A closed Final Settlement changes only through a post-settlement correction'
                USING ERRCODE='P5S01'; END IF;
        END LOOP;
        RETURN NEW;
    END $$;

    -- Before the Deposit balance trigger (b_deposit_balance_source).
    CREATE TRIGGER a0_deposit_disposition_reversals_final_settlement
        BEFORE INSERT ON app.deposit_disposition_reversals
        FOR EACH ROW EXECUTE FUNCTION app.refuse_closed_settlement_forfeiture_reversal();
"""

SOURCE_REPLACEMENTS = (
    (
        "            THEN RAISE EXCEPTION 'The forfeiture is already reversed' USING ERRCODE='22023'; END IF;\n",
        "            THEN RAISE EXCEPTION 'The forfeiture is already reversed' USING ERRCODE='22023'; END IF;\n"
        "            -- Sub-slice 10h-2 (owner answer 4 to Q-2026-10-06-36): after closure the reversal\n"
        "            -- runs only inside a FORFEITURE_REVERSAL correction of that Final Settlement (an\n"
        "            -- already reversed forfeiture keeps its own refusal).\n"
        "            IF EXISTS (SELECT 1 FROM app.final_settlements settlement\n"
        "                WHERE settlement.closed_at IS NOT NULL\n"
        "                  AND settlement.lease_id IN (v_disposition.governing_lease_id,\n"
        "                      (SELECT deposit.lease_id FROM app.deposits deposit\n"
        "                       WHERE deposit.id=v_disposition.deposit_id)))\n"
        "            THEN RAISE EXCEPTION 'The Lease''s Final Settlement is closed; reverse this forfeiture through a correction of that Final Settlement'\n"
        "                USING ERRCODE='P5S01'; END IF;\n",
    ),
)

ISOLATION = (
    "        -- Sub-slice 10h-2 (owner answer (a) to Q-2026-10-19-143): a snapshot older than a\n"
    "        -- Final Settlement's start would not see it, so only READ COMMITTED records a reversal.\n"
    "        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN\n"
    "            RAISE EXCEPTION 'A reversal of a Payment allocation or Credit application is recorded at READ COMMITTED'\n"
    "                USING ERRCODE='55000'; END IF;\n"
)

ALLOCATION_REPLACEMENTS = (
    (
        "    BEGIN\n"
        "        SELECT * INTO v_allocation FROM app.payment_allocations WHERE id=NEW.payment_allocation_id;\n",
        "    BEGIN\n" + ISOLATION + "        SELECT * INTO v_allocation FROM app.payment_allocations "
        "WHERE id=NEW.payment_allocation_id;\n",
    ),
)

CREDIT_REPLACEMENTS = (
    (
        "    BEGIN\n        SELECT * INTO v_application FROM app.customer_credit_applications\n",
        "    BEGIN\n"
        + ISOLATION
        + "        SELECT * INTO v_application FROM app.customer_credit_applications\n",
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


def _replaced(signature: str, replacements: tuple[tuple[str, str], ...]) -> str:
    definition = _definition(signature)
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Settlement forfeiture reversal contract changed: {signature}")
        definition = definition.replace(before, after)
    return definition


def upgrade() -> None:
    op.execute(INTERNAL_SQL)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    # CREATE OR REPLACE keeps each function's identity, owner and privileges.
    op.execute(_replaced(SOURCE, SOURCE_REPLACEMENTS))
    op.execute(_replaced(ALLOCATION_TRIGGER, ALLOCATION_REPLACEMENTS))
    op.execute(_replaced(CREDIT_TRIGGER, CREDIT_REPLACEMENTS))


def downgrade() -> None:
    raise RuntimeError("Settlement forfeiture reversal migration is forward-only")
