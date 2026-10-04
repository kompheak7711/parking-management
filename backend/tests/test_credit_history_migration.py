"""Coherent, bounded Credit-only history over retained financial source events."""

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest

from payment_test_support import seed_method
from property_rental.credit import (
    CreditAuthorizationError,
    CreditLedgerPage,
    CreditNotFoundError,
    CreditPage,
    RecognizeCreditCommand,
    ReverseCreditApplicationCommand,
    ReverseCreditCommand,
)
from property_rental.refund import RefundPage, ReverseRefundCorrectionCommand
from refund_test_support import create_usd_refund
from test_credit_application_migration import application_id, designated
from test_credit_application_migration import source as application_source
from test_credit_migration import actor, credit_id, recognize, service, source
from test_invoice_migration import runtime_database_url
from test_refund_migration import refund as insert_refund
from test_refund_service_migration import corrections, create, refund_id, returned
from test_refund_service_migration import service as refunds
from test_reservation_migration import (
    migrated_database_url,  # noqa: F401
    setup_reservation_sources,
)


def history(result: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], result["history"])


def events(result: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], history(result)["items"])


def position(result: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], result["position"])


def test_credit_ledger_reconstructs_all_event_families_and_exact_positions(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, payment = application_source(migrated_database_url)
    reader = actor(human, prop, "credits.read")
    applied = service().apply(
        prop, credit, designated(invoice, line, 30000), actor=actor(human, prop, "credits.apply")
    )
    paid = create_usd_refund(
        refunds(), prop, create(credit, 20000, "CREDIT"), actor=actor(human, prop, "refunds.create")
    )
    refund = refund_id(paid)
    partial = refunds().verify_usd_return(
        prop, refund, returned(5000), actor=actor(human, prop, "refunds.correct")
    )
    current = service().ledger(prop, credit, actor=reader)
    assert position(current)["recognized_usd_cents"] == 100000
    assert position(current)["applied_usd_cents"] == 30000
    assert position(current)["refunded_usd_cents"] == 15000
    assert position(current)["available_usd_cents"] == 55000
    refunds().reverse_correction(
        prop,
        refund,
        UUID(str(corrections(partial)[0]["id"])),
        ReverseRefundCorrectionCommand(uuid4(), "Verified correction evidence", "Wrong return"),
        actor=actor(human, prop, "refunds.corrections.reverse"),
    )
    refunds().verify_usd_return(
        prop, refund, returned(20000), actor=actor(human, prop, "refunds.correct")
    )
    service().reverse_application(
        prop,
        application_id(applied),
        ReverseCreditApplicationCommand(uuid4(), "Wrong application"),
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    service().reverse(
        prop,
        credit,
        ReverseCreditCommand(uuid4(), "Wrong consent"),
        actor=actor(human, prop, "credits.reverse"),
    )
    final = service().ledger(prop, credit, actor=reader)
    assert {
        k: position(final)[k]
        for k in (
            "recognized_usd_cents",
            "applied_usd_cents",
            "refunded_usd_cents",
            "reversed_usd_cents",
            "available_usd_cents",
        )
    } == dict(
        recognized_usd_cents=100000,
        applied_usd_cents=0,
        refunded_usd_cents=0,
        reversed_usd_cents=100000,
        available_usd_cents=0,
    )
    assert {event["event_kind"] for event in events(final)} == {
        "RECOGNITION",
        "APPLICATION",
        "REFUND",
        "REFUND_VALUE_CORRECTION",
        "REFUND_CORRECTION_REVERSAL",
        "APPLICATION_REVERSAL",
        "RECOGNITION_REVERSAL",
    }
    balance = 0
    for event in reversed(events(final)):
        balance += cast(int, event["balance_effect_usd_cents"])
        assert event["available_after_usd_cents"] == balance >= 0
        assert event["actor_id"] == str(human)
        assert event["currency"] == "USD"
    collected: list[dict[str, object]] = []
    page = CreditLedgerPage(1)
    for _ in range(10):
        result = service().ledger(prop, credit, page, actor=reader)
        collected.extend(events(result))
        cursor = history(result)["next_cursor"]
        if cursor is None:
            break
        data = cast(dict[str, str], cursor)
        page = CreditLedgerPage(
            1, datetime.fromisoformat(data["occurred_at"]), data["event_kind"], UUID(data["id"])
        )
    else:
        pytest.fail("Credit history cursor did not terminate")
    assert collected == events(final)
    assert len(collected) == 8
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT recognized_usd_cents FROM app.customer_credits WHERE id=%s", (credit,)
        ).fetchone() == (100000,)
        assert connection.execute(
            "SELECT app.payment_credit_value_at(%s,'infinity'),"
            "app.payment_refunded_value_at(%s,'infinity')",
            (payment, payment),
        ).fetchone() == (0, 0)


def test_credit_list_keysets_filter_customer_and_property_without_omitting_history(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    ids = [credit_id(recognize(prop, payment, human, 1000)) for _ in range(3)]
    other_human, other_prop, _, other_payment = source(migrated_database_url)
    recognize(other_prop, other_payment, other_human)
    reader = actor(human, prop, "credits.read")
    complete = service().list(prop, customer, actor=reader)
    all_items = cast(list[dict[str, object]], complete["items"])
    assert [credit_id(item) for item in all_items] == list(reversed(ids))
    assert all(position(item)["available_usd_cents"] == 1000 for item in all_items)
    page = CreditPage(1)
    seen: list[dict[str, object]] = []
    for _ in range(4):
        result = service().list(prop, customer, page, actor=reader)
        seen.extend(cast(list[dict[str, object]], result["items"]))
        if result["next_cursor"] is None:
            break
        cursor = cast(dict[str, str], result["next_cursor"])
        page = CreditPage(1, datetime.fromisoformat(cursor["occurred_at"]), UUID(cursor["id"]))
    assert seen == all_items
    assert service().list(prop, uuid4(), actor=reader) == {"items": [], "next_cursor": None}
    missing_prop = uuid4()
    with pytest.raises(CreditNotFoundError):
        service().ledger(missing_prop, ids[0], actor=actor(human, missing_prop, "credits.read"))
    with pytest.raises(CreditAuthorizationError):
        service().list(prop, customer, actor=actor(human, prop, "credits.recognize"))
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(CreditAuthorizationError):
        service().list(prop, customer, actor=reader)
    with pytest.raises(CreditAuthorizationError):
        service().ledger(prop, ids[0], actor=reader)


def test_credit_read_only_snapshot_survives_concurrent_refund_commit_without_guard_writes(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    credit = credit_id(recognize(prop, payment, human))
    sql = "SELECT app.customer_credit_ledger(%s,%s,%s,100,NULL,NULL,NULL)"
    with psycopg.connect(runtime_database_url()) as reader:
        reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        old = reader.execute(sql, (prop, credit, human)).fetchone()
        assert old is not None and position(old[0])["available_usd_cents"] == 8000
        create_usd_refund(
            refunds(),
            prop,
            create(credit, 3000, "CREDIT"),
            actor=actor(human, prop, "refunds.create"),
        )
        assert reader.execute(sql, (prop, credit, human)).fetchone() == old
        listed = reader.execute(
            "SELECT app.list_customer_credits(%s,%s,%s,100,NULL,NULL)", (prop, customer, human)
        ).fetchone()
        assert listed is not None and position(listed[0]["items"][0])["available_usd_cents"] == 8000
    fresh = service().ledger(prop, credit, actor=actor(human, prop, "credits.read"))
    assert position(fresh)["available_usd_cents"] == 5000
    assert events(fresh)[0]["available_after_usd_cents"] == 5000
    with psycopg.connect(migrated_database_url) as connection:
        before = connection.execute(
            "SELECT revision FROM app.payment_serialization_guards WHERE payment_id=%s", (payment,)
        ).fetchone()
        service().ledger(prop, credit, actor=actor(human, prop, "credits.read"))
        service().list(prop, customer, actor=actor(human, prop, "credits.read"))
        assert (
            connection.execute(
                "SELECT revision FROM app.payment_serialization_guards WHERE payment_id=%s",
                (payment,),
            ).fetchone()
            == before
        )


@pytest.mark.parametrize("invalid", ["limit", "partial", "kind", "infinite", "nil"])
def test_credit_ledger_database_rejects_invalid_cursor_envelopes(
    migrated_database_url: str,  # noqa: F811
    invalid: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    credit = credit_id(recognize(prop, payment, human))
    limit, at, kind, identity = 1, None, None, None
    values: dict[str, tuple[object, ...]] = {
        "limit": (101, at, kind, identity),
        "partial": (limit, at, "RECOGNITION", identity),
        "kind": (limit, "2026-01-01T00:00:00Z", "UNKNOWN", uuid4()),
        "infinite": (limit, "infinity", "RECOGNITION", uuid4()),
        "nil": (limit, "2026-01-01T00:00:00Z", "RECOGNITION", UUID(int=0)),
    }
    with psycopg.connect(runtime_database_url()) as connection:
        with pytest.raises(psycopg.Error) as failure:
            connection.execute(
                "SELECT app.customer_credit_ledger(%s,%s,%s,%s,%s,%s,%s)",
                (prop, credit, human, *values[invalid]),
            )
        assert failure.value.sqlstate == "P5102"


def test_credit_history_bounded_pages_keep_cross_family_event_identities(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url, 1000)
    credit = credit_id(recognize(prop, payment, human, 1000))
    with psycopg.connect(migrated_database_url) as connection:
        for index in range(105):
            insert_refund(
                connection,
                human,
                customer,
                credit=credit,
                amount=1,
                overrides={"id": credit} if index == 0 else None,
            )
    reader = actor(human, prop, "credits.read")
    first = service().ledger(prop, credit, CreditLedgerPage(100), actor=reader)
    assert len(events(first)) == 100
    assert len(str(first)) < 200000
    cursor = cast(dict[str, str], history(first)["next_cursor"])
    second = service().ledger(
        prop,
        credit,
        CreditLedgerPage(
            100,
            datetime.fromisoformat(cursor["occurred_at"]),
            cursor["event_kind"],
            UUID(cursor["id"]),
        ),
        actor=reader,
    )
    all_events = events(first) + events(second)
    assert len(all_events) == 106 and history(second)["next_cursor"] is None
    assert len({(e["event_kind"], e["event_id"]) for e in all_events}) == 106
    assert [e["event_kind"] for e in all_events if e["event_id"] == str(credit)] == [
        "REFUND",
        "RECOGNITION",
    ]
    assert position(first)["available_usd_cents"] == position(second)["available_usd_cents"] == 895


def test_credit_read_helpers_and_position_view_are_private_and_actor_checks_stable(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(runtime_database_url()) as connection:
        signatures = (
            "app.credit_read_summary(uuid)",
            "app.credit_history_events(uuid)",
            "app.assert_credit_read_actor(uuid,uuid)",
            "app.assert_credit_read_page(integer,timestamptz,uuid)",
        )
        for signature in signatures:
            assert connection.execute(
                "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (signature,)
            ).fetchone() == (False,)
        assert connection.execute(
            "SELECT has_table_privilege(current_user,"
            "'app.customer_credit_financial_position','SELECT')"
        ).fetchone() == (False,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute("SELECT app.credit_read_summary(%s)", (uuid4(),))
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute("SELECT * FROM app.customer_credit_financial_position")
        for signature in (
            "app.list_customer_credits(uuid,uuid,uuid,integer,timestamptz,uuid)",
            "app.customer_credit_ledger(uuid,uuid,uuid,integer,timestamptz,text,uuid)",
        ):
            assert connection.execute(
                "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (signature,)
            ).fetchone() == (True,)
            assert connection.execute(
                "SELECT provolatile FROM pg_proc WHERE oid=%s::regprocedure", (signature,)
            ).fetchone() == ("s",)


def test_credit_reads_preserve_exact_khr_source_and_bound_large_original_evidence(
    migrated_database_url: str,  # noqa: F811
) -> None:
    reference = "10000000000.000001"
    retained_evidence = "Synthetic retained evidence " * 30000
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, customer = setup_reservation_sources(connection)
        method = seed_method(connection, human)
        rate, payment = uuid4(), uuid4()
        at = datetime.now(UTC) - timedelta(seconds=2)
        connection.execute(
            "INSERT INTO app.exchange_rate_records(id,reference_rate_khr_per_usd,"
            "markup_basis_points,"
            "system_rate_khr_per_usd,rate_source,source_reference,applicable_at,calculation_trace,"
            "channel_actual_currency,channel_actual_rate_khr_per_usd,"
            "channel_transaction_reference,channel_confirmed_at) "
            "VALUES(%s,%s::numeric,50,ceil(%s::numeric*1.005),'ABA_AUTOMATIC',%s,%s,"
            "jsonb_build_object('ratio',0.1234567890123456789::numeric,'note',%s::text),"
            "'KHR',%s::numeric,'Synthetic channel',%s)",
            (
                rate,
                reference,
                reference,
                retained_evidence.strip(),
                at,
                retained_evidence,
                reference,
                at,
            ),
        )
        connection.execute(
            "INSERT INTO app.payments(id,payment_number,property_id,payer_customer_id,"
            "payment_scope_kind,"
            "payment_date,payment_method_id,received_currency,received_amount_minor,usd_accounting_value_cents,"
            "exchange_rate_record_id,confirmed_at,confirmed_by,authorization_reference,"
            "channel_transaction_reference) "
            "SELECT %s,%s,%s,%s,'NORMAL_CUSTOMER',"
            "(clock_timestamp() AT TIME ZONE 'Asia/Phnom_Penh')::date,"
            "%s,'KHR',ceil(101*channel_actual_rate_khr_per_usd*0.01),101,id,clock_timestamp(),%s,"
            "'payments.record','Synthetic channel' FROM app.exchange_rate_records WHERE id=%s",
            (payment, f"History-{payment}", prop, customer, method, human, rate),
        )
        original = connection.execute(
            "SELECT row_to_json(rate)::text FROM app.exchange_rate_records rate WHERE id=%s",
            (rate,),
        ).fetchone()
    request = RecognizeCreditCommand(uuid4(), 101, "Payer consent", "Retain exact excess")
    command_actor = actor(human, prop, "credits.read", "credits.recognize", "credits.reverse")
    recognized = service().recognize(prop, payment, request, actor=command_actor)
    credit = credit_id(recognized)
    assert len(str(recognized)) < 10000
    assert service().get(prop, credit, actor=command_actor) == recognized
    assert service().recognize(prop, payment, request, actor=command_actor) == recognized
    reader = actor(human, prop, "credits.read")
    listed = cast(list[dict[str, object]], service().list(prop, customer, actor=reader)["items"])[0]
    ledger = service().ledger(prop, credit, actor=reader)
    for result in (listed, ledger):
        fx = cast(dict[str, object], result["exchange_rate"])
        assert fx["id"] == str(rate)
        assert (
            fx["reference_rate_khr_per_usd"] == fx["channel_actual_rate_khr_per_usd"] == reference
        )
        assert "calculation_trace" not in fx and "source_reference" not in fx
        assert position(result)["available_usd_cents"] == 101
        assert type(position(result)["available_usd_cents"]) is int
        assert (
            cast(dict[str, object], result["source_payment"])["received_amount_minor"]
            == 10100000001
        )
        assert len(str(result)) < 10000
    refund_actor = actor(
        human,
        prop,
        "refunds.create",
        "refunds.read",
        "refunds.correct",
        "refunds.corrections.reverse",
    )
    refund_request = create(credit, 101, "CREDIT")
    outbound = create_usd_refund(refunds(), prop, refund_request, actor=refund_actor)
    identity = refund_id(outbound)
    assert create_usd_refund(refunds(), prop, refund_request, actor=refund_actor) == outbound
    first_return = returned(1)
    corrected = refunds().verify_usd_return(prop, identity, first_return, actor=refund_actor)
    assert (
        refunds().verify_usd_return(prop, identity, first_return, actor=refund_actor) == corrected
    )
    correction_id = UUID(str(corrections(corrected)[0]["id"]))
    reversal_request = ReverseRefundCorrectionCommand(uuid4(), "Evidence", "Reverse one cent")
    reversed_return = refunds().reverse_correction(
        prop, identity, correction_id, reversal_request, actor=refund_actor
    )
    assert (
        refunds().reverse_correction(
            prop, identity, correction_id, reversal_request, actor=refund_actor
        )
        == reversed_return
    )
    completed_return = refunds().verify_usd_return(
        prop, identity, returned(101), actor=refund_actor
    )
    paged = refunds().get(prop, identity, actor=refund_actor, page=RefundPage(1))
    for result in (outbound, corrected, reversed_return, completed_return, paged):
        summary = cast(dict[str, object], result["source_exchange_rate"])
        assert summary == recognized["exchange_rate"]
        assert summary["id"] == str(rate)
        assert summary["reference_rate_khr_per_usd"] == reference
        assert "source_reference" not in summary and "calculation_trace" not in summary
        assert len(str(result)) < 20000
    assert completed_return["net_refund_usd_cents"] == 0
    reverse_credit = ReverseCreditCommand(uuid4(), "Payer revoked consent")
    reversed_credit = service().reverse(prop, credit, reverse_credit, actor=command_actor)
    assert service().reverse(prop, credit, reverse_credit, actor=command_actor) == reversed_credit
    assert len(str(reversed_credit)) < 10000
    with psycopg.connect(migrated_database_url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,"
                "'app.credit_refund_exchange_rate_summary(uuid)','EXECUTE')",
                (role,),
            ).fetchone() == (False,)
        for table in ("credit_commands", "refund_commands"):
            sizes = connection.execute(
                f"SELECT octet_length(response::text) FROM app.{table} "
                "WHERE property_id=%s AND actor_id=%s",
                (prop, human),
            ).fetchall()
            assert sizes and all(int(str(row[0])) < 20000 for row in sizes)
        assert (
            connection.execute(
                "SELECT row_to_json(rate)::text FROM app.exchange_rate_records rate WHERE id=%s",
                (rate,),
            ).fetchone()
            == original
        )
