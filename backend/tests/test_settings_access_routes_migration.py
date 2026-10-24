"""Login sub-slice L5: the Settings routes need Settings access, through the real app.

DL-074 answer 2, DL-075, DL-081, SEC-002, SEC-003, SEC-016, API-008 (owner answer (a) to
Q-2026-10-21-151; L1c review round 2). One throwaway database at head; the Property is set up
through `configure_postgres_property`, which seeds the default bundles. The Owner, a Manager with
the default Manager bundle and a Staff account with a sign-in code sign in with their password and
sign-in code through `PostgresAuthenticationFlow` (the Staff account uses its code at every sign-in,
as L1e needs before Settings access); the requests go through `create_app` as the
runtime role with the session cookie, the configured Origin and the CSRF pair.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from property_rental.access_admin_flow import PostgresAccessAdministrationFlow
from property_rental.app import create_app
from property_rental.auth_flow import PostgresAuthenticationFlow
from property_rental.property import configure_postgres_property
from property_rental.settings import Settings
from test_access_admin_flow_migration import allow_admin_actions, context
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_sign_in_code_migration import (
    KEY,
    PASSWORD,
    Account,
    CodeDatabase,
    add_account,
    code_for,
    fresh_step,
)

ORIGIN = "https://localhost"
DONE = [201, 201, 200, 200, 200]
CSRF = "l5-csrf-token"
ASSIGN_BUNDLE = (
    "INSERT INTO app.user_role_assignments(assignment_id,actor_id,role_bundle_id,property_id,"
    "provenance) VALUES (%s,%s,%s,%s,'login-slice-l5-test')"
)
ADD_SERVICE = (
    "INSERT INTO app.property_services(id,property_id,service_code,display_name,configured_by,"
    "created_by,updated_by) VALUES (%s,%s,'TRASH','Trash Collection',%s,%s,%s)"
)
COUNTS = (
    "SELECT (SELECT count(*) FROM app.service_rates), (SELECT count(*) FROM app.utility_rates), "
    "(SELECT version FROM app.property_configuration WHERE property_id = %s)"
)


@dataclass(frozen=True)
class RouteDatabase:
    owner_url: str
    runtime_url: str
    property_id: uuid.UUID
    service_id: uuid.UUID
    owner: Account
    manager: Account
    staff: Account


@pytest.fixture(scope="module")
def route_database(migrated_database_url: str) -> Iterator[RouteDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_settings_routes") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        runtime_url = _url_with_database(
            runtime_database_url(), urlsplit(temporary).path.lstrip("/")
        )
        codes = CodeDatabase(temporary, runtime_url)
        owner = add_account(codes, f"l5-owner-{uuid.uuid4().hex[:6]}", account_class="owner")
        manager = add_account(codes, f"l5-manager-{uuid.uuid4().hex[:6]}")
        staff = add_account(
            codes, f"l5-staff-{uuid.uuid4().hex[:6]}", account_class="staff", mfa="required"
        )
        property_id = uuid.uuid4()
        configure_postgres_property(
            runtime_url, property_id, name="Riverside", actor_id=owner.actor_id
        )
        service_id = uuid.uuid4()
        with psycopg.connect(temporary) as setup:
            bundle = setup.execute(
                "SELECT role_bundle_id FROM app.role_bundles "
                "WHERE property_id = %s AND name = 'Manager'",
                (property_id,),
            ).fetchone()
            assert bundle is not None
            setup.execute(ASSIGN_BUNDLE, (uuid.uuid4(), manager.actor_id, bundle[0], property_id))
            setup.execute(
                ADD_SERVICE,
                (service_id, property_id, owner.actor_id, owner.actor_id, owner.actor_id),
            )
            setup.commit()
        allow_admin_actions(temporary, owner.actor_id)
        yield RouteDatabase(temporary, runtime_url, property_id, service_id, owner, manager, staff)


def signed_in(database: RouteDatabase, account: Account) -> TestClient:
    """A client of the real app holding the account's session after password and code."""
    flow = PostgresAuthenticationFlow(database.runtime_url, totp_protection_key=KEY)
    started = flow.login(
        username=account.username, password=PASSWORD, request_source="desk", request_id="l5"
    )
    assert started.preauth_token is not None
    done = flow.complete_mfa(
        preauth_token=started.preauth_token,
        method="totp",
        code=code_for(account, fresh_step(CodeDatabase(database.owner_url, database.runtime_url))),
        request_id="l5",
    )
    assert done.session_token is not None
    client = TestClient(create_app(Settings(database_url=SecretStr(database.runtime_url))))
    client.headers.update(
        {
            "Origin": ORIGIN,
            "X-CSRF-Token": CSRF,
            "Cookie": f"__Host-prm_session={done.session_token}; __Host-prm_csrf={CSRF}",
        }
    )
    return client


