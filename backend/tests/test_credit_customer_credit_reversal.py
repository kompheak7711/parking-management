"""The Credit reversal refusal of V1-056 sub-slice 8g reaches the user as a conflict."""

from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.credit import CreditConflictError, CustomerCreditService, ReverseCreditCommand
from property_rental.identity import AuthenticatedActor, CapabilityGrant


def test_a_refused_credit_reversal_is_a_conflict_with_a_safe_message() -> None:
    # Q-2026-10-06-35: a Credit released to a Customer other than the payer (P4904, as the
    # slice 7 refusal) stays with that Customer; the message names both ways out.
    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic private diagnostic")
    failure.sqlstate = "P4904"
    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant("credits.reverse", frozenset({str(prop)}))})
    )
    with patch("property_rental.credit.psycopg.connect", side_effect=failure):
        with pytest.raises(CreditConflictError) as caught:
            CustomerCreditService("read-only", "financial").reverse(
                prop, UUID(int=5), ReverseCreditCommand(UUID(int=6), "Return"), actor=actor
            )
    assert str(caught.value) == (
        "This Credit stays with its Customer; apply it to that Customer's obligations or "
        "refund it to that Customer"
    )
    assert "Synthetic private diagnostic" not in str(caught.value)
