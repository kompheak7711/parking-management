"""Real PostgreSQL HTTP scope, source selection, replay and read-only evaluation."""

from __future__ import annotations

from datetime import date
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import PostgresInvoiceService, VoidInvoiceCommand
from property_rental.lease_enforcement import (
    NONPAYMENT_EVENT,
    NONPAYMENT_OPEN,
    NONPAYMENT_READ,
    WARNING_CREATE,
    WARNING_READ,
    LeaseEnforcementAuthorizationError,
    LeaseEnforcementInvalidError,
    LeaseEnforcementNotFoundError,
    LeaseEnforcementUnavailableError,
)
from property_rental.lease_enforcement_context import EnforcementPage, PostgresEnforcementContext
from property_rental.nonpayment_evaluation import ScheduledRentNonpaymentEvaluator
from test_billing_service_migration import admin_database_url
from test_credit_refund_api_migration import headers
from test_invoice_migration import financial_database_url, invoice_api_actor, runtime_database_url
from test_lease_enforcement_migration import source, staff
from test_payment_api_migration import api
from test_reservation_migration import migrated_database_url  # noqa: F401


def data(reply: object, status: int = 200) -> dict[str, object]:
    from httpx import Response

    assert isinstance(reply, Response)
    assert reply.status_code == status, reply.text
    assert reply.headers["cache-control"] == "private, no-store"
    assert reply.headers["vary"] == "Cookie"
    return cast(dict[str, object], reply.json()["data"])


def unchanged(url: str) -> dict[str, object]:
    tables = (
        "leases",
        "occupancies",
        "units",
        "invoices",
        "invoice_lines",
        "payments",
        "payment_allocations",
        "rent_nonpayment_cases",
        "rent_nonpayment_events",
        "lease_violation_warnings",
        "audit_events",
        "lease_enforcement_commands",
    )
    with psycopg.connect(url) as connection:
        return {
            table: connection.execute(
                sql.SQL(
                    "SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM app.{} t"
                ).format(sql.Identifier(table))
            ).fetchone()
            for table in tables
        }


def opened(client: TestClient, human: UUID, lease: UUID, line: UUID) -> dict[str, object]:
    return data(
        client.post(
            f"/api/v1/leases/{lease}/rent-nonpayment-cases",
            json={"rent_invoice_line_id": str(line), "reason": "Record scoped case"},
            headers=headers(human),
        ),
        201,
    )


