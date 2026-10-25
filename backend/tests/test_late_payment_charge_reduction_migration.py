"""Real PostgreSQL coverage of reducing or waiving a Late-payment Charge (V1-056 slice 11g-2;
DL-076 answer 4 and reading (d)).

The Owner or a Manager lowers a Charge (0 waives it) after a staff mistake, with one of three
fixed reasons and what happened; the amount only goes down. Paid value above the new amount is
released: the paying sources are reversed whole, newest first, their unreleased rest is posted
again to the Charge, released Payment value becomes Customer Credit of the Charge's Customer at
once (BR-CREDIT-014) and released Credit value returns to its Credit.

Each Charge comes from the automatic pass of slice 11g-1 on its own Rent month (V1 holds one
Property, so every test shares it and its pass history).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from payment_test_support import seed_payment
from property_rental.credit import ApplyCreditCommand
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.late_payment import (
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    LatePaymentConflictError,
    LatePaymentIdempotencyKeyReused,
    LatePaymentInvalidError,
    LatePaymentNotFoundError,
    ReduceLatePaymentChargeCommand,
    ReductionReason,
)
from property_rental.payment_allocation import PostAllocationsCommand
from test_automatic_late_payment_charge_migration import (
    backdate_issue,
    clear_runs,
    due_of,
    moment,
    months_ago,
    overdue,
    record,
    refusal,
    seed_last_run,
)
from test_credit_application_migration import application_id
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credits
from test_final_settlement_migration import one
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    runtime_database_url,
)
from test_late_payment_migration import migrated_database_url as migrated_database_url
from test_late_payment_migration import service as late_payments
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import service as allocations
from test_settlement_late_charge_reduction_migration import charge_corrections, closed_overdue_case

COMMAND = "app.reduce_late_payment_charge(uuid,uuid,uuid,uuid,text,text,bigint,text,text,uuid,uuid)"
INTERNAL = (
    "app.late_payment_reduction_text_valid(text)",
    "app.late_payment_reduction_reason(text)",
    "app.validate_late_payment_charge_reduction()",
    "app.late_payment_charge_reduction_detail(uuid)",
)
RELEASE_REASON = "Late-payment Charge correction credit excess"
WHAT = "The Customer paid at the desk on the 4th; staff entered the Payment on the 7th."


@pytest.fixture(autouse=True)
def no_pass_yet(migrated_database_url: str) -> Iterator[None]:
    clear_runs(migrated_database_url)
    yield
    clear_runs(migrated_database_url)


def charged(url: str, months: int) -> dict[str, Any]:
    """An unpaid Rent Invoice of 800.00 and its automatic charge of 80.00."""
    case = overdue(url, months_ago(url, months))
    seed_last_run(url, case["prop"], case["service"], case["due"])
    outcome = record(case)
    assert outcome["outcome"] == "CHARGED"
    lease = one(url, "SELECT lease_id FROM app.invoices WHERE id=%s", case["invoice"])[0]
    return {**case, "url": url, "charge": UUID(str(outcome["charge"]["id"])), "lease": lease}


def manager(case: dict[str, Any]) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(case["human"]),
        capability_grants=frozenset(
            {
                CapabilityGrant(capability, frozenset({str(case["prop"])}))
                for capability in ("late_payment.review", "late_payment.charge_correction")
            }
        ),
    )


def reduce(
    case: dict[str, Any],
    new_amount: int,
    reason: ReductionReason = ReductionReason.PAID_ON_TIME_RECORDED_LATE,
    *,
    key: UUID | None = None,
    what: str = WHAT,
) -> dict[str, Any]:
    return late_payments().reduce_charge(
        case["prop"],
        case["charge"],
        ReduceLatePaymentChargeCommand(key or uuid4(), new_amount, reason, what),
        actor=manager(case),
    )


def pay_charge(case: dict[str, Any], amount: int, *, payer: UUID | None = None) -> UUID:
    """A Payment allocated directly to the Charge, by the tenant or by a third party identified
    for the Lease. Returns the allocation."""
    with psycopg.connect(case["url"]) as connection:
        if payer is not None:
            connection.execute(
                "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
                "VALUES (%s,'Third-party payer',%s,%s)",
                (payer, case["human"], case["human"]),
            )
        payment = seed_payment(
            connection,
            actor_id=case["human"],
            property_id=case["prop"],
            customer_id=payer or case["customer"],
            amount=amount,
            **({"scope": "THIRD_PARTY_IDENTIFIED", "lease_id": case["lease"]} if payer else {}),
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
    found = one(case["url"], "SELECT id FROM app.payment_allocations WHERE payment_id=%s", payment)
    return UUID(str(found[0]))


def apply_credit(case: dict[str, Any], amount: int) -> tuple[UUID, UUID]:
    """The tenant's own Credit applied directly to the Charge. The Credit comes from this slice's
    own release: an earlier Rent month of the same Lease gets its charge, which a Payment pays in
    full and a reduction lowers by `amount`. Returns the Credit and the application."""
    url, prop, human = case["url"], case["prop"], case["human"]
    earlier = case["due"].replace(day=1) - timedelta(days=1)
    with psycopg.connect(url) as connection:
        invoice, _ = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=case["customer"],
            lease_id=case["lease"],
            period_start=earlier.replace(day=1),
        )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    due = due_of(earlier.replace(day=1))
    backdate_issue(url, invoice, moment(due) - timedelta(days=10))
    seed_last_run(url, prop, case["service"], due)
    outcome = record(case, invoice)
    assert outcome["outcome"] == "CHARGED"
    other = {**case, "charge": UUID(str(outcome["charge"]["id"]))}
    pay_charge(other, 8_000)
    reduce(other, 8_000 - amount)
    credit = UUID(
        str(
            one(
                url,
                "SELECT id FROM app.customer_credits WHERE customer_id=%s AND reason=%s",
                case["customer"],
                RELEASE_REASON,
            )[0]
        )
    )
    application = application_id(
        credits().apply(
            prop,
            credit,
            ApplyCreditCommand(
                uuid4(),
                {
                    "mode": "DIRECT_CHARGE",
                    "late_payment_charge_id": str(case["charge"]),
                    "amount_usd_cents": amount,
                },
            ),
            actor=credit_actor(human, prop, "credits.apply"),
        )
    )
    return credit, application


def direct(
    connection: psycopg.Connection[Any],
    case: dict[str, Any],
    resulting: int,
    code: str = "WRONG_INVOICE",
    what: str = WHAT,
) -> None:
    """The command called as the financial role, without the service's checks."""
    connection.execute(
        f"SELECT {COMMAND.split('(')[0]}(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            case["prop"],
            case["charge"],
            case["human"],
            uuid4(),
            "0" * 64,
            "late-payment-test",
            resulting,
            code,
            what,
            uuid4(),
            uuid4(),
        ),
    )


