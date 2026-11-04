"""General Ledger automatic posting: "Needs check" and method accounts (phase 6 step 2).

Owner plan of 03/11/2026 (rights table L1): reading the ledger needs `ledger.read` (Owner and
Manager); setting the ledger account of a Payment Method or Refund method needs
`ledger.accounts.manage` (Owner only) and the browser mutation checks.

- `GET /api/v1/properties/{property_id}/ledger/needs-check` lists the money records the automatic
  posting could not post yet, with the reason.
- `GET /api/v1/properties/{property_id}/ledger/method-accounts` lists every Payment Method and
  Refund method with the ledger account it posts to today (none = its records wait in "Needs
  check").
- `PUT /api/v1/properties/{property_id}/ledger/method-accounts` sets one method's account from a
  date; `app.gl_set_method_account` writes the row and the audit event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.ledger_books_api import link_sql, source_link, source_sql
from property_rental.settings import Settings

LEDGER_READ = "ledger.read"
LEDGER_ACCOUNTS_MANAGE = "ledger.accounts.manage"
MethodKind = Literal["PAYMENT", "REFUND"]


class LedgerPostingNotFound(LookupError):
    """The Property or the method is not there."""


class LedgerPostingInvalid(ValueError):
    """The account or the method is refused."""


class LedgerPostingUnavailable(RuntimeError):
    """Persistence is unavailable."""


@dataclass(frozen=True, slots=True)
class PostingProblem:
    posting_key: str
    source_type: str
    source_id: UUID
    event_date: date
    problem: str
    first_seen_at: datetime
    last_seen_at: datetime
    # Step 6 part 1: the app record's number and the page that opens it, when known.
    source_number: str | None = None
    source_link: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class MethodAccount:
    kind: str
    method_id: UUID
    code: str
    name: str
    account_code: str | None
    account_name: str | None
    effective_from: date | None


class LedgerPostingFlow(Protocol):
    def needs_check(self, property_id: UUID) -> tuple[PostingProblem, ...]: ...

    def method_accounts(self, property_id: UUID) -> tuple[MethodAccount, ...]: ...

    def set_method_account(
        self,
        property_id: UUID,
        *,
        kind: str,
        method_id: UUID,
        account_code: str,
        effective_from: date,
        actor_id: str,
    ) -> None: ...


class UnavailableLedgerPostingFlow:
    def needs_check(self, property_id: UUID) -> tuple[PostingProblem, ...]:
        del property_id
        raise LedgerPostingUnavailable

    def method_accounts(self, property_id: UUID) -> tuple[MethodAccount, ...]:
        del property_id
        raise LedgerPostingUnavailable

    def set_method_account(self, property_id: UUID, **_: object) -> None:
        del property_id
        raise LedgerPostingUnavailable


class PostgresLedgerPostingFlow:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _property_day(self, connection: psycopg.Connection[tuple[object, ...]], prop: UUID) -> date:
        row = connection.execute(
            "SELECT timezone(timezone_name, statement_timestamp())::date FROM app.properties "
            "WHERE id = %s",
            (prop,),
        ).fetchone()
        if row is None or not isinstance(row[0], date):
            raise LedgerPostingNotFound("The Property was not found")
        return row[0]

    def needs_check(self, property_id: UUID) -> tuple[PostingProblem, ...]:
        try:
            with psycopg.connect(self._database_url) as connection:
                self._property_day(connection, property_id)
                rows = connection.execute(
                    "SELECT problem.posting_key, problem.source_type, problem.source_id, "
                    "problem.event_date, problem.problem, problem.first_seen_at, "
                    f"problem.last_seen_at, ({source_sql('problem', None)}), "
                    f"({link_sql('problem')}) FROM app.gl_posting_problems AS problem "
                    "WHERE problem.property_id = %s "
                    "ORDER BY problem.event_date, problem.posting_key",
                    (property_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise LedgerPostingUnavailable from exc
        return tuple(
            PostingProblem(
                str(key),
                str(kind),
                UUID(str(source)),
                day,
                str(problem),
                first,
                last,
                None if number is None else str(number),
                source_link(str(kind), target),
            )
            for key, kind, source, day, problem, first, last, number, target in rows
        )

    def method_accounts(self, property_id: UUID) -> tuple[MethodAccount, ...]:
        query = """
            SELECT method.kind, method.id, method.code, method.name, account.code,
                account.name_en, mapped.effective_from
            FROM (
                SELECT 'PAYMENT' AS kind, id, code, display_name AS name, accepted AS active
                FROM app.payment_methods
                UNION ALL
                SELECT 'REFUND', id, code, display_name, active FROM app.refund_methods
            ) AS method
            LEFT JOIN LATERAL (
                SELECT map.account_id, map.effective_from FROM app.gl_method_accounts AS map
                WHERE map.property_id = %(prop)s AND map.effective_from <= %(day)s
                  AND CASE method.kind WHEN 'PAYMENT' THEN map.payment_method_id
                      ELSE map.refund_method_id END = method.id
                ORDER BY map.effective_from DESC, map.created_at DESC LIMIT 1
            ) AS mapped ON true
            LEFT JOIN app.gl_accounts AS account ON account.id = mapped.account_id
            ORDER BY method.kind, method.code
        """
        try:
            with psycopg.connect(self._database_url) as connection:
                day = self._property_day(connection, property_id)
                rows = connection.execute(query, {"prop": property_id, "day": day}).fetchall()
        except psycopg.Error as exc:
            raise LedgerPostingUnavailable from exc
        return tuple(
            MethodAccount(
                str(kind),
                UUID(str(method)),
                str(code),
                str(name),
                None if account is None else str(account),
                None if account_name is None else str(account_name),
                since,
            )
            for kind, method, code, name, account, account_name, since in rows
        )

    def set_method_account(
        self,
        property_id: UUID,
        *,
        kind: str,
        method_id: UUID,
        account_code: str,
        effective_from: date,
        actor_id: str,
    ) -> None:
        payment = method_id if kind == "PAYMENT" else None
        refund = method_id if kind == "REFUND" else None
        try:
            with psycopg.connect(self._database_url) as connection:
                self._property_day(connection, property_id)
                connection.execute(
                    "SELECT app.gl_set_method_account(%s, %s, %s, %s, %s, %s, %s)",
                    (
                        property_id,
                        payment,
                        refund,
                        account_code,
                        effective_from,
                        UUID(actor_id),
                        uuid4(),
                    ),
                )
        except psycopg.errors.ForeignKeyViolation as exc:
            raise LedgerPostingNotFound("The method was not found") from exc
        except (psycopg.errors.InvalidParameterValue, psycopg.errors.CheckViolation) as exc:
            raise LedgerPostingInvalid(str(exc).splitlines()[0]) from exc
        except psycopg.Error as exc:
            raise LedgerPostingUnavailable from exc


class MethodAccountChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: MethodKind
    method_id: UUID
    account_code: str = Field(pattern=r"^[0-9]{4}$")
    effective_from: date

    @field_validator("method_id", mode="before")
    @classmethod
    def _uuid(cls, raw: object) -> object:
        return UUID(raw) if isinstance(raw, str) else raw

    @field_validator("effective_from", mode="before")
    @classmethod
    def _iso_date(cls, raw: object) -> object:
        return date.fromisoformat(raw) if isinstance(raw, str) else raw


def _require(
    request: Request, resolver: ActorResolver, capability: str, property_id: UUID
) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if not is_authorized(
        actor, AuthorizationRequirement(capability=capability, property_id=str(property_id))
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return actor


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, LedgerPostingNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, LedgerPostingInvalid):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


def _method_body(row: MethodAccount) -> dict[str, object]:
    return {
        "kind": row.kind,
        "method_id": str(row.method_id),
        "code": row.code,
        "name": row.name,
        "account_code": row.account_code,
        "account_name": row.account_name,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
    }


def create_ledger_posting_router(
    resolver: ActorResolver, flow: LedgerPostingFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["ledger"])

    def methods(property_id: UUID, request: Request) -> dict[str, object]:
        try:
            rows = flow.method_accounts(property_id)
        except (LedgerPostingNotFound, LedgerPostingUnavailable) as exc:
            raise _http(exc) from exc
        return {
            "data": [_method_body(row) for row in rows],
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/properties/{property_id}/ledger/needs-check")
    def list_needs_check(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        _require(request, resolver, LEDGER_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            rows = flow.needs_check(property_id)
        except (LedgerPostingNotFound, LedgerPostingUnavailable) as exc:
            raise _http(exc) from exc
        return {
            "data": [
                {
                    "posting_key": row.posting_key,
                    "source_type": row.source_type,
                    "source_id": str(row.source_id),
                    "event_date": row.event_date.isoformat(),
                    "problem": row.problem,
                    "first_seen_at": row.first_seen_at.isoformat(),
                    "last_seen_at": row.last_seen_at.isoformat(),
                    "source_number": row.source_number,
                    "source_link": row.source_link,
                }
                for row in rows
            ],
            "meta": {"request_id": request.state.request_id, "count": len(rows)},
        }

    @router.get("/properties/{property_id}/ledger/method-accounts")
    def list_method_accounts(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        _require(request, resolver, LEDGER_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        return methods(property_id, request)

    @router.put("/properties/{property_id}/ledger/method-accounts")
    def set_method_account(
        property_id: UUID, change: MethodAccountChange, request: Request
    ) -> dict[str, object]:
        actor = _require(request, resolver, LEDGER_ACCOUNTS_MANAGE, property_id)
        require_browser_mutation(request, settings)
        try:
            flow.set_method_account(
                property_id,
                kind=change.kind,
                method_id=change.method_id,
                account_code=change.account_code,
                effective_from=change.effective_from,
                actor_id=actor.actor_id,
            )
        except (LedgerPostingNotFound, LedgerPostingInvalid, LedgerPostingUnavailable) as exc:
            raise _http(exc) from exc
        return methods(property_id, request)

    return router