def test_enforcement_discovery_requires_exact_fresh_separate_property_grants(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, lease, _, line = source(migrated_database_url)
    context = PostgresEnforcementContext(runtime_database_url())
    writer = staff(human, prop, NONPAYMENT_OPEN)
    result = context.workspaces(EnforcementPage(1), actor=writer)
    items = cast(list[dict[str, object]], result["items"])
    assert len(items) == 1 and items[0]["property_id"] == str(prop)
    assert cast(dict[str, bool], items[0]["capabilities"])[NONPAYMENT_OPEN]
    assert not cast(dict[str, bool], items[0]["capabilities"])[NONPAYMENT_READ]
    before = unchanged(migrated_database_url)
    # The shared fixture reuses a Property; verify all authorized Leases across pages.
    with psycopg.connect(migrated_database_url) as connection:
        expected_leases = [
            str(row[0])
            for row in connection.execute(
                "SELECT l.id FROM app.leases l JOIN app.units u ON u.id=l.unit_id "
                "WHERE u.property_id=%s ORDER BY l.id",
                (prop,),
            ).fetchall()
        ]
    selected_leases: list[str] = []
    after: UUID | None = None
    while True:
        selected = context.read(
            prop, "LEASES", actor=writer, purpose="NONPAYMENT", page=EnforcementPage(50, after)
        )
        page_items = cast(list[dict[str, object]], selected["items"])
        assert len(page_items) <= 50
        assert all(row["property_id"] == str(prop) for row in page_items)
        page_ids = [str(row["id"]) for row in page_items]
        assert page_ids == sorted(set(page_ids))
        assert all(identity not in selected_leases for identity in page_ids)
        selected_leases.extend(page_ids)
        cursor = selected["next_cursor"]
        if cursor is None:
            break
        assert page_ids and str(cursor) == page_ids[-1]
        next_after = UUID(str(cursor))
        assert after is None or next_after > after
        assert len(selected_leases) < len(expected_leases)
        after = next_after
    assert selected_leases == expected_leases and str(lease) in selected_leases
    sources = context.read(prop, "SOURCES", actor=writer, lease_id=lease)
    assert [
        row["rent_invoice_line_id"] for row in cast(list[dict[str, object]], sources["items"])
    ] == [str(line)]
    assert unchanged(migrated_database_url) == before
    with pytest.raises(LeaseEnforcementAuthorizationError):
        context.read(prop, "ACTION_CASES", actor=writer, lease_id=lease)
    with pytest.raises(LeaseEnforcementNotFoundError):
        context.resolve("LEASE", lease, WARNING_CREATE, actor=writer)
    unrelated = AuthenticatedActor(
        str(human),
        frozenset(
            {
                CapabilityGrant("billing.generate", frozenset({str(prop)})),
                CapabilityGrant(NONPAYMENT_READ, frozenset({str(prop).upper()})),
            }
        ),
    )
    assert context.workspaces(EnforcementPage(), actor=unrelated)["items"] == []
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(LeaseEnforcementAuthorizationError):
        context.workspaces(EnforcementPage(), actor=writer)


def test_enforcement_http_canonical_warning_history_and_mutation_only_context(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, lease, _, _ = source(migrated_database_url)
    writer = api(staff(human, prop, WARNING_CREATE))
    path = f"/api/v1/leases/{lease}/violation-warnings"
    context = data(writer.get(f"/api/v1/leases/{lease}/violation-warning-context"))
    today = context["business_date"]
    body = {
        "warning_sequence": 1,
        "violation_date": today,
        "warning_date": today,
        "violation_description": "Documented\nviolation",
        "lease_provision": "Signed provision 2",
        "communication_record": "Delivered with witness",
        "reason": "Record explicit warning",
    }
    selected_headers = {
        **headers(human),
        "X-Request-ID": "original-warning",
        "X-Financial-Property-ID": str(prop),
    }
    before = unchanged(migrated_database_url)
    first = writer.post(path, json=body, headers=selected_headers)
    warning = data(first, 201)
    assert warning["lease_id"] == str(lease) and warning["warning_sequence"] == 1
    assert first.json()["meta"] == {"request_id": "original-warning", "property_id": str(prop)}
    replay = writer.post(
        path, json=body, headers={**selected_headers, "X-Request-ID": "replayed-warning"}
    )
    assert replay.status_code == 201 and replay.json() == first.json()
    assert writer.get(path).status_code == 404
    reader = api(staff(human, prop, WARNING_READ))
    assert data(reader.get(path))["items"] == [warning]
    assert (
        reader.post(path, json={**body, "warning_sequence": 2}, headers=headers(human)).status_code
        == 404
    )
    assert (
        data(writer.get(f"/api/v1/leases/{lease}/violation-warning-context"))["suggested_sequence"]
        == 2
    )
    after = unchanged(migrated_database_url)
    assert {
        k: v
        for k, v in before.items()
        if k not in {"lease_violation_warnings", "audit_events", "lease_enforcement_commands"}
    } == {
        k: v
        for k, v in after.items()
        if k not in {"lease_violation_warnings", "audit_events", "lease_enforcement_commands"}
    }
    assert (
        writer.post(path, json={**body, "reason": "Different"}, headers=selected_headers).json()[
            "error"
        ]["code"]
        == "IDEMPOTENCY_KEY_REUSED"
    )


def test_enforcement_http_case_and_event_capabilities_do_not_imply_each_other(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, lease, _, line = source(migrated_database_url)
    manager, poster, reader = [
        api(staff(human, prop, cap)) for cap in (NONPAYMENT_OPEN, NONPAYMENT_EVENT, NONPAYMENT_READ)
    ]
    case = opened(manager, human, lease, line)
    path = f"/api/v1/rent-nonpayment-cases/{case['id']}"
    assert manager.get(path).status_code == poster.get(path).status_code == 404
    assert manager.get(path + "/action-context").status_code == 404
    minimal = data(poster.get(path + "/action-context"))
    assert minimal["id"] == case["id"] and not {
        "opened_by",
        "opened_at",
        "event_count",
    }.intersection(minimal)
    assert data(reader.get(path))["id"] == case["id"]
    assert data(reader.get(f"/api/v1/leases/{lease}/rent-nonpayment-cases"))["total"] == 1
    assert data(reader.get(path + "/events"))["items"] == []
    body = {
        "event_kind": "TWENTY_DAY_WARNING",
        "reason": "Issue documented Notice",
        "notice_document_reference": "Notice1",
    }
    assert manager.post(path + "/events", json=body, headers=headers(human)).status_code == 404
    notice = data(poster.post(path + "/events", json=body, headers=headers(human)), 201)
    assert notice["rent_nonpayment_case_id"] == case["id"]
    assert (
        cast(list[dict[str, object]], data(reader.get(path + "/events"))["items"])[0]["id"]
        == notice["id"]
    )
    assert poster.get(path + "/events").status_code == 404
    assert reader.get(f"/api/v1/leases/{lease}/violation-warnings").status_code == 404


def test_enforcement_http_lost_reply_then_void_keeps_original_replay_and_current_zero(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, lease, invoice, line = source(migrated_database_url)
    client = api(staff(human, prop))
    path = f"/api/v1/leases/{lease}/rent-nonpayment-cases"
    body = {"rent_invoice_line_id": str(line), "reason": "Open original case"}
    original_headers = {**headers(human), "X-Request-ID": "original-case"}
    first = client.post(path, json=body, headers=original_headers)
    case = data(first, 201)
    casepath = f"/api/v1/rent-nonpayment-cases/{case['id']}"
    amount = cast(dict[str, object], cast(dict[str, object], case["assessment"])["remaining_rent"])[
        "minor_units"
    ]
    assert isinstance(amount, int) and amount > 0
    with psycopg.connect(migrated_database_url) as connection:
        version = connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert version is not None
    PostgresInvoiceService(runtime_database_url(), financial_database_url()).void(
        prop,
        invoice,
        VoidInvoiceCommand(uuid4(), "Cancel issued source", int(version[0])),
        actor=invoice_api_actor(human, prop),
    )
    assert data(client.get(f"/api/v1/leases/{lease}/rent-nonpayment-sources"))["items"] == []
    replay = client.post(
        path, json=body, headers={**original_headers, "X-Request-ID": "lost-reply-retry"}
    )
    assert replay.status_code == 201 and replay.json() == first.json()
    current = cast(dict[str, object], data(client.get(casepath))["assessment"])
    assert current["source_applicable"] is False and current["remaining_rent"] == {
        "currency": "USD",
        "minor_units": 0,
    }
    assert current["twenty_day_warning_eligible"] is False
    following = data(
        client.post(
            casepath + "/events",
            json={
                "event_kind": "AUTHORIZED_FOLLOW_UP",
                "reason": "Document cancellation follow-up",
                "authorization_reference": "Management approval",
            },
            headers=headers(human),
        ),
        201,
    )
    assert following["remaining_rent_usd_cents"] == 0
    assert (
        client.post(
            casepath + "/events",
            json={"event_kind": "CURE", "reason": "Wrong cancellation event"},
            headers=headers(human),
        ).status_code
        == 409
    )
    assert client.post(path, json=body, headers=headers(human)).status_code == 409
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.lease_enforcement_commands WHERE "
            "action='OPEN_CASE' AND lease_id=%s",
            (lease,),
        ).fetchone() == (1,)


@pytest.mark.parametrize(
    "field,value",
    [
        ("warning_sequence", True),
        ("warning_sequence", 1.5),
        ("warning_date", "2026-09-01T00:00:00Z"),
        ("violation_description", " trimmed "),
        ("lease_provision", "\x00"),
        ("remaining_rent_usd_cents", 1),
    ],
)
def test_enforcement_http_strict_inputs_never_write(
    migrated_database_url: str,  # noqa: F811
    field: str,
    value: object,
) -> None:
    human, prop, _, lease, _, _ = source(migrated_database_url)
    client = api(staff(human, prop))
    body = {
        "warning_sequence": 1,
        "violation_date": "2026-09-01",
        "warning_date": "2026-09-01",
        "violation_description": "Violation",
        "lease_provision": "Signed rule",
        "communication_record": "Delivered",
        "reason": "Record",
    }
    before = unchanged(migrated_database_url)
    reply = client.post(
        f"/api/v1/leases/{lease}/violation-warnings",
        json={**body, field: value},
        headers=headers(human),
    )
    assert reply.status_code == 422 and unchanged(migrated_database_url) == before


def test_enforcement_http_scope_query_csrf_and_duplicate_guards(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, _, lease, _, line = source(migrated_database_url)
    client = api(staff(human, prop))
    path = f"/api/v1/leases/{lease}/rent-nonpayment-cases"
    body = {"rent_invoice_line_id": str(line), "reason": "Scoped case"}
    before = unchanged(migrated_database_url)
    assert (
        client.post(
            path, json=body, headers={**headers(human), "X-Financial-Property-ID": str(uuid4())}
        ).status_code
        == 404
    )
    bad = headers(human)
    bad.pop("X-CSRF-Token")
    assert client.post(path, json=body, headers=bad).status_code == 403
    assert (
        client.post(
            path, json=body, headers={**headers(human), "Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )
    selected = [*headers(human).items(), ("Idempotency-Key", str(uuid4()))]
    assert client.post(path, json=body, headers=selected).status_code == 400
    for query in (
        "limit=01",
        "limit=0",
        "limit=101",
        "limit=1&limit=2",
        "offset=-1",
        "status=VOID",
    ):
        assert client.get(path + "?" + query).status_code == 400
    assert client.post(path + "?force=true", json=body, headers=headers(human)).status_code == 400
    assert unchanged(migrated_database_url) == before


def test_enforcement_alerts_include_unopened_rent_and_never_create_business_events(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, lease, _, line = source(migrated_database_url)
    client = api(staff(human, prop, NONPAYMENT_READ))
    before = unchanged(migrated_database_url)
    alert = data(
        client.get(
            f"/api/v1/properties/{prop}/rent-nonpayment-alerts",
            params={"limit": "1", "cursor": str(UUID(int=line.int - 1))},
        )
    )
    rows = cast(list[dict[str, object]], alert["items"])
    assert (
        len(rows) == 1
        and rows[0]["case_id"] is None
        and rows[0]["rent_invoice_line_id"] == str(line)
    )
    assert (
        rows[0]["lease_id"] == str(lease)
        and cast(dict[str, object], rows[0]["assessment"])["thirty_day_default_eligible"] is True
    )
    assert alert["timezone"] == "Asia/Phnom_Penh" and date.fromisoformat(
        str(alert["business_date"])
    )
    assert unchanged(migrated_database_url) == before
    writer = api(staff(human, prop, NONPAYMENT_EVENT))
    assert writer.get(f"/api/v1/properties/{prop}/rent-nonpayment-alerts").status_code == 403


def test_enforcement_evaluation_connection_is_bound_scoped_read_only_and_revocable(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _, _, line = source(migrated_database_url)
    role = "prm_eval_test_" + uuid4().hex
    password = uuid4().hex
    principal = uuid4()
    params = conninfo_to_dict(migrated_database_url)
    database = params["dbname"]
    assert isinstance(database, str)
    admin = make_conninfo(admin_database_url(), dbname=database)
    with psycopg.connect(admin) as connection:
        connection.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(role)
            )
        )
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA app TO {}").format(sql.Identifier(role)))
        connection.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION "
                "app.scheduled_rent_nonpayment_evaluation(uuid,uuid,integer,uuid) "
                "TO {}"
            ).format(sql.Identifier(role))
        )
        restricted = connection.execute(
            "SELECT app.nonpayment_evaluation_login_is_restricted(%s)", (role,)
        ).fetchone()
        if restricted != (True,):
            visible = connection.execute(
                "SELECT p.oid::regprocedure::text,p.proacl::text "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='app' AND p.prosecdef "
                "AND has_function_privilege(%s,p.oid,'EXECUTE') ORDER BY p.oid",
                (role,),
            ).fetchall()
            pytest.fail(f"Dedicated synthetic login has unexpected definer access: {visible}")
        connection.execute(
            "INSERT INTO "
            "app.rent_nonpayment_evaluation_principals(actor_id,property_id,da"
            "tabase_role,capability,lifecycle_state,created_by) "
            "VALUES(%s,%s,%s,'rent_nonpayment.evaluate','active',%s)",
            (principal, prop, role, human),
        )
    url = make_conninfo(migrated_database_url, user=role, password=password)
    # Even explicitly granted synthetic TEMP access cannot be combined with the
    # historical definer to alter match keys through a fabricated relation.
    with psycopg.connect(admin) as connection:
        connection.execute(
            sql.SQL("GRANT TEMPORARY ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(role)
            )
        )
    try:
        with psycopg.connect(url) as connection:
            connection.execute("CREATE TEMP TABLE fake_customer_source(id uuid,email_address text)")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "CREATE TRIGGER forged_customer_sync AFTER INSERT "
                    "ON fake_customer_source FOR EACH ROW "
                    "EXECUTE FUNCTION app.sync_customer_email_match_key()"
                )
    finally:
        with psycopg.connect(admin) as connection:
            connection.execute(
                sql.SQL("REVOKE TEMPORARY ON DATABASE {} FROM {}").format(
                    sql.Identifier(database), sql.Identifier(role)
                )
            )
    evaluator = ScheduledRentNonpaymentEvaluator(url, prop, principal)
    before = unchanged(migrated_database_url)
    result = evaluator.run_once(EnforcementPage(1, UUID(int=line.int - 1)))
    row = cast(list[dict[str, object]], result["items"])[0]
    assert row["rent_invoice_line_id"] == str(line) and row["case_id"] is None
    assert unchanged(migrated_database_url) == before
    with pytest.raises(LeaseEnforcementAuthorizationError):
        ScheduledRentNonpaymentEvaluator(url, uuid4(), principal).run_once()
    with pytest.raises(LeaseEnforcementAuthorizationError):
        ScheduledRentNonpaymentEvaluator(url, prop, human).run_once()
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as failure:
            connection.execute(
                "SELECT app.scheduled_rent_nonpayment_evaluation(%s,%s,1,NULL)", (principal, prop)
            )
        assert failure.value.sqlstate == "P5406"
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM app.rent_nonpayment_cases")
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT "
                "app.lease_enforcement_command(%s,%s,NULL,%s,'OPEN_CASE',%s,%s,'{}"
                "'::jsonb,'forged')",
                (prop, uuid4(), human, uuid4(), "a" * 64),
            )
    # Changes to a dedicated test login must invalidate evaluation immediately,
    # including a non-inherited role that could otherwise be reached by SET ROLE.
    drifts = (
        ("ALTER ROLE {} CREATEDB", "ALTER ROLE {} NOCREATEDB"),
        (
            "GRANT prm_runtime TO {} WITH INHERIT FALSE",
            "REVOKE prm_runtime FROM {}",
        ),
        (
            "GRANT SELECT ON app.rent_nonpayment_cases TO {}",
            "REVOKE SELECT ON app.rent_nonpayment_cases FROM {}",
        ),
        ("GRANT CREATE ON SCHEMA app TO {}", "REVOKE CREATE ON SCHEMA app FROM {}"),
        (
            "GRANT EXECUTE ON FUNCTION "
            "app.lease_enforcement_workspaces(uuid,uuid[],integer,uuid) TO {}",
            "REVOKE EXECUTE ON FUNCTION "
            "app.lease_enforcement_workspaces(uuid,uuid[],integer,uuid) FROM {}",
        ),
        (
            "GRANT EXECUTE ON FUNCTION "
            "app.lease_enforcement_command(uuid,uuid,uuid,uuid,text,uuid,text,jsonb,text) "
            "TO {}",
            "REVOKE EXECUTE ON FUNCTION "
            "app.lease_enforcement_command(uuid,uuid,uuid,uuid,text,uuid,text,jsonb,text) "
            "FROM {}",
        ),
    )
    for broaden, restore in drifts:
        try:
            with psycopg.connect(admin) as connection:
                connection.execute(sql.SQL(broaden).format(sql.Identifier(role)))
            with pytest.raises(LeaseEnforcementAuthorizationError):
                evaluator.run_once()
            with psycopg.connect(admin) as connection:
                with pytest.raises(psycopg.errors.CheckViolation):
                    connection.execute(
                        "INSERT INTO app.rent_nonpayment_evaluation_principals"
                        "(actor_id,property_id,database_role,capability,lifecycle_state,"
                        "created_by) VALUES(%s,%s,%s,'rent_nonpayment.evaluate','active',%s)",
                        (uuid4(), prop, role, human),
                    )
        finally:
            with psycopg.connect(admin) as connection:
                connection.execute(sql.SQL(restore).format(sql.Identifier(role)))
        assert evaluator.run_once(EnforcementPage(1, UUID(int=line.int - 1)))["items"]
    assert unchanged(migrated_database_url) == before
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.rent_nonpayment_evaluation_principals SET "
            "lifecycle_state='disabled',disabled_at=clock_timestamp(),disabled"
            "_by=%s WHERE actor_id=%s",
            (human, principal),
        )
    with pytest.raises(LeaseEnforcementAuthorizationError):
        evaluator.run_once()
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(
                "DELETE FROM app.rent_nonpayment_evaluation_principals WHERE actor_id=%s",
                (principal,),
            )
    # The unique test login has no remaining business authority and the disposable
    # cluster owns its cleanup. Retain its disabled principal/identity history.


@pytest.mark.parametrize("limit", [0, 101, True, 1.5])
def test_enforcement_page_bounds_fail_before_connection(limit: int) -> None:
    with pytest.raises(LeaseEnforcementInvalidError):
        EnforcementPage(limit)


def test_enforcement_new_context_permissions_and_forward_only_head(
    migrated_database_url: str,  # noqa: F811
) -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == ["20270207_195"]
    revision = scripts.get_revision("20260910_51")
    assert revision is not None and revision.down_revision == "20260910_50"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    private = (
        "app.sync_customer_email_match_key()",
        "app.rent_nonpayment_source_context(uuid,timestamptz)",
        "app.rent_nonpayment_alert_page(uuid,integer,uuid)",
        "app.nonpayment_evaluation_login_is_restricted(name)",
        "app.scheduled_rent_nonpayment_evaluation(uuid,uuid,integer,uuid)",
    )
    with psycopg.connect(migrated_database_url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
            for signature in private:
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
                ).fetchone() == (False,)
            assert connection.execute(
                "SELECT has_table_privilege(%s,'app.rent_nonpayment_evaluation_principals',"
                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')",
                (role,),
            ).fetchone() == (False,)
        for signature in (
            "app.lease_enforcement_workspaces(uuid,uuid[],integer,uuid)",
            "app.lease_enforcement_resolve(uuid,uuid[],text,uuid)",
            "app.lease_enforcement_context(uuid,uuid,text,uuid,uuid,integer,uuid)",
        ):
            assert connection.execute(
                "SELECT has_function_privilege('prm_runtime',%s,'EXECUTE')", (signature,)
            ).fetchone() == (True,)


def test_forward_trigger_revocation_preserves_runtime_customer_email_matching(
    migrated_database_url: str,  # noqa: F811
) -> None:
    from hashlib import md5

    from property_rental.customer import (
        CustomerReuseRequired,
        CustomerService,
        PostgresCustomerRepository,
    )

    human, _, _, _, _, _ = source(migrated_database_url)
    service = CustomerService(PostgresCustomerRepository(runtime_database_url(), human))
    original_email = f"{uuid4()}@example.com"
    customer = service.create(
        uuid4(),
        legal_name="Synthetic trigger regression",
        id_document_number=f"ID-{uuid4().hex[:12]}",
        email_address=original_email,
    )

    def match_key() -> tuple[object, ...] | None:
        with psycopg.connect(migrated_database_url) as connection:
            return connection.execute(
                "SELECT match_digest FROM app.customer_email_match_keys WHERE customer_id=%s",
                (customer.customer_id,),
            ).fetchone()

    assert match_key() == (md5(original_email.encode(), usedforsecurity=False).hexdigest(),)
    with pytest.raises(CustomerReuseRequired):
        service.create(
            uuid4(),
            legal_name="Synthetic duplicate",
            id_document_number=f"ID-{uuid4().hex[:12]}",
            email_address=original_email.upper(),
        )
    replacement = f"{uuid4()}@example.com"
    customer = service.update(
        customer,
        legal_name=customer.legal_name,
        phone_number=None,
        email_address=replacement,
        contact_address=None,
        memo=None,
    )
    assert match_key() == (md5(replacement.encode(), usedforsecurity=False).hexdigest(),)
    with pytest.raises(CustomerReuseRequired):
        service.create(
            uuid4(),
            legal_name="Synthetic updated duplicate",
            id_document_number=f"ID-{uuid4().hex[:12]}",
            email_address=replacement.upper(),
        )
    customer = service.update(
        customer,
        legal_name=customer.legal_name,
        phone_number=None,
        email_address=None,
        contact_address=None,
        memo=None,
    )
    assert match_key() is None
    assert customer.version == 3


@pytest.mark.parametrize("phase", ["registration", "evaluation"])
@pytest.mark.parametrize(
    ("privilege", "column", "public"),
    [
        ("SELECT", "email_address", False),
        ("INSERT", "email_address", False),
        ("UPDATE", "email_address", False),
        ("REFERENCES", "email_address", False),
        ("SELECT", "email_address", True),
        ("REFERENCES", None, False),
        ("TRIGGER", None, False),
        ("MAINTAIN", None, False),
    ],
)
def test_enforcement_evaluator_rejects_effective_column_and_relation_grants(
    migrated_database_url: str,  # noqa: F811
    phase: str,
    privilege: str,
    column: str | None,
    public: bool,
) -> None:
    human, prop, _, _, _, line = source(migrated_database_url)
    role, password, principal = "prm_eval_grant_" + uuid4().hex, uuid4().hex, uuid4()
    database = conninfo_to_dict(migrated_database_url)["dbname"]
    assert isinstance(database, str)
    admin = make_conninfo(admin_database_url(), dbname=database)
    registration = (
        "INSERT INTO app.rent_nonpayment_evaluation_principals"
        "(actor_id,property_id,database_role,capability,lifecycle_state,created_by) "
        "VALUES(%s,%s,%s,'rent_nonpayment.evaluate','active',%s)"
    )
    identity = (principal, prop, role, human)
    with psycopg.connect(admin) as connection:
        connection.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(role)
            )
        )
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA app TO {}").format(sql.Identifier(role)))
        connection.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION "
                "app.scheduled_rent_nonpayment_evaluation(uuid,uuid,integer,uuid) TO {}"
            ).format(sql.Identifier(role))
        )
        assert connection.execute(
            "SELECT app.nonpayment_evaluation_login_is_restricted(%s)", (role,)
        ).fetchone() == (True,)
        if phase == "evaluation":
            connection.execute(registration, identity)
    url = make_conninfo(migrated_database_url, user=role, password=password)
    evaluator = ScheduledRentNonpaymentEvaluator(url, prop, principal)
    grantee = sql.SQL("PUBLIC") if public else sql.Identifier(role)
    access = sql.SQL(privilege) + (
        sql.SQL(" ({})").format(sql.Identifier(column)) if column else sql.SQL("")
    )
    try:
        with psycopg.connect(admin) as connection:
            connection.execute(sql.SQL("GRANT {} ON app.customers TO {}").format(access, grantee))
            # Column-only access really exists while the corresponding table grant does not.
            if column:
                assert connection.execute(
                    "SELECT has_table_privilege(%s,'app.customers',%s),"
                    "has_column_privilege(%s,'app.customers',%s,%s)",
                    (role, privilege, role, column, privilege),
                ).fetchone() == (False, True)
        if privilege == "SELECT":
            with psycopg.connect(url) as connection:
                # Demonstrate effective direct access without reading any Customer values.
                assert (
                    connection.execute("SELECT email_address FROM app.customers LIMIT 0").fetchall()
                    == []
                )
        if phase == "registration":
            with psycopg.connect(admin) as connection:
                with pytest.raises(psycopg.errors.CheckViolation):
                    connection.execute(registration, identity)
        else:
            with pytest.raises(LeaseEnforcementAuthorizationError):
                evaluator.run_once()
    finally:
        with psycopg.connect(admin) as connection:
            connection.execute(
                sql.SQL("REVOKE {} ON app.customers FROM {}").format(access, grantee)
            )
    with psycopg.connect(admin) as connection:
        assert connection.execute(
            "SELECT app.nonpayment_evaluation_login_is_restricted(%s)", (role,)
        ).fetchone() == (True,)
        if phase == "registration":
            connection.execute(registration, identity)
    page = evaluator.run_once(EnforcementPage(1, UUID(int=line.int - 1)))
    assert cast(list[dict[str, object]], page["items"])[0]["rent_invoice_line_id"] == str(line)