def position(url: str, charge: UUID) -> tuple[int, int]:
    """The Charge's current amount and what is still unpaid."""
    row = one(
        url,
        "SELECT app.settlement_late_charge_obligation(%s),"
        "(app.late_payment_charge_application_summary(%s)->>'active_total_usd_cents')::bigint",
        charge,
        charge,
    )
    return int(cast(int, row[0])), int(cast(int, row[0])) - int(cast(int, row[1]))


def credits_of(url: str, customer: UUID) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT recognized_usd_cents,source_payment_id,reason,app.credit_available_value(id) "
            "FROM app.customer_credits WHERE customer_id=%s AND reason=%s "
            "ORDER BY recognized_usd_cents DESC",
            (customer, RELEASE_REASON),
        ).fetchall()


def reductions_of(url: str, charge: UUID) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT correction.correction_kind,correction.amount_usd_cents,"
            "correction.previous_obligation_usd_cents,correction.resulting_obligation_usd_cents,"
            "correction.reason,correction.authorization_reference,reduction.reason_code,"
            "reduction.what_happened,reduction.released_usd_cents "
            "FROM app.late_payment_charge_corrections correction "
            "JOIN app.late_payment_charge_reductions reduction "
            "ON reduction.late_payment_charge_correction_id=correction.id "
            "WHERE correction.late_payment_charge_id=%s ORDER BY correction.occurred_at",
            (charge,),
        ).fetchall()