def counts(database: RouteDatabase) -> tuple[Any, ...]:
    with psycopg.connect(database.owner_url) as connection:
        row = connection.execute(COUNTS, (database.property_id,)).fetchone()
    assert row is not None
    return tuple(row)


def settings_calls(
    database: RouteDatabase, client: TestClient, version: int, year: int = 2029
) -> list[int]:
    """The five Settings changes: a Service rate and a Utility Rate from 1 January of `year`
    (one rate per day each), the Property, its Payment Methods and the one-time charge due
    days, each with the current Property version."""
    property_id = database.property_id
    answers = [
        client.post(
            f"/api/v1/properties/{property_id}/service-rates",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "property_service_id": str(database.service_id),
                "monthly_rate_usd_cents": 1250,
                "effective_date": f"{year}-01-01",
            },
        ).status_code,
        client.post(
            f"/api/v1/properties/{property_id}/utility-rates",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "utility_type": "WATER",
                "measurement_unit_code": "M3",
                "rate_usd_per_unit": "0.5",
                "effective_date": f"{year}-01-01",
                "notice_at": "2026-10-24T08:00:00+07:00",
                "notice_evidence": "Notice given at the front desk",
            },
        ).status_code,
    ]
    changed = client.patch(
        f"/properties/{property_id}",
        headers={"If-Match": f'"{version}"'},
        json={"name": "Riverside", "address_text": f"Street {version}"},
    )
    answers.append(changed.status_code)
    if changed.status_code == 200:
        version = int(changed.json()["data"]["version"])
    configured = client.patch(
        f"/properties/{property_id}/configuration",
        headers={"If-Match": f'"{version}"'},
        json={
            "timezone_name": "Asia/Phnom_Penh",
            "payment_methods": [{"code": "CASH", "display_name": "Cash", "accepted": True}],
        },
    )
    answers.append(configured.status_code)
    if configured.status_code == 200:
        version = int(configured.json()["data"]["version"])
    answers.append(
        client.post(
            f"/api/v1/properties/{property_id}/one-time-charge-due-days",
            headers={"If-Match": f'"{version}"'},
            json={"days": 10, "reason": "Owner policy"},
        ).status_code
    )
    return answers


def current_version(database: RouteDatabase) -> int:
    return int(counts(database)[2])


def test_the_settings_routes_need_settings_access_and_the_owner_always_has_it(
    route_database: RouteDatabase,
) -> None:
    """L1c review round 2: the Manager, with every bundle capability of the default Manager
    bundle (`service_rates.manage`, `utility_rates.manage` and `property.manage` included), is
    refused the five Settings changes and nothing changes; once the Owner gives the Manager
    Settings access the same five succeed; the Owner succeeds with no per-user grant; a Staff
    account with a sign-in code and Settings access succeeds too; before any Settings access the
    Manager creates and updates a Unit with `property.manage`."""
    database = route_database
    manager = signed_in(database, database.manager)
    before = counts(database)
    assert settings_calls(database, manager, current_version(database)) == [403] * 5
    assert counts(database) == before
    # Review round 1: before any Settings access, `property.manage` alone creates and updates a
    # Unit.
    created = manager.post(
        f"/properties/{database.property_id}/units",
        json={"unit_number": "L5-101", "floor": "1", "unit_type": "STUDIO", "status": "VACANT"},
    )
    assert created.status_code == 201
    unit_id = created.json()["data"]["unit_id"]
    assert manager.get(f"/units/{unit_id}").status_code == 200
    updated = manager.patch(f"/units/{unit_id}", headers={"If-Match": '"1"'}, json={"floor": "2"})
    assert updated.status_code == 200

    admin = PostgresAccessAdministrationFlow(database.runtime_url)
    for account in (database.manager, database.staff):
        admin.give_settings_access(
            user_id=account.actor_id,
            property_id=str(database.property_id),
            reason="Keeps the rates",
            audit_context=context(database.owner.actor_id),
        )
    assert settings_calls(database, manager, current_version(database), 2030) == DONE
    owner = signed_in(database, database.owner)
    assert settings_calls(database, owner, current_version(database), 2031) == DONE
    staff = signed_in(database, database.staff)
    assert settings_calls(database, staff, current_version(database), 2032) == DONE

    # Staff reads the Unit (`units.read` is in no bundle of this Staff account), so 403.
    assert staff.get(f"/units/{unit_id}").status_code == 403