def evaluator_ownership_target(
    connection: psycopg.Connection[tuple[object, ...]], kind: str, database: str
) -> tuple[sql.Composable, sql.Composable | None, str, str, int, str]:
    """Select an isolated ownership fixture without changing business rows."""
    name = "eval_ownership_" + uuid4().hex
    target = sql.Identifier("app", name)
    alter: sql.Composable
    acl: sql.Composable | None
    if kind == "database":
        row = connection.execute(
            "SELECT oid FROM pg_database WHERE datname=%s", (database,)
        ).fetchone()
        alter = sql.SQL("ALTER DATABASE {} OWNER TO ").format(sql.Identifier(database))
        acl = sql.SQL("ON DATABASE {}").format(sql.Identifier(database))
        catalog, owner_column = "pg_database", "datdba"
    elif kind == "schema":
        row = connection.execute("SELECT oid FROM pg_namespace WHERE nspname='app'").fetchone()
        alter, acl = sql.SQL("ALTER SCHEMA app OWNER TO "), sql.SQL("ON SCHEMA app")
        catalog, owner_column = "pg_namespace", "nspowner"
    elif kind == "relation":
        row = connection.execute("SELECT 'app.customers'::regclass::oid").fetchone()
        alter, acl = (
            sql.SQL("ALTER TABLE app.customers OWNER TO "),
            sql.SQL("ON TABLE app.customers"),
        )
        catalog, owner_column = "pg_class", "relowner"
    elif kind == "sequence":
        connection.execute(sql.SQL("CREATE SEQUENCE {}").format(target))
        row = connection.execute("SELECT %s::regclass::oid", ("app." + name,)).fetchone()
        alter = sql.SQL("ALTER SEQUENCE {} OWNER TO ").format(target)
        acl = sql.SQL("ON SEQUENCE {}").format(target)
        catalog, owner_column = "pg_class", "relowner"
    elif kind in {"invoker_routine", "evaluation_wrapper"}:
        function: sql.Composable
        if kind == "invoker_routine":
            connection.execute(
                sql.SQL(
                    "CREATE FUNCTION {}() RETURNS integer LANGUAGE sql SECURITY INVOKER "
                    "SET search_path=pg_catalog AS 'SELECT 1'"
                ).format(target)
            )
            signature = "app." + name + "()"
            function = sql.SQL("{}()").format(target)
            connection.execute(sql.SQL("REVOKE ALL ON FUNCTION {} FROM PUBLIC").format(function))
        else:
            signature = "app.scheduled_rent_nonpayment_evaluation(uuid,uuid,integer,uuid)"
            function = sql.SQL(signature)
        row = connection.execute("SELECT %s::regprocedure::oid", (signature,)).fetchone()
        alter = sql.SQL("ALTER FUNCTION {} OWNER TO ").format(function)
        acl = sql.SQL("ON FUNCTION {}").format(function)
        catalog, owner_column = "pg_proc", "proowner"
    elif kind == "type":
        connection.execute(sql.SQL("CREATE TYPE {} AS ENUM ('synthetic')").format(target))
        connection.execute(sql.SQL("REVOKE ALL ON TYPE {} FROM PUBLIC").format(target))
        row = connection.execute("SELECT %s::regtype::oid", ("app." + name,)).fetchone()
        alter = sql.SQL("ALTER TYPE {} OWNER TO ").format(target)
        acl = sql.SQL("ON TYPE {}").format(target)
        catalog, owner_column = "pg_type", "typowner"
    else:
        assert kind == "extension_operator_class"
        dependency = connection.execute(
            "SELECT c.oid,n.nspname,c.opcname,a.amname,e.oid,e.extowner "
            "FROM pg_opclass c JOIN pg_namespace n ON n.oid=c.opcnamespace "
            "JOIN pg_am a ON a.oid=c.opcmethod "
            "JOIN pg_depend d ON d.classid='pg_opclass'::regclass AND d.objid=c.oid "
            "AND d.refclassid='pg_extension'::regclass AND d.deptype='e' "
            "JOIN pg_extension e ON e.oid=d.refobjid "
            "WHERE e.extname='btree_gist' AND c.opcname='gist_uuid_ops' AND a.amname='gist'"
        ).fetchone()
        assert dependency is not None and dependency[1] != "app"
        assert connection.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='app' "
            "AND %s=ANY(i.indclass::oid[]))",
            (dependency[0],),
        ).fetchone() == (True,)
        # The extension container also has a target-database ownership dependency;
        # the shared catalog guard covers it as well as this real external member.
        assert connection.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_shdepend d JOIN pg_database b ON b.oid=d.dbid "
            "WHERE b.datname=current_database() AND d.classid='pg_extension'::regclass "
            "AND d.objid=%s AND d.refclassid='pg_authid'::regclass "
            "AND d.refobjid=%s AND d.deptype='o')",
            (dependency[4], dependency[5]),
        ).fetchone() == (True,)
        row = (dependency[0],)
        alter = sql.SQL("ALTER OPERATOR CLASS {} USING {} OWNER TO ").format(
            sql.Identifier(str(dependency[1]), str(dependency[2])),
            sql.Identifier(str(dependency[3])),
        )
        acl = None
        catalog, owner_column = "pg_opclass", "opcowner"
    assert row is not None and isinstance(row[0], int)
    target_id = row[0]
    owner = connection.execute(
        sql.SQL("SELECT pg_get_userbyid({})::text FROM pg_catalog.{} WHERE oid=%s").format(
            sql.Identifier(owner_column), sql.Identifier(catalog)
        ),
        (target_id,),
    ).fetchone()
    assert owner is not None and isinstance(owner[0], str)
    return alter, acl, catalog, owner_column, target_id, owner[0]


