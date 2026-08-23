"""Canonical Customer identity, reuse matching, and protected persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

import psycopg

NIL_UUID = UUID(int=0)


def normalize_optional(value: str | None) -> str | None:
    """Normalize an optional contact value without inventing a mandatory channel."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def normalized_email(value: str | None) -> str | None:
    """Return the technical email match key while preserving the entered value."""
    normalized = normalize_optional(value)
    return None if normalized is None else normalized.casefold()


def normalized_phone(value: str | None) -> str | None:
    """Return a conservative digit match key; never use it to merge automatically."""
    normalized = normalize_optional(value)
    if normalized is None:
        return None
    digits = "".join(character for character in normalized if character.isdigit())
    return digits or None


@dataclass(frozen=True, slots=True)
class Customer:
    """One stable person identity with current, optional contact values."""

    customer_id: UUID
    legal_name: str
    phone_number: str | None = None
    email_address: str | None = None
    contact_address: str | None = None
    memo: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if self.customer_id == NIL_UUID:
            raise ValueError("customer_id must not be the nil UUID")
        if not self.legal_name.strip():
            raise ValueError("legal_name must not be blank")
        if self.legal_name != self.legal_name.strip():
            raise ValueError("legal_name must not have surrounding whitespace")
        for field_name in (
            "phone_number",
            "email_address",
            "contact_address",
            "memo",
        ):
            value = getattr(self, field_name)
            if value is not None and (not value.strip() or value != value.strip()):
                raise ValueError(f"{field_name} must be null or normalized nonblank text")
        if self.version < 1:
            raise ValueError("version must be positive")


class CustomerIdentityAlreadyExistsError(ValueError):
    """Raised when a stable Customer UUID has already been assigned."""


class CustomerVersionConflict(RuntimeError):
    """Raised when a Customer update targets an obsolete version."""

    def __init__(self, current_version: int) -> None:
        super().__init__("the Customer version precondition was not met")
        self.current_version = current_version


class CustomerReuseRequired(ValueError):
    """Require an explicit reuse-or-distinct decision for plausible duplicates."""

    def __init__(self, candidates: tuple[Customer, ...]) -> None:
        super().__init__("an existing Customer may represent the same person")
        self.candidates = candidates


class CustomerRepository(Protocol):
    """Persistence operations required by the Customer service."""

    def find_reuse_candidates(
        self,
        *,
        email_key: str | None,
        phone_key: str | None,
    ) -> tuple[Customer, ...]: ...

    def add(self, customer: Customer) -> None: ...

    def update(self, customer: Customer, *, expected_version: int) -> Customer: ...


@dataclass(frozen=True, slots=True)
class PostgresCustomerRepository:
    """Read and mutate Customers only through protected PostgreSQL functions."""

    database_url: str
    actor_id: UUID

    _columns = "id, legal_name, phone_number, email_address, contact_address, memo, version"

    def find_reuse_candidates(
        self,
        *,
        email_key: str | None,
        phone_key: str | None,
    ) -> tuple[Customer, ...]:
        if email_key is None and phone_key is None:
            return ()
        clauses: list[str] = []
        parameters: list[object] = []
        if email_key is not None:
            clauses.append("lower(email_address) = %s")
            parameters.append(email_key)
        if phone_key is not None:
            clauses.append("regexp_replace(phone_number, '[^0-9]', '', 'g') = %s")
            parameters.append(phone_key)
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                f"SELECT {self._columns} FROM app.customers "
                f"WHERE {' OR '.join(clauses)} ORDER BY legal_name, id LIMIT 20",
                tuple(parameters),
            ).fetchall()
        return tuple(_customer_from_row(row) for row in rows)

    def add(self, customer: Customer) -> None:
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(
                    """
                    SELECT * FROM app.create_customer(
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        customer.customer_id,
                        customer.legal_name,
                        customer.phone_number,
                        customer.email_address,
                        customer.contact_address,
                        customer.memo,
                        self.actor_id,
                        uuid4(),
                    ),
                ).fetchone()
        except psycopg.errors.UniqueViolation as error:
            raise CustomerIdentityAlreadyExistsError(
                f"Customer identity {customer.customer_id} already exists"
            ) from error
        if row is None or _customer_from_row(row) != customer:
            raise RuntimeError("Customer creation returned an invalid result")

    def update(self, customer: Customer, *, expected_version: int) -> Customer:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                """
                SELECT * FROM app.update_customer(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    customer.customer_id,
                    customer.legal_name,
                    customer.phone_number,
                    customer.email_address,
                    customer.contact_address,
                    customer.memo,
                    expected_version,
                    self.actor_id,
                    uuid4(),
                ),
            ).fetchone()
            if row is None:
                current = connection.execute(
                    "SELECT version FROM app.customers WHERE id = %s",
                    (customer.customer_id,),
                ).fetchone()
                if current is None:
                    raise LookupError("Customer was not found")
                raise CustomerVersionConflict(int(str(current[0])))
        return _customer_from_row(row)


@dataclass(frozen=True, slots=True)
class CustomerService:
    """Create and update stable Customer identities without silent merging."""

    repository: CustomerRepository

    def create(
        self,
        customer_id: UUID,
        *,
        legal_name: str,
        phone_number: str | None = None,
        email_address: str | None = None,
        contact_address: str | None = None,
        memo: str | None = None,
        confirmed_distinct: bool = False,
    ) -> Customer:
        customer = Customer(
            customer_id=customer_id,
            legal_name=legal_name.strip(),
            phone_number=normalize_optional(phone_number),
            email_address=normalize_optional(email_address),
            contact_address=normalize_optional(contact_address),
            memo=normalize_optional(memo),
        )
        candidates = self._other_candidates(customer)
        if candidates and not confirmed_distinct:
            raise CustomerReuseRequired(candidates)
        self.repository.add(customer)
        return customer

    def update(
        self,
        current: Customer,
        *,
        legal_name: str,
        phone_number: str | None,
        email_address: str | None,
        contact_address: str | None,
        memo: str | None,
        confirmed_distinct: bool = False,
    ) -> Customer:
        candidate = Customer(
            customer_id=current.customer_id,
            legal_name=legal_name.strip(),
            phone_number=normalize_optional(phone_number),
            email_address=normalize_optional(email_address),
            contact_address=normalize_optional(contact_address),
            memo=normalize_optional(memo),
            version=current.version + 1,
        )
        matches = self._other_candidates(candidate)
        if matches and not confirmed_distinct:
            raise CustomerReuseRequired(matches)
        return self.repository.update(candidate, expected_version=current.version)

    def _other_candidates(self, customer: Customer) -> tuple[Customer, ...]:
        matches = self.repository.find_reuse_candidates(
            email_key=normalized_email(customer.email_address),
            phone_key=normalized_phone(customer.phone_number),
        )
        return tuple(match for match in matches if match.customer_id != customer.customer_id)


def _customer_from_row(row: tuple[object, ...]) -> Customer:
    return Customer(
        customer_id=UUID(str(row[0])),
        legal_name=str(row[1]),
        phone_number=None if row[2] is None else str(row[2]),
        email_address=None if row[3] is None else str(row[3]),
        contact_address=None if row[4] is None else str(row[4]),
        memo=None if row[5] is None else str(row[5]),
        version=int(str(row[6])),
    )
