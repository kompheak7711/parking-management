"""Keep returned pay-back money out of every Lease Deposit forfeiture (V1-056 sub-slice 10c-2b-6).

Owner answer (a) to Q-2026-10-10-73 and owner answer 4 of 2026-10-12 to the sub-slice 10c-2b-5
report (an approved tightening): returned Pet Refund-review money is the Customer's, so no path
may forfeit it, including the owner-only one-call Lease Deposit disposition. The disposition
insert check refuses an amount above the held money beyond the pay-back value (23514), the same
limit the forfeiture draft's source has used since sub-slice 10c-2b-5.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from deposit_disposition_test_support import disposition_context
from lease_deposit_forfeiture_test_support import record_disposition_as_owner
from property_rental.deposit import DepositInvalidError, RecordDepositDispositionCommand
from property_rental.lease_deposit_forfeiture import LeaseDepositForfeitureInvalidError
from test_credit_migration import actor as refund_actor
from test_deposit_migration import deposit_actor
from test_final_settlement_migration import held, one
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_refund_service_migration import returned
from test_refund_service_migration import service as refunds
from test_settlement_extra_charge_migration import cause
from test_settlement_pet_payback_migration import (
    NOTHING_TO_FORFEIT,
    forfeit,
    forfeited,
    path,
    pet_case,
)

REVISION = "20261125_121"
CHANGED = {"app.validate_lease_deposit_disposition()": "DISPOSITION_CHECK_REPLACEMENTS"}
PAYBACK = ("23514", "Lease Deposit disposition would forfeit returned pay-back money")
ABOVE_HELD = ("23514", "Lease Deposit disposition exceeds held refundable value")
WRITTEN = (
    "SELECT (SELECT count(*) FROM app.deposit_dispositions),"
    "(SELECT count(*) FROM app.lease_deposit_disposition_contexts)"
)


def one_call(case: dict[str, Any], deposit: str, amount: int) -> None:
    """The owner's one-call Lease Deposit disposition of amount, with a fresh context."""
    record_disposition_as_owner(
        case["deposits"],
        RecordDepositDispositionCommand(
            uuid4(),
            uuid4(),
            case[deposit],
            case["lease"],
            amount,
            case["day"],
            "Approved BR-DEP-022 source",
            context=disposition_context(case["url"], case[deposit]),
        ),
        actor=deposit_actor(case["human"], case["prop"]),
    )


def refused_one_call(case: dict[str, Any], deposit: str, amount: int) -> tuple[Any, Any]:
    with pytest.raises(DepositInvalidError) as failure:
        one_call(case, deposit, amount)
    return cause(failure)


def refused_draft(case: dict[str, Any], deposit: str) -> tuple[Any, Any]:
    with pytest.raises(LeaseDepositForfeitureInvalidError) as failure:
        forfeit(case, deposit)
    return cause(failure)


def test_returned_money_in_a_kept_pet_deposit_is_never_forfeited(
    migrated_database_url: str,
) -> None:
    """The Q-2026-10-09-61 shape: a Pet Refund-review Refund pays 15,000 of the 20,000 Pet Deposit
    while the Lease is signed; after the pet noncompliance termination both Deposits are
    forfeited through the draft (the Pet Deposit's 5,000); then 2,000 of the Pet Refund comes
    back, so the kept Pet Deposit holds 2,000 of pay-back money. The forfeiture draft refuses it
    (22023, since sub-slice 10c-2b-5; moved here from the 10d fixture), and the owner's one-call
    disposition is now refused too, for all of it and for 1 cent (23514); nothing is written and
    the Pet Deposit stays on the DL-032 path with its 2,000."""
    url = migrated_database_url
    case = pet_case(url, (("refund", 15_000),))
    forfeit(case, "security")
    forfeit(case, "pet")
    refunds().verify_usd_return(
        case["prop"],
        case["review_refund"],
        returned(2_000),
        actor=refund_actor(case["human"], case["prop"], "refunds.correct"),
    )
    assert (held(url, case["pet"]), path(case, "pet")) == (2_000, ("DL_032", 2_000))
    written = one(url, WRITTEN)
    assert refused_draft(case, "pet") == NOTHING_TO_FORFEIT
    assert refused_one_call(case, "pet", 2_000) == PAYBACK
    assert refused_one_call(case, "pet", 1) == PAYBACK
    assert one(url, WRITTEN) == written
    assert forfeited(case, "pet") == [5_000]
    assert (held(url, case["pet"]), path(case, "pet")) == (2_000, ("DL_032", 2_000))


def test_a_forfeiture_takes_at_most_the_money_beyond_the_payback_value(
    migrated_database_url: str,
) -> None:
    """15,000 of the 20,000 Pet Deposit is refunded and 3,000 comes back before the termination:
    it holds 8,000, 3,000 of it pay-back money. An amount above the whole held value keeps the old
    refusal first (8,001); 5,001 is refused as pay-back money (23514) and nothing is written;
    exactly 5,000 is forfeited by the owner's one-call disposition, after which the Pet Deposit
    holds only its 3,000 of pay-back money, is on the DL-032 path, and the draft refuses it
    (22023). The Security Deposit has no pay-back value, so its draft still forfeits its whole held
    value through the patched check."""
    url = migrated_database_url
    case = pet_case(url, (("refund", 15_000), ("return", 3_000)))
    assert held(url, case["security"]) > 0
    forfeit(case, "security")
    assert held(url, case["security"]) == 0
    assert (held(url, case["pet"]), path(case, "pet")) == (8_000, ("FORFEITURE_REQUIRED", 3_000))
    written = one(url, WRITTEN)
    assert refused_one_call(case, "pet", 8_001) == ABOVE_HELD
    assert refused_one_call(case, "pet", 5_001) == PAYBACK
    assert one(url, WRITTEN) == written
    one_call(case, "pet", 5_000)
    assert forfeited(case, "pet") == [5_000]
    assert (held(url, case["pet"]), path(case, "pet")) == (3_000, ("DL_032", 3_000))
    assert refused_draft(case, "pet") == NOTHING_TO_FORFEIT
    assert refused_one_call(case, "pet", 1) == PAYBACK
    assert forfeited(case, "pet") == [5_000]


def test_the_payback_limit_migration_changes_only_the_disposition_check(
    migrated_database_url: str,
) -> None:
    """The migration patches only the Lease Deposit disposition insert check, its new body exactly
    the old one with the listed replacement, keeping owner, SECURITY DEFINER, settings and
    privileges; it adds no function, table or trigger and is forward-only."""
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT prosecdef,proconfig::text FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure",
            (next(iter(CHANGED)),),
        ).fetchone() == (True, "{search_path=pg_catalog}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261124_120"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            relations = {
                str(row[0])
                for row in connection.execute(
                    "SELECT c.oid::regclass::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
                ).fetchall()
            }
            triggers = {
                f"{row[0]}:{row[1]}:{row[2]}"
                for row in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname,pg_catalog.pg_get_triggerdef(t.oid) "
                    "FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
        return functions, relations, triggers

    with _temporary_migration_database("pet_deposit_payback_limit") as temporary:
        alembic_command.upgrade(config, "20261124_120")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED)
    for function, replacements in CHANGED.items():
        body = str(before_functions[function][0])
        for anchor, replacement in getattr(revision.module, replacements):
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
        assert after_functions[function][1:] == before_functions[function][1:], function
