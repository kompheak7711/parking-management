"""Time the screens' reads on the made-up 300-Unit history (V1-060, DL-071 answer 14).

Test-only, run by scripts/speed-test.sh after speed/seed.py. A Manager with the default Manager
bundle signs in with password and sign-in code like a person; each read then goes through the
real app (sign-in cookie, capability checks, the runtime database role), as the screens call it.
Each read runs once to warm up and then ``--repeat`` times. Last, next month's scheduled Rent run
bills every Unit. The limits are a Claude decision under the owner's 2026-10-23 22:30 rule (no
money and no rule changes): a read's middle time at most 0.5 seconds and its slowest at most
1 second; the Rent run at most 120 seconds; on the 4-core test computer.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from fastapi.testclient import TestClient
from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).parents[1] / "tests"))

from property_rental.app import create_app
from property_rental.auth_flow import PostgresAuthenticationFlow
from property_rental.billing_run import BillingRunCommand, PostgresBillingRunService
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.settings import Settings
from test_sign_in_code_migration import (
    KEY,
    PASSWORD,
    CodeDatabase,
    add_account,
    code_for,
    fresh_step,
)

ORIGIN = "https://localhost"
CSRF = "speed-test-csrf"
MIDDLE_LIMIT_SECONDS = 0.5
SLOWEST_LIMIT_SECONDS = 1.0
# Decided by Claude under the owner's 2026-10-23 22:30 rule (V1-060 part B): the Home page adds
# up ten sections, the Rent nonpayment alerts check every overdue line with the exact balance
# function, and a report or register with no dates ("All") reads the whole 10 years, so they
# have their own limits (middle, slowest).
HOME_LIMITS = (1.5, 2.0)
ALERT_LIMITS = (1.0, 1.5)
REPORT_LIMITS = (3.0, 4.0)
REPORTS = frozenset(
    {
        "Total income report",
        "Total payment report",
        "Total electricity report",
        "Invoice register",
        "Payments register",
        "Credit ledger",
        "Deposits register",
        "Unit occupancy",
        "Lease dates",
    }
)


def limits(name: str) -> tuple[float, float]:
    if name == "Home page":
        return HOME_LIMITS
    if name == "Rent nonpayment alerts":
        return ALERT_LIMITS
    if name in REPORTS:
        return REPORT_LIMITS
    return MIDDLE_LIMIT_SECONDS, SLOWEST_LIMIT_SECONDS


RENT_RUN_LIMIT_SECONDS = 120.0


def signed_in_client(url: str, runtime_url: str) -> TestClient:
    """A Manager with the default Manager bundle, signed in with password and sign-in code."""
    database = CodeDatabase(url, runtime_url)
    manager = add_account(database, f"speed-manager-{uuid4().hex[:6]}")
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.user_role_assignments(assignment_id,actor_id,role_bundle_id,"
            "property_id,provenance) SELECT %s,%s,role_bundle_id,property_id,'speed-test' "
            "FROM app.role_bundles WHERE name='Manager'",
            (uuid4(), manager.actor_id),
        )
    flow = PostgresAuthenticationFlow(runtime_url, totp_protection_key=KEY)
    started = flow.login(
        username=manager.username, password=PASSWORD, request_source="speed", request_id="speed"
    )
    assert started.preauth_token is not None, started
    done = flow.complete_mfa(
        preauth_token=started.preauth_token,
        method="totp",
        code=code_for(manager, fresh_step(database)),
        request_id="speed",
    )
    assert done.session_token is not None, done
    client = TestClient(
        create_app(
            Settings(
                database_url=SecretStr(runtime_url),
                financial_database_url=SecretStr(os.environ["FINANCIAL_DATABASE_URL"]),
            )
        )
    )
    client.headers.update(
        {
            "Origin": ORIGIN,
            "X-CSRF-Token": CSRF,
            "Cookie": f"__Host-prm_session={done.session_token}; __Host-prm_csrf={CSRF}",
        }
    )
    return client


def sample_ids(url: str) -> dict[str, str]:
    """One record of each kind from the made-up history: the busiest Customer and Unit."""
    with psycopg.connect(url) as connection:
        row = connection.execute(
            """
            SELECT p.id, lease.id, lease.primary_tenant_id, lease.unit_id, meter.id,
                   invoice.id, payment.id
            FROM app.properties AS p
            JOIN app.leases AS lease ON lease.status='SIGNED'
            JOIN app.utility_meters AS meter ON meter.unit_id=lease.unit_id
            JOIN app.invoices AS invoice ON invoice.lease_id=lease.id
            JOIN app.payments AS payment ON payment.payer_customer_id=lease.primary_tenant_id
            ORDER BY lease.end_date DESC, invoice.invoice_date DESC
            LIMIT 1
            """
        ).fetchone()
    assert row is not None, "run speed/seed.py first"
    names = ("property", "lease", "customer", "unit", "meter", "invoice", "payment")
    return dict(zip(names, (str(value) for value in row), strict=True))


def reads(ids: dict[str, str]) -> list[tuple[str, str]]:
    """The reads behind the screens: lists first, then one record's pages."""
    p = ids["property"]
    first = date.today().replace(day=1)
    month = f"from={first.isoformat()}&to={date.today().isoformat()}"
    customer = f"customer_id={ids['customer']}"
    return [
        ("Units list", f"/properties/{p}/units"),
        ("Customers list", f"/api/v1/properties/{p}/customers"),
        ("Leases list", f"/api/v1/properties/{p}/leases"),
        ("Invoices list", f"/api/v1/properties/{p}/invoices"),
        ("Payments list", f"/api/v1/properties/{p}/payments"),
        ("Refunds list", f"/api/v1/properties/{p}/refunds"),
        ("Reservations list", f"/properties/{p}/reservations"),
        ("Rent nonpayment alerts", f"/api/v1/properties/{p}/rent-nonpayment-alerts"),
        ("Initial Rent unpaid alerts", f"/api/v1/properties/{p}/initial-rent-unpaid-alerts"),
        ("Unbilled Utility periods", f"/api/v1/properties/{p}/unbilled-utility-periods"),
        ("Waiting for approval", f"/api/v1/properties/{p}/financial-drafts"),
        ("Customer ledger list", "/api/v1/customer-ledger/customers"),
        ("Financial workspaces", "/api/v1/financial-workspaces"),
        ("Customer page", f"/api/v1/customers/{ids['customer']}"),
        ("Customer account ledger", f"/api/v1/customers/{ids['customer']}/account-ledger"),
        ("Customer money summary", f"/api/v1/customers/{ids['customer']}/financial-summary"),
        ("Lease page", f"/api/v1/leases/{ids['lease']}"),
        ("Lease timeline", f"/api/v1/leases/{ids['lease']}/timeline"),
        ("Unit page", f"/units/{ids['unit']}"),
        ("Unit timeline", f"/units/{ids['unit']}/timeline"),
        ("Unit meters", f"/api/v1/units/{ids['unit']}/meters"),
        ("Meter readings", f"/api/v1/meters/{ids['meter']}/readings"),
        ("Invoice page", f"/api/v1/invoices/{ids['invoice']}"),
        ("Payment page", f"/api/v1/payments/{ids['payment']}"),
        ("Payment receipt", f"/api/v1/payments/{ids['payment']}/receipt"),
        # The V1-057 Home and reports and the V1-058 screens' own reads.
        ("Home page", f"/api/v1/properties/{p}/home"),
        ("Payments page (this month)", f"/api/v1/properties/{p}/payments/summary?{month}"),
        ("Receive payment list", f"/api/v1/properties/{p}/payments/payable?{customer}"),
        ("Waiting for approval page", f"/api/v1/properties/{p}/financial-drafts-waiting"),
        ("Move-out list", f"/api/v1/properties/{p}/final-settlements"),
        ("Services settings", f"/api/v1/properties/{p}/service-settings"),
        ("Unit inventory", f"/units/{ids['unit']}/inventory"),
        ("Total income report", f"/api/v1/properties/{p}/reports/totals/total_income"),
        ("Total payment report", f"/api/v1/properties/{p}/reports/totals/total_payment"),
        ("Total electricity report", f"/api/v1/properties/{p}/reports/totals/total_electricity"),
        ("Invoice register", f"/api/v1/properties/{p}/reports/invoice_register"),
        ("Payments register", f"/api/v1/properties/{p}/reports/payments"),
        ("Credit ledger", f"/api/v1/properties/{p}/reports/credit_ledger"),
        ("Deposits register", f"/api/v1/properties/{p}/reports/deposits"),
        ("Unit occupancy", f"/api/v1/properties/{p}/reports/unit_occupancy"),
        ("Lease dates", f"/api/v1/properties/{p}/reports/lease_dates"),
    ]


