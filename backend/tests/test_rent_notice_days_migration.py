"""Unpaid Rent: notices on day 10, 20 and 25, the termination letter on day 30 (migration 413).

Owner (13 Nov 2026, DL-237): "First notice: 10 days count from day first. Second notice: 20 days.
Third notice: 25 days. issue termination letter on 30 days. notice will send automatically since
we build telegram." With the owner's "all yes" of the same day: the three notices go by
themselves at 09:00 while the Rent is unpaid, one a day, never before the Due Date has passed;
a tenant with no Telegram link gets none by itself (staff give the paper letter and record it);
the termination letter is a step of a Manager or the Owner and needs the three notices.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import seed_payment
from property_rental.payment_allocation import PaymentAllocationService, PostAllocationsCommand
from test_hr_employees_migration import HrDatabase, make_hr_database, run
from test_invoice_migration import create_recurring_rent_invoice
from test_lease_migration import create_draft, sign_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_telegram_base_migration import RECORD, item, refused

REVISION = "20270726_413"
PHNOM_PENH = ZoneInfo("Asia/Phnom_Penh")
LINK = "SELECT app.telegram_tenant_link(%s, %s, %s, %s, %s)"
RUN = "SELECT app.rent_notices_run(%s, %s)"
SEND = "SELECT app.rent_notices_send(%s, %s)"
QUEUE = "SELECT app.telegram_warnings_queue(%s, %s)"
FIRST_DAY = "SELECT app.rent_notice_first_day(%s, %s, %s)"
NEXT = "SELECT app.rent_notice_next(%s, %s, %s, %s::text[], %s)"
TENANT = 8890001
NOTICES = ("TEN_DAY_NOTICE", "TWENTY_DAY_WARNING", "TWENTY_FIVE_DAY_NOTICE")
LETTER = "THIRTY_DAY_SERIOUS_DEFAULT"
RENT = 80_000


def test_migration_413_follows_378_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270725_378"
    with pytest.raises(RuntimeError, match="forward-only"):
        cast(Any, revision.module).downgrade()


@pytest.fixture(scope="module")
def notice_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_rent_notice")


def make_lease(db: HrDatabase, unit: str, name: str) -> dict[str, Any]:
    """A signed Lease with one Rent Invoice of about two months ago, issued and not paid."""
    day = run(db.owner_url, "SELECT app.gl_today(%s)", db.property_id)
    unit_id, customer_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, status, "
            "created_by, updated_by) VALUES (%s, %s, %s, '6', 'ONE_BEDROOM', 'VACANT', %s, %s)",
            (unit_id, db.property_id, unit, db.owner, db.owner),
        )
        connection.execute(
            "INSERT INTO app.customers (id, legal_name, phone_number, created_by, updated_by) "
            "VALUES (%s, %s, '012 889 777', %s, %s)",
            (customer_id, name, db.owner, db.owner),
        )
        lease_id = create_draft(
            connection,
            actor_id=db.owner,
            unit_id=unit_id,
            primary_tenant_id=customer_id,
            start_date=day - timedelta(days=200),
            end_date=day + timedelta(days=240),
        )
        sign_lease(connection, lease_id, db.owner)
    invoice_id, line_id = rent_invoice(db, lease_id, customer_id, day - timedelta(days=70))
    return {"lease": lease_id, "customer": customer_id, "invoice": invoice_id, "line": line_id}


def rent_invoice(
    db: HrDatabase, lease_id: uuid.UUID, customer_id: uuid.UUID, in_month: date
) -> tuple[uuid.UUID, uuid.UUID]:
    with psycopg.connect(db.owner_url) as connection:
        return create_recurring_rent_invoice(
            connection,
            actor_id=db.owner,
            customer_id=customer_id,
            lease_id=lease_id,
            period_start=in_month.replace(day=1),
            issue=True,
        )


@pytest.fixture(scope="module")
def linked(notice_database: HrDatabase) -> dict[str, Any]:
    """The tenant of Unit 612 is linked to the Tenant bot."""
    db = notice_database
    lease = make_lease(db, "Unit 612", "Sok Dara")
    body = json.loads(item("item-rent-notice-0001", None))
    body.update(
        telegram_user_id=TENANT, chat_id=TENANT, account={"language": "en", "phone": "+85512889777"}
    )
    run(db.runtime_url, RECORD, db.property_id, json.dumps(body), db.manager)
    run(
        db.runtime_url,
        "SELECT app.telegram_choose_language(%s, 'TENANT', %s, 'en', %s)",
        db.property_id,
        TENANT,
        db.manager,
    )
    found = run(db.runtime_url, LINK, db.property_id, TENANT, "dara sok", "612", db.manager)
    assert found["result"] == "LINKED", found
    return lease


@pytest.fixture(scope="module")
def not_linked(notice_database: HrDatabase) -> dict[str, Any]:
    """The tenant of Unit 613 has no Telegram link."""
    return make_lease(notice_database, "Unit 613", "Chan Vanna")


def events(db: HrDatabase, line: uuid.UUID) -> list[dict[str, Any]]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT event.event_kind, event.remaining_rent_usd_cents, "
            "event.notice_document_reference, event.communication_record, event.reason, "
            "event.actor_id, event.id "
            "FROM app.rent_nonpayment_events AS event "
            "JOIN app.rent_nonpayment_cases AS rent_case "
            "ON rent_case.id = event.rent_nonpayment_case_id "
            "WHERE rent_case.rent_invoice_line_id = %s ORDER BY event.occurred_at, event.id",
            (line,),
        ).fetchall()
    return [
        {
            "kind": row[0],
            "remaining": row[1],
            "reference": row[2],
            "how": row[3],
            "reason": row[4],
            "actor": row[5],
            "id": row[6],
        }
        for row in rows
    ]


def by_hand(db: HrDatabase, line: uuid.UUID, kind: str) -> None:
    """Staff record a step by hand today, as the Letters screen does through the database."""
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.rent_nonpayment_cases (lease_id, customer_id, invoice_id, "
            "rent_invoice_line_id, due_date_snapshot, opened_at, opened_by) "
            "SELECT invoice.lease_id, invoice.customer_id, invoice.id, line.id, invoice.due_date, "
            "clock_timestamp(), %s FROM app.invoice_lines AS line "
            "JOIN app.invoices AS invoice ON invoice.id = line.invoice_id "
            "WHERE line.id = %s AND NOT EXISTS (SELECT 1 FROM app.rent_nonpayment_cases AS kept "
            "WHERE kept.rent_invoice_line_id = line.id)",
            (db.owner, line),
        )
        connection.execute(
            "INSERT INTO app.rent_nonpayment_events (rent_nonpayment_case_id, event_kind, "
            "event_date, remaining_rent_usd_cents, notice_document_reference, "
            "communication_record, reason, occurred_at, actor_id) "
            "SELECT rent_case.id, %s, timezone('Asia/Phnom_Penh', moment)::date, "
            "app.invoice_line_outstanding(rent_case.rent_invoice_line_id), 'Letter B-3', "
            "'Handed to the tenant: signed our copy', 'Rent not paid', moment, %s "
            "FROM app.rent_nonpayment_cases AS rent_case, "
            "(SELECT clock_timestamp() AS moment) AS now "
            "WHERE rent_case.rent_invoice_line_id = %s",
            (kind, db.owner, line),
        )


def pay_rent(
    db: HrDatabase, customer: uuid.UUID, invoice: uuid.UUID, line: uuid.UUID, amount: int
) -> None:
    """A Payment of the Customer put on the Rent line of one Invoice."""
    with psycopg.connect(db.owner_url) as connection:
        payment = seed_payment(
            connection,
            actor_id=db.owner,
            property_id=db.property_id,
            customer_id=customer,
            amount=amount,
        )
    PaymentAllocationService(db.runtime_url, db.financial_url).post(
        db.property_id,
        payment,
        PostAllocationsCommand(
            uuid.uuid4(),
            {
                "mode": "DESIGNATED",
                "designation_reference": "Rent instruction",
                "targets": [
                    {
                        "invoice_id": str(invoice),
                        "amount_usd_cents": amount,
                        "details": [{"invoice_line_id": str(line), "amount_usd_cents": amount}],
                    }
                ],
            },
        ),
        actor=allocation_actor(db.owner, db.property_id),
    )


def letters_due(db: HrDatabase) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """What Home asks a person to do about unpaid Rent: the counts, and (kind, Unit) of each."""
    page = run(
        db.runtime_url,
        "SELECT app.home_page(%s, %s, %s::uuid[], %s::text[])",
        db.owner,
        db.property_id,
        [db.property_id],
        ["letters"],
    )
    steps = sorted(
        (todo["kind"], todo["unit_number"])
        for todo in page["todo"]
        if todo["kind"].startswith("letter_day_")
    )
    return page["cards"]["letters_due"], steps


def assessment(db: HrDatabase, line: uuid.UUID) -> dict[str, Any]:
    context = run(
        db.owner_url, "SELECT app.rent_nonpayment_source_context(%s, clock_timestamp())", line
    )
    return cast(dict[str, Any], context)


@pytest.mark.parametrize(
    ("kind", "period", "due", "first_day"),
    [
        # August Rent, due on the 5th: day 10, 20, 25 and 30 of August.
        ("TEN_DAY_NOTICE", date(2026, 8, 1), date(2026, 8, 5), date(2026, 8, 10)),
        ("TWENTY_DAY_WARNING", date(2026, 8, 1), date(2026, 8, 5), date(2026, 8, 20)),
        ("TWENTY_FIVE_DAY_NOTICE", date(2026, 8, 1), date(2026, 8, 5), date(2026, 8, 25)),
        (LETTER, date(2026, 8, 1), date(2026, 8, 5), date(2026, 8, 30)),
        # February has 28 days: day 30 is 2 March.
        (LETTER, date(2027, 2, 1), date(2027, 2, 5), date(2027, 3, 2)),
        # A Due Date on the 15th: no notice before it has passed.
        ("TEN_DAY_NOTICE", date(2026, 8, 1), date(2026, 8, 15), date(2026, 8, 16)),
        ("TWENTY_DAY_WARNING", date(2026, 8, 1), date(2026, 8, 15), date(2026, 8, 20)),
        # A Due Date on the 28th, the latest Settings allow.
        ("TWENTY_FIVE_DAY_NOTICE", date(2026, 8, 1), date(2026, 8, 28), date(2026, 8, 29)),
        (LETTER, date(2026, 8, 1), date(2026, 8, 28), date(2026, 8, 30)),
    ],
)
def test_each_step_counts_from_the_first_and_waits_for_the_due_date(
    notice_database: HrDatabase, kind: str, period: date, due: date, first_day: date
) -> None:
    assert run(notice_database.owner_url, FIRST_DAY, kind, period, due) == first_day


def test_a_step_opens_at_phnom_penh_midnight_of_its_first_day(
    notice_database: HrDatabase, linked: dict[str, Any]
) -> None:
    db = notice_database
    with psycopg.connect(db.owner_url) as connection:
        found = connection.execute(
            "SELECT billing_period_start, due_date FROM app.invoices WHERE id = %s",
            (linked["invoice"],),
        ).fetchone()
        assert found is not None
        period, due = found
        query = (
            "SELECT app.rent_nonpayment_milestone_eligible(%s, "
            "app.rent_notice_day_zero(%s, %s), %s, 1, false)"
        )
        for kind in (*NOTICES, LETTER):
            first_day = run(db.owner_url, FIRST_DAY, kind, period, due)
            opens = datetime(first_day.year, first_day.month, first_day.day, tzinfo=PHNOM_PENH)
            assert connection.execute(query, (kind, linked["invoice"], kind, opens)).fetchone() == (
                True,
            )
            assert connection.execute(
                query, (kind, linked["invoice"], kind, opens - timedelta(microseconds=1))
            ).fetchone() == (False,)


@pytest.mark.parametrize(
    ("today", "given", "given_today", "next_kind"),
    [
        (date(2026, 8, 9), [], False, None),
        (date(2026, 8, 10), [], False, "TEN_DAY_NOTICE"),
        (date(2026, 8, 19), ["TEN_DAY_NOTICE"], False, None),
        (date(2026, 8, 20), ["TEN_DAY_NOTICE"], False, "TWENTY_DAY_WARNING"),
        (date(2026, 8, 25), ["TEN_DAY_NOTICE", "TWENTY_DAY_WARNING"], False, NOTICES[2]),
        # All three are given: nothing more goes by itself, the letter is a person's step.
        (date(2026, 8, 31), list(NOTICES), False, None),
        # The app was off until day 26: one notice a day, in order.
        (date(2026, 8, 26), [], False, "TEN_DAY_NOTICE"),
        (date(2026, 8, 26), ["TEN_DAY_NOTICE"], True, None),
        (date(2026, 8, 27), ["TEN_DAY_NOTICE"], False, "TWENTY_DAY_WARNING"),
        # Staff gave the day-20 letter by hand before: the missing first notice still goes.
        (date(2026, 8, 21), ["TWENTY_DAY_WARNING"], False, "TEN_DAY_NOTICE"),
        # After the termination letter no notice goes.
        (date(2026, 9, 2), ["TEN_DAY_NOTICE", LETTER], False, None),
    ],
)
def test_the_next_notice_goes_in_order_and_one_a_day(
    notice_database: HrDatabase,
    today: date,
    given: list[str],
    given_today: bool,
    next_kind: str | None,
) -> None:
    found = run(
        notice_database.owner_url,
        NEXT,
        date(2026, 8, 1),
        date(2026, 8, 5),
        today,
        given,
        given_today,
    )
    assert found == next_kind


def test_notices_go_from_nine_in_the_morning_in_phnom_penh(notice_database: HrDatabase) -> None:
    hour = "SELECT app.rent_notice_hour_reached(%s)"
    url = notice_database.owner_url
    # 09:00 in Phnom Penh is 02:00 UTC.
    assert run(url, hour, datetime(2026, 8, 10, 1, 59, 59, tzinfo=UTC)) is False
    assert run(url, hour, datetime(2026, 8, 10, 2, 0, 0, tzinfo=UTC)) is True
    assert run(url, hour, datetime(2026, 8, 10, 16, 59, 59, tzinfo=UTC)) is True
    # 17:00 UTC is midnight in Phnom Penh: the next day waits for its own 09:00.
    assert run(url, hour, datetime(2026, 8, 10, 17, 0, 0, tzinfo=UTC)) is False


def test_a_linked_tenant_gets_the_first_notice_by_itself_once_a_day(
    notice_database: HrDatabase, linked: dict[str, Any]
) -> None:
    db = notice_database
    assert events(db, linked["line"]) == []
    shown = assessment(db, linked["line"])
    assert shown["assessment"]["telegram_linked"] is True
    assert shown["assessment"]["ten_day_notice_eligible"] is True
    assert shown["assessment"]["thirty_day_default_eligible"] is False

    assert run(db.owner_url, SEND, db.property_id, db.manager) == 1
    recorded = events(db, linked["line"])
    assert [event["kind"] for event in recorded] == ["TEN_DAY_NOTICE"]
    first = recorded[0]
    assert first["remaining"] == RENT and first["actor"] == db.manager
    assert first["how"].startswith("Sent by Telegram: ")
    assert first["reference"] and "DL-237" in first["reason"]
    # One notice a day: the second waits for tomorrow.
    assert run(db.owner_url, SEND, db.property_id, db.manager) == 0
    assert [event["kind"] for event in events(db, linked["line"])] == ["TEN_DAY_NOTICE"]

    with psycopg.connect(db.owner_url) as connection:
        audit = connection.execute(
            "SELECT action, source, outcome, actor_id, lease_id FROM app.audit_events "
            "WHERE entity_type = 'rent_nonpayment_event' AND entity_id = %s",
            (first["id"],),
        ).fetchone()
    assert audit == (
        "rent_nonpayment.event_post",
        "SCHEDULED",
        "SUCCEEDED",
        db.manager,
        linked["lease"],
    )

    # The Tenant bot sends it with the words of the first notice.
    assert run(db.runtime_url, QUEUE, db.property_id, db.manager) == 1
    with psycopg.connect(db.owner_url) as connection:
        message = connection.execute(
            "SELECT outbox.text_code, outbox.chat_id, outbox.language, outbox.details, "
            "notice.warning_kind FROM app.telegram_warning_notices AS notice "
            "JOIN app.telegram_outbox AS outbox ON outbox.id = notice.outbox_id "
            "WHERE notice.rent_event_id = %s",
            (first["id"],),
        ).fetchone()
    assert message is not None
    assert message[:3] == ("tenant.rent_notice_1", TENANT, "en") and message[4] == "RENT_10"
    details = message[3]
    assert details["unit"] == "Unit 612" and details["amount"] == "$800.00"
    assert details["invoice"] and details["due"] and details["date"] and details["letter_day"]

    after = assessment(db, linked["line"])["assessment"]
    assert after["ten_day_notice_recorded"] is True and after["ten_day_notice_eligible"] is False
    assert after["twenty_day_warning_eligible"] is True


def test_the_run_keeps_the_hour_and_needs_the_telegram_right(
    notice_database: HrDatabase, linked: dict[str, Any], not_linked: dict[str, Any]
) -> None:
    db = notice_database
    assert linked and not_linked
    refused(db.runtime_url, "42501", RUN, db.property_id, db.staff)
    # The first notice of today is given already, so the run adds nothing at any hour.
    assert run(db.runtime_url, RUN, db.property_id, db.manager) == 0
    # The step without the hour is not open to the application's database account.
    with psycopg.connect(db.runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(SEND, (db.property_id, db.manager))
    with psycopg.connect(db.runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT count(*) FROM app.rent_nonpayment_events")


def test_a_tenant_without_telegram_gets_no_notice_by_itself(
    notice_database: HrDatabase, not_linked: dict[str, Any]
) -> None:
    db = notice_database
    assert run(db.owner_url, SEND, db.property_id, db.manager) == 0
    assert events(db, not_linked["line"]) == []
    shown = assessment(db, not_linked["line"])
    # Staff see that the first notice is due and that nobody is linked: the paper letter.
    assert shown["assessment"]["telegram_linked"] is False and shown["case_id"] is None
    assert shown["assessment"]["ten_day_notice_eligible"] is True
    with psycopg.connect(db.owner_url) as connection:
        page = connection.execute(
            "SELECT app.rent_nonpayment_alert_page(%s, 100, NULL)", (db.property_id,)
        ).fetchone()
    assert page is not None
    assert str(not_linked["line"]) in {row["rent_invoice_line_id"] for row in page[0]["items"]}
    # Staff give the paper letter and record it; nothing goes to Telegram for this Lease.
    # Home asks for it too. The linked tenant's notices go by themselves and are not listed.
    assert letters_due(db) == (
        {"count": 1, "day_20": 1, "day_30": 0},
        [("letter_day_20", "Unit 613")],
    )
    by_hand(db, not_linked["line"], "TEN_DAY_NOTICE")
    assert [event["kind"] for event in events(db, not_linked["line"])] == ["TEN_DAY_NOTICE"]
    assert run(db.runtime_url, QUEUE, db.property_id, db.manager) == 0


def test_the_termination_letter_needs_the_three_notices(
    notice_database: HrDatabase, linked: dict[str, Any]
) -> None:
    db = notice_database
    line = linked["line"]
    assert [event["kind"] for event in events(db, line)] == ["TEN_DAY_NOTICE"]
    for given in ("TWENTY_DAY_WARNING", "TWENTY_FIVE_DAY_NOTICE"):
        with pytest.raises(psycopg.errors.CheckViolation):
            by_hand(db, line, LETTER)
        assert assessment(db, line)["assessment"]["thirty_day_default_eligible"] is False
        by_hand(db, line, given)
    shown = assessment(db, line)["assessment"]
    assert shown["thirty_day_default_eligible"] is True
    assert shown["twenty_five_day_notice_recorded"] is True
    # Home shows the termination letter as ready, next to the notice of Unit 613.
    assert letters_due(db) == (
        {"count": 2, "day_20": 1, "day_30": 1},
        [("letter_day_20", "Unit 613"), ("letter_day_30", "Unit 612")],
    )
    # A notice is given once.
    with pytest.raises(psycopg.errors.UniqueViolation):
        by_hand(db, line, "TWENTY_FIVE_DAY_NOTICE")
    by_hand(db, line, LETTER)
    assert [event["kind"] for event in events(db, line)] == [*NOTICES, LETTER]
    # Nothing more goes by itself after the letter.
    assert run(db.owner_url, SEND, db.property_id, db.manager) == 0

    assert run(db.runtime_url, QUEUE, db.property_id, db.manager) == 3
    with psycopg.connect(db.owner_url) as connection:
        codes = connection.execute(
            "SELECT notice.warning_kind, outbox.text_code "
            "FROM app.telegram_warning_notices AS notice "
            "JOIN app.telegram_outbox AS outbox ON outbox.id = notice.outbox_id "
            "JOIN app.rent_nonpayment_events AS event ON event.id = notice.rent_event_id "
            "ORDER BY event.occurred_at, event.id"
        ).fetchall()
    assert codes == [
        ("RENT_10", "tenant.rent_notice_1"),
        ("RENT_20", "tenant.rent_warning"),
        ("RENT_25", "tenant.rent_notice_3"),
        ("RENT_30", "tenant.rent_default"),
    ]


def test_paying_the_rent_in_full_stops_the_notices_and_a_part_payment_does_not(
    notice_database: HrDatabase, linked: dict[str, Any]
) -> None:
    db = notice_database
    day = run(db.owner_url, "SELECT app.gl_today(%s)", db.property_id)
    paid, paid_line = rent_invoice(db, linked["lease"], linked["customer"], day - timedelta(110))
    part, part_line = rent_invoice(db, linked["lease"], linked["customer"], day - timedelta(140))
    pay_rent(db, linked["customer"], paid, paid_line, RENT)
    pay_rent(db, linked["customer"], part, part_line, 30_000)

    assert run(db.owner_url, SEND, db.property_id, db.manager) == 1
    assert events(db, paid_line) == []
    given = events(db, part_line)
    assert [event["kind"] for event in given] == ["TEN_DAY_NOTICE"]
    assert given[0]["remaining"] == RENT - 30_000
