"""Narrow financial references and exact non-persisting KHR preview."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import psycopg

from property_rental.configuration_api import ExchangeRateProvider, UnavailableExchangeRateProvider
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.khr_payment_confirmation import (
    ApprovedKhrSourceUnavailable,
    ManualKhrReference,
    _money,
    select_khr_reference,
)
from property_rental.payment_confirmation import (
    PaymentConfirmationConflictError,
    PaymentConfirmationInvalidError,
    PaymentConfirmationUnavailableError,
)
from property_rental.payment_read import (
    PaymentReadAuthorizationError,
    PaymentReadInvalidError,
    PaymentReadNotFoundError,
    PaymentReadUnavailableError,
    _uuid,
)

FINANCIAL_CAPABILITIES = (
    "payments.read",
    "payments.record",
    "payments.allocate",
    "payments.allocations.reverse",
    "payments.reverse",
    "receipts.read",
    "receipts.reprint",
    "credits.read",
    "credits.recognize",
    "credits.reverse",
    "credits.apply",
    "credits.applications.reverse",
    "refunds.read",
    "refunds.create",
    "refunds.correct",
    "refunds.corrections.reverse",
)


def capabilities(actor: AuthenticatedActor, property_id: UUID) -> dict[str, bool]:
    _uuid(property_id)
    return {
        cap: is_authorized(actor, AuthorizationRequirement(cap, str(property_id)))
        for cap in (*FINANCIAL_CAPABILITIES, "exchange_rates.manage")
    }


def require_record(actor: AuthenticatedActor, property_id: UUID) -> None:
    if not capabilities(actor, property_id)["payments.record"]:
        raise PaymentReadAuthorizationError("Payment references are not authorized")


@dataclass(frozen=True, slots=True)
class ReferencePage:
    limit: int = 50
    after_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise PaymentReadInvalidError("Reference page limit is invalid")
        if self.after_id is not None:
            _uuid(self.after_id)


_ACTIVE_ACTOR = """
SELECT EXISTS(SELECT 1 FROM app.user_accounts account
JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
WHERE account.actor_id=%s AND account.lifecycle_state='active'
AND identity.identity_kind='HUMAN')
"""


@dataclass(frozen=True, slots=True)
class FinancialReferenceService:
    database_url: str | None
    provider: ExchangeRateProvider = field(default_factory=UnavailableExchangeRateProvider)

    @contextmanager
    def _read(
        self, actor: AuthenticatedActor, property_id: UUID | None = None
    ) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
        try:
            actor_id = UUID(actor.actor_id)
            _uuid(actor_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise PaymentReadAuthorizationError("Financial actor is invalid") from exc
        if property_id is not None:
            _uuid(property_id)
        if self.database_url is None:
            raise PaymentReadUnavailableError("Financial references are unavailable")
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                fresh = connection.execute(_ACTIVE_ACTOR, (actor_id,)).fetchone()
                if fresh != (True,):
                    raise PaymentReadAuthorizationError("Financial actor is not active")
                if property_id is not None:
                    found = connection.execute(
                        "SELECT 1 FROM app.property_configuration WHERE property_id=%s",
                        (property_id,),
                    ).fetchone()
                    if found is None:
                        raise PaymentReadNotFoundError("Financial Property was not found")
                yield connection
        except psycopg.Error as exc:
            if exc.sqlstate == "42501":
                raise PaymentReadAuthorizationError("Financial reference access is denied") from exc
            raise PaymentReadUnavailableError("Financial references are unavailable") from exc

    def workspaces(self, page: ReferencePage, *, actor: AuthenticatedActor) -> dict[str, object]:
        checked = ReferencePage(page.limit, page.after_id)
        # Only explicit exact financial grant Property scopes are selectable. Global,
        # object-only, unrelated or noncanonical provider scopes infer no rights.
        ids: set[UUID] = set()
        for grant in actor.capability_grants:
            if grant.capability not in FINANCIAL_CAPABILITIES:
                continue
            for identity in grant.property_ids:
                try:
                    value = UUID(identity)
                    if value.int and str(value) == identity:
                        ids.add(value)
                except (ValueError, TypeError, AttributeError):
                    continue
        with self._read(actor) as connection:
            rows = connection.execute(
                "SELECT property_id,name,timezone_name FROM app.property_configuration "
                "WHERE property_id=ANY(%s::uuid[]) AND (%s::uuid IS NULL OR property_id>%s) "
                "ORDER BY property_id LIMIT %s",
                (sorted(ids), checked.after_id, checked.after_id, checked.limit + 1),
            ).fetchall()
        items = [
            {
                "property_id": str(row[0]),
                "name": row[1],
                "timezone": row[2],
                "capabilities": capabilities(actor, cast(UUID, row[0])),
            }
            for row in rows[: checked.limit]
        ]
        return {
            "items": items,
            "next_cursor": str(rows[checked.limit - 1][0]) if len(rows) > checked.limit else None,
        }

    def capability_view(self, property_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        with self._read(actor, property_id):
            return {
                "property_id": str(property_id),
                "capabilities": capabilities(actor, property_id),
            }

    def methods(
        self, property_id: UUID, page: ReferencePage, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        require_record(actor, property_id)
        checked = ReferencePage(page.limit, page.after_id)
        with self._read(actor, property_id) as connection:
            # Accepted methods belong to the canonical singleton Property. Do not
            # load PropertyResource's unbounded configuration method collection.
            rows = connection.execute(
                "SELECT id,code,display_name FROM app.payment_methods WHERE accepted "
                "AND (%s::uuid IS NULL OR id>%s) ORDER BY id LIMIT %s",
                (checked.after_id, checked.after_id, checked.limit + 1),
            ).fetchall()
        return {
            "items": [
                {
                    "id": str(row[0]),
                    "property_id": str(property_id),
                    "code": row[1],
                    "display_name": row[2],
                }
                for row in rows[: checked.limit]
            ],
            "next_cursor": str(rows[checked.limit - 1][0]) if len(rows) > checked.limit else None,
        }

    def preview(
        self,
        property_id: UUID,
        usd_amount_cents: int,
        manual: ManualKhrReference | None,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        require_record(actor, property_id)
        _money(usd_amount_cents)
        allowed = capabilities(actor, property_id)["exchange_rates.manage"]
        if manual is not None:
            if not allowed:
                raise PaymentReadAuthorizationError("Manual reference is not authorized")
            if not isinstance(manual, ManualKhrReference):
                raise PaymentConfirmationInvalidError("Manual reference is invalid")
            manual = ManualKhrReference(
                manual.reference_rate_khr_per_usd,
                manual.source_reference,
                manual.applicable_at,
                manual.fallback_reason,
            )
        with self._read(actor, property_id):
            pass
        common = {
            "property_id": str(property_id),
            "usd_amount_cents": usd_amount_cents,
            "provisional": True,
        }
        try:
            # Preview must establish valid automatic evidence before calling it
            # available. Keep the accepted confirmation selector/replay unchanged.
            selected = select_khr_reference(self.provider, None)
        except ApprovedKhrSourceUnavailable:
            if manual is None:
                return {
                    **common,
                    "status": "source_unavailable",
                    "manual_fallback_allowed": allowed,
                }
            selected = {
                **manual.intent(),
                "rate_source": "ABA_EQUIVALENT_MANUAL",
                "automatic_source_unavailable": True,
            }
        applicable = datetime.fromisoformat(cast(str, selected["applicable_at"]))
        if applicable > datetime.now(UTC):
            if selected["automatic_source_unavailable"] is True:
                raise PaymentConfirmationInvalidError("Manual reference timestamp is in the future")
            raise PaymentConfirmationUnavailableError("Approved reference timestamp is invalid")
        if manual is not None and selected["automatic_source_unavailable"] is False:
            raise PaymentConfirmationConflictError(
                "Automatic source is available; manual fallback is not permitted"
            )
        millionths = int(cast(str, selected["reference_rate_khr_per_usd"]).replace(".", ""))
        marked = millionths * 1005
        rate = (marked + 1_000_000_000 - 1) // 1_000_000_000
        unrounded = usd_amount_cents * rate
        payable = (unrounded + 99) // 100
        _money(payable)
        return {
            **common,
            **selected,
            "status": "available",
            "markup_basis_points": 50,
            "system_rate_khr_per_usd": rate,
            "unrounded_khr_amount": f"{unrounded // 100}.{unrounded % 100:02d}",
            "payable_khr_amount": payable,
        }