def test_an_unpaid_charge_only_goes_down_and_a_waived_charge_takes_no_more_change(
    migrated_database_url: str,
) -> None:
    """DL-076 answer 4: one of three fixed reasons and what happened; the amount only goes down;
    0 waives the Charge (the correction's CHARGE_REVERSAL); history keeps every change."""
    url = migrated_database_url
    case = charged(url, 4)
    key = uuid4()

    first = reduce(case, 5_000, ReductionReason.WRONG_INVOICE, key=key)
    assert position(url, case["charge"]) == (5_000, 5_000)
    # An exact repeat answers the same; the same key with other input is refused.
    assert reduce(case, 5_000, ReductionReason.WRONG_INVOICE, key=key) == first
    with pytest.raises(LatePaymentIdempotencyKeyReused):
        reduce(case, 4_000, ReductionReason.WRONG_INVOICE, key=key)
    for higher in (5_000, 6_000):
        with pytest.raises(LatePaymentConflictError):
            reduce(case, higher)
    assert position(url, case["charge"]) == (5_000, 5_000)

    waived = reduce(case, 0, ReductionReason.OTHER_STAFF_MISTAKE)
    assert position(url, case["charge"]) == (0, 0)
    with pytest.raises(LatePaymentConflictError):
        reduce(case, 0)
    assert reductions_of(url, case["charge"]) == [
        (
            "REDUCTION",
            3_000,
            8_000,
            5_000,
            "Staff recorded the payment on the wrong Invoice",
            "late_payment.charge_correction",
            "WRONG_INVOICE",
            WHAT,
            0,
        ),
        (
            "CHARGE_REVERSAL",
            5_000,
            5_000,
            0,
            "Other staff mistake",
            "late_payment.charge_correction",
            "OTHER_STAFF_MISTAKE",
            WHAT,
            0,
        ),
    ]
    # The Charge read names each reduction.
    items = cast(list[dict[str, Any]], waived["corrections"])
    assert [item["reduction"]["reason_code"] for item in items] == [
        "WRONG_INVOICE",
        "OTHER_STAFF_MISTAKE",
    ]
    assert items[1]["reduction"]["released"] == {"currency": "USD", "minor_units": 0}
    assert items[1]["reduction"]["customer_credit_ids"] == []
    assert cast(dict[str, Any], waived["remaining_balance"])["minor_units"] == 0


def test_paid_value_above_the_new_amount_becomes_credit_of_the_charge_s_customer(
    migrated_database_url: str,
) -> None:
    """DL-076 reading (d) and BR-CREDIT-014: the newest paying source is released first; a source
    released in part keeps its rest on the Charge; released Payment value is Credit of the Charge's
    Customer, also when a third party paid."""
    url = migrated_database_url
    case = charged(url, 6)
    older = pay_charge(case, 3_000)
    newer = pay_charge(case, 4_000, payer=uuid4())
    assert position(url, case["charge"]) == (8_000, 1_000)

    result = reduce(case, 2_000)

    assert position(url, case["charge"]) == (2_000, 0)
    with psycopg.connect(url) as connection:
        reversed_allocations = connection.execute(
            "SELECT payment_allocation_id,reason FROM app.payment_allocation_reversals "
            "WHERE payment_allocation_id IN (%s,%s) ORDER BY occurred_at",
            (older, newer),
        ).fetchall()
        reposted = connection.execute(
            "SELECT allocation.amount_usd_cents,allocation.payment_id FROM app.payment_allocations "
            "allocation WHERE allocation.late_payment_charge_id=%s AND NOT EXISTS(SELECT 1 FROM "
            "app.payment_allocation_reversals reversal "
            "WHERE reversal.payment_allocation_id=allocation.id)",
            (case["charge"],),
        ).fetchall()
        older_payment = connection.execute(
            "SELECT payment_id FROM app.payment_allocations WHERE id=%s", (older,)
        ).fetchone()
        newer_payment = connection.execute(
            "SELECT payment_id FROM app.payment_allocations WHERE id=%s", (newer,)
        ).fetchone()
    assert older_payment is not None and newer_payment is not None
    # Newest first: the third party's 4,000 whole, then 1,000 of the tenant's 3,000.
    assert reversed_allocations == [(newer, RELEASE_REASON), (older, RELEASE_REASON)]
    assert reposted == [(2_000, older_payment[0])]
    assert credits_of(url, case["customer"]) == [
        (4_000, newer_payment[0], RELEASE_REASON, 4_000),
        (1_000, older_payment[0], RELEASE_REASON, 1_000),
    ]
    assert reductions_of(url, case["charge"])[0][-1] == 5_000
    detail = cast(list[dict[str, Any]], result["corrections"])[0]["reduction"]
    assert detail["released"] == {"currency": "USD", "minor_units": 5_000}
    assert len(detail["customer_credit_ids"]) == 2
    audit = one(
        url,
        "SELECT action,authorization_reference,authorization_evidence->>'released_usd_cents',"
        "authorization_evidence->>'reason_code',customer_id FROM app.audit_events "
        "WHERE entity_id=%s AND action='late_payment.charge_corrected'",
        case["charge"],
    )
    assert audit == (
        "late_payment.charge_corrected",
        "late_payment.charge_correction",
        "5000",
        "PAID_ON_TIME_RECORDED_LATE",
        case["customer"],
    )


