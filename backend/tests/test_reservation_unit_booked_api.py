"""Reserve Unit on a Unit a short-stay guest has booked (DL-225): the API names the reason.

Both Make Reservation requests answer 409 with the code RESERVATION_UNIT_BOOKED and the fixed
words of the refusal, so the screen can say why and what to do (another Unit, or Change Unit).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from property_rental.identity import AuthenticatedActor
from property_rental.reservation import (
    UNIT_BOOKED_BY_SHORT_STAY_GUEST,
    ReservationCreateCommand,
    ReservationUnitBookedError,
)
from property_rental.reservation_api import ReservationResource
from test_reservation_api import InMemoryReservationFlow, actor, client, headers


@dataclass
class BookedUnitFlow(InMemoryReservationFlow):
    """The database refused: a booked guest has the Unit."""

    def create(
        self,
        property_id: UUID,
        command: ReservationCreateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        del property_id, command, actor
        raise ReservationUnitBookedError(UNIT_BOOKED_BY_SHORT_STAY_GUEST)


def body() -> dict[str, object]:
    return {
        "reservation_id": str(uuid4()),
        "unit_id": str(uuid4()),
        "customer_id": str(uuid4()),
        "reservation_date": "2026-11-12",
        "agreed_monthly_rent_usd_cents": 50_000,
        "expiration_date": "2026-11-22",
        "acceptance_id": str(uuid4()),
        "accepted_initial_deposit_usd_cents": 10_000,
        "required_security_deposit_usd_cents": 50_000,
        "acceptance_reason": "Suggested 20% of the agreed Rent",
        "deposit_id": str(uuid4()),
        "receipt_id": str(uuid4()),
    }


def test_make_reservation_on_a_booked_unit_answers_the_reason_with_a_code() -> None:
    property_id = uuid4()
    cashier = client(BookedUnitFlow(), actor(property_id, "reservations.create", "payments.record"))
    payment = {
        "payment_method_id": str(uuid4()),
        "received_at": "2026-11-12T03:00:00Z",
        "evidence_reference": "Cash received, Cash",
        "payer_intent_memo": "Reservation deposit, Unit 301",
        "amount": {"currency": "USD", "minor_units": 10_000},
    }
    for url, sent in (
        (f"/properties/{property_id}/reservations", {**body(), "payment_id": str(uuid4())}),
        (f"/properties/{property_id}/reservations/with-payment", {**body(), "payment": payment}),
    ):
        answer = cashier.post(url, json=sent, headers=headers())
        assert answer.status_code == 409, answer.text
        error = answer.json()["error"]
        assert error["code"] == "RESERVATION_UNIT_BOOKED"
        assert "A short-stay guest has booked this Unit" in error["message"]
        assert "Change Unit" in error["message"]
        assert "DL-225" in error["rule_ids"]
