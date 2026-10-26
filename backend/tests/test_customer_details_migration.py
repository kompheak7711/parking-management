"""Real PostgreSQL coverage for the Customer date of birth, gender and nationality.

DL-078 answer 3 (owner, 2026-10-20), SEC-006, DB-CUST-001, BR-CUST-003 (V1-058 R2c, migration
`20270307_226`).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import Error

from property_rental.customer import CustomerService, PostgresCustomerRepository
from property_rental.customer_api import PostgresCustomerResourceFlow
from test_customer_id_document_number_migration import committed_actor, runtime_url, unique_number
from test_customer_migration import migrated_database_url

__all__ = ["migrated_database_url"]


def test_the_details_are_stored_returned_and_audited_without_their_values(
    migrated_database_url: str,
) -> None:
    actor_id, _ = committed_actor(migrated_database_url)
    service = CustomerService(PostgresCustomerRepository(runtime_url(), actor_id))
    created = service.create(
        uuid4(),
        legal_name="Srey Mom",
        id_document_number=unique_number(),
        date_of_birth=date(1987, 3, 9),
        gender="FEMALE",
        nationality=" Cambodian ",
    )
    assert (created.date_of_birth, created.gender, created.nationality) == (
        date(1987, 3, 9),
        "FEMALE",
        "Cambodian",
    )
    cleared = service.update(
        created,
        legal_name=created.legal_name,
        phone_number=None,
        email_address=None,
        contact_address=None,
        memo=None,
        gender=None,
    )
    assert (cleared.date_of_birth, cleared.gender, cleared.nationality) == (
        date(1987, 3, 9),
        None,
        "Cambodian",
    )
    with psycopg.connect(runtime_url()) as runtime:
        rows = runtime.execute(
            "SELECT action, previous_state, resulting_state FROM app.audit_events "
            "WHERE customer_id = %s ORDER BY occurred_at",
            (created.customer_id,),
        ).fetchall()
    assert [row[0] for row in rows] == ["customer.created", "customer.updated"]
    created_state, updated_state = rows[0][2], rows[1][2]
    assert isinstance(created_state, dict) and isinstance(updated_state, dict)
    assert created_state["date_of_birth_recorded"] is True
    assert created_state["gender_recorded"] is True
    assert updated_state["gender_recorded"] is False
    assert updated_state["gender_changed"] is True
    assert updated_state["date_of_birth_changed"] is False
    assert updated_state["nationality_changed"] is False
    for row in rows:
        text = f"{row[1]} {row[2]}"
        assert "1987" not in text and "FEMALE" not in text and "Cambodian" not in text


def test_the_database_refuses_details_outside_the_rules(migrated_database_url: str) -> None:
    actor_id, _ = committed_actor(migrated_database_url)
    tomorrow = date.today() + timedelta(days=2)
    with psycopg.connect(runtime_url()) as runtime:
        for date_of_birth, gender, nationality in (
            (date(1899, 12, 31), None, None),
            (tomorrow, None, None),
            (None, "OTHER", None),
            (None, None, "x" * 65),
        ):
            with pytest.raises(Error) as refused:
                runtime.execute(
                    "SELECT * FROM app.create_customer(%s, 'Refused', NULL, NULL, NULL, NULL,"
                    " %s, %s, %s, %s, %s, %s)",
                    (
                        uuid4(),
                        actor_id,
                        uuid4(),
                        unique_number(),
                        date_of_birth,
                        gender,
                        nationality,
                    ),
                )
            assert refused.value.sqlstate == "22023"
            runtime.rollback()
        with pytest.raises(Error) as direct:
            runtime.execute("SELECT app.assert_customer_details(NULL, NULL, NULL)")
        assert direct.value.sqlstate == "42501"
    with psycopg.connect(migrated_database_url) as admin:
        checks = admin.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'app.customers'::regclass AND contype = 'c' "
            "AND conname IN ('customers_date_of_birth_range', 'customers_gender_supported', "
            "'customers_nationality_normalized')"
        ).fetchall()
    assert len(checks) == 3


def test_an_update_through_the_earlier_overload_keeps_the_details(
    migrated_database_url: str,
) -> None:
    actor_id, _ = committed_actor(migrated_database_url)
    service = CustomerService(PostgresCustomerRepository(runtime_url(), actor_id))
    number = unique_number()
    created = service.create(
        uuid4(),
        legal_name="Dara Sok",
        id_document_number=number,
        date_of_birth=date(1979, 1, 2),
        gender="MALE",
        nationality="Khmer",
    )
    with psycopg.connect(runtime_url()) as runtime:
        row = runtime.execute(
            "SELECT * FROM app.update_customer(%s, 'Dara Sok K.', NULL, NULL, NULL, NULL,"
            " %s, %s, %s, %s)",
            (created.customer_id, created.version, actor_id, uuid4(), number),
        ).fetchone()
        assert row is not None
        stored = runtime.execute(
            "SELECT date_of_birth, gender, nationality FROM app.customers WHERE id = %s",
            (created.customer_id,),
        ).fetchone()
    assert stored == (date(1979, 1, 2), "MALE", "Khmer")


def test_the_details_are_kept_in_the_command_replay(migrated_database_url: str) -> None:
    actor_id, property_id = committed_actor(migrated_database_url)
    flow = PostgresCustomerResourceFlow(runtime_url())
    arguments: dict[str, object] = {
        "customer_id": uuid4(),
        "legal_name": "Replay Details",
        "phone_number": None,
        "email_address": None,
        "contact_address": None,
        "memo": None,
        "confirmed_distinct": False,
        "actor_id": str(actor_id),
        "idempotency_key": uuid4(),
        "request_digest": "f" * 64,
        "id_document_number": unique_number(),
        "date_of_birth": date(2001, 12, 1),
        "gender": "FEMALE",
        "nationality": "Thai",
    }
    created = flow.create(property_id, **arguments)  # type: ignore[arg-type]
    replayed = flow.create(property_id, **arguments)  # type: ignore[arg-type]
    assert replayed == created
    assert (
        replayed.customer.date_of_birth,
        replayed.customer.gender,
        replayed.customer.nationality,
    ) == (date(2001, 12, 1), "FEMALE", "Thai")
    detail, _ = flow.detail(created.customer.customer_id, limit=5, cursor=None)
    assert detail.customer.nationality == "Thai"


def test_v1_058_r2c_is_forward_only_and_follows_v1_059_part_b(migrated_database_url: str) -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("20270307_226")
    assert revision is not None and revision.down_revision == "20270306_225"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with psycopg.connect(migrated_database_url) as admin:
        rows = admin.execute(
            "SELECT p.oid::regprocedure::text, "
            "has_function_privilege('prm_runtime', p.oid, 'EXECUTE'), "
            "has_function_privilege('public', p.oid, 'EXECUTE') "
            "FROM pg_proc AS p JOIN pg_namespace AS n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'app' AND p.oid::regprocedure::text LIKE '%date,text,text)' "
            "AND p.proname LIKE '%customer%'"
        ).fetchall()
    assert {str(name): (bool(runtime), bool(public)) for name, runtime, public in rows} == {
        "app.assert_customer_details(date,text,text)": (False, False),
        "app.create_customer(uuid,text,text,text,text,text,uuid,uuid,text,date,text,text)": (
            True,
            False,
        ),
        "app.update_customer("
        "uuid,text,text,text,text,text,integer,uuid,uuid,text,date,text,text)": (True, False),
        "app.execute_customer_create("
        "uuid,uuid,text,uuid,text,text,text,text,text,uuid,text,date,text,text)": (True, False),
        "app.execute_customer_update("
        "uuid,uuid,text,uuid,text,text,text,text,text,integer,uuid,text,date,text,text)": (
            True,
            False,
        ),
    }


def test_the_customers_page_search_finds_a_whole_id_number_and_never_shows_it(
    migrated_database_url: str,
) -> None:
    """DL-078 answer 4 and its reading: whole number only; the list shows no number."""
    actor_id, property_id = committed_actor(migrated_database_url)
    number = unique_number()
    created = CustomerService(PostgresCustomerRepository(runtime_url(), actor_id)).create(
        uuid4(), legal_name="Searchable Person", id_document_number=number
    )
    flow = PostgresCustomerResourceFlow(runtime_url())

    def found(query: str) -> set[object]:
        page = flow.list(property_id, query=query, active=None, limit=50, cursor=None)
        assert all(item.customer.id_document_number is None for item in page.items)
        return {item.customer.customer_id for item in page.items}

    assert created.customer_id in found(number)
    assert created.customer_id in found(number.lower().replace(" ", "").replace("-", ""))
    assert created.customer_id not in found(number[:5])
