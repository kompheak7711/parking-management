"""V1-056 sub-slice 8e-2: the refusal of a one-call reversal of a Final Settlement Credit
application reaches the Credit service as a conflict."""

from uuid import uuid4

import psycopg
import pytest

from property_rental.credit import (
    CreditConflictError,
    CustomerCreditService,
    ReverseCreditApplicationCommand,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant

MESSAGE = "A Final Settlement Credit application changes only through a post-settlement correction"


def test_a_settlement_credit_application_reversal_is_reported_as_a_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Business state reaches the user as a conflict (owner answer, plan slice 11c), not as an
    unresolved outcome to replay (owner answer 3 to Q-2026-10-06-32)."""

    class Failure(psycopg.Error):
        pass

    failure = Failure(MESSAGE)
    failure.sqlstate = "P5S01"

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    property_id, actor_id = uuid4(), uuid4()
    actor = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant("credits.applications.reverse", frozenset({str(property_id)}))}
        ),
    )
    with pytest.raises(CreditConflictError, match="post-settlement correction") as refused:
        CustomerCreditService("postgresql://unused", "postgresql://unused").reverse_application(
            property_id,
            uuid4(),
            ReverseCreditApplicationCommand(uuid4(), "Customer changed the instruction"),
            actor=actor,
        )
    assert refused.value.__cause__ is failure
