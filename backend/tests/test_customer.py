"""Domain tests for canonical Customer identity and reuse decisions."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from property_rental.customer import (
    Customer,
    CustomerIdentityAlreadyExistsError,
    CustomerReuseRequired,
    CustomerService,
    CustomerVersionConflict,
    normalized_email,
    normalized_phone,
)


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


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("customer_id", UUID(int=0), "customer_id"),
        ("legal_name", "  ", "legal_name must not be blank"),
        ("legal_name", " Dara ", "legal_name must not have surrounding"),
        ("phone_number", " ", "phone_number must be null or normalized"),
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

    customer = service.create(
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
    existing = service.create(uuid4(), legal_name="Dara Sok", email_address="Dara@Example.com")

    with pytest.raises(CustomerReuseRequired) as raised:
        service.create(uuid4(), legal_name="Dara S.", email_address="dara@example.com")

    assert raised.value.candidates == (existing,)
    distinct = service.create(
        uuid4(),
        legal_name="Dara S.",
        email_address="dara@example.com",
        confirmed_distinct=True,
    )
    assert distinct.customer_id != existing.customer_id
    assert len(repository.customers) == 2


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
    current = service.create(uuid4(), legal_name="Dara Sok", phone_number="012 345 678")

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


def test_phone_matching_is_conservative_and_never_merges_automatically() -> None:
    repository = InMemoryCustomerRepository()
    service = CustomerService(repository)
    existing = service.create(uuid4(), legal_name="Srey Mom", phone_number="+855 12-345-678")

    with pytest.raises(CustomerReuseRequired) as raised:
        service.create(uuid4(), legal_name="S. Mom", phone_number="85512345678")

    assert raised.value.candidates == (existing,)
    assert repository.customers == {existing.customer_id: existing}
