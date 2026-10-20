# ruff: noqa: E501
"""The termination time from the database clock, and the termination locks the Lease's Deposits (V1-056 sub-slice 10i-1).

BR-AUDIT-003, BR-LEASE-005, BR-DEP-023, BR-DEP-026; owner answer (a) to Q-2026-10-14-112 point 1
and owner answer (a) to Q-2026-10-18-133.

- app.terminate_lease_with_context: its replay branch no longer compares the saved termination
  time with the call's. The route sends no time any more; the service passes the database's
  statement time, so a retry of the same request carries a new time. The request digest, which
  app.replay_lease_command and this branch still compare, binds the given time (null when the
  database's time is used). A relaxing change; every other comparison stays.
- app.terminate_lease: after the Lease and Unit locks and the version and status checks (review
  round 2), the Lease's Deposits are locked in id order (the Lease-then-Deposit order of the
  closing confirm), before the chronology, context and ground checks. A receipt or a
  required-amount adjustment saved beside a termination waits for it and reads the terminated
  Lease; a termination that comes second waits and its ground reads the committed adjustment.
- Review round 1 (security should-fix 1): the termination time is the start of its statement, and
  its locks come later. When it is the database's own time, a Deposit balance event (a receipt,
  for example) or a required-amount adjustment of the Lease dated after it was saved while the
  termination waited, and the ground would not read it: the termination is refused (40001); a new
  attempt takes a new time and reads it.
- Review round 1 (independent note 3): app.adjust_deposit_required_amount dates its row with
  clock_timestamp() after its Deposit lock, not with its statement time, so an adjustment that
  waited for a termination is dated after it.
- Review round 1 (independent blocker 1): app.record_active_lease_pet_departure locks the Lease
  (FOR KEY SHARE) before its Pet Deposit, the termination's order, so its foreign key to the
  Lease never waits while it holds the Deposit (no deadlock with a termination). A departure that
  waited for a termination reads the terminated Lease and is refused as for any terminated Lease.

Exact-text replacements, each checked to match once; signatures, owners, settings and privileges
are kept. No table, column, trigger, constraint or grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20270114_171"
down_revision = "20270113_170"
branch_labels = None
depends_on = None

WITH_CONTEXT = "app.terminate_lease_with_context(uuid,uuid,text,uuid,uuid,integer,date,timestamp with time zone,text,text,uuid,jsonb)"
TERMINATE = "app.terminate_lease(uuid,uuid,text,uuid,uuid,integer,date,timestamp with time zone,text,text,uuid)"

WITH_CONTEXT_REPLACEMENTS = (
    (
        "                    OR v_saved.actual_termination_date IS DISTINCT FROM p_actual_termination_date\n"
        "                    OR v_saved.occurred_at IS DISTINCT FROM p_occurred_at\n",
        "                    OR v_saved.actual_termination_date IS DISTINCT FROM p_actual_termination_date\n"
        "                    -- Sub-slice 10i-1 (owner answer (a) to Q-2026-10-14-112 point 1): the time\n"
        "                    -- is the database's at each call; the request digest binds the given time.\n",
    ),
)

TERMINATE_REPLACEMENTS = (
    (
        "            IF v_lease.status <> 'SIGNED' THEN\n"
        "                RAISE EXCEPTION 'Only a signed Lease may be terminated' USING ERRCODE = '55000';\n"
        "            END IF;\n",
        "            IF v_lease.status <> 'SIGNED' THEN\n"
        "                RAISE EXCEPTION 'Only a signed Lease may be terminated' USING ERRCODE = '55000';\n"
        "            END IF;\n"
        "            -- Sub-slice 10i-1 (owner answer (a) to Q-2026-10-18-133): the Lease's Deposits after\n"
        "            -- the Lease, in id order (the closing confirm's order), so a receipt or an adjustment\n"
        "            -- saved beside this termination waits for it, and this one reads what came first.\n"
        "            -- Review round 2: after the version and status checks, so a termination that is\n"
        "            -- refused anyway never waits for a Deposit.\n"
        "            PERFORM 1 FROM app.deposits WHERE lease_id = p_lease_id ORDER BY id FOR UPDATE;\n"
        "            -- Review round 1 (security should-fix 1): stamped with the database's time, this\n"
        "            -- termination's time is the start of its statement; a Deposit event or adjustment\n"
        "            -- dated after it was saved while it waited, and the ground would not read it.\n"
        "            IF p_occurred_at = statement_timestamp() AND EXISTS(\n"
        "                SELECT 1 FROM app.deposits AS deposit WHERE deposit.lease_id = p_lease_id\n"
        "                  AND (app.deposit_balance_latest_at(deposit.id) > p_occurred_at\n"
        "                    OR EXISTS(SELECT 1 FROM app.deposit_required_amount_adjustments AS adjustment\n"
        "                        WHERE adjustment.deposit_id = deposit.id\n"
        "                          AND adjustment.occurred_at > p_occurred_at)))\n"
        "            THEN RAISE EXCEPTION 'The Lease''s Deposits changed while this termination waited; record it again'\n"
        "                USING ERRCODE = '40001'; END IF;\n",
    ),
)

ADJUST = "app.adjust_deposit_required_amount(uuid,uuid,uuid,text,uuid,uuid,text,bigint,date,text,text)"

ADJUST_REPLACEMENTS = (
    (
        "                p_effective_date,btrim(p_reason),statement_timestamp(),p_actor_id,p_authorization_reference);\n",
        "                -- Sub-slice 10i-1 review round 1: the time after the Deposit lock, so an adjustment\n"
        "                -- that waited for a termination is dated after it.\n"
        "                p_effective_date,btrim(p_reason),clock_timestamp(),p_actor_id,p_authorization_reference);\n",
    ),
)

DEPARTURE = "app.record_active_lease_pet_departure(uuid,uuid,uuid,text,uuid,uuid,date,text,text)"

DEPARTURE_REPLACEMENTS = (
    (
        "            THEN RAISE EXCEPTION 'Pet departure evidence is invalid' USING ERRCODE='22023'; END IF;\n"
        "            SELECT deposit.lease_id,deposit.pet_approval_id,approval.approved_date,\n",
        "            THEN RAISE EXCEPTION 'Pet departure evidence is invalid' USING ERRCODE='22023'; END IF;\n"
        "            -- Sub-slice 10i-1 review round 1: the Lease before its Pet Deposit, the termination's\n"
        "            -- order, so the departure's foreign key to the Lease never waits while it holds the\n"
        "            -- Deposit.\n"
        "            PERFORM 1 FROM app.leases AS lease JOIN app.deposits AS deposit ON deposit.lease_id=lease.id\n"
        "            WHERE deposit.id=p_deposit_id FOR KEY SHARE OF lease;\n"
        "            SELECT deposit.lease_id,deposit.pet_approval_id,approval.approved_date,\n",
    ),
)

PATCHES = (
    (WITH_CONTEXT, WITH_CONTEXT_REPLACEMENTS),
    (TERMINATE, TERMINATE_REPLACEMENTS),
    (ADJUST, ADJUST_REPLACEMENTS),
    (DEPARTURE, DEPARTURE_REPLACEMENTS),
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
            raise RuntimeError(f"Termination database time contract changed: {signature}")
        definition = definition.replace(before, after)
    return definition


def upgrade() -> None:
    # CREATE OR REPLACE keeps each function's identity, owner, settings and privileges.
    for signature, replacements in PATCHES:
        op.execute(_replaced(signature, replacements))


def downgrade() -> None:
    raise RuntimeError("Termination database time migration is forward-only")
