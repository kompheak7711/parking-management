"""Hand-built waiting drafts in tests after V1-056 sub-slice 10h-3 (BR-SETTLE-002).

Since migration 20270111_168 the Final Settlement preview lists a waiting Payment return draft or
Adjustment reversal draft on the Lease's sources (owner answer (a) to Q-2026-10-17-120 point 3),
so a Settlement does not close while such a draft waits. Committed tests that need a draft
recorded before the closure and still waiting after it keep their scenario with a hand-built
set-up (standing rule of 2026-10-19 with Q-2026-10-19-144):

- ``recorded_then_rolled_back`` runs the real recorder as the database owner in a transaction that
  is rolled back, asserts there that the preview lists that draft (``PENDING_DRAFT``) and that the
  Settlement draft recorder refuses (55000, nothing written), and keeps the kind, payload, source
  revision and reason it stored. No draft is left behind, so every draft count stays as it was.
- ``written_after_closure`` writes the same draft as the owner through
  app.insert_financial_draft, under a new id, after the closure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

BLOCKED = "The Final Settlement has blocking issues"
SETTLEMENT_DRAFTS = "SELECT count(*) FROM app.financial_drafts WHERE kind='FINAL_SETTLEMENT'"


@dataclass(frozen=True)
class HeldDraft:
    """What the recorder stored, kept from the rolled-back transaction."""

    kind: str
    prepare_capability: str
    payload: dict[str, Any]
    source_revision: str
    reason: str
    actor: UUID


def recorded_then_rolled_back(
    url: str,
    statement: str,
    parameters: tuple[object, ...],
    *,
    draft: UUID,
    prop: UUID,
    actor: UUID,
    settlement: UUID,
) -> HeldDraft:
    """Run the recorder (which writes draft ``draft``) and the preview in one owner transaction,
    then roll it back."""
    with psycopg.connect(url) as connection:
        connection.execute(statement, parameters)
        row = connection.execute(
            "SELECT kind,prepare_capability,payload,source_revision,reason "
            "FROM app.financial_drafts WHERE id=%s",
            (draft,),
        ).fetchone()
        preview = connection.execute(
            "SELECT app.final_settlement_preview(%s,%s,%s,ARRAY['financial.approve'])",
            (prop, actor, settlement),
        ).fetchone()
        # The refusal: the Settlement draft is not recorded while the draft waits.
        settlement_drafts = connection.execute(SETTLEMENT_DRAFTS).fetchone()
        refused: tuple[str | None, str | None]
        try:
            with connection.transaction():
                connection.execute(
                    "SELECT app.record_final_settlement_draft(%s,%s,%s,%s,"
                    "'{\"steps\":[]}'::jsonb,'Recorded while a draft waits',"
                    "'final_settlements.prepare')",
                    (prop, actor, uuid4(), settlement),
                )
        except psycopg.Error as error:
            refused = (error.sqlstate, error.diag.message_primary)
        else:
            refused = (None, None)
        assert refused == ("55000", BLOCKED)
        assert connection.execute(SETTLEMENT_DRAFTS).fetchone() == settlement_drafts
        connection.rollback()
        left = connection.execute(
            "SELECT count(*) FROM app.financial_drafts WHERE id=%s", (draft,)
        ).fetchone()
    assert row is not None and preview is not None and left == (0,)
    kind, prepare_capability, payload, source_revision, reason = row
    view = cast(dict[str, Any], preview[0])
    # The draft is the only blocking issue (review round 2), so the refusal comes from it.
    assert view["ready"] is False
    assert view["blocking_issues"] == [
        {
            "code": "PENDING_DRAFT",
            "draft_id": str(draft),
            "kind": kind,
            "variant": cast(dict[str, Any], payload).get("variant"),
        }
    ]
    return HeldDraft(
        str(kind),
        str(prepare_capability),
        cast(dict[str, Any], payload),
        str(source_revision),
        str(reason),
        actor,
    )


def written_after_closure(url: str, prop: UUID, held: HeldDraft) -> UUID:
    """The same draft, written as the owner under a new id."""
    draft = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                prop,
                held.actor,
                draft,
                held.kind,
                held.prepare_capability,
                Jsonb(held.payload),
                held.source_revision,
                held.reason,
            ),
        )
    return draft
