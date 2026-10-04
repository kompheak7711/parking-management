"""Reach a Reservation Deposit outcome the V1-056 way: a draft confirmed under financial.approve.

Earlier tests cancelled a Reservation and recorded its Deposit outcome in one call
(``app.cancel_reservation_v2``) or corrected the outcome in one call
(``app.correct_reservation_deposit_outcome``). Since slice 3b the cancellation only releases the
Unit and the outcome is a draft that takes effect only when a financial.approve holder confirms
it (BR-AUTH-010). These helpers keep the earlier call shape and result row: the same person
prepares and confirms in the caller's transaction, the draft id is derived from the command key,
and the row has the fourteen columns the earlier functions returned. A repeated call replays
every step.
"""

from __future__ import annotations

import os
from datetime import date
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg import Connection

TEST_DRAFT_NAMESPACE = uuid5(NAMESPACE_URL, "property-rental/tests/reservation-deposit-draft")
CASH_REFERENCE_NOTE = "Cash handed over at the Property office"


def _runtime_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    assert value is not None
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def cash_method_id(property_id: UUID, actor_id: UUID) -> UUID:
    with psycopg.connect(_runtime_url()) as runtime:
        row = runtime.execute(
            "SELECT app.list_refund_methods(%s,%s)", (property_id, actor_id)
        ).fetchone()
    assert row is not None
    items = cast(dict[str, list[dict[str, str]]], row[0])["items"]
    return UUID(next(item["id"] for item in items if item["code"] == "CASH"))


def draft_id_for(idempotency_key: UUID) -> UUID:
    return uuid5(TEST_DRAFT_NAMESPACE, str(idempotency_key))


def lifecycle_row(snapshot: dict[str, object]) -> tuple[object, ...]:
    """The fourteen columns of the earlier cancel, expire and correct functions."""
    outcome = snapshot.get("outcome_id")
    return (
        UUID(str(snapshot["reservation_id"])),
        UUID(str(snapshot["unit_id"])),
        snapshot["status"],
        snapshot["cancellation_reason_code"],
        snapshot["cancellation_responsibility"],
        date.fromisoformat(str(snapshot["effective_expiration_date"])),
        int(str(snapshot["version"])),
        snapshot["unit_status"],
        int(str(snapshot["unit_version"])),
        UUID(str(snapshot["deposit_id"])),
        int(str(snapshot["deposit_received_usd_cents"])),
        snapshot["deposit_outcome_state"],
        None if outcome is None else UUID(str(outcome)),
        snapshot.get("refund_number"),
    )


def confirm_reservation_outcome(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    reservation_id: UUID,
    idempotency_key: UUID,
    outcome_id: UUID,
    responsibility: str,
    reason: str,
    refund_number: str | None = None,
) -> tuple[object, ...]:
    """Record and confirm the Deposit decision draft of a cancelled Reservation."""
    refund = responsibility == "PROPERTY"
    draft_id = draft_id_for(idempotency_key)
    connection.execute(
        "SELECT app.record_reservation_deposit_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            property_id,
            actor_id,
            draft_id,
            reservation_id,
            "REFUND" if refund else "DEPOSIT_FORFEITURE",
            outcome_id,
            reason,
            refund_number if refund else None,
            cash_method_id(property_id, actor_id) if refund else None,
            CASH_REFERENCE_NOTE if refund else None,
            "reservation_deposits.refund" if refund else "reservation_deposits.dispose",
        ),
    )
    row = connection.execute(
        "SELECT app.confirm_reservation_deposit_draft(%s,%s,%s,%s,%s)",
        (property_id, actor_id, reservation_id, draft_id, "financial.approve"),
    ).fetchone()
    assert row is not None
    return lifecycle_row(cast(dict[str, dict[str, object]], row[0])["reservation"])


def correct_reservation_outcome(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    reservation_id: UUID,
    idempotency_key: UUID,
    correction_id: UUID,
    expected_outcome_id: UUID,
    replacement_outcome_id: UUID,
    replacement_refund_number: str | None,
    reason: str,
    evidence_reference: str,
) -> tuple[object, ...]:
    """Record and confirm a draft that replaces the confirmed outcome."""
    refund = replacement_refund_number is not None
    draft_id = draft_id_for(idempotency_key)
    connection.execute(
        "SELECT app.record_reservation_deposit_correction_draft("
        "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            property_id,
            actor_id,
            draft_id,
            reservation_id,
            "REFUND" if refund else "DEPOSIT_FORFEITURE",
            expected_outcome_id,
            correction_id,
            replacement_outcome_id,
            reason,
            evidence_reference,
            replacement_refund_number,
            cash_method_id(property_id, actor_id) if refund else None,
            CASH_REFERENCE_NOTE if refund else None,
            "reservation_deposits.correct",
            "reservation_deposits.refund" if refund else "reservation_deposits.dispose",
        ),
    )
    row = connection.execute(
        "SELECT app.confirm_reservation_deposit_draft(%s,%s,%s,%s,%s)",
        (property_id, actor_id, reservation_id, draft_id, "financial.approve"),
    ).fetchone()
    assert row is not None
    return lifecycle_row(cast(dict[str, dict[str, object]], row[0])["reservation"])
