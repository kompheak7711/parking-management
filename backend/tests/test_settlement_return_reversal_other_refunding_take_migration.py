"""Post-settlement correction: a take by another Lease's correction that also paid a Refund from
the returned Credit is undone through the companion (sub-slice 10e-3d-2d-2b-1), and two companion
set-ups of sub-slice 10e-3d-2d-2a's review round 2.

Owner answers (a) to Q-2026-10-13-100 point 2 and Q-2026-10-13-103 point 3. A correction's draw
covers, in order, what it brought back itself, its own return, then the return it names, before any
other return's money, and its records are laid out Refunds first; every Credit Refund writer caps
its Refund by one of those three. So a return's money taken by another Lease's correction that also
paid a Credit Refund sits on that correction's applications, which the companion correction of that
Lease's Settlement undoes: a `REFUND` correction (the committed case in
`test_settlement_return_reversal_companion_migration.py`), a `REFUND_RETURN` with a new Refund and a
held-value Refund (here). A part on such a Refund (no real path through a take found) stays one
open part. Also here: a companion put-back on the other Lease's Initial Rent line (labelled put back
by a correction) and two companions in one reversal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

import test_unpaid_initial_termination_migration as initial_fixture
from property_rental.final_settlement import SettlementCreditStep, SettlementDepositStep
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_deposit_refund_correction_migration import command as refund_command
from test_settlement_deposit_refund_correction_migration import confirm_refund, record_refund
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_held_value_refund_migration import (
    COUNTS,
    confirm_held,
    held_command,
    record_held,
    return_only,
)
from test_settlement_refund_return_migration import (
    available,
    confirm,
    net,
    record,
    return_command,
)
from test_settlement_return_reversal_companion_migration import (
    STATE,
    applications_of,
    charge,
    companion_of,
)
from test_settlement_return_reversal_migration import (
    app_catalog,
    confirm_reversal,
    record_reversal,
    reversal_command,
)
from test_settlement_return_reversal_put_back_migration import APPLICATION, LABEL, open_rent_line
from test_settlement_returned_payment_migration import closed_case
from test_settlement_returned_value_left_migration import counted
from test_settlement_returned_value_other_settlements_migration import (
    OTHER_SETTLEMENT,
    second_lease,
    two_lease_case,
)

REVISION = "20261213_139"
PLACED = "app.settlement_returned_value_placed(uuid,text,uuid,uuid,boolean)"


def refunded_first(url: str) -> tuple[dict[str, Any], UUID, UUID]:
    """The first Lease, closed; a REFUND correction of its Initial Rent line refunds 2,000 of
    released Payment value from a new Credit to the Customer; the case, the Refund and the
    Credit."""
    first = {**closed_case(url), "url": url}
    rent, _ = initial_fixture.rent_line(url, first["initial"])
    [paid] = confirm_refund(first, record_refund(first, refund_command(first, rent, 2_000)))[
        "refunds"
    ]
    refund, credit = UUID(str(paid["id"])), UUID(str(paid["source_customer_credit_id"]))
    assert available(url, credit) == 0
    return first, refund, credit


def credit_pays(lease: dict[str, Any], credit: UUID, line: UUID, from_credit: int) -> UUID:
    """A REFUND_RETURN of the Lease's Settlement Pet Deposit Refund (5,400) lets the Credit pay
    `from_credit` of the line first (DL-032: all the Credit holds), the Pet Deposit as much of the
    rest as it holds, and refunds what the Pet Deposit has left; the correction."""
    url = lease["url"]
    owed = outstanding(url, line)
    from_pet = min(owed - from_credit, 5_400)
    steps: list[Any] = [SettlementCreditStep(credit, LINE, line, from_credit)]
    if from_pet:
        steps.append(SettlementDepositStep(PET_REST, lease["pet"], LINE, line, from_pet))
    if from_pet < 5_400:
        steps.append(settlement_refund(lease, "pet", 5_400 - from_pet))
    result = confirm(
        lease,
        record(
            lease,
            return_command(
                lease,
                pet_refund(lease),
                5_400,
                *steps,
                pet_remainder=STAFF if from_pet else None,
            ),
        ),
    )
    assert (outstanding(url, line), held(url, lease["pet"])) == (owed - from_credit - from_pet, 0)
    return UUID(str(result["settlement_correction"]["id"]))


def test_a_companion_puts_back_another_lease_s_rent_line_payment_on_its_own_line(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent review round 2 set-up (a) of sub-slice 10e-3d-2d-2a: X1 and X3 of the first
    Lease each bring back 300; the second Lease's Initial Rent line is opened after closure and
    its correction lets the Credit pay 600 of it (X1's 300, then X3's) and the Pet Deposit 5,400.
    X1's reversal reverses the 600 whole and puts X3's 300 back on the Rent line through the
    companion: labelled put back by a correction on the payment and its line (owner answer (b)
    to Q-2026-10-13-104), no Rent-first proposal, the second Settlement's, naming the payment it
    restores. The Rent line owes 300 more again, the Credit stays empty; the ledger
    reconciles."""
    url = migrated_database_url
    first, refund, credit = refunded_first(url)
    second = {**second_lease(url, monkeypatch, first["customer"]), "url": url}
    earlier = return_only(first, refund, 300)
    return_only(first, refund, 300)
    rent, owed = open_rent_line(url, second)
    assert owed > 6_000
    taker = credit_pays(second, credit, rent, 600)
    assert (available(url, credit), outstanding(url, rent)) == (0, owed - 6_000)
    [(application, line, amount)] = applications_of(url, taker)
    assert (line, amount) == (rent, 600)
    draft = record_reversal(first, reversal_command(first, earlier))
    result = confirm_reversal(first, draft)
    assert result["credit_application_reversals"] == [] and result["reapplied"] == []
    [named] = result["companions"]
    [undone] = named["credit_application_reversals"]
    [restored] = named["reapplied"]
    assert (undone["credit_application_id"], undone["amount_usd_cents"]) == (application, 600)
    assert (
        restored["invoice_line_id"],
        restored["amount_usd_cents"],
        restored["within_invoice_basis"],
    ) == (str(rent), 300, LABEL)
    assert one(url, APPLICATION, restored["id"]) == (
        LABEL,
        None,
        None,
        second["settlement"],
        "financial.approve",
        LABEL,
        rent,
        300,
        application,
    )
    companion = companion_of(url, draft, second["settlement"])
    assert companion["effects"] == [(undone["id"], None), (None, restored["id"])]
    assert (outstanding(url, rent), available(url, credit), net(url, refund)) == (
        owed - 5_700,
        0,
        1_700,
    )
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_a_reversal_writes_one_companion_for_each_other_lease(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent review round 2 set-up (b) of sub-slice 10e-3d-2d-2a: two more Leases of the
    same Customer close; X1 of the first Lease brings back 600; each other Lease's correction lets
    the Credit pay a 300 charge there. X1's reversal writes two companions, one per
    other Settlement in Settlement id order, each reversing its Lease's 300 payment; drafts and
    corrections grow by three; X1's count is the same from each of the three Settlements before
    the reversal; every record of the reversal and its companions is dated after the later
    companion header; each charge owes 300 again, the Credit ends empty and the Refund's net is
    2,000 again; the ledger reconciles."""
    url = migrated_database_url
    first, refund, credit = refunded_first(url)
    others = [{**second_lease(url, monkeypatch, first["customer"]), "url": url} for _ in range(2)]
    earlier = return_only(first, refund, 600)
    lines = []
    for lease in others:
        line = charge(url, lease, 300)
        credit_pays(lease, credit, line, 300)
        lines.append(line)
    assert available(url, credit) == 0
    expected = {str(earlier): (600, 600, 600, 0)}
    for settlement in [first["settlement"], *(lease["settlement"] for lease in others)]:
        assert counted(url, settlement, "CREDIT", credit) == expected
    before = one(url, COUNTS)
    draft = record_reversal(first, reversal_command(first, earlier))
    result = confirm_reversal(first, draft)
    reversal = UUID(str(result["settlement_correction"]["id"]))
    assert result["credit_application_reversals"] == [] and result["reapplied"] == []
    settlements = sorted(str(lease["settlement"]) for lease in others)
    assert [named["final_settlement_id"] for named in result["companions"]] == settlements
    for named in result["companions"]:
        assert [item["amount_usd_cents"] for item in named["credit_application_reversals"]] == [300]
        assert named["reapplied"] == []
    assert one(url, COUNTS) == (before[0] + 3, before[1] + 3, *before[2:])
    for lease in others:
        companion = companion_of(url, draft, lease["settlement"])
        assert str(companion["header"][1]) == str(lease["settlement"])
    with psycopg.connect(url) as connection:
        [(latest_header,)] = connection.execute(
            "SELECT max(correction.occurred_at) FROM app.settlement_corrections correction "
            "WHERE correction.id = ANY(%s::uuid[])",
            ([named["settlement_correction_id"] for named in result["companions"]],),
        ).fetchall()
        [(earliest_record,)] = connection.execute(
            "SELECT min(written.occurred_at) FROM ("
            "SELECT reversal.occurred_at FROM app.settlement_correction_effects effect "
            "JOIN app.customer_credit_application_reversals reversal "
            "ON reversal.id=effect.credit_application_reversal_id "
            "WHERE effect.settlement_correction_id = ANY(%s::uuid[]) "
            "UNION ALL SELECT returned.occurred_at FROM app.settlement_correction_effects effect "
            "JOIN app.refund_corrections returned ON returned.id=effect.refund_correction_id "
            "WHERE effect.settlement_correction_id = ANY(%s::uuid[])) written",
            (
                [named["settlement_correction_id"] for named in result["companions"]],
                [str(reversal)],
            ),
        ).fetchall()
    assert earliest_record > latest_header
    assert [outstanding(url, line) for line in lines] == [300, 300]
    assert (available(url, credit), net(url, refund)) == (0, 2_000)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def refunded_on_second(url: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The 10e-3d-2d-1 two-Lease case with X0 = 1,500 (the second Lease's correction paid its whole
    1,500 charge from the Credit); then a REFUND correction of the second Lease refunds 400 of
    that charge line from the Credit (it releases the 1,500 payment and writes 1,100 again), so
    the Credit holds nothing; its Refund is `returned_refund`."""
    found = two_lease_case(url, monkeypatch, returned=1_500, credit_paid=1_500)
    second = found["second"]
    [(_, line, _)] = applications_of(url, found["taker"])
    [paid] = confirm_refund(second, record_refund(second, refund_command(second, line, 400)))[
        "refunds"
    ]
    assert available(url, found["credit"]) == 0
    return {**found, "returned_refund": UUID(str(paid["id"]))}


def refund_of(url: str, correction: object) -> UUID:
    """The one Refund a correction paid."""
    [(paid,)] = rows(
        url,
        "SELECT effect.refund_id FROM app.settlement_correction_effects effect "
        "WHERE effect.settlement_correction_id=%s AND effect.refund_id IS NOT NULL",
        correction,
    )
    return UUID(str(paid))


def rows(url: str, statement: str, *parameters: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(statement, parameters).fetchall()


def undone_on_second(found: dict[str, Any], earlier: UUID, taker: UUID, line: UUID) -> None:
    """E's 300 sits on the other Lease's correction's 300 payment of `line`, after its Refund:
    E's source lists that payment (no open part, nothing charged back, one companion) and E's
    reversal reverses it whole through the companion; the line owes 300 again, the Credit stays
    empty, the first Lease's Refund's net is 500; the ledger reconciles."""
    first, second, credit, refund = (
        found["first"],
        found["second"],
        found["credit"],
        found["refund"],
    )
    url = first["url"]
    [(application, applied, amount)] = applications_of(url, taker)
    assert (applied, amount) == (line, 300)
    [source] = one(url, STATE, first["settlement"], earlier)
    assert source["swept_open"] == [] and source["recoveries"] == []
    assert [
        (item["record_kind"], item["record_id"], item["amount_usd_cents"], item["part_usd_cents"])
        for item in source["swept"]
    ] == [("CREDIT_APPLICATION", application, 300, 300)]
    assert [item["final_settlement_id"] for item in source["companions"]] == [
        str(second["settlement"])
    ]
    before = one(url, COUNTS)
    result = confirm_reversal(first, record_reversal(first, reversal_command(first, earlier)))
    assert result["credit_application_reversals"] == [] and result["recoveries"] == []
    [named] = result["companions"]
    assert [
        (item["credit_application_id"], item["amount_usd_cents"])
        for item in named["credit_application_reversals"]
    ] == [(application, 300)]
    assert named["reapplied"] == []
    assert one(url, COUNTS) == (before[0] + 2, before[1] + 2, *before[2:])
    assert (outstanding(url, line), available(url, credit), net(url, refund)) == (300, 0, 500)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_a_take_by_another_lease_s_refund_return_with_a_new_refund_is_undone(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent review round 1 set-up S1: after the second Lease's REFUND correction refunded
    400 from the Credit, X1 of the first Lease brings back 300; a REFUND_RETURN of the second
    Lease records the 400 Refund's return and a new 400 Refund and lets the Credit pay a 300
    charge first. Its draw covers its own return (400) before X1's 300, laid over its Refund
    first, so X1's money sits on the 300 payment: undone through the companion, the new Refund
    untouched (it keeps its net of 400)."""
    url = migrated_database_url
    found = refunded_on_second(url, monkeypatch)
    first, second, credit = found["first"], found["second"], found["credit"]
    earlier = return_only(first, found["refund"], 300)
    line = charge(url, second, 300)
    result = confirm(
        second,
        record(
            second,
            return_command(
                second,
                found["returned_refund"],
                400,
                SettlementCreditStep(credit, LINE, line, 300),
            ),
        ),
    )
    taker = UUID(str(result["settlement_correction"]["id"]))
    new_refund = refund_of(url, taker)
    assert (available(url, credit), outstanding(url, line), net(url, new_refund)) == (0, 0, 400)
    undone_on_second(found, earlier, taker, line)
    assert net(url, new_refund) == 400


def test_a_take_by_another_lease_s_held_value_refund_is_undone(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent review round 1 set-up S2: after the second Lease's REFUND correction refunded
    400 from the Credit, a return-only correction N of the second Lease brings that 400 back and
    X1 of the first Lease brings back 300; a held-value Refund of the second Lease naming N lets
    the Credit pay a 300 charge first and refunds N's 400. Its draw covers the named return (400)
    before X1's 300, laid over its Refund first, so X1's money sits on the 300 payment: undone
    through the companion, N has nothing left from either Settlement and the held-value Refund
    keeps its net of 400."""
    url = migrated_database_url
    found = refunded_on_second(url, monkeypatch)
    first, second, credit = found["first"], found["second"], found["credit"]
    named = return_only(second, found["returned_refund"], 400)
    earlier = return_only(first, found["refund"], 300)
    assert available(url, credit) == 700
    line = charge(url, second, 300)
    result = confirm_held(
        second,
        record_held(
            second, held_command(second, named, SettlementCreditStep(credit, LINE, line, 300))
        ),
    )
    taker = UUID(str(result["settlement_correction"]["id"]))
    held_refund = refund_of(url, taker)
    assert (available(url, credit), outstanding(url, line), net(url, held_refund)) == (0, 0, 400)
    for settlement in (first["settlement"], second["settlement"]):
        assert counted(url, settlement, "CREDIT", credit)[str(named)][3] == 0
    undone_on_second(found, earlier, taker, line)
    assert net(url, held_refund) == 400
    # Review round 2 (independent note): N's left value stays 0 after the reversal too.
    for settlement in (first["settlement"], second["settlement"]):
        assert counted(url, settlement, "CREDIT", credit)[str(named)][3] == 0


TRIGGERS = (
    "SELECT trigger.tgname,trigger.tgenabled FROM pg_catalog.pg_trigger trigger "
    "WHERE trigger.tgrelid='app.settlement_correction_effects'::regclass "
    "AND NOT trigger.tgisinternal ORDER BY trigger.tgname"
)


def test_a_part_on_another_lease_s_refund_stays_one_open_part_refused_first(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Security review round 1: the placed function names a part on a Refund of another
    Settlement's correction as one open OTHER_SETTLEMENT part. No real path places a return's
    money there, so in an owner transaction that is always rolled back the other Lease's REFUND
    correction's link to its release is hidden (it then brought nothing back), so its draw starts
    at 0 and X1's 300 falls on its 200 Refund and 100 of its newest payment: the placed function
    gives the OTHER_SETTLEMENT part (200, named by that correction) and the payment part (100);
    the source holds the open part, the totals still match, and the refusal function refuses the
    whole reversal with the 10e-3d-2d-1 message. Afterwards every trigger and the links are as
    before."""
    url = migrated_database_url
    found = two_lease_case(url, monkeypatch, returned=1_500, credit_paid=1_500)
    first, second, refund, credit = (
        found["first"],
        found["second"],
        found["refund"],
        found["credit"],
    )
    [(_, first_charge, _)] = applications_of(url, found["taker"])
    later = return_only(first, refund, 300)
    second_charge = charge(url, second, 300)
    refunding = UUID(
        str(
            confirm_refund(
                second,
                record_refund(
                    second,
                    refund_command(
                        second,
                        first_charge,
                        200,
                        SettlementCreditStep(credit, LINE, second_charge, 300),
                    ),
                ),
            )["settlement_correction"]["id"]
        )
    )
    [(step, _, _)] = [
        written for written in applications_of(url, refunding) if written[1] == second_charge
    ]
    links = rows(
        url,
        "SELECT id FROM app.settlement_correction_effects WHERE settlement_correction_id=%s "
        "ORDER BY id",
        refunding,
    )
    triggers = rows(url, TRIGGERS)
    with psycopg.connect(url) as connection:
        try:
            # Review rounds 2 and 3: nothing inside this block may open another connection; it
            # would not see this transaction's hidden links (`one` and `rows` read the committed
            # state), and a record or a confirm would wait on the ALTER's lock until the rollback.
            connection.execute("ALTER TABLE app.settlement_correction_effects DISABLE TRIGGER USER")
            connection.execute(
                "DELETE FROM app.settlement_correction_effects WHERE settlement_correction_id=%s "
                "AND credit_application_reversal_id IS NOT NULL",
                (refunding,),
            )
            parts = connection.execute(
                "SELECT record_kind,record_id,part_usd_cents "
                "FROM app.settlement_returned_value_placed(%s,'CREDIT',%s,%s,true) "
                "ORDER BY record_kind",
                (first["settlement"], credit, later),
            ).fetchall()
            assert [(row[0], str(row[1]), row[2]) for row in parts] == [
                ("CREDIT_APPLICATION", step, 100),
                ("OTHER_SETTLEMENT", str(refunding), 200),
            ]
            [(source,)] = connection.execute(STATE, (first["settlement"], later)).fetchall()
            assert [
                (item["kind"], item["record_id"], item["part_usd_cents"])
                for item in source["swept_open"]
            ] == [("OTHER_SETTLEMENT", str(refunding), 200)]
            assert [
                (item["record_kind"], item["record_id"], item["part_usd_cents"])
                for item in source["swept"]
            ] == [("CREDIT_APPLICATION", step, 100)]
            assert (source["swept_usd_cents"], source["swept_undone_usd_cents"]) == (300, 100)
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(
                    "SELECT app.assert_settlement_return_reversal_allowed(%s)", (Jsonb(source),)
                )
            assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
                "55000",
                OTHER_SETTLEMENT,
            )
        finally:
            connection.rollback()
    # Review round 2 (security N2): every trigger is as it was before, compared, not assumed.
    assert rows(url, TRIGGERS) == triggers
    assert (
        rows(
            url,
            "SELECT id FROM app.settlement_correction_effects WHERE settlement_correction_id=%s "
            "ORDER BY id",
            refunding,
        )
        == links
    )


def test_the_other_refunding_take_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Migration 139 changes only the placed function (its body exactly the old one with the
    module's replacements, each anchor found as often as listed; privileges, owner, definer and
    settings kept), adds no function, constraint or trigger, no application role may call the
    placed function, and it is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, PLACED)
            ).fetchone() == (False,), role
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261212_138"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database(
        "settlement_return_reversal_other_refunding_take"
    ) as temporary:
        alembic_command.upgrade(config, "20261212_138")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) == set(before_functions)
    patched = dict(revision.module.PATCHES)
    assert (
        {name for name in before_functions if after_functions[name] != before_functions[name]}
        == set(patched)
        == {PLACED}
    )
    for name, replacements in patched.items():
        assert after_functions[name][1:] == before_functions[name][1:], name
        body = str(before_functions[name][0])
        for anchor, replacement, count in replacements:
            assert body.count(anchor) == count, name
            body = body.replace(anchor, replacement)
        assert after_functions[name][0] == body, name
