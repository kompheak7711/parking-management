"""The preview also lists another Settlement's waiting REFUND_RETURN correction draft (V1-056
slice 12d).

Owner answer (a) to Q-2026-10-20-149 (BR-SETTLE-002, BR-SETTLE-013, BR-CREDIT-008; DL-093): a
waiting `REFUND_RETURN` correction draft whose plan overlay gives value back to a Credit held by a
person of another Lease is listed by that other Lease's Final Settlement preview the same way as
a `REFUND` draft (sub-slice 10i-4c). The other Lease's Settlement waits until the draft is
confirmed, rejected or withdrawn; no amount rule changes, only the order.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.final_settlement import SettlementCreditStep, SettlementDepositStep
from test_final_settlement_confirm_migration import BLOCKED
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_draft_migration import (
    LINE,
    PET_FIRST,
    PET_REST,
    SECURITY,
    STAFF,
    refusal,
)
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_preview_credit_step_wait_migration import DRAFT_PARTS, closed, other_lease
from test_settlement_preview_waiting_drafts_migration import (
    SETTLEMENT_DRAFTS,
    blocked_only_by,
    pending,
    ready_again,
    withdraw,
)
from test_settlement_refund_return_migration import (
    available,
    record,
    refunded_case,
    return_command,
)

REVISION = "20270218_206"
PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"


def test_a_waiting_refund_return_that_gives_value_back_to_a_credit_holds_the_other_lease(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Q-149 case on the real path (here K holds no other money, so the draft cannot go
    stale). Customer C's Lease A is closed; a correction Refund of 2,000 from C's Credit K came
    back, and A's REFUND_RETURN correction draft gives the 2,000 back
    to K and refunds it again in cash, with no CUSTOMER_CREDIT step. C's second Lease B is
    terminated. While the draft waits it is B's only blocking issue and B's Settlement draft is
    not recorded (55000, nothing written); A's own preview does not list its own draft. After the
    withdrawal B is ready again and closes; C's other Credit (300, from A's closure) and B's own
    Initial Rent Credit (400) pay B's line first."""
    url = migrated_database_url
    first = refunded_case(url)
    credit, other_credit = first["refund_credit"], first["new_credit"]
    assert available(url, other_credit) == 300
    draft = record(first, return_command(first, first["refund"], 2_000))
    # `other_lease` names B's own Credit: the one with value that is not `other_credit` (K has
    # none until the draft is confirmed).
    second = other_lease(url, monkeypatch, first["customer"], other_credit)
    steps, released = one(url, DRAFT_PARTS, draft)
    assert [step for step in steps if step["kind"] == "CUSTOMER_CREDIT"] == []
    assert released[str(credit)]["add_usd_cents"] == 2_000
    issue: dict[str, object] = {
        "code": "PENDING_DRAFT",
        "draft_id": str(draft),
        "kind": "SETTLEMENT_CORRECTION",
        "variant": "REFUND_RETURN",
    }
    blocked_only_by(second, issue)
    assert pending(second) == [issue]
    assert pending(first) == []
    plan = (
        SettlementCreditStep(second["credit"], LINE, second["other_line"], 400),
        SettlementCreditStep(other_credit, LINE, second["other_line"], 300),
        SettlementDepositStep(PET_FIRST, second["pet"], LINE, second["pet_line"], 12_500),
        SettlementDepositStep(SECURITY, second["security"], LINE, second["other_line"], 10_000),
        SettlementDepositStep(PET_REST, second["pet"], LINE, second["other_line"], 1_800),
        settlement_refund(second, "pet", 5_700),
    )
    before = one(url, SETTLEMENT_DRAFTS)
    assert refusal(record_settlement, second, plan, pet_remainder=STAFF) == ("55000", BLOCKED)
    assert (one(url, SETTLEMENT_DRAFTS), available(url, credit)) == (before, 0)

    withdraw(first, draft, "final_settlements.prepare")
    ready_again(second)
    confirm_settlement(second, record_settlement(second, plan, pet_remainder=STAFF))
    assert closed(url, second)
    assert (available(url, other_credit), outstanding(url, second["other_line"])) == (0, 0)


def test_the_refund_return_wait_migration_changes_only_the_preview_and_is_forward_only(
    migrated_database_url: str,
) -> None:
    """The migration changes only the body of app.final_settlement_preview (owner, privileges,
    definer flag and settings kept), widens the release branch once, adds no function, and is
    forward-only."""
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270217_205"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def functions(database: str) -> dict[str, tuple[Any, ...]]:
        with psycopg.connect(database) as connection:
            return {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }

    with _temporary_migration_database("settlement_preview_refund_return_wait") as temporary:
        alembic_command.upgrade(config, "20270217_205")
        before = functions(temporary)
        alembic_command.upgrade(config, REVISION)
        after = functions(temporary)
    assert set(after) == set(before)
    assert {name for name in before if after[name] != before[name]} == {PREVIEW}
    assert after[PREVIEW][1:] == before[PREVIEW][1:]
    assert str(after[PREVIEW][0]).count("IN ('REFUND','REFUND_RETURN')") == 1
    assert str(before[PREVIEW][0]).count("IN ('REFUND','REFUND_RETURN')") == 0
