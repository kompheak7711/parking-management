"""Canonical Customer identity, reuse matching, and protected persistence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import InitVar, dataclass
from hashlib import md5
from typing import Protocol, cast, runtime_checkable
from uuid import UUID, uuid4

import psycopg

CUSTOMER_LOCK_TIMEOUT_MS = 1_000
CUSTOMER_STATEMENT_TIMEOUT_MS = 3_000
CUSTOMER_CONNECT_TIMEOUT_SECONDS = 3

NIL_UUID = UUID(int=0)
ID_DOCUMENT_NUMBER_MAX_LENGTH = 64
ID_DOCUMENT_NUMBER_INDEX = "customers_id_document_number_unique"


def normalize_optional(value: str | None) -> str | None:
    """Normalize an optional contact value without inventing a mandatory channel."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def normalized_email(value: str | None) -> str | None:
    """Return the migration-equivalent technical email match key."""
    normalized = normalize_optional(value)
    if normalized is None:
        return None
    try:
        canonical = canonical_email(normalized)
    except ValueError:
        # Revision 15 intentionally accepted arbitrary source text. Revision 16
        # backfills the same deterministic raw key when an historic domain cannot
        # be IDNA-canonicalized, so unrelated updates must use that key too.
        return normalized.casefold()
    return None if canonical is None else canonical.casefold()


def canonical_email(value: str | None) -> str | None:
    """Canonicalize an optional IDN domain for identical storage and reuse matching."""
    normalized = normalize_optional(value)
    if normalized is None or normalized.count("@") != 1:
        return normalized
    local, domain = normalized.rsplit("@", 1)
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("email_address must use a valid domain") from exc
    return f"{local}@{ascii_domain}"


def id_document_match_key(value: str | None) -> str | None:
    """Return the ID number compared for duplicates: no spaces or dashes, any capital letters.

    The same reading as `app.customer_id_document_match_key` (DL-071 answer 11, owner answer of
    2026-10-21).
    """
    normalized = normalize_optional(value)
    if normalized is None:
        return None
    key = "".join(character for character in normalized if not character.isspace())
    return key.replace("-", "").lower() or None


def normalized_phone(value: str | None) -> str | None:
    """Return a conservative digit match key; never use it to merge automatically."""
    normalized = normalize_optional(value)
    if normalized is None:
        return None
    digits = "".join(character for character in normalized if character in "0123456789")
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
    id_document_number: str | None = None
    _allow_legacy_phone: InitVar[bool] = False
    _allow_legacy_fields: InitVar[frozenset[str]] = frozenset()

    def __post_init__(
        self,
        _allow_legacy_phone: bool,
        _allow_legacy_fields: frozenset[str],
    ) -> None:
        if self.customer_id == NIL_UUID:
            raise ValueError("customer_id must not be the nil UUID")
        if "legal_name" not in _allow_legacy_fields:
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
            if (
                field_name not in _allow_legacy_fields
                and value is not None
                and (not value.strip() or value != value.strip())
            ):
                raise ValueError(f"{field_name} must be null or normalized nonblank text")
        if (
            not _allow_legacy_phone
            and "phone_number" not in _allow_legacy_fields
            and self.phone_number is not None
            and (
                not any(character in "0123456789" for character in self.phone_number)
                or any(character not in "0123456789+-.() " for character in self.phone_number)
            )
        ):
            raise ValueError("phone_number must use supported ASCII phone characters")
        if self.version < 1:
            raise ValueError("version must be positive")
        if "id_document_number" not in _allow_legacy_fields and self.id_document_number is not None:
            value = self.id_document_number
            if value != value.strip() or not 1 <= len(value) <= ID_DOCUMENT_NUMBER_MAX_LENGTH:
                raise ValueError(
                    "id_document_number must be normalized text of at most 64 characters"
                )
            if id_document_match_key(value) is None:
                raise ValueError("id_document_number must hold a letter or a digit")


class CustomerIdentityAlreadyExistsError(ValueError):
    """Raised when a stable Customer UUID has already been assigned."""


class CustomerVersionConflict(RuntimeError):
    """Raised when a Customer update targets an obsolete version."""

    def __init__(self, current_version: int) -> None:
        super().__init__("the Customer version precondition was not met")
        self.current_version = current_version