@pytest.mark.parametrize("phase", ["registration", "evaluation"])
@pytest.mark.parametrize(
    "kind",
    [
        "database",
        "schema",
        "relation",
        "sequence",
        "invoker_routine",
        "evaluation_wrapper",
        "type",
        "extension_operator_class",
    ],
)
def test_enforcement_evaluator_rejects_ownership_with_revoked_acl_and_runtime_drift(
    migrated_database_url: str,  # noqa: F811
    phase: str,
    kind: str,
) -> None:
    human, prop, _, _, _, line = source(migrated_database_url)
    role, password, principal = "prm_eval_owner_" + uuid4().hex, uuid4().hex, uuid4()
    database = conninfo_to_dict(migrated_database_url)["dbname"]
    assert isinstance(database, str)
    admin = make_conninfo(admin_database_url(), dbname=database)
    registration = (
        "INSERT INTO app.rent_nonpayment_evaluation_principals"
        "(actor_id,property_id,database_role,capability,lifecycle_state,created_by) "
        "VALUES(%s,%s,%s,'rent_nonpayment.evaluate','active',%s)"
    )
    identity = (principal, prop, role, human)

    def minimum_grants(connection: psycopg.Connection[tuple[object, ...]]) -> None:
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(role)
            )
        )
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA app TO {}").format(sql.Identifier(role)))
        connection.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION app.scheduled_rent_nonpayment_evaluation"
                "(uuid,uuid,integer,uuid) TO {}"
            ).format(sql.Identifier(role))
        )

    with psycopg.connect(admin) as connection:
        connection.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
        minimum_grants(connection)
        alter, acl, catalog, owner_column, target_id, original_owner = evaluator_ownership_target(
            connection, kind, database
        )
        assert connection.execute(
            "SELECT app.nonpayment_evaluation_login_is_restricted(%s)", (role,)
        ).fetchone() == (True,)
        if phase == "evaluation":
            connection.execute(registration, identity)
    url = make_conninfo(migrated_database_url, user=role, password=password)
    evaluator = ScheduledRentNonpaymentEvaluator(url, prop, principal)
    before = unchanged(migrated_database_url)
    try:
        with psycopg.connect(admin) as connection:
            connection.execute(alter + sql.Identifier(role))
            if acl is not None:
                connection.execute(
                    sql.SQL("REVOKE ALL {} FROM {}").format(acl, sql.Identifier(role))
                )
                # Preserve the trusted original owner's ordinary access while
                # isolating ownership as the evaluator's sole unexpected power.
                connection.execute(
                    sql.SQL("GRANT ALL {} TO {}").format(acl, sql.Identifier(original_owner))
                )
            minimum_grants(connection)
            assert connection.execute(
                sql.SQL("SELECT pg_get_userbyid({})::text FROM pg_catalog.{} WHERE oid=%s").format(
                    sql.Identifier(owner_column), sql.Identifier(catalog)
                ),
                (target_id,),
            ).fetchone() == (role,)
            assert connection.execute(
                "SELECT has_schema_privilege(%s,'app','CREATE'), EXISTS("
                "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND CASE WHEN c.relkind IN ('r','p','v','m','f') THEN "
                "(has_table_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,"
                "REFERENCES,TRIGGER,MAINTAIN') "
                "OR has_any_column_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,REFERENCES')) "
                "ELSE false END) "
                ",EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND CASE WHEN c.relkind='S' "
                "THEN has_sequence_privilege(%s,c.oid,'SELECT,USAGE,UPDATE') ELSE false END)",
                (role, role, role, role),
            ).fetchone() == (False, False, False)
            assert connection.execute(
                "SELECT app.nonpayment_evaluation_login_is_restricted(%s)", (role,)
            ).fetchone() == (False,)
        if phase == "registration":
            with psycopg.connect(admin) as connection:
                with pytest.raises(psycopg.errors.CheckViolation):
                    connection.execute(registration, identity)
        elif kind == "evaluation_wrapper":
            # An owner-transferred definer also loses its trusted table authority.
            # Keep the conservative unavailable error mapping; the predicate above
            # independently rejects that otherwise permitted routine's owner.
            with pytest.raises(LeaseEnforcementUnavailableError) as failure:
                evaluator.run_once()
            assert isinstance(failure.value.__cause__, psycopg.Error)
            assert failure.value.__cause__.sqlstate == "42501"
        else:
            with pytest.raises(LeaseEnforcementAuthorizationError):
                evaluator.run_once()
    finally:
        with psycopg.connect(admin) as connection:
            connection.execute(alter + sql.Identifier(original_owner))
            if acl is not None:
                connection.execute(
                    sql.SQL("REVOKE ALL {} FROM {}").format(acl, sql.Identifier(role))
                )
                connection.execute(
                    sql.SQL("GRANT ALL {} TO {}").format(acl, sql.Identifier(original_owner))
                )
            minimum_grants(connection)
    with psycopg.connect(admin) as connection:
        assert connection.execute(
            sql.SQL("SELECT pg_get_userbyid({})::text FROM pg_catalog.{} WHERE oid=%s").format(
                sql.Identifier(owner_column), sql.Identifier(catalog)
            ),
            (target_id,),
        ).fetchone() == (original_owner,)
        assert connection.execute(
            "SELECT app.nonpayment_evaluation_login_is_restricted(%s)", (role,)
        ).fetchone() == (True,)
        if phase == "registration":
            connection.execute(registration, identity)
    page = evaluator.run_once(EnforcementPage(1, UUID(int=line.int - 1)))
    assert cast(list[dict[str, object]], page["items"])[0]["rent_invoice_line_id"] == str(line)
    assert unchanged(migrated_database_url) == before


