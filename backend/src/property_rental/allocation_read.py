"""Fresh-authorized, coherent reads for the staff allocation HTTP boundary.

The accepted allocation command service remains authoritative for posting and
reversals. A proposal is only a read: it cannot grant authority or move value.
"""

import json
from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb, set_json_loads

from property_rental.due_preview import DesignationPreviewInput, PreviewInputError
from property_rental.identity import AuthenticatedActor
from property_rental.payment_allocation import (
    AllocationAuthorizationError,
    AllocationConflictError,
    AllocationInvalidError,
    AllocationNotFoundError,
    AllocationUnavailableError,
    PaymentAllocationService,
    _uuid,
)

_CONTEXT = """
    SELECT EXISTS(SELECT 1 FROM app.properties WHERE id=%s),
        EXISTS(SELECT 1 FROM app.user_accounts account
            JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
            WHERE account.actor_id=%s AND account.lifecycle_state='active'
                AND identity.identity_kind='HUMAN')
"""


@dataclass(frozen=True, slots=True)
class AllocationReadService:
    database_url: str

    def proposal(
        self, property_id: UUID, payment_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        actor_id = PaymentAllocationService._authorize(actor, property_id, "payments.allocate")
        _uuid(payment_id)
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                # Recheck the human and project all dependencies in the same
                # snapshot; never turn an old resolver grant into fresh authority.
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                set_json_loads(lambda value: json.loads(value, parse_float=str), connection)
                context = connection.execute(_CONTEXT, (property_id, actor_id)).fetchone()
                if context is None or context[1] is not True:
                    raise AllocationAuthorizationError("Payment actor is not active")
                if context[0] is not True:
                    raise AllocationNotFoundError("Payment Property was not found")
                # The accepted producer bounds its targets, details and UTF-8
                # snapshot, preserving exact confirmed-proposal replay semantics.
                row = connection.execute(
                    "SELECT app.payment_allocation_proposal(%s,%s,clock_timestamp(),%s)",
                    (property_id, payment_id, uuid4()),
                ).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate in {"P4901", "P0002"}:
                raise AllocationNotFoundError("Payment resource was not found") from exc
            if exc.sqlstate in {"P4506", "42501"}:
                raise AllocationAuthorizationError("Payment actor is not authorized") from exc
            if exc.sqlstate == "P4904":
                raise AllocationConflictError(
                    "Payment state changed; request a new proposal"
                ) from exc
            if exc.sqlstate == "P4902":
                raise AllocationInvalidError("Payment proposal is invalid") from exc
            raise AllocationUnavailableError("Payment proposal is temporarily unavailable") from exc
        if row is None or len(row) != 1 or not isinstance(row[0], dict):
            raise AllocationUnavailableError("Payment proposal is temporarily unavailable")
        return cast(dict[str, object], row[0])

    def designation_preview(
        self,
        property_id: UUID,
        payment_id: UUID,
        intent: dict[str, object],
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Prepare a Customer designation without a command key or financial write."""
        actor_id = PaymentAllocationService._authorize(actor, property_id, "payments.allocate")
        _uuid(payment_id)
        try:
            request = DesignationPreviewInput("PAYMENT", intent)
        except PreviewInputError as exc:
            raise AllocationInvalidError("Payment designation preview is invalid") from exc
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                set_json_loads(lambda value: json.loads(value, parse_float=str), connection)
                # The wrapper rechecks the active human and source/target context
                # inside this coherent read snapshot before returning any evidence.
                row = connection.execute(
                    "SELECT app.payment_allocation_designation_preview(%s,%s,%s,%s)",
                    (property_id, payment_id, actor_id, Jsonb(request.intent)),
                ).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate in {"P4901", "P0002"}:
                raise AllocationNotFoundError("Payment resource was not found") from exc
            if exc.sqlstate in {"P4506", "42501"}:
                raise AllocationAuthorizationError("Payment actor is not authorized") from exc
            if exc.sqlstate == "P4904":
                raise AllocationConflictError("Payment state changed; refresh the preview") from exc
            if exc.sqlstate == "P4902":
                raise AllocationInvalidError("Payment designation preview is invalid") from exc
            raise AllocationUnavailableError("Payment preview is temporarily unavailable") from exc
        if row is None or len(row) != 1 or not isinstance(row[0], dict):
            raise AllocationUnavailableError("Payment preview is temporarily unavailable")
        return cast(dict[str, object], row[0])

    def history(
        self,
        property_id: UUID,
        payment_id: UUID,
        page: "AllocationHistoryPage | None" = None,
        *,
        actor: AuthenticatedActor,
        allocation_id: UUID | None = None,
    ) -> dict[str, object]:
        """Read summaries, or one original header and a page of its detail evidence.

        The immutable proposal appears once only when an allocation is explicitly
        selected. Summary pages never multiply that potentially large snapshot.
        Cursor anchors are resolved inside the exact Payment/allocation scope.
        """
        actor_id = PaymentAllocationService._authorize(actor, property_id, "payments.read")
        _uuid(payment_id)
        if allocation_id is not None:
            _uuid(allocation_id)
        supplied = page or AllocationHistoryPage()
        checked = AllocationHistoryPage(supplied.limit, supplied.after_id)
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                set_json_loads(lambda value: json.loads(value, parse_float=str), connection)
                context = connection.execute(_CONTEXT, (property_id, actor_id)).fetchone()
                if context is None or context[1] is not True:
                    raise AllocationAuthorizationError("Payment actor is not active")
                if context[0] is not True:
                    raise AllocationNotFoundError("Payment Property was not found")
                payment = connection.execute(
                    "SELECT id FROM app.payments WHERE property_id=%s AND id=%s",
                    (property_id, payment_id),
                ).fetchone()
                if payment is None:
                    raise AllocationNotFoundError("Payment was not found")

                allocation: dict[str, object] | None = None
                if allocation_id is None:
                    anchor = None
                    if checked.after_id is not None:
                        anchor = connection.execute(
                            "SELECT posted_at,id FROM app.payment_allocations "
                            "WHERE payment_id=%s AND id=%s",
                            (payment_id, checked.after_id),
                        ).fetchone()
                        if anchor is None:
                            raise AllocationInvalidError("Allocation cursor is invalid")
                    rows = connection.execute(
                        _ALLOCATION_SUMMARIES,
                        (
                            payment_id,
                            anchor[0] if anchor else None,
                            anchor[0] if anchor else None,
                            anchor[1] if anchor else None,
                            checked.limit + 1,
                        ),
                    ).fetchall()
                else:
                    header = connection.execute(
                        _ALLOCATION_EVIDENCE, (payment_id, allocation_id)
                    ).fetchone()
                    if header is None:
                        raise AllocationNotFoundError("Allocation was not found")
                    allocation = _history_objects([header])[0]
                    sequence = 0
                    if checked.after_id is not None:
                        detail = connection.execute(
                            "SELECT detail_sequence FROM app.payment_allocation_details "
                            "WHERE payment_allocation_id=%s AND id=%s",
                            (allocation_id, checked.after_id),
                        ).fetchone()
                        if detail is None:
                            raise AllocationInvalidError("Allocation detail cursor is invalid")
                        sequence = cast(int, detail[0])
                    rows = connection.execute(
                        "SELECT to_jsonb(detail) FROM app.payment_allocation_details detail "
                        "WHERE payment_allocation_id=%s AND detail_sequence>%s "
                        "ORDER BY detail_sequence,id LIMIT %s",
                        (allocation_id, sequence, checked.limit + 1),
                    ).fetchall()
        except psycopg.Error as exc:
            if exc.sqlstate == "42501":
                raise AllocationAuthorizationError("Allocation read is not authorized") from exc
            raise AllocationUnavailableError("Allocation history is unavailable") from exc

        objects = _history_objects(rows)
        items = objects[: checked.limit]
        next_cursor = None
        if len(objects) > checked.limit:
            next_cursor = {
                "payment_id": str(payment_id),
                "allocation_id": str(allocation_id) if allocation_id is not None else None,
                "after_id": str(items[-1]["id"]),
            }
        result: dict[str, object] = {
            "property_id": str(property_id),
            "payment_id": str(payment_id),
            "allocation": allocation,
            "items": items,
            "next_cursor": next_cursor,
        }
        # Accepted commands bound all original intent to 250KB. A focused page
        # contains at most one proposal plus one page of its original details.
        # Keep a separate response ceiling as a fail-closed defense for bad data;
        # never silently omit financial evidence to fit a response.
        if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) > 1_048_576:
            raise AllocationUnavailableError("Allocation history is unavailable")
        return result


@dataclass(frozen=True, slots=True)
class AllocationHistoryPage:
    limit: int = 50
    after_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise AllocationInvalidError("Allocation history page size is invalid")
        if self.after_id is not None:
            _uuid(self.after_id)


def _history_objects(rows: list[tuple[object, ...]]) -> list[dict[str, object]]:
    if any(len(row) != 1 or not isinstance(row[0], dict) for row in rows):
        raise AllocationUnavailableError("Allocation history is unavailable")
    return [cast(dict[str, object], row[0]) for row in rows]


_ALLOCATION_SUMMARIES = """
    WITH selected AS MATERIALIZED (
        SELECT * FROM app.payment_allocations
        WHERE payment_id=%s
            AND (%s::timestamptz IS NULL OR (posted_at,id)<(%s::timestamptz,%s::uuid))
        ORDER BY posted_at DESC,id DESC LIMIT %s
    )
    SELECT jsonb_build_object(
        'id',allocation.id,'payment_id',allocation.payment_id,
        'target_customer_id',allocation.target_customer_id,
        'target_kind',allocation.target_kind,'invoice_id',allocation.invoice_id,
        'late_payment_charge_id',allocation.late_payment_charge_id,
        'amount_usd_cents',allocation.amount_usd_cents,
        'between_invoice_basis',allocation.between_invoice_basis,
        'within_invoice_basis',allocation.within_invoice_basis,
        'customer_designation_reference',allocation.customer_designation_reference,
        'proposal_batch_id',allocation.proposal_batch_id,
        'between_invoice_sequence',allocation.between_invoice_sequence,
        'posted_at',allocation.posted_at,'posted_by',allocation.posted_by,
        'reversal',to_jsonb(reversal),
        'detail_count',(SELECT count(*) FROM app.payment_allocation_details
            WHERE payment_allocation_id=allocation.id))
    FROM selected allocation LEFT JOIN app.payment_allocation_reversals reversal
        ON reversal.payment_allocation_id=allocation.id
    ORDER BY allocation.posted_at DESC,allocation.id DESC
"""

_ALLOCATION_EVIDENCE = """
    SELECT to_jsonb(allocation)||jsonb_build_object('reversal',to_jsonb(reversal),
        'detail_count',(SELECT count(*) FROM app.payment_allocation_details
            WHERE payment_allocation_id=allocation.id))
    FROM app.payment_allocations allocation
    LEFT JOIN app.payment_allocation_reversals reversal
        ON reversal.payment_allocation_id=allocation.id
    WHERE allocation.payment_id=%s AND allocation.id=%s
"""