def test_released_credit_value_returns_to_its_own_credit(migrated_database_url: str) -> None:
    """A Credit application on the Charge is reversed whole; its value goes back to that Credit,
    not to a new one."""
    url = migrated_database_url
    case = charged(url, 10)
    credit, application = apply_credit(case, 3_000)
    assert int(cast(int, one(url, "SELECT app.credit_available_value(%s)", credit)[0])) == 0

    reduce(case, 0, ReductionReason.WRONG_INVOICE)

    assert position(url, case["charge"]) == (0, 0)
    assert int(cast(int, one(url, "SELECT app.credit_available_value(%s)", credit)[0])) == 3_000
    assert one(
        url,
        "SELECT count(*) FROM app.customer_credit_application_reversals "
        "WHERE credit_application_id=%s AND reason=%s",
        application,
        RELEASE_REASON,
    ) == (1,)
    # No new Credit: the one Credit (of the earlier month's reduction) has its value back.
    assert [row[0] for row in credits_of(url, case["customer"])] == [3_000]
    assert reductions_of(url, case["charge"])[0][-1] == 3_000


def test_two_reductions_at_once_lower_the_charge_once(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = charged(url, 11)
    pay_charge(case, 8_000)

    def attempt(_: int) -> str:
        try:
            reduce(case, 5_000)
        except LatePaymentConflictError:
            return "CONFLICT"
        return "REDUCED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(attempt, range(2)))

    assert outcomes == ["CONFLICT", "REDUCED"]
    assert position(url, case["charge"]) == (5_000, 0)
    assert [row[0] for row in credits_of(url, case["customer"])] == [3_000]


def test_bad_input_an_unknown_charge_and_a_closed_settlement_are_refused(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = charged(url, 12)
    with pytest.raises(LatePaymentNotFoundError):
        late_payments().reduce_charge(
            case["prop"],
            uuid4(),
            ReduceLatePaymentChargeCommand(uuid4(), 0, ReductionReason.WRONG_INVOICE, WHAT),
            actor=manager(case),
        )
    # Input the command type cannot hold is refused by the database too (P4602).
    with psycopg.connect(financial_database_url()) as financial:
        for resulting, code, what in (
            (-1, "WRONG_INVOICE", WHAT),
            (0, "CUSTOMER_ASKED", WHAT),
            (0, "WRONG_INVOICE", " padded"),
            (0, "WRONG_INVOICE", "ends with a line feed\n"),
            (0, "WRONG_INVOICE", "a bell \x07 inside"),
            (0, "WRONG_INVOICE", "a C1 control \x9b inside"),
            (0, "WRONG_INVOICE", "the first C1 control \x80 inside"),
            (0, "WRONG_INVOICE", "the last C1 control \x9f inside"),
            (0, "WRONG_INVOICE", "x" * 501),
        ):
            with pytest.raises(psycopg.Error) as failure, financial.transaction():
                direct(financial, case, resulting, code, what)
            assert failure.value.sqlstate == "P4602"
    assert position(url, case["charge"]) == (8_000, 8_000)
    assert issubclass(LatePaymentInvalidError, ValueError)

    # A closed Final Settlement refuses the command (P5S01) and nothing is written.
    closed = closed_overdue_case(url)
    before = (charge_corrections(url, closed["charge"]), position(url, closed["charge"]))
    with pytest.raises(LatePaymentConflictError):
        late_payments().reduce_charge(
            closed["prop"],
            closed["charge"],
            ReduceLatePaymentChargeCommand(uuid4(), 0, ReductionReason.WRONG_INVOICE, WHAT),
            actor=manager(closed),
        )
    with (
        pytest.raises(psycopg.Error) as failure,
        psycopg.connect(financial_database_url()) as financial,
    ):
        direct(financial, closed, 0)
    assert failure.value.sqlstate == "P5S01"
    assert (charge_corrections(url, closed["charge"]), position(url, closed["charge"])) == before
    assert one(
        url,
        "SELECT count(*) FROM app.late_payment_charge_reductions WHERE late_payment_charge_id=%s",
        closed["charge"],
    ) == (0,)


def test_reductions_are_append_only_checked_and_run_only_through_the_financial_role(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = charged(url, 13)
    reduce(case, 7_000)
    correction = one(
        url,
        "SELECT late_payment_charge_correction_id FROM app.late_payment_charge_reductions "
        "WHERE late_payment_charge_id=%s",
        case["charge"],
    )[0]
    for statement in (
        "UPDATE app.late_payment_charge_reductions SET what_happened='Changed' "
        "WHERE late_payment_charge_correction_id=%s",
        "DELETE FROM app.late_payment_charge_reductions WHERE late_payment_charge_correction_id=%s",
    ):
        assert refusal(url, statement, correction)[0] == "55000"
    assert refusal(url, "TRUNCATE app.late_payment_charge_reductions")[0] == "55000"
    # A reduction row that does not match its correction is refused at commit.
    other = charged(url, 14)
    with psycopg.connect(url) as owner:
        owner.execute(
            "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
            "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
            "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,"
            "correlation_id) VALUES (%s,%s,'REDUCTION',1000,'Other staff mistake',8000,7000,"
            "clock_timestamp(),%s,'late_payment.charge_correction',%s)",
            (row := uuid4(), other["charge"], other["human"], uuid4()),
        )
        owner.execute(
            "INSERT INTO app.late_payment_charge_reductions(late_payment_charge_correction_id,"
            "late_payment_charge_id,reason_code,what_happened,released_usd_cents,recorded_at) "
            "VALUES (%s,%s,'WRONG_INVOICE','x',0,clock_timestamp())",
            (row, other["charge"]),
        )
        with pytest.raises(psycopg.Error) as failure:
            owner.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert failure.value.sqlstate == "23514"
        assert "reduction does not match its correction" in str(failure.value)
        owner.rollback()
    # The right reason but a released value that no release row backs is refused too.
    with psycopg.connect(url) as owner:
        owner.execute(
            "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
            "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
            "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,"
            "correlation_id) VALUES (%s,%s,'REDUCTION',1000,'Other staff mistake',8000,7000,"
            "clock_timestamp(),%s,'late_payment.charge_correction',%s)",
            (row := uuid4(), other["charge"], other["human"], uuid4()),
        )
        owner.execute(
            "INSERT INTO app.late_payment_charge_reductions(late_payment_charge_correction_id,"
            "late_payment_charge_id,reason_code,what_happened,released_usd_cents,recorded_at) "
            "VALUES (%s,%s,'OTHER_STAFF_MISTAKE','x',1,clock_timestamp())",
            (row, other["charge"]),
        )
        with pytest.raises(psycopg.Error) as failure:
            owner.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert "reduction does not match its correction" in str(failure.value)
        owner.rollback()
    with psycopg.connect(url) as owner:
        privileges = owner.execute(
            "SELECT has_function_privilege('prm_financial',%s,'EXECUTE'),"
            "has_function_privilege('prm_runtime',%s,'EXECUTE'),"
            "has_table_privilege('prm_financial','app.late_payment_charge_reductions','SELECT'),"
            "has_table_privilege('prm_runtime','app.late_payment_charge_reductions','SELECT')",
            (COMMAND, COMMAND),
        ).fetchone()
        internal = [
            owner.execute(
                "SELECT has_function_privilege(role,%s,'EXECUTE') "
                "FROM unnest(ARRAY['prm_financial','prm_runtime']) role",
                (function,),
            ).fetchall()
            for function in INTERNAL
        ]
    assert privileges == (True, False, False, False)
    assert all(rows == [(False,), (False,)] for rows in internal)
    with (
        pytest.raises(psycopg.Error) as failure,
        psycopg.connect(runtime_database_url()) as runtime,
    ):
        direct(runtime, case, 0)
    assert failure.value.sqlstate == "42501"


def test_a_credit_application_released_in_part_keeps_its_rest_on_the_charge(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = charged(url, 15)
    credit, application = apply_credit(case, 3_000)

    reduce(case, 1_000)

    assert position(url, case["charge"]) == (1_000, 0)
    assert int(cast(int, one(url, "SELECT app.credit_available_value(%s)", credit)[0])) == 2_000
    with psycopg.connect(url) as connection:
        active = connection.execute(
            "SELECT application.customer_credit_id,application.amount_usd_cents "
            "FROM app.customer_credit_applications application "
            "WHERE application.late_payment_charge_id=%s AND NOT EXISTS(SELECT 1 FROM "
            "app.customer_credit_application_reversals reversal "
            "WHERE reversal.credit_application_id=application.id)",
            (case["charge"],),
        ).fetchall()
    assert active == [(credit, 1_000)]
    assert application not in [row[0] for row in active]
    assert reductions_of(url, case["charge"])[0][-1] == 2_000


def test_a_reduction_waits_for_another_writer_of_the_same_payment(
    migrated_database_url: str,
) -> None:
    """Round 1 money review B1: the Payment pass takes each Payment's serializer before its row
    lock, as every Payment writer does, so the two never wait on each other in a circle."""
    url = migrated_database_url
    case = charged(url, 16)
    allocation = pay_charge(case, 8_000)
    payment = one(url, "SELECT payment_id FROM app.payment_allocations WHERE id=%s", allocation)[0]
    with psycopg.connect(url) as holder, ThreadPoolExecutor(max_workers=1) as pool:
        holder.execute("SELECT app.serialize_payment_state(%s)", (payment,))
        holder_pid = holder.info.backend_pid
        waiting = pool.submit(reduce, case, 5_000)
        with psycopg.connect(url, autocommit=True) as watcher:
            for _ in range(250):
                blocked = watcher.execute(
                    "SELECT count(*) FROM pg_catalog.pg_stat_activity "
                    "WHERE %s=ANY(pg_catalog.pg_blocking_pids(pid))",
                    (holder_pid,),
                ).fetchone()
                if blocked is not None and blocked[0] > 0:
                    break
                time.sleep(0.02)
            else:
                error = waiting.exception() if waiting.done() else None
                outcome = (
                    (error, getattr(error.__cause__, "sqlstate", None)) if error else "running"
                )
                pytest.fail(f"The reduction did not wait for the Payment's serializer: {outcome!r}")
        # The waiting reduction holds no lock on the Payment row yet (serializer first), so the
        # holder, like any Payment writer, takes it next without waiting.
        holder.execute("SELECT pg_catalog.set_config('lock_timeout','1s',true)")
        holder.execute("SELECT 1 FROM app.payments WHERE id=%s FOR UPDATE", (payment,))
        assert not waiting.done()
        holder.commit()
        waiting.result(timeout=30)
    assert position(url, case["charge"]) == (5_000, 0)


def test_the_old_route_does_not_reverse_a_reduction_and_shares_its_keys(
    migrated_database_url: str,
) -> None:
    """Round 1 security review S1: a reduction released its paid value as Credit, so the old
    correction route refuses to reverse it (P4603). Both routes share the idempotency keys."""
    url = migrated_database_url
    case = charged(url, 17)
    key = uuid4()
    reduce(case, 6_000, key=key)
    correction = one(
        url,
        "SELECT late_payment_charge_correction_id FROM app.late_payment_charge_reductions "
        "WHERE late_payment_charge_id=%s",
        case["charge"],
    )[0]
    with pytest.raises(LatePaymentConflictError):
        late_payments().correct_charge(
            case["prop"],
            case["charge"],
            CorrectLatePaymentChargeCommand(
                uuid4(),
                CorrectionKind.REDUCTION_REVERSAL,
                "Undo the reduction",
                reverses_correction_id=UUID(str(correction)),
            ),
            actor=manager(case),
        )
    with pytest.raises(LatePaymentIdempotencyKeyReused):
        late_payments().correct_charge(
            case["prop"],
            case["charge"],
            CorrectLatePaymentChargeCommand(
                key, CorrectionKind.REDUCTION, "Same key, other route", amount_usd_cents=1_000
            ),
            actor=manager(case),
        )
    assert position(url, case["charge"]) == (6_000, 6_000)
    assert charge_corrections(url, case["charge"]) == 1