def rent_run(url: str, property_id: str, business_date: date) -> tuple[float, str, int]:
    """Time next month's scheduled Rent run for every Unit, as the billing worker runs it.

    The worker runs it on the Property's day 25 (BR-RENT), so the tool passes the 25th of this
    month, whatever today is."""
    period_start = (business_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    period_end = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(
        days=1
    )
    with psycopg.connect(url) as connection:
        owner = connection.execute(
            "SELECT actor_id FROM app.user_accounts WHERE normalized_username='speed-owner'"
        ).fetchone()
        assert owner is not None
        principal = uuid4()
        connection.execute(
            "INSERT INTO app.billing_service_principals(actor_id,property_id,capability,"
            "lifecycle_state,created_by) VALUES (%s,%s,'billing.generate','active',%s)",
            (principal, property_id, owner[0]),
        )
        before = int(str(connection.execute("SELECT count(*) FROM app.invoices").fetchone()[0]))  # type: ignore[index]
    actor = AuthenticatedActor(
        actor_id=str(principal),
        capability_grants=frozenset(
            {CapabilityGrant(capability="billing.generate", property_ids=frozenset({property_id}))}
        ),
    )
    started = time.perf_counter()
    detail = PostgresBillingRunService(os.environ["FINANCIAL_DATABASE_URL"]).execute(
        BillingRunCommand(
            property_id=UUID(property_id),
            run_kind="RENT",
            logical_run_key=f"rent/{period_start:%Y-%m}",
            business_date=business_date,
            period_start=period_start,
            period_end=period_end,
            idempotency_key=uuid4(),
        ),
        actor=actor,
        invocation_source="SCHEDULED",
    )
    seconds = time.perf_counter() - started
    with psycopg.connect(url) as connection:
        after = int(str(connection.execute("SELECT count(*) FROM app.invoices").fetchone()[0]))  # type: ignore[index]
    return seconds, detail.status, after - before


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    url = os.environ["MIGRATION_DATABASE_URL"]
    runtime_url = os.environ["APP_DATABASE_URL"]
    with psycopg.connect(url) as connection:
        counts = {
            table: int(str(connection.execute(f"SELECT count(*) FROM app.{table}").fetchone()[0]))  # type: ignore[index]
            for table in (
                "units",
                "customers",
                "leases",
                "invoices",
                "invoice_lines",
                "payments",
                "payment_allocations",
                "receipts",
                "utility_readings",
                "audit_events",
            )
        }
    client = signed_in_client(url, runtime_url)
    ids = sample_ids(url)
    rows = []
    failed = False
    for name, path in reads(ids):
        first = client.get(path)
        times = []
        for _ in range(arguments.repeat):
            started = time.perf_counter()
            answer = client.get(path)
            times.append(time.perf_counter() - started)
        middle = statistics.median(times)
        slowest = max(times)
        ok = (
            first.status_code == 200
            and answer.status_code == 200
            and middle <= limits(name)[0]
            and slowest <= limits(name)[1]
        )
        failed = failed or not ok
        rows.append((name, answer.status_code, middle, slowest, len(answer.content), ok))
    run_seconds, run_status, run_invoices = rent_run(
        url, ids["property"], date.today().replace(day=25)
    )
    run_ok = run_status == "SUCCEEDED" and run_seconds <= RENT_RUN_LIMIT_SECONDS
    failed = failed or not run_ok
    lines = [
        "# V1-060 speed test",
        "",
        "Made-up history (rows): "
        + ", ".join(f"{table} {count:,}" for table, count in counts.items()),
        "",
        f"Limits: middle time at most {MIDDLE_LIMIT_SECONDS} s, slowest at most "
        f"{SLOWEST_LIMIT_SECONDS} s, over {arguments.repeat} calls after one warm-up call. "
        f"Home page: {HOME_LIMITS[0]} s and {HOME_LIMITS[1]} s. Rent nonpayment alerts: "
        f"{ALERT_LIMITS[0]} s and {ALERT_LIMITS[1]} s. Reports and registers with no dates "
        f"(the whole history): {REPORT_LIMITS[0]} s and {REPORT_LIMITS[1]} s.",
        "",
        "| Read | HTTP | Middle (s) | Slowest (s) | Answer size (bytes) | Result |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {name} | {status} | {middle:.3f} | {slowest:.3f} | {size:,} | "
        f"{'pass' if ok else 'FAIL'} |"
        for name, status, middle, slowest, size, ok in rows
    ]
    lines += [
        "",
        f"Next month's scheduled Rent run (limit {RENT_RUN_LIMIT_SECONDS:.0f} s): "
        f"{run_seconds:.1f} s, status {run_status}, {run_invoices} new Rent Invoices: "
        f"{'pass' if run_ok else 'FAIL'}.",
    ]
    arguments.report.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
