"""Domain tests for canonical Customer identity and reuse decisions."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from property_rental.customer import (
    Customer,
    CustomerIdentityAlreadyExistsError,
    CustomerIdNumberInUse,
    CustomerReuseRequired,
    CustomerService,
    CustomerVersionConflict,
    _customer_from_row,
    id_document_match_key,
    normalized_email,
    normalized_phone,
)


def create_customer(service: CustomerService, customer_id: UUID, **values: object) -> Customer:
    """Create with a fresh ID number unless the test gives one (DL-071 answer 11)."""
    values.setdefault("id_document_number", f"ID {customer_id.hex[:10]}")
    return service.create(customer_id, **values)  # type: ignore[arg-type]


@dataclass
class InMemoryCustomerRepository:
    customers: dict[UUID, Customer] = field(default_factory=dict)

    def find_reuse_candidates(
        self,
        *,
        email_key: str | None,
        phone_key: str | None,
    ) -> tuple[Customer, ...]:
        return tuple(
            customer
            for customer in self.customers.values()
            if (email_key is not None and normalized_email(customer.email_address) == email_key)
            or (phone_key is not None and normalized_phone(customer.phone_number) == phone_key)
        )

    def find_by_id_document_number(self, id_document_number: str) -> Customer | None:
        key = id_document_match_key(id_document_number)
        return next(
            (
                customer
                for customer in self.customers.values()
                if id_document_match_key(customer.id_document_number) == key
            ),
            None,
        )

    def add(self, customer: Customer) -> None:
        if customer.customer_id in self.customers:
            raise CustomerIdentityAlreadyExistsError
        self.customers[customer.customer_id] = customer

    def update(self, customer: Customer, *, expected_version: int) -> Customer:
        current = self.customers.get(customer.customer_id)
        if current is None:
            raise LookupError
        if current.version != expected_version:
            raise CustomerVersionConflict(current.version)
        self.customers[customer.customer_id] = customer
        return customer

    def assert_version(self, customer_id: UUID, expected_version: int) -> None:
        current = self.customers.get(customer_id)
        if current is None:
            raise LookupError
        if current.version != expected_version:
            raise CustomerVersionConflict(current.version)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("customer_id", UUID(int=0), "customer_id"),
        ("legal_name", "  ", "legal_name must not be blank"),
        ("legal_name", " Dara ", "legal_name must not have surrounding"),
        ("phone_number", " ", "phone_number must be null or normalized"),
        ("phone_number", "١٢٣", "supported ASCII phone characters"),
        ("phone_number", "012/345", "supported ASCII phone characters"),
        ("email_address", " dara@example.com ", "email_address must be null or"),
        ("contact_address", " ", "contact_address must be null or"),
        ("memo", " note ", "memo must be null or"),
        ("version", 0, "version must be positive"),
    ],
)
def test_customer_rejects_invalid_identity_or_source_values(
    field_name: str, value: object, message: str
) -> None:
    values: dict[str, object] = {
        "customer_id": uuid4(),
        "legal_name": "Dara Sok",
        "phone_number": None,
        "email_address": None,
        "contact_address": None,
        "memo": None,
        "version": 1,
    }
    values[field_name] = value

    with pytest.raises(ValueError, match=message):
        Customer(**values)  # type: ignore[arg-type]


def test_service_normalizes_optional_contact_without_requiring_a_channel() -> None:
    service = CustomerService(InMemoryCustomerRepository())

    customer = create_customer(
        service,
        uuid4(),
        legal_name="  Dara Sok  ",
        phone_number="  ",
        email_address=None,
        contact_address=" Phnom Penh ",
        memo=" New inquiry ",
    )

    assert customer.legal_name == "Dara Sok"
    assert customer.phone_number is None
    assert customer.email_address is None
    assert customer.contact_address == "Phnom Penh"
    assert customer.memo == "New inquiry"


def test_service_requires_explicit_reuse_or_distinct_decision() -> None:
    repository = InMemoryCustomerRepository()
    service = CustomerService(repository)
    existing = create_customer(
        service, uuid4(), legal_name="Dara Sok", email_address="Dara@Example.com"
    )

    with pytest.raises(CustomerReuseRequired) as raised:
        create_customer(service, uuid4(), legal_name="Dara S.", email_address="dara@example.com")

    assert raised.value.candidates == (existing,)
    distinct = create_customer(
        service,
        uuid4(),
        legal_name="Dara S.",
        email_address="dara@example.com",
        confirmed_distinct=True,
    )
    assert distinct.customer_id != existing.customer_id
    assert len(repository.customers) == 2


def test_service_canonicalizes_idn_domains_before_reuse_matching() -> None:
    repository = InMemoryCustomerRepository()
    service = CustomerService(repository)

    existing = create_customer(
        service,
        uuid4(),
        legal_name="IDN Customer",
        email_address="user@straße.de",
    )

    assert existing.email_address == "user@strasse.de"
    with pytest.raises(CustomerReuseRequired) as raised:
        create_customer(
            service,
            uuid4(),
            legal_name="Duplicate IDN Customer",
            email_address="USER@STRASSE.DE",
        )
    assert raised.value.candidates == (existing,)


def test_one_customer_identity_can_be_reused_across_domain_relationships() -> None:
    customer = Customer(uuid4(), "Dara Sok")
    relationship_customer_ids = {
        "reservation": customer.customer_id,
        "lease_signer": customer.customer_id,
        "occupancy": customer.customer_id,
        "payment": customer.customer_id,
    }

    assert set(relationship_customer_ids.values()) == {customer.customer_id}
    assert not hasattr(customer, "customer_type")
    assert not hasattr(customer, "category")


def test_contact_update_preserves_identity_and_advances_version() -> None:
    repository = InMemoryCustomerRepository()
    service = CustomerService(repository)
    current = create_customer(service, uuid4(), legal_name="Dara Sok", phone_number="012 345 678")

    updated = service.update(
        current,
        legal_name="Dara Sok",
        phone_number="098 765 432",
        email_address="dara@example.com",
        contact_address=None,
        memo=None,
    )

    assert updated.customer_id == current.customer_id
    assert updated.version == 2
    assert updated.phone_number == "098 765 432"

    with pytest.raises(ValueError, match="must change source data"):
        service.update(
            updated,
            legal_name="  Dara Sok  ",
            phone_number=" 098 765 432 ",
            email_address=" dara@example.com ",
            contact_address=None,
            memo=None,
        )
    assert repository.customers[current.customer_id] == updated


def test_update_preserves_an_omitted_legacy_email_verbatim() -> None:
    customer_id = uuid4()
    legacy = Customer(customer_id, "Legacy Email", email_address="user@BÜCHER.de")
    repository = InMemoryCustomerRepository({customer_id: legacy})

    updated = CustomerService(repository).update(
        legacy,
        legal_name=legacy.legal_name,
        phone_number=None,
        email_address=legacy.email_address,
        contact_address=None,
        memo="Audited memo only",
    )

    assert updated.email_address == "user@BÜCHER.de"
    assert updated.memo == "Audited memo only"


def test_update_preserves_a_malformed_legacy_email_during_unrelated_work() -> None:
    customer_id = uuid4()
    legacy = _customer_from_row((customer_id, "Legacy Email", None, "user@a..com", None, None, 1))
    repository = InMemoryCustomerRepository({customer_id: legacy})

    updated = CustomerService(repository).update(
        legacy,
        legal_name=legacy.legal_name,
        phone_number=None,
        email_address=legacy.email_address,
        contact_address=None,
        memo="Audited memo only",
    )

    assert updated.email_address == "user@a..com"
    assert updated.memo == "Audited memo only"


def test_update_preserves_unmodified_revision_15_whitespace_fields() -> None:
    customer_id = uuid4()
    legacy = _customer_from_row(
        (
            customer_id,
            "\tLegacy Customer\u00a0",
            None,
            None,
            "\u00a0Historic address\t",
            None,
            1,
        )
    )
    repository = InMemoryCustomerRepository({customer_id: legacy})

    updated = CustomerService(repository).update(
        legacy,
        legal_name=legacy.legal_name,
        phone_number=None,
        email_address=None,
        contact_address=legacy.contact_address,
        memo="Audited memo only",
    )

    assert updated.legal_name == "\tLegacy Customer\u00a0"
    assert updated.contact_address == "\u00a0Historic address\t"
    assert updated.memo == "Audited memo only"


def test_normalized_noop_rechecks_the_persisted_version() -> None:
    customer_id = uuid4()
    stale = Customer(customer_id, "Dara Sok")
    repository = InMemoryCustomerRepository(
        {customer_id: Customer(customer_id, "Dara Sok", version=2)}
    )

    with pytest.raises(CustomerVersionConflict) as raised:
        CustomerService(repository).update(
            stale,
            legal_name="  Dara Sok  ",
            phone_number=None,
            email_address=None,
            contact_address=None,
            memo=None,
        )

    assert raised.value.current_version == 2


def test_persisted_legacy_phone_remains_readable_but_new_input_is_strict() -> None:
    customer_id = uuid4()

    hydrated = _customer_from_row((customer_id, "Legacy Customer", "012/345", None, None, None, 1))
    repository = InMemoryCustomerRepository({customer_id: hydrated})
    updated = CustomerService(repository).update(
        hydrated,
        legal_name=hydrated.legal_name,
        phone_number=hydrated.phone_number,
        email_address="legacy@example.com",
        contact_address=None,
        memo=None,
    )

    assert hydrated.phone_number == "012/345"
    assert updated.phone_number == "012/345"
    assert updated.email_address == "legacy@example.com"
    with pytest.raises(ValueError, match="supported ASCII phone characters"):
        Customer(customer_id, "New Customer", phone_number="012/345")
    with pytest.raises(ValueError, match="supported ASCII phone characters"):
        CustomerService(repository).update(
            updated,
            legal_name=updated.legal_name,
            phone_number="012/999",
            email_address=updated.email_address,
            contact_address=None,
            memo=None,
        )


def test_phone_matching_is_conservative_and_never_merges_automatically() -> None:
    repository = InMemoryCustomerRepository()
    service = CustomerService(repository)
    existing = create_customer(
        service, uuid4(), legal_name="Srey Mom", phone_number="+855 12-345-678"
    )

    with pytest.raises(CustomerReuseRequired) as raised:
        create_customer(service, uuid4(), legal_name="S. Mom", phone_number="85512345678")

    assert raised.value.candidates == (existing,)
    assert repository.customers == {existing.customer_id: existing}


def test_phone_matching_uses_only_supported_ascii_digits() -> None:
    assert normalized_phone("+855 (12) 345-678") == "85512345678"
    assert normalized_phone("١٢٣") is None


def test_create_needs_an_id_number_and_refuses_one_another_customer_has() -> None:
    """DL-071 answer 11 and the owner's 2026-10-21 answer (V1-059 part B)."""
    service = CustomerService(InMemoryCustomerRepository())
    with pytest.raises(ValueError, match="id_document_number is required"):
        service.create(uuid4(), legal_name="Dara Sok")
    existing = create_customer(
        service, uuid4(), legal_name="Dara Sok", id_document_number="N-0123 456"
    )
    for same in ("n0123456", "N 0123-456", "N0123456"):
        with pytest.raises(CustomerIdNumberInUse) as refused:
            create_customer(
                service,
                uuid4(),
                legal_name="Dara S.",
                id_document_number=same,
                confirmed_distinct=True,
            )
        assert refused.value.existing == existing