class CustomerIdNumberInUse(ValueError):
    """Another Customer has the same ID number; staff must use that Customer (DL-071 answer 11)."""

    def __init__(self, existing: Customer | None) -> None:
        super().__init__("another Customer has the same ID number")
        self.existing = existing


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


@runtime_checkable
class IdNumberCustomerRepository(Protocol):
    """Repository extension that finds the Customer holding an ID number."""

    def find_by_id_document_number(self, id_document_number: str) -> Customer | None: ...


@runtime_checkable
class SerializedCustomerRepository(Protocol):
    """Repository extension that serializes reuse decisions for contact keys."""

    def serialize_reuse_keys(
        self,
        *,
        email_key: str | None,
        phone_key: str | None,
    ) -> AbstractContextManager[None]: ...


@runtime_checkable
class VersionedCustomerRepository(Protocol):
    """Repository extension for an atomic optimistic-version assertion."""

    def assert_version(self, customer_id: UUID, expected_version: int) -> None: ...


@dataclass(frozen=True, slots=True)
class CustomerCommandContext:
    """Durable identity and canonical input for one Customer API command."""

    property_id: UUID
    action: str
    idempotency_key: UUID
    request_digest: str


@dataclass(frozen=True, slots=True)
class PostgresCustomerRepository:
    """Read and mutate Customers only through protected PostgreSQL functions."""

    database_url: str
    actor_id: UUID
    command: CustomerCommandContext | None = None

    _columns = (
        "id, legal_name, phone_number, email_address, contact_address, memo, version, "
        "id_document_number"
    )
    _qualified_columns = ", ".join(f"customer.{column.strip()}" for column in _columns.split(","))

    @staticmethod
    def _bound_work(connection: psycopg.Connection[tuple[object, ...]]) -> None:
        """Bound every statement executed while the serialized reuse lock is held."""
        connection.execute(
            "SELECT pg_catalog.set_config('lock_timeout', %s, true)",
            (str(CUSTOMER_LOCK_TIMEOUT_MS),),
        )
        connection.execute(
            "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
            (str(CUSTOMER_STATEMENT_TIMEOUT_MS),),
        )

    @contextmanager
    def serialize_reuse_keys(
        self,
        *,
        email_key: str | None,
        phone_key: str | None,
    ) -> Iterator[None]:
        """Hold deterministic transaction locks across each reuse check and write."""
        keys = sorted(
            key
            for key in (
                None if email_key is None else f"customer-email:{email_key}",
                None if phone_key is None else f"customer-phone:{phone_key}",
            )
            if key is not None
        )
        if not keys:
            yield
            return
        with psycopg.connect(
            self.database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
        ) as lock_connection:
            lock_connection.execute(
                "SELECT pg_catalog.set_config('lock_timeout', %s, true)",
                (str(CUSTOMER_LOCK_TIMEOUT_MS),),
            )
            lock_connection.execute(
                "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
                (str(CUSTOMER_STATEMENT_TIMEOUT_MS),),
            )
            for key in keys:
                lock_connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (key,),
                )
            yield

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
            clauses.append("email_match.match_digest = %s")
            parameters.append(md5(email_key.encode(), usedforsecurity=False).hexdigest())
        if phone_key is not None:
            clauses.append("regexp_replace(phone_number, '[^0-9]', '', 'g') = %s")
            parameters.append(phone_key)
        with psycopg.connect(
            self.database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
        ) as connection:
            self._bound_work(connection)
            rows = connection.execute(
                "SELECT customer.id, left(customer.legal_name, 255), "
                "NULL::text, NULL::text, NULL::text, NULL::text, customer.version "
                "FROM app.customers AS customer "
                "LEFT JOIN app.customer_email_match_keys AS email_match "
                "ON email_match.customer_id = customer.id "
                f"WHERE {' OR '.join(clauses)} "
                "ORDER BY customer.legal_name, customer.id LIMIT 20",
                tuple(parameters),
            ).fetchall()
        return tuple(_customer_from_row(row) for row in rows)

    def find_by_id_document_number(self, id_document_number: str) -> Customer | None:
        """Return the minimized Customer (id and name only) that holds this ID number."""
        key = id_document_match_key(id_document_number)
        if key is None:
            return None
        with psycopg.connect(
            self.database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
        ) as connection:
            self._bound_work(connection)
            row = connection.execute(
                "SELECT customer.id, left(customer.legal_name, 255), "
                "NULL::text, NULL::text, NULL::text, NULL::text, customer.version "
                "FROM app.customers AS customer "
                "WHERE customer.id_document_number IS NOT NULL "
                "AND app.customer_id_document_match_key(customer.id_document_number) = %s",
                (key,),
            ).fetchone()
        return None if row is None else _customer_from_row(row)

    def _id_number_in_use(self, error: psycopg.Error, customer: Customer) -> bool:
        return (
            error.diag.constraint_name == ID_DOCUMENT_NUMBER_INDEX
            and customer.id_document_number is not None
        )

    def add(self, customer: Customer) -> None:
        try:
            with psycopg.connect(
                self.database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_work(connection)
                if self.command is None:
                    row = connection.execute(
                        """
                        SELECT * FROM app.create_customer(
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
                            self.actor_id,
                            uuid4(),
                            customer.id_document_number,
                        ),
                    ).fetchone()
                else:
                    row = connection.execute(
                        """
                        SELECT * FROM app.execute_customer_create(
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            self.command.property_id,
                            self.command.idempotency_key,
                            self.command.request_digest,
                            customer.customer_id,
                            customer.legal_name,
                            customer.phone_number,
                            customer.email_address,
                            customer.contact_address,
                            customer.memo,
                            self.actor_id,
                            customer.id_document_number,
                        ),
                    ).fetchone()
        except psycopg.errors.UniqueViolation as error:
            if self._id_number_in_use(error, customer):
                raise CustomerIdNumberInUse(
                    self.find_by_id_document_number(cast(str, customer.id_document_number))
                ) from error
            raise CustomerIdentityAlreadyExistsError(
                f"Customer identity {customer.customer_id} already exists"
            ) from error
        if row is None or _customer_from_row(row) != customer:
            raise RuntimeError("Customer creation returned an invalid result")

    def update(self, customer: Customer, *, expected_version: int) -> Customer:
        try:
            return self._update(customer, expected_version=expected_version)
        except psycopg.errors.UniqueViolation as error:
            if self._id_number_in_use(error, customer):
                raise CustomerIdNumberInUse(
                    self.find_by_id_document_number(cast(str, customer.id_document_number))
                ) from error
            raise

    def _update(self, customer: Customer, *, expected_version: int) -> Customer:
        with psycopg.connect(
            self.database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
        ) as connection:
            self._bound_work(connection)
            if self.command is None:
                row = connection.execute(
                    """
                    SELECT * FROM app.update_customer(
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
                        customer.id_document_number,
                    ),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT * FROM app.execute_customer_update(
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        self.command.property_id,
                        self.command.idempotency_key,
                        self.command.request_digest,
                        customer.customer_id,
                        customer.legal_name,
                        customer.phone_number,
                        customer.email_address,
                        customer.contact_address,
                        customer.memo,
                        expected_version,
                        self.actor_id,
                        customer.id_document_number,
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

    def assert_version(self, customer_id: UUID, expected_version: int) -> None:
        """Linearize a no-op decision against the currently committed version."""
        with psycopg.connect(
            self.database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
        ) as connection:
            self._bound_work(connection)
            row = connection.execute(
                "SELECT version FROM app.customers WHERE id = %s",
                (customer_id,),
            ).fetchone()
        if row is None:
            raise LookupError("Customer was not found")
        current_version = int(str(row[0]))
        if current_version != expected_version:
            raise CustomerVersionConflict(current_version)


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
        id_document_number: str | None = None,
    ) -> Customer:
        """Create a Customer; the ID number is required (DL-071 answer 11)."""
        normalized_id_number = normalize_optional(id_document_number)
        if normalized_id_number is None:
            raise ValueError("id_document_number is required")
        customer = Customer(
            customer_id=customer_id,
            legal_name=legal_name.strip(),
            phone_number=normalize_optional(phone_number),
            email_address=canonical_email(email_address),
            contact_address=normalize_optional(contact_address),
            memo=normalize_optional(memo),
            id_document_number=normalized_id_number,
        )
        with self._reuse_guard(customer):
            self._refuse_used_id_number(customer)
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
        id_document_number: str | None = None,
    ) -> Customer:
        """Update current values; a recorded ID number may be corrected, never removed.

        `id_document_number=None` keeps the current number.
        """
        normalized_id_number = (
            current.id_document_number
            if id_document_number is None
            else normalize_optional(id_document_number)
        )
        if current.id_document_number is not None and normalized_id_number is None:
            raise ValueError("id_document_number cannot be removed")
        normalized_legal_name = legal_name.strip()
        normalized_phone_number = normalize_optional(phone_number)
        normalized_email_address = normalize_optional(email_address)
        normalized_contact_address = normalize_optional(contact_address)
        normalized_memo = normalize_optional(memo)
        candidate_values = {
            "legal_name": (
                current.legal_name if legal_name == current.legal_name else normalized_legal_name
            ),
            "phone_number": (
                current.phone_number
                if phone_number == current.phone_number
                else normalized_phone_number
            ),
            "email_address": (
                current.email_address
                if email_address == current.email_address
                else canonical_email(normalized_email_address)
            ),
            "contact_address": (
                current.contact_address
                if contact_address == current.contact_address
                else normalized_contact_address
            ),
            "memo": current.memo if memo == current.memo else normalized_memo,
            "id_document_number": normalized_id_number,
        }
        preserved_legacy_fields = frozenset(
            field_name
            for field_name, candidate_value in candidate_values.items()
            if candidate_value == getattr(current, field_name)
        )
        candidate = Customer(
            customer_id=current.customer_id,
            legal_name=cast(str, candidate_values["legal_name"]),
            phone_number=candidate_values["phone_number"],
            email_address=candidate_values["email_address"],
            contact_address=candidate_values["contact_address"],
            memo=candidate_values["memo"],
            id_document_number=candidate_values["id_document_number"],
            version=current.version + 1,
            _allow_legacy_phone=normalized_phone_number == current.phone_number,
            _allow_legacy_fields=preserved_legacy_fields,
        )
        if (
            candidate.legal_name,
            candidate.phone_number,
            candidate.email_address,
            candidate.contact_address,
            candidate.memo,
            candidate.id_document_number,
        ) == (
            current.legal_name,
            current.phone_number,
            current.email_address,
            current.contact_address,
            current.memo,
            current.id_document_number,
        ):
            if isinstance(self.repository, VersionedCustomerRepository):
                repository = cast(VersionedCustomerRepository, self.repository)
                repository.assert_version(current.customer_id, current.version)
            raise ValueError("Customer update must change source data")
        with self._reuse_guard(candidate):
            self._refuse_used_id_number(candidate)
            matches = self._other_candidates(candidate)
            if matches and not confirmed_distinct:
                raise CustomerReuseRequired(matches)
            return self.repository.update(candidate, expected_version=current.version)

    def _reuse_guard(self, customer: Customer) -> AbstractContextManager[None]:
        if not isinstance(self.repository, SerializedCustomerRepository):
            return nullcontext()
        repository = cast(SerializedCustomerRepository, self.repository)
        return repository.serialize_reuse_keys(
            email_key=normalized_email(customer.email_address),
            phone_key=normalized_phone(customer.phone_number),
        )

    def _refuse_used_id_number(self, customer: Customer) -> None:
        """Refuse early, whatever `confirmed_distinct` says; the unique index decides races."""
        if customer.id_document_number is None or not isinstance(
            self.repository, IdNumberCustomerRepository
        ):
            return
        repository = cast(IdNumberCustomerRepository, self.repository)
        holder = repository.find_by_id_document_number(customer.id_document_number)
        if holder is not None and holder.customer_id != customer.customer_id:
            raise CustomerIdNumberInUse(holder)

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
        id_document_number=None if len(row) < 8 or row[7] is None else str(row[7]),
        _allow_legacy_phone=True,
        _allow_legacy_fields=frozenset(
            {
                "legal_name",
                "phone_number",
                "email_address",
                "contact_address",
                "memo",
                "id_document_number",
            }
        ),
    )
