"""BR-AUTH-010: financial drafts are prepared first and decided only once (V1-056 slice 2)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.financial_draft import (
    FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
    FINANCIAL_APPROVE_CAPABILITY,
    FinancialDraftAuthorizationError,
    FinancialDraftConflictError,
    FinancialDraftInvalidError,
    FinancialDraftNotFoundError,
    FinancialDraftPage,
    FinancialDraftService,
    FinancialDraftState,
    require_draft_preparer,
)
from test_invoice_migration import financial_database_url, runtime_database_url
from test_lease_lifecycle_migration import (
    actor,
    migrated_database_url,  # noqa: F401
    setup_sources,
)
from test_migrations import _temporary_migration_database

NEW_TABLES = {"app.financial_drafts", "app.financial_draft_decisions"}
INTERNAL_FUNCTIONS = (
    "app.insert_financial_draft(uuid,uuid,uuid,text,text,jsonb,text,text)",
    "app.confirm_financial_draft_record(uuid,uuid,uuid,text,jsonb,text)",
    "app.lock_pending_financial_draft(uuid,uuid)",
    "app.decided_financial_draft_replay(uuid,uuid,uuid,text,text)",
    "app.financial_draft_json(app.financial_drafts)",
)


def _human(url: str, name: str) -> UUID:
    actor_id = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            """
            INSERT INTO app.user_accounts(
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, provenance
            ) VALUES (%s,%s,%s,%s,'active','optional','test')
            """,
            (actor_id, f"{name}-{actor_id}", name, name),
        )
        connection.commit()
    return actor_id


def _sources(url: str) -> tuple[UUID, UUID]:
    with psycopg.connect(url) as setup:
        actor_id, property_id, _, _, _ = setup_sources(setup)
        setup.commit()
    return actor_id, property_id


def _draft(
    url: str,
    property_id: UUID,
    preparer: UUID,
    capability: str = "refunds.create",
    kind: str = "REFUND",
) -> UUID:
    """Insert a pending draft through the internal helper, as a later kind command does."""
    draft_id = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                preparer,
                draft_id,
                kind,
                capability,
                Jsonb({"amount_usd_cents": 1_000}),
                "revision-1",
                "Customer asked for the rest of the deposit",
            ),
        )
        connection.commit()
    return draft_id


def _service() -> FinancialDraftService:
    return FinancialDraftService(runtime_database_url(), financial_database_url())


def _decision(url: str, draft_id: UUID) -> tuple[object, ...] | None:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT decision,decided_by,authorization_reference,reason "
            "FROM app.financial_draft_decisions WHERE draft_id=%s",
            (draft_id,),
        ).fetchone()


def test_staff_cannot_reject_and_approver_decides_a_draft_once(
    migrated_database_url: str,  # noqa: F811
) -> None:
    staff_id, property_id = _sources(migrated_database_url)
    approver_id = _human(migrated_database_url, "approver")
    draft_id = _draft(migrated_database_url, property_id, staff_id)
    service = _service()
    staff = actor(staff_id, property_id, "refunds.create")
    approver = actor(approver_id, property_id, FINANCIAL_APPROVE_CAPABILITY)

    with pytest.raises(FinancialDraftAuthorizationError):
        service.reject(property_id, draft_id, "Not supported", actor=staff)
    elsewhere = actor(approver_id, uuid4(), FINANCIAL_APPROVE_CAPABILITY)
    with pytest.raises(FinancialDraftAuthorizationError):
        service.reject(property_id, draft_id, "Not supported", actor=elsewhere)
    assert _decision(migrated_database_url, draft_id) is None

    rejected = service.reject(property_id, draft_id, "Amount not supported", actor=approver)
    assert rejected["state"] == "REJECTED"
    assert rejected["prepared_by"] == str(staff_id)
    assert service.reject(property_id, draft_id, "Amount not supported", actor=approver) == (
        rejected
    )
    with pytest.raises(FinancialDraftConflictError):
        service.reject(property_id, draft_id, "Another reason", actor=approver)
    with pytest.raises(FinancialDraftConflictError):
        service.withdraw(
            property_id, draft_id, "Too late", prepare_capability="refunds.create", actor=staff
        )
    assert _decision(migrated_database_url, draft_id) == (
        "REJECTED",
        approver_id,
        FINANCIAL_APPROVE_CAPABILITY,
        "Amount not supported",
    )


def test_database_refuses_a_rejection_without_the_approval_reference(
    migrated_database_url: str,  # noqa: F811
) -> None:
    staff_id, property_id = _sources(migrated_database_url)
    draft_id = _draft(migrated_database_url, property_id, staff_id)
    for reference in ("refunds.create", "", None):
        with psycopg.connect(financial_database_url()) as connection:
            with pytest.raises(psycopg.Error) as failure:
                connection.execute(
                    "SELECT app.reject_financial_draft(%s,%s,%s,%s,%s)",
                    (property_id, staff_id, draft_id, "Staff tries to decide", reference),
                )
        assert failure.value.sqlstate == "42501"
    assert _decision(migrated_database_url, draft_id) is None

    approver = actor(staff_id, property_id, FINANCIAL_APPROVE_CAPABILITY)
    rejected = _service().reject(property_id, draft_id, "Not supported", actor=approver)
    # After the decision, the same request with a wrong reference is still refused.
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as repeated:
            connection.execute(
                "SELECT app.reject_financial_draft(%s,%s,%s,%s,%s)",
                (property_id, staff_id, draft_id, "Not supported", "refunds.create"),
            )
    assert repeated.value.sqlstate == "42501"
    assert _service().reject(property_id, draft_id, "Not supported", actor=approver) == rejected


def test_only_the_preparer_with_the_prepare_capability_may_withdraw(
    migrated_database_url: str,  # noqa: F811
) -> None:
    staff_id, property_id = _sources(migrated_database_url)
    other_id = _human(migrated_database_url, "other-staff")
    draft_id = _draft(
        migrated_database_url,
        property_id,
        staff_id,
        FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
        "FINAL_SETTLEMENT",
    )
    service = _service()

    with pytest.raises(FinancialDraftAuthorizationError):
        service.withdraw(
            property_id,
            draft_id,
            "Prepared twice",
            prepare_capability=FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            actor=actor(staff_id, property_id, "refunds.read"),
        )
    with pytest.raises(FinancialDraftAuthorizationError):
        service.withdraw(
            property_id,
            draft_id,
            "Prepared twice",
            prepare_capability=FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            actor=actor(other_id, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY),
        )
    with pytest.raises(FinancialDraftAuthorizationError):
        service.withdraw(
            property_id,
            draft_id,
            "Prepared twice",
            prepare_capability="refunds.create",
            actor=actor(staff_id, property_id, "refunds.create"),
        )
    assert _decision(migrated_database_url, draft_id) is None

    withdrawn = service.withdraw(
        property_id,
        draft_id,
        "Prepared twice",
        prepare_capability=FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
        actor=actor(staff_id, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY),
    )
    assert withdrawn["state"] == "WITHDRAWN"
    assert _decision(migrated_database_url, draft_id) == (
        "WITHDRAWN",
        staff_id,
        FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
        "Prepared twice",
    )
    # After the decision, a repeat with another capability is refused; the exact repeat replays.
    with pytest.raises(FinancialDraftAuthorizationError):
        service.withdraw(
            property_id,
            draft_id,
            "Prepared twice",
            prepare_capability="refunds.create",
            actor=actor(staff_id, property_id, "refunds.create"),
        )
    assert (
        service.withdraw(
            property_id,
            draft_id,
            "Prepared twice",
            prepare_capability=FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            actor=actor(staff_id, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY),
        )
        == withdrawn
    )


def test_confirmation_is_recorded_once_with_preparer_and_confirmer(
    migrated_database_url: str,  # noqa: F811
) -> None:
    owner_id, property_id = _sources(migrated_database_url)
    draft_id = _draft(migrated_database_url, property_id, owner_id)
    for reference in ("refunds.create", None):
        with psycopg.connect(migrated_database_url) as connection:
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(
                    "SELECT app.confirm_financial_draft_record(%s,%s,%s,%s,%s,%s)",
                    (property_id, owner_id, draft_id, "REFUND", Jsonb({}), reference),
                )
        assert refused.value.sqlstate == "42501"
    # A confirm command of another kind can never confirm this Refund draft.
    for kind in ("FINAL_SETTLEMENT", None):
        with psycopg.connect(migrated_database_url) as connection:
            with pytest.raises(psycopg.Error) as mismatched:
                connection.execute(
                    "SELECT app.confirm_financial_draft_record(%s,%s,%s,%s,%s,%s)",
                    (
                        property_id,
                        owner_id,
                        draft_id,
                        kind,
                        Jsonb({}),
                        FINANCIAL_APPROVE_CAPABILITY,
                    ),
                )
        assert mismatched.value.sqlstate == "22023"
        assert mismatched.value.diag.message_primary == (
            "Financial draft kind does not match the confirm command"
        )
    assert _decision(migrated_database_url, draft_id) is None
    with psycopg.connect(migrated_database_url) as connection:
        confirmed = connection.execute(
            "SELECT app.confirm_financial_draft_record(%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                owner_id,
                draft_id,
                "REFUND",
                Jsonb({"refund_id": str(uuid4())}),
                FINANCIAL_APPROVE_CAPABILITY,
            ),
        ).fetchone()
        connection.commit()
    assert confirmed is not None
    # The same person prepared and confirmed; both are recorded.
    assert cast(dict[str, object], confirmed[0])["prepared_by"] == str(owner_id)
    assert _decision(migrated_database_url, draft_id) == (
        "CONFIRMED",
        owner_id,
        FINANCIAL_APPROVE_CAPABILITY,
        None,
    )
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error) as failure:
            connection.execute(
                "SELECT app.confirm_financial_draft_record(%s,%s,%s,%s,%s,%s)",
                (
                    property_id,
                    owner_id,
                    draft_id,
                    "REFUND",
                    Jsonb({"refund_id": str(uuid4())}),
                    FINANCIAL_APPROVE_CAPABILITY,
                ),
            )
    assert failure.value.sqlstate == "55000"
    with pytest.raises(FinancialDraftConflictError):
        _service().reject(
            property_id,
            draft_id,
            "Too late",
            actor=actor(owner_id, property_id, FINANCIAL_APPROVE_CAPABILITY),
        )


def test_draft_history_is_append_only_and_internal_helpers_are_not_granted(
    migrated_database_url: str,  # noqa: F811
) -> None:
    staff_id, property_id = _sources(migrated_database_url)
    draft_id = _draft(migrated_database_url, property_id, staff_id)
    _service().reject(
        property_id,
        draft_id,
        "Not supported",
        actor=actor(staff_id, property_id, FINANCIAL_APPROVE_CAPABILITY),
    )
    for statement in (
        "UPDATE app.financial_drafts SET reason='changed' WHERE id=%s",
        "DELETE FROM app.financial_drafts WHERE id=%s",
        "UPDATE app.financial_draft_decisions SET reason='changed' WHERE draft_id=%s",
        "DELETE FROM app.financial_draft_decisions WHERE draft_id=%s",
    ):
        with psycopg.connect(migrated_database_url) as connection:
            with pytest.raises(psycopg.Error) as failure:
                connection.execute(statement, (draft_id,))
        assert failure.value.sqlstate == "55000"
    for table in sorted(NEW_TABLES):
        with psycopg.connect(migrated_database_url) as connection:
            with pytest.raises(psycopg.Error) as failure:
                connection.execute(f"TRUNCATE {table} CASCADE")
        assert failure.value.sqlstate == "55000"

    for url in (runtime_database_url(), financial_database_url()):
        for table in sorted(NEW_TABLES):
            with psycopg.connect(url) as connection:
                with pytest.raises(psycopg.Error) as failure:
                    connection.execute(f"SELECT count(*) FROM {table}")
            assert failure.value.sqlstate == "42501"
        with psycopg.connect(url) as connection:
            for function in INTERNAL_FUNCTIONS:
                assert connection.execute(
                    "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (function,)
                ).fetchone() == (False,)
            assert connection.execute(
                "SELECT has_function_privilege(current_user,%s,'EXECUTE')",
                ("app.reject_financial_draft(uuid,uuid,uuid,text,text)",),
            ).fetchone() == ((url == financial_database_url()),)
            assert connection.execute(
                "SELECT has_function_privilege(current_user,%s,'EXECUTE')",
                ("app.financial_draft_resource(uuid,uuid,uuid,text[])",),
            ).fetchone() == ((url == runtime_database_url()),)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_proc p "
            "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='app' AND p.proname LIKE '%%financial_draft%%' "
            "AND has_function_privilege('public',p.oid,'EXECUTE')"
        ).fetchone() == (0,)


def test_reads_need_a_draft_capability_and_stay_inside_the_property(
    migrated_database_url: str,  # noqa: F811
) -> None:
    staff_id, property_id = _sources(migrated_database_url)
    first = _draft(migrated_database_url, property_id, staff_id)
    second = _draft(migrated_database_url, property_id, staff_id)
    service = _service()
    reader = actor(staff_id, property_id, "refunds.create")

    with pytest.raises(FinancialDraftAuthorizationError):
        service.get(property_id, first, actor=actor(staff_id, property_id, "refunds.read"))
    with pytest.raises(FinancialDraftNotFoundError):
        service.get(property_id, uuid4(), actor=reader)
    detail = service.get(property_id, first, actor=reader)
    assert detail["state"] == "PENDING"
    assert detail["decision"] is None
    assert detail["payload"] == {"amount_usd_cents": 1_000}

    service.reject(
        property_id,
        second,
        "Duplicate",
        actor=actor(staff_id, property_id, FINANCIAL_APPROVE_CAPABILITY),
    )
    pending = service.list(
        property_id, actor=reader, page=FinancialDraftPage(state=FinancialDraftState.PENDING)
    )
    pending_ids = {item["draft_id"] for item in cast(list[dict[str, object]], pending["items"])}
    assert str(first) in pending_ids and str(second) not in pending_ids
    newest = service.list(property_id, actor=reader, page=FinancialDraftPage(limit=1))
    items = cast(list[dict[str, object]], newest["items"])
    assert len(items) == 1

    inactive = _human(migrated_database_url, "inactive")
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
            (inactive,),
        )
        connection.commit()
    with pytest.raises(FinancialDraftAuthorizationError):
        service.get(property_id, first, actor=actor(inactive, property_id, "refunds.create"))


def _catalog(url: str) -> tuple[dict[str, tuple[object, ...]], set[str]]:
    with psycopg.connect(url) as connection:
        functions = {
            str(row[0]): row[1:]
            for row in connection.execute(
                "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                "p.proacl::text FROM pg_catalog.pg_proc p "
                "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='app' AND p.prokind='f'"
            ).fetchall()
        }
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT c.oid::regclass::text FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
            ).fetchall()
        }
    return functions, tables


def test_financial_draft_migration_is_additive_and_forward_only(
    migrated_database_url: str,  # noqa: F811
) -> None:
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261012_77")
    assert revision is not None and revision.down_revision == "20261011_76"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("financial_drafts") as temporary:
        alembic_command.upgrade(config, "20261011_76")
        before_functions, before_tables = _catalog(temporary)
        alembic_command.upgrade(config, "20261012_77")
        after_functions, after_tables = _catalog(temporary)
    assert after_tables - before_tables == NEW_TABLES
    assert before_tables <= after_tables
    assert {name: after_functions[name] for name in before_functions} == before_functions
    assert all("financial_draft" in name for name in set(after_functions) - set(before_functions))


def test_each_draft_kind_accepts_only_its_own_prepare_capabilities(
    migrated_database_url: str,  # noqa: F811
) -> None:
    staff_id, property_id = _sources(migrated_database_url)
    for kind, capability in (
        ("FINAL_SETTLEMENT", "refunds.create"),
        ("SETTLEMENT_CORRECTION", "deposits.dispose"),
        ("REFUND", "final_settlements.prepare"),
        ("PAYMENT_MOVE", "refunds.create"),
        ("DEPOSIT_FORFEITURE", "payments.allocations.reverse"),
    ):
        with pytest.raises(psycopg.Error) as failure:
            _draft(migrated_database_url, property_id, staff_id, capability, kind)
        assert failure.value.sqlstate == "23514"
    for kind, capability in (
        ("REFUND", "reservation_deposits.refund"),
        ("DEPOSIT_FORFEITURE", "reservation_deposits.dispose"),
        ("PAYMENT_MOVE", "payments.allocations.reverse"),
        ("SETTLEMENT_CORRECTION", "final_settlements.prepare"),
    ):
        _draft(migrated_database_url, property_id, staff_id, capability, kind)


def test_readers_see_only_their_kinds_and_never_another_property(
    migrated_database_url: str,  # noqa: F811
) -> None:
    staff_id, property_id = _sources(migrated_database_url)
    refund = _draft(migrated_database_url, property_id, staff_id)
    settlement = _draft(
        migrated_database_url,
        property_id,
        staff_id,
        FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
        "FINAL_SETTLEMENT",
    )
    service = _service()
    mover = actor(staff_id, property_id, "payments.allocations.reverse")
    preparer = actor(staff_id, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY)
    approver = actor(staff_id, property_id, FINANCIAL_APPROVE_CAPABILITY)

    with pytest.raises(FinancialDraftNotFoundError):
        service.get(property_id, refund, actor=mover)
    with pytest.raises(FinancialDraftNotFoundError):
        service.get(property_id, refund, actor=preparer)
    assert service.get(property_id, settlement, actor=preparer)["kind"] == "FINAL_SETTLEMENT"
    assert service.get(property_id, refund, actor=approver)["kind"] == "REFUND"
    seen = {
        item["draft_id"]
        for item in cast(
            list[dict[str, object]],
            service.list(property_id, actor=preparer, page=FinancialDraftPage(limit=100))["items"],
        )
    }
    assert str(settlement) in seen and str(refund) not in seen
    assert all(
        item["kind"] in {"FINAL_SETTLEMENT", "SETTLEMENT_CORRECTION"}
        for item in cast(
            list[dict[str, object]],
            service.list(property_id, actor=preparer, page=FinancialDraftPage(limit=100))["items"],
        )
    )

    other_property = uuid4()
    elsewhere = actor(staff_id, other_property, FINANCIAL_APPROVE_CAPABILITY)
    with pytest.raises(FinancialDraftNotFoundError):
        service.get(other_property, refund, actor=elsewhere)
    assert service.list(other_property, actor=elsewhere)["items"] == []
    with pytest.raises(FinancialDraftNotFoundError):
        service.reject(other_property, refund, "Wrong Property", actor=elsewhere)
    with pytest.raises(FinancialDraftNotFoundError):
        service.withdraw(
            other_property,
            settlement,
            "Wrong Property",
            prepare_capability=FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            actor=actor(staff_id, other_property, FINAL_SETTLEMENTS_PREPARE_CAPABILITY),
        )
    assert _decision(migrated_database_url, refund) is None
    assert _decision(migrated_database_url, settlement) is None


@pytest.mark.parametrize("reason", ("", "  padded  ", None))
def test_reject_and_withdraw_need_a_trimmed_reason(
    migrated_database_url: str,  # noqa: F811
    reason: str | None,
) -> None:
    staff_id, property_id = _sources(migrated_database_url)
    draft_id = _draft(migrated_database_url, property_id, staff_id)
    service = _service()
    with pytest.raises(FinancialDraftInvalidError):
        service.reject(
            property_id,
            draft_id,
            cast(str, reason),
            actor=actor(staff_id, property_id, FINANCIAL_APPROVE_CAPABILITY),
        )
    with pytest.raises(FinancialDraftInvalidError):
        service.withdraw(
            property_id,
            draft_id,
            cast(str, reason),
            prepare_capability="refunds.create",
            actor=actor(staff_id, property_id, "refunds.create"),
        )
    for statement, reference in (
        ("SELECT app.reject_financial_draft(%s,%s,%s,%s,%s)", FINANCIAL_APPROVE_CAPABILITY),
        ("SELECT app.withdraw_financial_draft(%s,%s,%s,%s,%s)", "refunds.create"),
    ):
        with psycopg.connect(financial_database_url()) as connection:
            with pytest.raises(psycopg.Error) as failure:
                connection.execute(statement, (property_id, staff_id, draft_id, reason, reference))
        assert failure.value.sqlstate == "22023"
    assert _decision(migrated_database_url, draft_id) is None


def test_bad_page_and_capability_input_is_refused_as_invalid() -> None:
    with pytest.raises(FinancialDraftInvalidError):
        FinancialDraftPage(after_prepared_at=cast(datetime, "2026-10-03"), after_id=uuid4())
    with pytest.raises(FinancialDraftInvalidError):
        require_draft_preparer(
            actor(uuid4(), UUID(int=1), "refunds.create"),
            UUID(int=1),
            cast(str, ["refunds.create"]),
        )