def test_update_corrects_but_never_removes_the_id_number_and_keeps_it_unique() -> None:
    repository = InMemoryCustomerRepository()
    service = CustomerService(repository)
    first = create_customer(service, uuid4(), legal_name="Dara Sok", id_document_number="A111")
    other = create_customer(service, uuid4(), legal_name="Srey Mom", id_document_number="B222")
    corrected = service.update(
        first,
        legal_name=first.legal_name,
        phone_number=None,
        email_address=None,
        contact_address=None,
        memo=None,
        id_document_number="A112",
    )
    assert corrected.id_document_number == "A112"
    with pytest.raises(ValueError, match="cannot be removed"):
        service.update(
            corrected,
            legal_name=corrected.legal_name,
            phone_number=None,
            email_address=None,
            contact_address=None,
            memo=None,
            id_document_number=" ",
        )
    with pytest.raises(CustomerIdNumberInUse):
        service.update(
            other,
            legal_name=other.legal_name,
            phone_number=None,
            email_address=None,
            contact_address=None,
            memo=None,
            id_document_number="a-112",
        )
    kept = service.update(
        other,
        legal_name="Srey Mom Sok",
        phone_number=None,
        email_address=None,
        contact_address=None,
        memo=None,
    )
    assert kept.id_document_number == "B222"
