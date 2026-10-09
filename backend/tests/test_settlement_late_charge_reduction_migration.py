"""Post-settlement correction: CHARGE_REDUCTION of an unpaid Late-payment Charge (V1-056 10c-3a).

Owner answer to Q-2026-10-07-38 (recommendation (a)) and BR-LATE-005 as amended: after the Lease's
Final Settlement is closed, a wrong Late-payment Charge that is still unpaid is reduced only by a
linked Late-payment Charge correction, prepared under final_settlements.prepare and confirmed only
by financial.approve (BR-SETTLE-013, BR-AUTH-010). It never releases paid value: more than the
unpaid rest is refused, and a Charge a Deposit application paid is refused (the paid case is
sub-slice 10c-3b).
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementStaleDraftError,
    SettlementCreditStep,
    SettlementDepositStep,
    SettlementTargetKind,
)
from property_rental.payment_allocation import PostAllocationsCommand
from property_rental.settlement_correction import (
    RecordChargeReductionCorrectionCommand,
    RecordLateChargeReductionCorrectionCommand,
)
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_closed_refusal_migration import close, overdue_case
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_draft_migration import (
    LINE,
    PET_REST,
    STAFF,
    two_signer_case,
)
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_migration import one, preparer
from test_invoice_migration import register_billing_service_principal
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import service as allocations
from test_settlement_correction_migration import approver, settlement_row
from test_settlement_extra_charge_migration import approving, cause, corrections, state

REASON = "The Late-payment Charge used the wrong rate"
RECORD = "app.record_settlement_late_charge_reduction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_late_charge_reduction(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.settlement_late_charge_reduction_input(jsonb)",
    "app.settlement_late_charge_obligation(uuid)",
    "app.settlement_late_charge_reduction_source_state(uuid,uuid)",
    "app.settlement_late_charge_reduction_plan(uuid,uuid,jsonb)",
    "app.settlement_late_charge_reduction_result(uuid)",
)
CHANGED = {
    "app.confirm_settlement_charge_reduction(uuid,uuid,uuid,text)": "LINE_CONFIRM_REPLACEMENTS"
}
RELEASES_PAID = "The charge reduction would release paid value"
NOT_OPEN = "The reduced Late-payment Charge is not an open obligation of this Final Settlement"
NOT_OURS = "The reduced Late-payment Charge is not a Charge of this Final Settlement"


def closed_overdue_case(url: str) -> dict[str, Any]:
    """The overdue Lease of sub-slice 8e-1 with its unpaid Late-payment Charge, its Final
    Settlement closed; a correction approver is ready."""
    case = {**overdue_case(url), "url": url}
    close(url, case["human"], case["settlement"])
    case["person"] = approver(url)
    return case


def charge_amount(url: str, charge: object) -> int:
    return int(one(url, "SELECT app.settlement_late_charge_obligation(%s)", charge)[0])


def unpaid(url: str, charge: object) -> int:
    return int(
        one(
            url,
            "SELECT app.settlement_late_charge_obligation(%s)-(app.late_payment_charge_application_"
            "summary(%s)->>'active_total_usd_cents')::bigint",
            charge,
            charge,
        )[0]
    )


def charge_corrections(url: str, charge: object) -> int:
    return int(
        one(
            url,
            "SELECT count(*) FROM app.late_payment_charge_corrections "
            "WHERE late_payment_charge_id=%s",
            charge,
        )[0]
    )


def command(
    case: dict[str, Any], amount: int, **changes: Any
) -> RecordLateChargeReductionCorrectionCommand:
    return replace(
        RecordLateChargeReductionCorrectionCommand(
            uuid4(), case["settlement"], case["charge"], amount, REASON
        ),
        **changes,
    )


def record(case: dict[str, Any], reduction: RecordLateChargeReductionCorrectionCommand) -> UUID:
    found = corrections().record_late_charge_reduction(
        case["prop"], reduction, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def confirm(case: dict[str, Any], draft: UUID) -> dict[str, Any]:
    return corrections().confirm_late_charge_reduction(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )


def pay_charge(case: dict[str, Any], amount: int) -> None:
    """A Payment allocated directly to the Charge after closure (owner answer 7 to
    Q-2026-10-05-20: the Customer can still pay)."""
    with psycopg.connect(case["url"]) as connection:
        payment = seed_payment(
            connection,
            actor_id=case["human"],
            property_id=case["prop"],
            customer_id=case["customer"],
            amount=amount,
        )
    allocations().post(
        case["prop"],
        payment,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DIRECT_CHARGE",
                "late_payment_charge_id": str(case["charge"]),
                "amount_usd_cents": amount,
            },
        ),
        actor=allocation_actor(case["human"], case["prop"]),
    )


def test_an_unpaid_late_payment_charge_is_reduced_then_reversed_after_closure(
    migrated_database_url: str,
) -> None:
    """Staff record a reduction of the unpaid Charge as a draft with no effect; Staff cannot
    confirm it; the approver's confirm writes one linked REDUCTION (financial.approve, the draft's
    reason, the previous and resulting obligation) and its audit; an exact repeat replays. A second
    correction of the whole rest writes the CHARGE_REVERSAL; after it the Charge is terminal and a
    further correction is refused. The Settlement row is unchanged and the ledger reconciles."""
    url = migrated_database_url
    case = closed_overdue_case(url)
    charge, customer = case["charge"], case["customer"]
    original = charge_amount(url, charge)
    assert original > 1_000
    before = settlement_row(url, case["settlement"])
    draft = record(case, command(case, 1_000))
    assert (state(url, draft), charge_corrections(url, charge)) == ("PENDING", 0)
    assert one(
        url,
        "SELECT payload->>'variant',payload->>'target_kind',payload->'reduction' "
        "FROM app.financial_drafts WHERE id=%s",
        draft,
    ) == (
        "CHARGE_REDUCTION",
        "LATE_PAYMENT_CHARGE",
        {"late_payment_charge_id": str(charge), "amount_usd_cents": 1_000},
    )
    with pytest.raises(FinalSettlementAuthorizationError):
        corrections().confirm_late_charge_reduction(
            case["prop"], draft, actor=preparer(case["human"], case["prop"])
        )
    result = confirm(case, draft)
    reduced = result["late_payment_charge_correction"]
    assert (
        reduced["correction_kind"],
        reduced["amount_usd_cents"],
        reduced["previous_obligation_usd_cents"],
        reduced["resulting_obligation_usd_cents"],
        reduced["reason"],
        reduced["authorization_reference"],
        reduced["actor_id"],
    ) == (
        "REDUCTION",
        1_000,
        original,
        original - 1_000,
        REASON,
        "financial.approve",
        str(case["person"]),
    )
    correction = result["settlement_correction"]["id"]
    assert one(
        url,
        "SELECT count(*),count(late_payment_charge_correction_id) "
        "FROM app.settlement_correction_effects WHERE settlement_correction_id=%s",
        correction,
    ) == (1, 1)
    assert one(
        url,
        "SELECT count(*) FROM app.audit_events WHERE correlation_id=%s AND action IN "
        "('late_payment.charge_corrected','final_settlement.correction.confirmed')",
        correction,
    ) == (2,)
    assert confirm(case, draft) == result
    assert (charge_amount(url, charge), unpaid(url, charge)) == (original - 1_000, original - 1_000)
    reversed_ = confirm(case, record(case, command(case, original - 1_000)))
    assert (
        reversed_["late_payment_charge_correction"]["correction_kind"],
        reversed_["late_payment_charge_correction"]["resulting_obligation_usd_cents"],
    ) == ("CHARGE_REVERSAL", 0)
    with pytest.raises(FinalSettlementConflictError) as terminal:
        record(case, command(case, 1))
    assert cause(terminal) == ("55000", NOT_OPEN)
    assert (charge_amount(url, charge), charge_corrections(url, charge)) == (0, 2)
    assert settlement_row(url, case["settlement"]) == before
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_partly_paid_charge_is_reduced_only_within_its_unpaid_rest(
    migrated_database_url: str,
) -> None:
    """The Customer pays part of the Charge after closure. A reduction of more than the unpaid rest
    is refused and writes nothing (releasing paid value is a REFUND); a draft whose Charge changes
    (another Payment) is stale and stays pending, and it first waits for the Lease row or the
    Charge row another session holds, which shows that the confirm locks both before its stale
    check; a reduction of the whole unpaid rest is a REDUCTION, not a reversal, because the Charge
    keeps its paid part."""
    url = migrated_database_url
    case = closed_overdue_case(url)
    charge = case["charge"]
    original = charge_amount(url, charge)
    paid = original // 4
    pay_charge(case, paid)
    rest = original - paid
    assert unpaid(url, charge) == rest
    drafts = int(one(url, "SELECT count(*) FROM app.financial_drafts")[0])
    with pytest.raises(FinalSettlementConflictError) as too_much:
        record(case, command(case, rest + 1))
    assert cause(too_much) == ("55000", RELEASES_PAID)
    assert int(one(url, "SELECT count(*) FROM app.financial_drafts")[0]) == drafts
    stale = record(case, command(case, rest))
    pay_charge(case, 1)
    # Review round 1: the confirm locks the Lease row and the Charge row before its stale check,
    # so a Payment or Credit on the Charge commits before or waits, and the unpaid rest cannot
    # change between the check and the write. While another session holds either row, the stale
    # draft waits for it (lock_timeout, 55P03) instead of being reported stale at once.
    lease = one(url, "SELECT lease_id FROM app.final_settlements WHERE id=%s", case["settlement"])[
        0
    ]
    for table, row in (("leases", lease), ("late_payment_charges", charge)):
        with psycopg.connect(url) as holding:
            holding.execute(f"SELECT 1 FROM app.{table} WHERE id=%s FOR UPDATE", (row,))
            with (
                pytest.raises(psycopg.errors.LockNotAvailable),
                psycopg.connect(make_conninfo(url, connect_timeout=10)) as waiting,
            ):
                waiting.execute("SET lock_timeout='1s'")
                waiting.execute(
                    f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
                    (case["prop"], case["person"], stale),
                )
            holding.rollback()
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm(case, stale)
    assert (state(url, stale), charge_corrections(url, charge)) == ("PENDING", 0)
    result = confirm(case, record(case, command(case, rest - 1)))
    assert (
        result["late_payment_charge_correction"]["correction_kind"],
        result["late_payment_charge_correction"]["resulting_obligation_usd_cents"],
    ) == ("REDUCTION", paid + 1)
    assert (charge_amount(url, charge), unpaid(url, charge)) == (paid + 1, 0)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_charge_a_deposit_paid_or_of_another_lease_is_refused(
    migrated_database_url: str,
) -> None:
    """8a-1, as the Invoice-line form: on a really closed two-Signer Settlement whose Pet Deposit
    paid the Late-payment Charge, a reduction of that Charge is refused (the paid case is sub-slice
    10c-3b). A Charge of another Lease named on this Settlement is not found (P0002). Nothing is
    written."""
    url = migrated_database_url
    case = {**two_signer_case(url, overdue_rent=True), "url": url}
    pet, charge = case["pet"], case["charge"]
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
                SettlementDepositStep(
                    PET_REST, pet, SettlementTargetKind.LATE_PAYMENT_CHARGE, charge, 8_000
                ),
                SettlementDepositStep(PET_REST, pet, LINE, case["rent_line"], 12_000),
            ),
            pet_remainder=STAFF,
        ),
    )
    case["person"] = approver(url)
    other = closed_overdue_case(url)
    drafts = int(one(url, "SELECT count(*) FROM app.financial_drafts")[0])
    with pytest.raises(FinalSettlementConflictError) as deposit_paid:
        record(case, command(case, 1))
    assert cause(deposit_paid) == (
        "55000",
        "A Deposit application paid this obligation at Final Settlement",
    )
    with pytest.raises(FinalSettlementNotFoundError) as elsewhere:
        record(case, command(case, 1, late_payment_charge_id=other["charge"]))
    assert cause(elsewhere) == ("P0002", NOT_OURS)
    assert int(one(url, "SELECT count(*) FROM app.financial_drafts")[0]) == drafts
    assert (charge_corrections(url, charge), charge_corrections(url, other["charge"])) == (0, 0)


def test_the_late_charge_reduction_guards_and_the_two_confirms_take_only_their_own_drafts(
    migrated_database_url: str,
) -> None:
    """The database guards: malformed input 22023; the recorder takes only
    final_settlements.prepare and the confirm only financial.approve (42501); a reused key P5205
    and an exact repeat replays; a service identity that is not a person cannot confirm (P4506);
    the confirm runs only at READ COMMITTED (55000). The Invoice-line confirm refuses a Charge
    draft and the Charge confirm an Invoice-line draft (not found), pending and, on the replay
    path, confirmed. Nothing of a refused call is written."""
    url = migrated_database_url
    case = closed_overdue_case(url)
    prop, human = case["prop"], case["human"]
    drafts = int(one(url, "SELECT count(*) FROM app.financial_drafts")[0])
    good = command(case, 500).reduction()
    for malformed in (
        {**good, "surprise": True},
        {"late_payment_charge_id": str(case["charge"])},
        {**good, "late_payment_charge_id": "not-a-uuid"},
        {**good, "amount_usd_cents": 0},
        {**good, "amount_usd_cents": "500"},
        {**good, "amount_usd_cents": 5.5},
        {**good, "amount_usd_cents": 9_000_000_000_000_001},
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,'final_settlements.prepare')",
                (prop, human, uuid4(), case["settlement"], Jsonb(malformed), REASON),
            )
        assert refused.value.sqlstate == "22023", malformed
    for authorization in ("financial.approve", "late_payment.charge_correction", None):
        with pytest.raises(psycopg.Error) as recorder, psycopg.connect(url) as connection:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,%s)",
                (prop, human, uuid4(), case["settlement"], Jsonb(good), REASON, authorization),
            )
        assert recorder.value.sqlstate == "42501", authorization
    assert int(one(url, "SELECT count(*) FROM app.financial_drafts")[0]) == drafts
    reused = command(case, 500)
    draft = record(case, reused)
    assert record(case, reused) == draft
    with pytest.raises(FinalSettlementKeyReused):
        record(case, replace(reused, amount_usd_cents=400))
    with pytest.raises(psycopg.Error) as staff, psycopg.connect(url) as connection:
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'final_settlements.prepare')",
            (prop, case["person"], draft),
        )
    assert staff.value.sqlstate == "42501"
    with psycopg.connect(url) as connection:
        machine = register_billing_service_principal(connection, property_id=prop, created_by=human)
    with pytest.raises(FinalSettlementAuthorizationError) as not_a_person:
        corrections().confirm_late_charge_reduction(prop, draft, actor=approving(machine, prop))
    assert cause(not_a_person)[0] == "P4506"
    with pytest.raises(psycopg.Error) as isolation, psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
            (prop, case["person"], draft),
        )
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "A post-settlement correction is confirmed at READ COMMITTED",
    )
    with pytest.raises(FinalSettlementNotFoundError) as line_confirm:
        corrections().confirm_charge_reduction(prop, draft, actor=approving(case["person"], prop))
    assert cause(line_confirm) == ("P0002", "Post-settlement correction draft was not found")
    line = UUID(
        str(one(url, "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", case["undecided"])[0])
    )
    line_draft = UUID(
        str(
            corrections().record_charge_reduction(
                prop,
                RecordChargeReductionCorrectionCommand(
                    uuid4(), case["settlement"], case["undecided"], line, 100, REASON
                ),
                actor=preparer(human, prop),
            )["draft_id"]
        )
    )
    with pytest.raises(FinalSettlementNotFoundError) as charge_confirm:
        confirm(case, line_draft)
    assert cause(charge_confirm) == ("P0002", "Post-settlement correction draft was not found")
    assert (state(url, draft), state(url, line_draft), charge_corrections(url, case["charge"])) == (
        "PENDING",
        "PENDING",
        0,
    )
    result = confirm(case, draft)
    assert result["late_payment_charge_correction"]["amount_usd_cents"] == 500
    # Review round 1: the replay path keeps the two forms apart too. The same approver's confirmed
    # Charge draft is not found by the Invoice-line confirm, and a confirmed Invoice-line draft is
    # not found by the Charge confirm; nothing more is written.
    with pytest.raises(FinalSettlementNotFoundError) as line_replay:
        corrections().confirm_charge_reduction(prop, draft, actor=approving(case["person"], prop))
    assert cause(line_replay) == ("P0002", "Post-settlement correction draft was not found")
    line_result = corrections().confirm_charge_reduction(
        prop, line_draft, actor=approving(case["person"], prop)
    )
    assert cast(dict[str, Any], line_result["invoice_adjustment"])["amount_usd_cents"] == 100
    with pytest.raises(FinalSettlementNotFoundError) as charge_replay:
        confirm(case, line_draft)
    assert cause(charge_replay) == ("P0002", "Post-settlement correction draft was not found")
    assert confirm(case, draft) == result
    assert charge_corrections(url, case["charge"]) == 1


def test_late_charge_reduction_functions_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the financial role records and confirms; no role calls the internal functions; no new
    function has a time limit (BR-SETTLE-013); the migration adds only its functions, changes
    only the Invoice-line confirm (its new body exactly the old one with its replacements,
    privileges, owner, SECURITY DEFINER and settings kept) and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (RECORD, CONFIRM, *INTERNAL):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (role == "prm_financial" and function in (RECORD, CONFIRM),), (
                    function,
                    role,
                )
    # BR-SETTLE-013, no time limit (review round 1): no age check and no interval other than the
    # chronology step after the Charge's latest correction.
    for function in (RECORD, CONFIRM, *INTERNAL):
        source = str(
            one(url, "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure", function)[
                0
            ]
        )
        assert "age(" not in source, function
        assert set(re.findall(r"interval '([^']*)'", source)) <= {"1 microsecond"}, function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("20261115_111")
    assert revision is not None and revision.down_revision == "20261114_110"
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
                f"{row[0]}:{row[1]}"
                for row in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
        return functions, relations, triggers

    with _temporary_migration_database("settlement_late_charge_reduction") as temporary:
        alembic_command.upgrade(config, "20261114_110")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261115_111")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED)
    for function, replacements in CHANGED.items():
        body = str(before_functions[function][0])
        for anchor, replacement in getattr(revision.module, replacements):
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
        assert after_functions[function][1:] == before_functions[function][1:], function
