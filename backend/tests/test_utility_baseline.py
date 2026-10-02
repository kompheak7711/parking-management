"""Utility baseline command validation without a database."""

from dataclasses import replace
from datetime import date
from uuid import UUID, uuid4

import pytest

from property_rental.utility_baseline import (
    BASELINE_READ,
    BASELINE_RECORD,
    BaselineItem,
    RecordUtilityBaseline,
    UtilityBaselineInvalidError,
    utility_baseline_digest,
)

NIL = UUID(int=0)


def command(**changes: object) -> RecordUtilityBaseline:
    values: dict[str, object] = {
        "idempotency_key": uuid4(),
        "event_id": uuid4(),
        "baseline_date": date(2024, 7, 2),
        "items": (BaselineItem(uuid4(), uuid4()),),
        "reason": "Baseline recorded after cleaning and repair",
        "evidence_reference": "Handover sheet 17",
    }
    values.update(changes)
    return RecordUtilityBaseline(**values)  # type: ignore[arg-type]


def test_baseline_uses_the_existing_utility_reading_capabilities() -> None:
    assert BASELINE_RECORD == "utility_readings.record"
    assert BASELINE_READ == "utility.read"


def test_baseline_command_requires_nonzero_identities_and_a_real_date() -> None:
    with pytest.raises(UtilityBaselineInvalidError):
        command(idempotency_key=NIL)
    with pytest.raises(UtilityBaselineInvalidError):
        command(event_id=NIL)
    with pytest.raises(UtilityBaselineInvalidError):
        command(baseline_date="2024-07-02")
    with pytest.raises(UtilityBaselineInvalidError):
        BaselineItem(NIL, uuid4())
    with pytest.raises(UtilityBaselineInvalidError):
        BaselineItem(uuid4(), NIL)


def test_baseline_command_requires_bounded_unique_items_and_normalized_text() -> None:
    meter = uuid4()
    with pytest.raises(UtilityBaselineInvalidError):
        command(items=())
    with pytest.raises(UtilityBaselineInvalidError):
        command(items=(BaselineItem(meter, uuid4()), BaselineItem(meter, uuid4())))
    with pytest.raises(UtilityBaselineInvalidError):
        command(items=tuple(BaselineItem(uuid4(), uuid4()) for _ in range(21)))
    for field in ("reason", "evidence_reference"):
        for value in ("", " padded", "padded ", "x" * 501, "bad\x00text"):
            with pytest.raises(UtilityBaselineInvalidError):
                command(**{field: value})


def test_successor_must_reference_a_different_event() -> None:
    event = uuid4()
    with pytest.raises(UtilityBaselineInvalidError):
        command(event_id=event, supersedes_event_id=event)
    assert command(supersedes_event_id=uuid4()).supersedes_event_id is not None


def test_intent_orders_items_and_digest_binds_the_scope() -> None:
    first, second = sorted((uuid4(), uuid4()))
    value = command(
        items=(BaselineItem(second, uuid4()), BaselineItem(first, uuid4())),
    )
    intent = value.intent()
    items = intent["items"]
    assert isinstance(items, list)
    assert [item["meter_id"] for item in items] == [str(first), str(second)]
    assert intent["baseline_date"] == "2024-07-02"
    prop, lease = uuid4(), uuid4()
    digest = utility_baseline_digest(prop, lease, intent)
    assert digest == utility_baseline_digest(prop, lease, dict(intent))
    assert digest != utility_baseline_digest(prop, uuid4(), intent)
    assert digest != utility_baseline_digest(uuid4(), lease, intent)
    other = replace(value, baseline_date=date(2024, 7, 1)).intent()
    assert digest != utility_baseline_digest(prop, lease, other)
