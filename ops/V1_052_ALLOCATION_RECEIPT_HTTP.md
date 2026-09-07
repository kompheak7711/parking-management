# V1-052 Allocation and Receipt HTTP slice

Base: accepted Payment HTTP `1e79851ec5e8530d35927fe93ed2346c407a5820`.
Authority: `ops/CODEX_TAKEOVER_V1_048_053.md` and `ops/V1_052_SCOPE.md`.
This records the API-059/060/092 adapter contract within the frozen V1-052 scope.
Whole-version UI, Credit/Refund HTTP and release gates remain separate required work.

## Operations

All paths below start with `/api/v1`. Each object is resolved within the actor's
exact capability grants, with a fresh persisted active HUMAN check before financial
lookup. The accepted service then rechecks the exact Property and command actor.

| Method and path | Capability | Success |
| --- | --- | --- |
| GET `/payments/{id}/allocation-proposal` | `payments.allocate` | 200 proposal resource |
| POST `/payments/{id}/allocations` | `payments.allocate` | 201 command result; Location is the Payment's allocation history |
| GET `/payments/{id}/allocations` | `payments.read` | 200 history page or selected evidence resource |
| POST `/payment-allocations/{id}/reverse` | `payments.allocations.reverse` | 200 original command result |
| POST `/payments/{id}/reverse` | `payments.reverse` | 200 original command result |
| GET `/payments/{id}/receipt` | `receipts.read` | 200 Receipt with reprint history |
| GET `/receipts/{id}` | `receipts.read` | 200 Receipt with reprint history |
| POST `/receipts/{id}/reprints` | `receipts.reprint` | 200 original reprint command result |

Allocation POST body is `{"intent": <accepted allocation intent>}`. The existing
PROPOSAL, DESIGNATED and DIRECT_CHARGE commands retain their exact validation.
An Allocation Reversal requires `reason`. Payment Reversal requires `reason` and
explicit `expected_status: "RECEIVED"`. Reprint requires `reason` and permits optional
`delivery_reference`. Unknown body fields are rejected. Reasons are normalized,
unchanged strings of 1–1000 characters; delivery references are 1–500 characters.

POST requires the original Idempotency-Key and existing browser Origin/CSRF checks.
A supplied X-Billing-Actor-ID must match the resolved actor. Duplicate command or
browser security headers are rejected. Replays delegate to the accepted transaction
and return its original data/status; reused keys return the API-016 conflict code.
Existing unresolved downstream Payment reversal guards retain the service's safe
unknown-outcome behavior. Staff must preserve the original command for exact replay.

UTF-8 JSON is required. A 262144-byte streaming ceiling runs before framework body
buffering/decoding and does not trust Content-Length. The existing 250000-byte
canonical allocation-intent limit still applies. Duplicate JSON members, non-JSON
numbers and invalid Unicode are rejected before financial dispatch. Money remains
exact integer cents; Receipt FX fields retain their authoritative decimal strings.

## Complete, bounded history

Allocation history accepts only `limit`, `cursor`, and optional `allocation_id`.
Default/max page size is 50/100. Summary pages sort by posted_at and id descending,
include original target, amount, attribution, actor, detail count and linked reversal,
and link the full original evidence through allocation_id. They return the standard
API-012 data array and page envelope. Summary pages omit the large proposal snapshot.

Selecting allocation_id returns API-011 data containing the original `allocation`
header, including its complete proposal snapshot, plus one `details` page. The page
envelope remains alongside data. Details sort by their immutable unique sequence and
id ascending. Opaque cursors bind the Payment, selected allocation and anchor identity;
anchors must exist inside that exact scope. All reads use one repeatable-read,
read-only snapshot with bounded timeouts. The response ceiling is 1 MiB; failure to
fit rejects the read rather than silently discarding evidence. The valid 500-detail
producer case is tested across five pages with full original-detail equality.

Both Receipt GET paths accept only `limit` and `cursor`. Their data contains the
accepted Receipt resource plus `reprints: {items, page: {limit, next_cursor}}`.
Reprints sort by reprinted_at and id ascending; default/max size is 50/100.
Cursors are opaque and bound to the immutable Receipt. The accepted Receipt reader
retains its Payment FOR SHARE lock and its existing transaction semantics.

The app applies safe errors, request correlation and private/no-store headers to
all three path families, including validation errors and idempotency conflicts.
Read-only Receipt access works with runtime credentials alone. Commands require the
separate financial connection; runtime credentials are never used for mutation.

## Verification and acceptance

Tests cover the full app's eight routes, permission separation, fresh disabled users,
cross-resource cursor denial, strict schemas, exact values, request byte limits,
explicit posting, original replay, competing Payments, linked reversals, stable
Receipt identity, original KHR/FX facts and complete reprint/detail paging.
Assertion mappings are in `ops/traceability.json`.

Preserve the initial history-fixture failures and HTTP reason-validator failure with
their correction evidence. Focused passes do not accept the slice. The complete
normal candidate requires fresh applicable exact-SHA checks and one independent
Astra max Standard read-only review of the entire base-to-candidate diff with zero
HIGH/MEDIUM/LOW findings. Full V1-052 publication/CI/ref/card closure precedes V1-053.