@pytest.mark.parametrize("phase", ["registration", "evaluation"])
def test_enforcement_evaluator_rejects_temporary_catalog_shadowing_after_ownership_drift(
    migrated_database_url: str,  # noqa: F811
    phase: str,
) -> None:
    human, prop, _, _, _, line = source(migrated_database_url)
    role, harmless = "prm_eval_shadow_" + uuid4().hex, "prm_eval_safe_" + uuid4().hex
    password, principal = uuid4().hex, uuid4()
    database = conninfo_to_dict(migrated_database_url)["dbname"]
    assert isinstance(database, str)
    admin = make_conninfo(admin_database_url(), dbname=database)
    url = make_conninfo(migrated_database_url, user=role, password=password)
    registration = (
        "INSERT INTO app.rent_nonpayment_evaluation_principals"
        "(actor_id,property_id,database_role,capability,lifecycle_state,created_by) "
        "VALUES(%s,%s,%s,'rent_nonpayment.evaluate','active',%s)"
    )
    identity = (principal, prop, role, human)
    database_acl = sql.SQL("ON DATABASE {}").format(sql.Identifier(database))

    with psycopg.connect(admin) as connection:
        for name in (role, harmless):
            connection.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(name), sql.Literal(password))
            )
            connection.execute(
                sql.SQL("GRANT CONNECT {} TO {}").format(database_acl, sql.Identifier(name))
            )
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA app TO {}").format(sql.Identifier(name))
            )
            connection.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION app.scheduled_rent_nonpayment_evaluation"
                    "(uuid,uuid,integer,uuid) TO {}"
                ).format(sql.Identifier(name))
            )
            assert connection.execute(
                "SELECT app.nonpayment_evaluation_login_is_restricted(%s)", (name,)
            ).fetchone() == (True,)
        row = connection.execute(
            "SELECT pg_catalog.pg_get_userbyid(datdba)::text "
            "FROM pg_catalog.pg_database WHERE datname=%s",
            (database,),
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        original_owner = row[0]
        row = connection.execute(
            "SELECT pg_catalog.pg_get_userbyid(proowner)::text FROM pg_catalog.pg_proc "
            "WHERE oid='app.nonpayment_evaluation_login_is_restricted(name)'::regprocedure"
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        function_owner = row[0]
        if phase == "evaluation":
            connection.execute(registration, identity)
    before = unchanged(migrated_database_url)
    try:
        with psycopg.connect(admin) as connection:
            connection.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                    sql.Identifier(database), sql.Identifier(role)
                )
            )
            connection.execute(
                sql.SQL("REVOKE ALL {} FROM {}").format(database_acl, sql.Identifier(role))
            )
            connection.execute(
                sql.SQL("GRANT CONNECT {} TO {}").format(database_acl, sql.Identifier(role))
            )
            connection.execute(
                sql.SQL("GRANT ALL {} TO {}").format(database_acl, sql.Identifier(original_owner))
            )
            # Genuine catalog resolution rejects the new owner before shadowing.
            assert connection.execute(
                "SELECT app.nonpayment_evaluation_login_is_restricted(%s)", (role,)
            ).fetchone() == (False,)
        with psycopg.connect(admin if phase == "registration" else url) as session:
            if phase == "evaluation":
                # Exercise retained owner grant authority, not a standing TEMP grant.
                session.execute(
                    sql.SQL("GRANT TEMP {} TO {}").format(database_acl, sql.Identifier(role))
                )
            session.execute(
                "CREATE TEMP TABLE pg_roles AS SELECT oid,%s::name AS rolname,rolcanlogin,"
                "rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
                "FROM pg_catalog.pg_roles WHERE rolname=%s",
                (role, harmless),
            )
            session.execute(
                sql.SQL("GRANT SELECT ON pg_temp.pg_roles TO {}").format(
                    sql.Identifier(function_owner)
                )
            )
            if phase == "evaluation":
                session.execute(
                    sql.SQL("REVOKE TEMP {} FROM {}").format(database_acl, sql.Identifier(role))
                )
            assert session.execute(
                "SELECT pg_catalog.has_database_privilege(%s,%s,'CREATE,TEMP'),"
                "pg_catalog.has_schema_privilege(%s,'app','CREATE')",
                (role, database, role),
            ).fetchone() == (False, False)
            assert session.execute(
                "SELECT f.oid=h.oid,f.oid<>r.oid,f.rolname=r.rolname,b.datdba=r.oid "
                "FROM pg_temp.pg_roles f JOIN pg_catalog.pg_roles h ON h.rolname=%s "
                "JOIN pg_catalog.pg_roles r ON r.rolname=%s "
                "JOIN pg_catalog.pg_database b ON b.datname=%s",
                (harmless, role, database),
            ).fetchone() == (True, True, True, True)
            session.commit()
            if phase == "registration":
                with pytest.raises(psycopg.errors.CheckViolation):
                    with session.transaction():
                        session.execute(registration, identity)
                assert session.execute(
                    "SELECT app.nonpayment_evaluation_login_is_restricted(%s)", (role,)
                ).fetchone() == (False,)
            else:
                session.read_only = True
                with pytest.raises(psycopg.Error) as failure:
                    with session.transaction():
                        assert session.execute("SHOW transaction_read_only").fetchone() == ("on",)
                        session.execute(
                            "SELECT app.scheduled_rent_nonpayment_evaluation(%s,%s,%s,%s)",
                            (principal, prop, 1, UUID(int=line.int - 1)),
                        )
                assert failure.value.sqlstate == "P5406"
        # Closing the synthetic session removes its temporary objects.
    finally:
        with psycopg.connect(admin) as connection:
            connection.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                    sql.Identifier(database), sql.Identifier(original_owner)
                )
            )
            connection.execute(
                sql.SQL("REVOKE ALL {} FROM {}").format(database_acl, sql.Identifier(role))
            )
            connection.execute(
                sql.SQL("GRANT CONNECT {} TO {}").format(database_acl, sql.Identifier(role))
            )
    with psycopg.connect(admin) as connection:
        assert connection.execute(
            "SELECT app.nonpayment_evaluation_login_is_restricted(%s)", (role,)
        ).fetchone() == (True,)
        if phase == "registration":
            connection.execute(registration, identity)
    page = ScheduledRentNonpaymentEvaluator(url, prop, principal).run_once(
        EnforcementPage(1, UUID(int=line.int - 1))
    )
    assert cast(list[dict[str, object]], page["items"])[0]["rent_invoice_line_id"] == str(line)
    assert unchanged(migrated_database_url) == before
