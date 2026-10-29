# 005 — API Specification

**Document Status:** Owner Review
**Authority:** Downstream of `001_DOMAIN_MODEL.md` through `004_DATABASE_MODEL.md`
**Style:** REST over HTTPS with JSON
**Requirement identifiers:** `API-*`

---

# 1. Purpose

This document defines the application API that exposes approved Property Rental
Management workflows. The API is an action-oriented REST interface around domain
resources; it is not a generic database editor.

Callers cannot set derived balances, calculated amounts, immutable history,
authorization outcomes, or lifecycle statuses directly. Significant transitions
use explicit command endpoints that invoke the authoritative business rules.

# 2. Conventions

## API-001 — Base Path and Version

All endpoints use `/api/v1`. Breaking contract changes require a new API version or
a compatible migration period.

## API-002 — Media Type

Requests and responses use `application/json` unless a separately specified export
uses a download media type. UTF-8 is required.

## API-003 — Identifiers

Resource identifiers are opaque strings in the API. Clients must not infer record
type, chronology, authorization, or Property scope from an identifier.

## API-004 — Dates and Times

- Calendar dates use `YYYY-MM-DD`.
- Timestamps use RFC 3339 with an explicit offset and are normalized to UTC in
  canonical responses where appropriate.
- Business-date responses include `property_timezone` when interpretation matters.
- Period schemas state start/end inclusivity explicitly.

## API-005 — Money

```json
{
  "currency": "USD",
  "minor_units": 12500
}
```

USD uses integer minor units. KHR uses exact integer whole-KHR units represented by
`minor_units` under the currency-specific scale defined by the data model. Binary
floating-point money values are prohibited.

## API-006 — Versions

Mutable source-data resources expose an integer `version`. Update commands require
`If-Match` or an equivalent expected version. Stale writes return `409 Conflict`.
Financial events are corrected by new commands rather than versioned overwrite.

## API-007 — Correlation

Every response includes a correlation identifier in `X-Request-ID`; callers may
send a valid identifier which the server sanitizes/normalizes.

# 3. Authentication and Authorization

## API-008 — Authentication

Protected human endpoints require a local username/password-authenticated browser
session and, where policy requires, completed MFA. Authentication failures return `401`
without revealing account or resource existence. The API boundary remains independent
of password-hashing and MFA library details, but production normal operation does not
depend on an external identity provider.

Amended by DL-081 (login sub-slice L5, owner answers (a) to Q-2026-10-21-151 and Q-2026-10-21-160; technical points Q-2026-10-24-186, decided by Claude under the owner's 2026-10-23 22:30 rule): every route except `GET /health/live`, `GET /health/ready`, `GET /api/v1/identity/me` and the sign-in routes of API-096 to API-098 (13 operations, kept in `backend/tests/test_route_authorization_inventory.py`) first needs a signed-in user, before the request body is validated: 401 without one, whatever JSON body it gets (a body that is not JSON answers 400, because the JSON is parsed first). A change (any method but GET, HEAD and OPTIONS) then needs the configured Origin and the CSRF pair (403) before its body is validated. The generated documentation pages (`/docs`, `/redoc`, `/openapi.json`) are turned off. The route's own capability checks run after it. The customer ledger reads still refuse any GET body first (400).

## API-009 — Capability Checks

Each endpoint declares a capability family. The server checks capability, Property
scope, exact object access, and action preconditions. `403` is returned for an
authenticated actor lacking permission.

## API-010 — Role Independence

The API authorizes capabilities, not hard-coded staff role names. Role-to-capability
mapping is configured according to `008_SECURITY_MODEL.md`.

# 4. Standard Response Shapes

## API-011 — Resource Envelope

Single-resource reads return:

```json
{
  "data": {},
  "meta": {
    "request_id": "opaque-id"
  }
}
```

Successful creation returns `201 Created` with `Location`. Successful commands that
return a resulting resource use `200`; commands accepted for a durable asynchronous
job use `202 Accepted` with a job resource.

## API-012 — List Envelope

```json
{
  "data": [],
  "page": {
    "next_cursor": null,
    "limit": 50
  },
  "meta": {
    "request_id": "opaque-id"
  }
}
```

Default and maximum limits are server configuration. Ordering is deterministic and
includes an identifier tie-breaker.

## API-013 — Error Envelope

```json
{
  "error": {
    "code": "BUSINESS_RULE_VIOLATION",
    "message": "Safe human-readable summary",
    "fields": [],
    "rule_ids": ["BR-..."],
    "current_version": null
  },
  "meta": {
    "request_id": "opaque-id"
  }
}
```

Error messages never expose secrets, SQL, stack traces, or unauthorized object
existence.

## API-014 — Error Statuses

| Status | Meaning |
|---|---|
| `400` | Malformed request or unsupported query |
| `401` | Authentication required/invalid |
| `403` | Authenticated but forbidden |
| `404` | Resource not found or not revealable |
| `409` | State, uniqueness, concurrency, or idempotency conflict |
| `412` | Required precondition/version absent or failed where used |
| `422` | Schema or business validation failure |
| `429` | Rate limit exceeded |
| `500` | Unexpected safe internal error |
| `503` | Required dependency temporarily unavailable |

# 5. Idempotency and Transactions

## API-015 — Idempotency Header

Creation and significant command endpoints marked idempotent require
`Idempotency-Key`. The key is scoped to actor/client, Property, endpoint/action,
and a retention window.

## API-016 — Replay

A replay with the same key and equivalent canonical request returns the original
status/body without duplicating effects. Reusing a key with different canonical
input returns `409 IDEMPOTENCY_KEY_REUSED`.

## API-017 — Transaction Boundary

A command and its required business events, derived-state update, and audit event
commit atomically. Partial success is prohibited.

## API-018 — Concurrency

The server locks or versions affected aggregates and revalidates limits inside the
transaction. Conflicts return current safe state/version; clients must not retry
with changed values automatically.

# 6. Common Query Behavior

## API-019 — Pagination

List endpoints accept `limit` and opaque `cursor`. Offset pagination may be used
only for bounded administrative lists where deterministic behavior is preserved.

## API-020 — Filters

Filters are allowlisted per endpoint. Unknown filters return `400`; they are not
silently ignored.

## API-021 — Sorting

`sort` accepts documented fields with `-` for descending. Default sort and stable
identifier tie-breaker are documented by resource.

## API-022 — Includes

Optional `include` values may embed documented related summaries. Undocumented
relationship expansion is rejected to prevent scope/data leakage.

# 7. Core Schemas

## API-023 — Audit Metadata

```json
{
  "created_at": "2026-08-09T00:00:00Z",
  "created_by": "actor-id",
  "updated_at": "2026-08-09T00:00:00Z",
  "updated_by": "actor-id",
  "version": 1
}
```

Immutable events omit misleading update fields and expose source/reversal links.

## API-024 — Business Period

```json
{
  "start_date": "2026-08-01",
  "end_date": "2026-08-31",
  "start_inclusive": true,
  "end_inclusive": true
}
```

## API-025 — Financial Event Summary

Financial responses expose identifier, event type, Customer, optional Lease,
amount/currency, source links, effective/business date, recorded timestamp,
actor/system identity, reversal/correction links, and current derived effect.

# 8. Property Endpoints

## API-026 — Property Resource

`GET /properties/{property_id}` returns configured identity, address/source data,
Property timezone, version, and permitted configuration summaries.

`PATCH /properties/{property_id}` updates only documented mutable source fields and
requires `property.manage` plus version precondition.

## API-027 — Property Configuration

- `GET /properties/{property_id}/configuration`
- `PATCH /properties/{property_id}/configuration`

Configuration includes accepted Payment Methods and other approved configurable
business data. Historical effective-dated rates use their own resources.

Amended by DL-081 (login sub-slice L5, owner answers (a) to Q-2026-10-21-151 and Q-2026-10-21-160; technical points Q-2026-10-24-186, decided by Claude under the owner's 2026-10-23 22:30 rule): `GET /properties/{property_id}` needs `property.read` for the Property. `PATCH /properties/{property_id}` and `PATCH /properties/{property_id}/configuration` need `settings.manage` (Settings access; the Owner always has it) instead of `property.manage`. `GET /properties/{property_id}/configuration` accepts `settings.manage` or `property.manage`.

# 9. Unit Endpoints

## API-028 — Units

- `GET /properties/{property_id}/units`
- `POST /properties/{property_id}/units`
- `GET /units/{unit_id}`
- `PATCH /units/{unit_id}`

Filters include current occupancy/reservation/Lease attention and Meter/Reading
attention where derivable. Creation/update accepts identity and approved source
attributes only.

## API-029 — Unit Timeline

`GET /units/{unit_id}/timeline` returns paginated authorized Reservation, Lease,
Occupancy, Meter, Reading, billing, and audit summaries without flattening event
history.

Amended by DL-081 (login sub-slice L5, owner answers (a) to Q-2026-10-21-151 and Q-2026-10-21-160; technical points Q-2026-10-24-186, decided by Claude under the owner's 2026-10-23 22:30 rule): the Unit list, `GET /units/{unit_id}` and the Unit timeline need `units.read` for the Unit's Property (checked before the Unit is read, then again for its Property); a caller with `units.read` for no Property gets 403 at once. `POST /properties/{property_id}/units` and `PATCH /units/{unit_id}` keep `property.manage` and now need the configured Origin and the CSRF pair.

# 10. Customer Endpoints

## API-030 — Customers

- `GET /properties/{property_id}/customers`
- `POST /properties/{property_id}/customers`
- `GET /customers/{customer_id}`
- `PATCH /customers/{customer_id}`

No permanent customer-type field is accepted. Search and response fields are
limited by capability and scope.

## API-031 — Customer Financial Summary

`GET /customers/{customer_id}/financial-summary` returns currency-separated
outstanding Invoice and separate Late-payment Charge obligations, unallocated Payment,
Customer Credit, and Deposit-liability summaries. Deposit and Credit are separate
values.

## API-093 — Customer Account Ledger

`GET /customers/{customer_id}/account-ledger` returns the authorized chronological,
reconstructable Customer Account Ledger derived from the authoritative financial
sources. It exposes obligation composition, Payments and applications, Late-payment
Charges, Customer Credit events, Refunds, Deposits as separately identifiable
liabilities, current amount owed, and available Customer Credit with stable source
links and timestamps.

The endpoint is read-only. It does not create a General Ledger, Accounts Payable,
journal-entry system, or competing financial source of truth.

Amended by V1-056 sub-slice 8a-2 (migration `20261023_88`): a Final Settlement Deposit
application is the event kind `DEPOSIT_APPLIED` (order 75), accepted as a history filter.
The Deposit owner's ledger shows the Deposit held reduced and the evidence names the
obligation's Customer; the ledger of the Customer named on the Invoice or Late-payment
Charge shows that obligation reduced. One Customer gets one header with both components.

Amended by V1-056 sub-slice 10c-2a-1 (migration `20261105_101`): the reversal of such an
application by a post-settlement correction is the event kind `DEPOSIT_APPLICATION_REVERSED`
(order 76), accepted as a history filter, with the same components and the opposite effect.

# 11. Reservation Endpoints

## API-032 — Reservation Resource

- `GET /properties/{property_id}/reservations`
- `POST /properties/{property_id}/reservations`
- `GET /reservations/{reservation_id}`

Creation requires one Customer, one Unit, Reservation/Expiration dates, agreed
monthly Rent evidence, and approved Security Deposit receipt/input workflow. It
must satisfy `BR-RES-*` and create no Reservation Deposit type.

The `POST` body takes no time: the server records the database's own time at the command
as both the holding deposit's receipt time and its acceptance time; a body that sends
`received_at` is refused with 422. The money's own receipt time stays on the linked
Payment (owner answer (a) to Q-2026-10-20-147, V1-056 sub-slice 10i-4b).

The resource's `deposit_required_usd_cents` is the Security Deposit's required total with its
required-amount adjustments (BR-DEP-004; since V1-056 sub-slice 10e-2b-4f), and
`deposit_received_usd_cents` counts only receipts that are not reversed (since 10e-2b-4c).

## API-033 — Reservation Commands

- `POST /reservations/{id}/extend`
- `POST /reservations/{id}/cancel`
- `POST /reservations/{id}/complete-move-in`

Commands require idempotency. `extend` records the Notice and new date under the
one-extension/14-day rules. `cancel` requires reason; expiration uses
`RESERVATION_EXPIRED` while status becomes `CANCELLED`. `complete-move-in`
coordinates Reservation `COMPLETED` with the resulting Lease, Occupancy, Unit, and
continuing Security Deposit effects.

The `extend` body is `notice_id`, `new_expiration_date` and the optional `reason_memo`.
The server records the database's own time at the command as the extension approval
time; a body that sends `approved_at` is refused with 422 (BR-RES-010, owner answer (a)
to Q-2026-10-14-112 point 1, V1-056 sub-slice 10i-3).

Amended by V1-056 slice 3b (owner answers of 2026-10-04 to Q-2026-10-03-2): `cancel`
records the classified cancellation and releases the Unit at once; it takes no
`outcome_id` or `refund_number` and needs only `reservations.cancel`. The Security
Deposit stays held (`deposit_outcome_state` `AWAITING_DECISION`) until a
`financial.approve` holder confirms its Refund or forfeiture draft (BR-AUTH-010).
Automatic expiration also cancels and releases the Unit but never forfeits. A reused
`Idempotency-Key` with a different body answers 409 `IDEMPOTENCY_KEY_REUSED` (API-016).

Reservation Deposit drafts (V1-056 slice 3b):

- `GET /properties/{property_id}/reservation-deposit-decisions` (capability
  `reservations.read`; `limit` 1 to 100, default 50; opaque `cursor`) lists the
  Reservations waiting for a Deposit decision: cancelled or expired, Deposit received,
  and no outcome record yet, oldest cancellation first. Each item gives the Reservation,
  Unit, Customer, cancellation reason and responsibility, `cancelled_at`, the held amount
  in USD cents, the `decision_kind` the responsibility allows (`DEPOSIT_FORFEITURE` for
  Customer-caused, `REFUND` for Property-caused) and the `pending_draft_id`, if any.
- `POST /reservations/{reservation_id}/deposit-drafts` (`Idempotency-Key` required)
  records the decision draft. The kind follows the cancellation responsibility
  (BR-RES-021, BR-RES-022): a forfeiture draft needs `reservation_deposits.dispose`, a
  Refund draft `reservation_deposits.refund` plus `refund_number`, `refund_method_id` and
  `reference_note` (BR-REFUND-014). Body: `outcome_id`, `reason` and, for a Refund, those
  three fields. The draft covers the whole received Deposit, the Refund always goes to
  the Reservation Customer, and only one draft per Reservation may be pending. It answers
  201 with the pending draft and changes no balance.

Amended by DL-071 (owner, 2026-10-20; answer 10a): a Refund draft no longer takes a staff-typed `refund_number`; the Refund gets its `RFD` number (for example `RFD260001`) when the draft is confirmed, and the draft carries only an internal draft reference. Not built yet (V1-059).

Built in V1-059 part B (2026-10-24): the two Reservation Deposit draft bodies no longer have `refund_number`; sending it answers 422 (unknown field). The Customer create body needs `id_document_number` (1 to 64 characters) and the update body may correct it (null refused); a number another Customer has answers 409 `CUSTOMER_ID_NUMBER_IN_USE` with `existing_customer` (id and legal name, never the number); the number shows in the Customer detail only. A Meter install or Utility rate with a unit code other than `KWH` (electricity) or `M3` (water) answers 422, and a serial used in the Property answers 409 `METER_SERIAL_NUMBER_IN_USE`.
- `POST /reservations/{reservation_id}/deposit-correction-drafts` records a draft that
  replaces the confirmed outcome with a new outcome of the same kind; it needs
  `reservation_deposits.correct` and the kind's capability. Body: `expected_outcome_id`,
  `correction_id`, `replacement_outcome_id`, `reason`, `evidence_reference` and, for a
  Refund, the three Refund fields. The original outcome stays unchanged until
  confirmation.
- `POST /reservations/{reservation_id}/deposit-drafts/{draft_id}/confirm` (capability
  `financial.approve`, `Idempotency-Key` required but not stored) applies the outcome
  under every earlier Reservation outcome rule, with the approver as actor, and answers
  200 with the draft and the Reservation result. An exact repeat by the same approver
  returns the stored result; another approver gets 409. A stale draft (the Reservation
  or its received Deposit changed; defensive, since neither can change while waiting) is
  refused with 422 and stays pending. A Deposit receipt cannot be reversed while a
  Reservation Deposit draft is pending.

- `POST /reservations/{reservation_id}/deposit-drafts/{draft_id}/reject` (capability
  `financial.approve`) and `.../withdraw` (the preparer, with the draft's prepare
  capability) take `{"reason": "..."}` (1 to 1,000 characters, `Idempotency-Key`
  required but not stored), record the decision and answer 200 with the draft. They never
  move money; the Reservation stays on the waiting list. Brought forward from slice 11b for
  Reservation Deposit drafts only.

The draft id is derived from the Property, the preparer and the key, so an exact repeat
returns the same draft and a changed body with the same key answers 409
`IDEMPOTENCY_KEY_REUSED`. `AWAITING_DECISION` appears only while a Deposit is held and no
outcome record exists.

## API-034 — No Generic Reservation Status Patch

Clients cannot set `ACTIVE`, `CANCELLED`, or `COMPLETED` through PATCH. Unsupported
`EXPIRED` and `MOVED_IN` Reservation statuses are rejected.

# 12. Lease, Signer, and Occupancy Endpoints

## API-035 — Leases

- `GET /properties/{property_id}/leases`
- `POST /properties/{property_id}/leases`
- `GET /leases/{lease_id}`
- `PATCH /leases/{lease_id}` for DRAFTED source fields only

Creation accepts Customer/Unit/period/terms, approved Deposit/pet/Service terms,
and optional predecessor link. It does not create month-to-month behavior.

## API-036 — Lease Signers

- `GET /leases/{lease_id}/signers`
- `POST /leases/{lease_id}/signers` while permitted
- `PATCH /lease-signers/{signer_id}` while permitted

Schemas identify Customer and Primary Tenant/signing responsibility attributes.
Multiple Signers are supported and Occupants are not inferred.

The signature body is `event_id` and `reason` only. The server records the
database's own time at the command as the signature time; a body that sends
`signed_at` is refused with 422 (BR-AUDIT-003, Q-2026-10-14-110).

## API-037 — Occupancy

- `GET /leases/{lease_id}/occupancies`
- `POST /leases/{lease_id}/occupancies`
- `POST /occupancies/{occupancy_id}/end`

Occupancy commands preserve actual move-in/out dates and do not grant signer
responsibility.

## API-038 — Lease Commands

- `POST /leases/{id}/sign` (removed by DL-110; Sign Lease is `POST /leases/{id}/sign-with-payment`)
- `POST /leases/{id}/renew`
- `POST /leases/{id}/terminate`

Lease-violation Warning, Termination Notice, and Move-out creation use only the
canonical API-067, API-068, and API-069 routes; API-038 defines no aliases for those
actions. Rent-specific nonpayment cases, 20-day warnings, 30-day Serious Nonpayment
Defaults, cures, and authorized follow-up use API-095 instead.

Each action has an explicit schema, authorization, reason/evidence, idempotency,
and applicable rule references. Signing/renewal rechecks non-overlapping
contractual periods transactionally. End Date alone invokes none of these actions.

The signing body is `event_id` and `reason` only. The server records the
database's own time at the command as the Lease signing time; a body that sends
`signed_at` is refused with 422 (BR-AUDIT-003, Q-2026-10-14-110).

The termination body is `event_id`, `actual_termination_date`,
`governing_event_reference`, `reason` and the optional `context`. The server records
the database's own time at the command as the termination time; a body that sends
`occurred_at` is refused with 422, and a retry with the same Idempotency-Key and body
returns the first result with its first time (BR-AUDIT-003, owner answer (a) to
Q-2026-10-14-112 point 1, V1-056 sub-slice 10i-1).

For an approved voluntary early termination, the termination result charges the
full move-out calendar month's Rent, applicable Utility/fixed Service/other
approved obligations, records Security Deposit non-refundability through explicit
disposition, does not automatically forfeit Pet Deposit, creates no standard early-
termination fee, and generates no later-month Rent after approved termination.
Violation termination additionally requires at least three documented warning
letters and authority from the signed Lease.

# 13. Deposit Endpoints

## API-039 — Deposit Resource

- `GET /reservations/{id}/deposits`
- `GET /leases/{id}/deposits`
- `GET /deposits/{deposit_id}`
- `GET /deposits/{deposit_id}/ledger`

Security and Pet Deposits remain separate typed liabilities with receipt,
application, disposition, and Refund history.

Amended by V1-056 sub-slice 8a-2: `GET /deposits/{deposit_id}/ledger` lists each Final
Settlement Deposit application as `APPLICATION_INVOICE_LINE` or
`APPLICATION_LATE_PAYMENT_CHARGE`, with `source_id` the Invoice line or Late-payment
Charge, `governing_source_kind` `FINAL_SETTLEMENT` and `governing_source_id` the
Settlement, the approver as `actor_id`, `authorization_reference` `financial.approve`,
the amount in USD cents and `can_reverse` false, so every lower held amount has its event
(BR-SETTLE-009).

Amended by V1-056 sub-slice 10c-2a-1: the same read lists the reversal of such an application
by a post-settlement correction as `APPLICATION_REVERSAL_INVOICE_LINE` or
`APPLICATION_REVERSAL_LATE_PAYMENT_CHARGE`, with `source_id` the reversed application,
`governing_source_kind` `FINAL_SETTLEMENT`, the correction's approver as `actor_id`,
`authorization_reference` `financial.approve`, the reversed amount in USD cents and
`can_reverse` false.

## API-040 — Deposit Receipt

The following explicit commands create or continue the applicable liability and
record its receipt:

- `POST /reservations/{id}/security-deposit-receipts`
- `POST /leases/{id}/security-deposit-receipts`
- `POST /leases/{id}/pet-deposit-receipts`
- `POST /deposits/{id}/receipts` for a subsequent receipt against an existing
  Deposit

Each records Customer, amount/currency, Payment/source, timestamp, and evidence.
No command may recognize Deposit income or ordinary Invoice Credit. Reservation
Security Deposit continuity into the resulting Lease reuses the existing Deposit
and ledger rather than creating a duplicate liability.

V1-056 sub-slice 10e-2b-4b-2b (owner answer to Q-2026-10-12-92): the database
writer and the Deposit service command for a receipt into an existing Deposit of
a signed or terminated Lease exist (`payments.allocate`, no draft; refused once
the Lease's Final Settlement is closed, as a conflict, P5S01, which the Deposit
service now maps to a conflict for every Deposit command; a Payment confirmed for
an Invoice or a Late-payment Charge is refused). The receipt keeps a reason, the
actor and the Payment; no separate evidence reference. The routes above are not
built yet; they come with the staff screens in slice 11.

V1-056 sub-slice 10e-2b-4c (owner answers to Q-2026-10-17-124): the database
command and the Deposit service command `create_lease_security_deposit` create a
walk-in Lease's Security Deposit with its required total from the Lease terms
(`deposits.manage`; a SIGNED Lease signed with no Reservation, not a renewal,
with no Security Deposit yet; refused at another isolation level than READ
COMMITTED). The same receipt command now also records a second receipt into an
ACTIVE Reservation's Security Deposit before signing, within the required total,
while the Reservation's expiration date has not passed. The route for the create
(for example `POST /leases/{lease_id}/security-deposit`) comes with the staff
screens in slice 11.

V1-056 sub-slice 10e-2b-4d (owner answers of 2026-10-18): the receipt command
takes what is left of a Payment confirmed for an Invoice or a Late-payment
Charge once that target has nothing outstanding (refused, invalid, while it is
owed), and refuses (invalid) a receipt into a Deposit whose Refund is not fully
returned and a receipt into a Deposit of a terminated Lease whose termination
ground keeps that Deposit (also after a forfeiture reversal; staff record that
money as a normal Payment); after any lock refusal (55P03, also a lock
timeout) the service replays the same command at most three times and then
answers unavailable (DL-067; at worst about 14 seconds).

V1-056 slice 11c-4 (2026-10-24; no migration): two of the routes above are built, each with
`Idempotency-Key` (the same key and body answer the same result again; the same key with another
body answers 409 `IDEMPOTENCY_KEY_REUSED`), the browser mutation rules and a strict JSON body; a
person without the route's capability in the Property gets a hidden 404. These replace the route
list above for what exists: the separate Reservation and Pet Deposit receipt paths named above
are not built, because `POST /deposits/{deposit_id}/receipts` records a receipt into any existing
Deposit, a Pet Deposit and an ACTIVE Reservation's Security Deposit before signing included.

- `POST /leases/{lease_id}/security-deposit` (`deposits.manage`; body `deposit_id`, a new id the
  form chooses, `required_usd_cents` above 0 and `reason` of up to 1,000 characters): a walk-in
  Lease's Security Deposit. Answers 201 with the Deposit resource and its `Location`. Named
  refusals (409): `DEPOSIT_SECURITY_LEASE_NOT_SIGNED`, `DEPOSIT_SECURITY_NOT_WALK_IN` (the Lease
  was signed from a Reservation or through the old path, BR-DEP-005), `DEPOSIT_SECURITY_RENEWAL`
  (Q-2026-10-18-129 is still open), `DEPOSIT_SECURITY_ALREADY_EXISTS` and, fail-closed,
  `FINAL_SETTLEMENT_CLOSED`. The Deposit is listed by `GET /leases/{lease_id}/deposits`; the Lease
  resource's `security_deposit_id` stays the one its draft named (none for a walk-in Lease).
- `POST /deposits/{deposit_id}/receipts` (`payments.allocate`, no draft; body `receipt_id`,
  `payment_id`, `amount_usd_cents` above 0 and `reason` of up to 1,000 characters): a receipt
  from a received Payment into an existing Deposit. Answers 201 with the receipt and the
  Deposit's money only, with no `Location` (`deposit_receipt_id`, `deposit_id`, `payment_id`, `amount_usd_cents`,
  `occurred_at`, `payment_available_usd_cents`, `required_usd_cents`,
  `held_refundable_usd_cents`, `outstanding_required_usd_cents`, `version`), not the Deposit
  resource, because a holder of `payments.allocate` alone may not read Deposits (decided by
  Claude under the owner's 2026-10-23 22:30 rule); the answer still shows that person the
  Deposit's required, held and outstanding money. Named refusals: 409
  `DEPOSIT_RECEIPT_LEASE_NOT_SIGNED`, `DEPOSIT_RECEIPT_RESERVATION_NOT_ACTIVE`,
  `DEPOSIT_RECEIPT_GROUND_KEEPS_DEPOSIT`, `DEPOSIT_RECEIPT_FORFEITURE_ACTIVE`,
  `DEPOSIT_RECEIPT_PAYMENT_OWED`, `DEPOSIT_RECEIPT_PAYMENT_ALREADY_USED` and
  `FINAL_SETTLEMENT_CLOSED`; 422 on `payment_id`: `DEPOSIT_RECEIPT_PAYMENT_NOT_FOUND` and
  `DEPOSIT_RECEIPT_PAYMENT_INELIGIBLE` (not a received Payment of the Deposit's Customer or for
  its Lease); 422 on `amount_usd_cents`: `DEPOSIT_RECEIPT_OVER_PAYMENT`,
  `DEPOSIT_RECEIPT_AMOUNT_NOT_ALLOWED` (a Security Deposit: more than it still needs, or a
  Reservation's Deposit with no active receipt and an amount other than its accepted amount) and
  `DEPOSIT_RECEIPT_OVER_REQUIRED` (a Pet Deposit). A Payment with nothing left answers
  `DEPOSIT_RECEIPT_OVER_PAYMENT` before `DEPOSIT_RECEIPT_PAYMENT_ALREADY_USED`.

Other refusals keep their plain status. The Deposit resource still carries
`new_receipt_creation_deferred: true` for the current screens; the rebuilt screens use the
receipt route. No route adjusts a Deposit's required total yet: the database command has no
closed-Final-Settlement refusal, so the route waits for that check (decided by Claude under the
owner's 2026-10-23 22:30 rule; ops/V1_056_PLAN.md, "11c-4 as built"). Until then a walk-in
Deposit's required total cannot be corrected through the API, and a second receipt into a
Reservation's Security Deposit before signing is refused whenever its required total equals its
accepted amount.

## API-041 — Pet Deposit Preconditions

Pet Deposit creation/receipt is accepted only when the pet is approved and the
applicable signed Lease terms require it. The API enforces beginning/later timing
rules without inventing a penalty.

## API-042 — Deposit Disposition

- `POST /reservations/{id}/security-deposit-dispositions` for customer-caused
  cancellation or expiration before a Lease exists
- `POST /final-settlements/{id}/deposit-dispositions`

Each idempotent command records Deposit, amount, governing event,
cause/responsibility, reason, authorization, timestamp, and actor. Property-caused
pre-Lease cancellation uses the explicit Refund path instead. Unsupported free-form
forfeiture is rejected, and ordinary Invoice APIs never accept a Deposit balance.

Amended by V1-056 slice 3b: `POST /reservations/{id}/security-deposit-dispositions`
validates and authorizes the request but records nothing and answers 409
`RESERVATION_DEPOSIT_DRAFT_REQUIRED`; the forfeiture is a draft (API-033). For a
Reservation disposition, `POST /deposit-dispositions/{id}/reverse` answers the same 409;
the correction is a Reservation Deposit correction draft. Lease dispositions are
unchanged.

Amended by V1-056 slice 6 (owner answers to Q-2026-10-04-12 and Q-2026-10-04-13): a
Lease Deposit forfeiture is a `DEPOSIT_FORFEITURE` draft confirmed by a
`financial.approve` holder (its draft routes come with the draft screens). For a Lease
disposition, `POST /deposit-dispositions/{id}/reverse` checks `deposits.correct` and the
browser mutation rules, then records nothing and answers 409
`LEASE_DEPOSIT_DRAFT_REQUIRED` (rule IDs `BR-AUTH-010`, `BR-DEP-026`); the forfeiture
reversal draft exists since V1-056 sub-slice 6b (database and service; prepared under
`deposits.correct`, confirmed under `financial.approve`) and its routes come in slice 11c. The Deposit ledger no longer offers `can_reverse` for
any disposition.

`POST /deposit-receipts/{id}/reverse` and
`POST /deposit-dispositions/{id}/reverse` create DB-DEP-007/DB-DEP-008 linked
correction events and never rewrite originals. Since V1-056 slices 3b and 6 only the
receipt reversal records anything here; a disposition reversal is a draft (see the
amendments above).

Amended by V1-056 sub-slice 8r (owner answer to Q-2026-10-05-22): a Deposit receipt
reversal, for a Lease or a Reservation Deposit, is a `DEPOSIT_FORFEITURE` draft with
variant `DEPOSIT_RECEIPT_REVERSAL`, prepared under `deposits.correct` and confirmed by a
`financial.approve` holder (database and service; its routes come in slice 11c).
`POST /deposit-receipts/{id}/reverse` checks `deposits.correct` and the browser mutation
rules, then records nothing and answers 409 `DEPOSIT_RECEIPT_REVERSAL_DRAFT_REQUIRED`
(rule ID `BR-AUTH-010`). The Deposit resource's `can_reverse_receipt` and the ledger's
`can_reverse` are always false, so no event offers a one-call reverse route.

Amended by V1-056 sub-slice 10h-2 (owner answer 4 to Q-2026-10-06-36): once the Final
Settlement of a forfeiture's governing Lease or of its Deposit's Lease is closed, the Lease
forfeiture reversal draft (database and service; its routes come in slice 11c) is refused as a
conflict (409) at record and at confirmation, and a draft refused at confirmation stays pending;
the forfeiture is reversed only through a `FORFEITURE_REVERSAL` correction of that Settlement
(slice 11e routes). An already reversed forfeiture keeps its own refusal.

Amended by V1-056 sub-slice 8a-2 (owner answer 2 to Q-2026-10-05-23): while a receipt
reversal draft for a Deposit is pending, confirming a Refund draft or a forfeiture draft
for the same Deposit is refused as a conflict and the draft stays pending: the Refund
draft and Reservation Deposit draft confirm routes answer 409, and the Lease forfeiture
draft service reports a conflict (its routes come in slice 11c). Recording such drafts
stays allowed.

Amended by V1-056 sub-slice 10c-2b-2a (owner answer 5 to Q-2026-10-08-55, an approved
tightening): once a Lease's Final Settlement is closed, recording or confirming a receipt
reversal draft for that Lease's Deposit is refused as a conflict (the service maps the
database's P5S01 to a conflict; the draft routes come in slice 11c); a wrong receipt is then
fixed only through a post-settlement correction (`RETURNED_PAYMENT`, `DEPOSIT_RECEIPT_CORRECTION`;
not built yet). After its review round 1 (owner answers 1 and 4 to Q-2026-10-08-59): a receipt
reversal draft is recorded only at READ COMMITTED, and recording a Lease Deposit forfeiture draft
after the Lease's Final Settlement is closed is refused as a conflict too (the forfeiture service
maps P5S01 to a conflict; its routes come in slice 11c).

V1-056 slice 11c-3 (2026-10-24; no migration): the draft routes of this section. Each needs the
browser mutation rules, a strict JSON body and `Idempotency-Key` (the same key and body answer the
same draft again; the same key with another body answers 409 `IDEMPOTENCY_KEY_REUSED`), and
answers 201 with the draft as API-101 shows it. A person without the route's capability in the
Property gets a hidden 404. The draft has no financial effect until a `financial.approve` holder
confirms it through `POST /properties/{property_id}/financial-drafts/{draft_id}/confirm`; it is
rejected or withdrawn there too (API-101).

- `POST /properties/{property_id}/deposits/{deposit_id}/forfeiture-drafts` (`deposits.dispose`;
  body `disposition_id`, a new id the form chooses, and `reason`): a `DEPOSIT_FORFEITURE` draft
  of variant `LEASE_FORFEITURE` that forfeits the whole held Deposit of a terminated Lease on the
  ground the database works out from the termination record (BR-DEP-026).
- `POST /properties/{property_id}/deposit-dispositions/{disposition_id}/reversal-drafts`
  (`deposits.correct`; body `reversal_id`, `reason` of up to 500 characters and
  `evidence_reference`): variant `LEASE_FORFEITURE_REVERSAL`.
- `POST /properties/{property_id}/deposit-receipts/{receipt_id}/reversal-drafts`
  (`deposits.correct`; body `reversal_id` and `reason` of up to 500 characters): variant
  `DEPOSIT_RECEIPT_REVERSAL`, for a Lease or a Reservation Deposit.
- `POST /properties/{property_id}/payments/{payment_id}/return-drafts` (`payments.reverse`; body
  `reason` and `evidence_reference`): a `PAYMENT_RETURN` draft (BR-SETTLE-013).

A business-state refusal answers 409 with its own code, at record and, for the same rule, at the
shared confirm: `DEPOSIT_FORFEITURE_LEASE_NOT_TERMINATED`, `DEPOSIT_FORFEITURE_NO_GROUND`,
`DEPOSIT_FORFEITURE_PET_AT_SETTLEMENT`, `DEPOSIT_FORFEITURE_NOTHING_HELD`,
`DEPOSIT_FORFEITURE_DRAFT_WAITING`, `DEPOSIT_FORFEITURE_ALREADY_REVERSED`,
`DEPOSIT_FORFEITURE_REVERSAL_DRAFT_WAITING`, `DEPOSIT_RECEIPT_ALREADY_REVERSED`,
`DEPOSIT_DRAFT_WAITING`, `PAYMENT_RETURN_NOT_RECEIVED`, `PAYMENT_RETURN_THROUGH_CORRECTION`,
`PAYMENT_RETURN_REFUND_NOT_RETURNED`, `PAYMENT_RETURN_REFUND_NO_RECOVERY`,
`PAYMENT_RETURN_SETTLEMENT_NOT_CORRECTABLE`, `PAYMENT_RETURN_FORFEITURE_ACTIVE`,
`PAYMENT_RETURN_DEPOSIT_USED`, `PAYMENT_RETURN_DRAFT_WAITING`, `PAYMENT_RETURN_TOO_LARGE` and
`FINAL_SETTLEMENT_CLOSED`; a `disposition_id` or `reversal_id` that is already used answers 409
`DRAFT_RECORD_ID_IN_USE`. At the shared confirm a Deposit draft whose Deposit changed since it
was recorded answers 409 `DRAFT_OUT_OF_DATE` and stays pending; Reservation Deposit drafts (the
same kind) keep their earlier answers. Other refusals keep their plain status. The one-call routes
`POST /deposit-receipts/{id}/reverse` and `POST /deposit-dispositions/{id}/reverse` still record
nothing and answer their draft-required 409.

## API-094 — Active-Lease Pet Deposit Refund Qualification

- `POST /leases/{lease_id}/pet-departures`
- `GET /leases/{lease_id}/pet-departures`
- `POST /pet-departures/{pet_departure_id}/refund-review`
- `GET /pet-deposit-refund-reviews/{review_id}`

A pet-departure command records only the approved pet's permanent departure fact and
does not terminate the Lease or itself authorize a Refund.

A qualifying refund review is append-only and verifies the matching Pet approval,
SIGNED Lease, Pet Deposit, Customer, permanent departure, resolved pet obligations,
remaining refundable Pet Deposit, reason, authorization, actor, and supporting
resolution reference. Only a qualifying review may support the active-Lease Pet
Deposit Refund exception.

The resulting Refund is created through API-065 using the Pet Deposit as its source and
the qualifying review as `pet_refund_review_id`. This path does not require or create a
Final Settlement, does not apply the Deposit to an Invoice, and does not limit other
Customer liability.

# 14. Service Rate Endpoints

## API-043 — Service Rates

- `GET /properties/{property_id}/service-rates`
- `POST /properties/{property_id}/service-rates`
- `GET /service-rates/{rate_id}`

Only configured Services may receive effective-dated rate records. A Service becomes
billable only when it also has an applicable Owner-approved Service approval period and
applicable Lease Service term. The initial production configuration approves Trash
Collection for billing. Internet and Monthly Cleaning have no approved active period and
must not be treated as currently provided or billable. A future Service requires its
separate authoritative Owner-approved rule and explicit approval period before billing.
Historical rate records are not overwritten. No generic one-time Service endpoint is
authorized.

Amended by DL-081 (login sub-slice L5, owner answers (a) to Q-2026-10-21-151 and Q-2026-10-21-160; technical points Q-2026-10-24-186, decided by Claude under the owner's 2026-10-23 22:30 rule): creating a Service rate and a Utility Rate needs `settings.manage` instead of `service_rates.manage` and `utility_rates.manage`; the old names stay in the catalog and open no route. The configuration capability summary answers `manage_service_rates` and `manage_utility_rates` from `settings.manage`. The riel rate keeps `exchange_rates.manage`.

# 15. Utility Meter and Reading Endpoints

## API-044 — Meters

- `GET /units/{unit_id}/meters`
- `POST /units/{unit_id}/meters`
- `GET /meters/{meter_id}`
- `POST /meters/{meter_id}/replace`

Installation/replacement accepts Unit, Utility Type, physical identity, dates, and
required boundary evidence. It preserves replacement chain and rejects overlapping
active assignments.

Amended by DL-104 (V1-060 B6, 2026-10-28): `POST /meters/{meter_id}/report-broken` records a Meter broken before it is replaced; see "V1-060 Report broken meter" at the end of this file.

## API-045 — Readings

- `GET /meters/{meter_id}/readings`
- `POST /meters/{meter_id}/readings`
- `POST /utility-readings/{reading_id}/correct`

Schemas include reading value, reading date/period, source/evidence, and expected
Meter version. Correction creates history and does not mutate issued Invoice lines.

## API-046 — Bulk Reading Entry

`POST /properties/{property_id}/utility-readings:batch` may accept a bounded list.
Each item has an idempotency key and item-level result. Atomic-all or partial
behavior must be explicit in the request. Each item is an independent command under
API-017; partial mode is an envelope over those commands, while atomic-all mode is
one command covering the complete list. Neither mode leaves a half-written item.

## API-047 — Utility Rates

- `GET /properties/{property_id}/utility-rates`
- `POST /properties/{property_id}/utility-rates`
- `GET /utility-rates/{rate_id}`

Rates are effective-dated by Utility Type. Existing Rate history is immutable;
creation requires advance-notice timestamp/evidence whose Property-local date is
before the Effective Date. Correction uses an approved version/event mechanism
defined by the data model.

## API-048 — Utility Calculation Preview

`POST /utility-billing/preview` accepts approved Unit/Utility Type/period source
identifiers and returns a non-persisted server calculation with Reading/Meter,
consumption, generation-date Rate, broken-Meter basis, represented days, and amount.
Preview does not authorize issuance.

## API-049 — Broken-meter Pending Basis

Broken-Meter preview/generation follows the authoritative basis hierarchy exactly:

- with three or more complete historical actual periods for the same Unit and
  Utility Type, use the three most recent complete historical periods preceding the
  affected period;
- with exactly one or two complete historical actual periods, use all available
  one or two periods as the weighted historical basis; and
- with zero complete historical actual periods, return
  `PENDING_FUTURE_ACTUAL_BASIS` and wait until one complete future actual period
  for the same Unit and Utility Type exists.

The API accepts no arbitrary estimate, substitute/comparable Unit, omitted available
one/two-period history, or averaging of separately rounded period averages.

# 16. Invoice Endpoints

## API-050 — Invoice Resource

- `GET /properties/{property_id}/invoices`
- `POST /properties/{property_id}/invoices` for approved draft sources
- `GET /invoices/{invoice_id}`
- `PATCH /invoices/{invoice_id}` only while DRAFT and only for allowed source fields

Every request/response has exactly one `customer_id`; `lease_id` is nullable and
at most one. Rent requires the applicable signed Lease.

## API-051 — Invoice Schema

An Invoice includes:

- identifier/number;
- Property and exactly one Customer;
- optional Lease;
- category;
- issue and due dates;
- currency;
- represented period where applicable;
- immutable issued lines/source links;
- original and adjusted totals;
- active application totals;
- outstanding balance;
- status; and
- audit/version metadata.

Callers do not send calculated totals, outstanding balance, or status.

## API-052 — Invoice Commands

- `POST /invoices/{id}/issue`
- `POST /invoices/{id}/adjustments`
- `POST /invoices/{id}/void`

Issue validates source uniqueness and calculation. Adjustment requires debit/credit
direction, exact amount/currency, reason, and authorization. Void is exceptional,
preserves history, and rejects unresolved active applications when rules require
reversal first.

Slice 9b routes (capabilities reuse existing ones; no new capability):

- `POST /properties/{id}/one-time-charges` (201) records a manual Damage (`damage_charges.bill`) or Miscellaneous (`invoices.create`) charge: `charge_id`, `category`, `customer_id`, `lease_id`, `inspection_damage_finding_id`, `description`, `amount_usd_cents` (integer), `reason`, `evidence_reference`. The existing `POST /properties/{id}/invoices` then creates the DRAFT from the charge.
- `POST /properties/{id}/one-time-charge-due-days` (`property.manage`, `If-Match` Property version) with `days` (1 to 90) and `reason`.
- `POST /invoices/{id}/issue` accepts the optional `due_date` and `due_date_reason` pair (both or neither).
- `POST /properties/{id}/leases/{lease_id}/initial-rent-due-date` (`invoices.issue`, owner decision 2026-10-02) records an authorized Initial Rent Due Date before the Initial Rent Invoice is issued: `override_id`, `due_date`, `reason`; actor and timestamp are recorded and it is fixed once issued; an exact replay returns the saved result and a reused identity is a conflict. Since migration `20261009_74` the stored audit evidence names the capability the caller was authorized under: this route records `invoices.issue`, while the billing service path keeps `billing.generate`; earlier records are unchanged.
- `GET /properties/{id}/billing-capabilities` visibility now also lists `damage_charges.bill` and `property.manage` so the staff screen can show the one-time charge and due-days forms. Visibility only; each route still authorizes.

Amended by DL-081 (login sub-slice L5, owner answers (a) to Q-2026-10-21-151 and Q-2026-10-21-160; technical points Q-2026-10-24-186, decided by Claude under the owner's 2026-10-23 22:30 rule): `POST /properties/{id}/one-time-charge-due-days` needs `settings.manage` instead of `property.manage`, and `billing-capabilities` also lists `settings.manage`. The move-out cleaning rate keeps `property.manage` until the DL-075 Settings screen.

Amended by DL-103 (owner, 2026-10-28): `POST /properties/{id}/invoices/drafts` makes one Miscellaneous DRAFT of 1 to 20 typed items, and `PUT /invoices/{id}/items` changes the items of such a DRAFT; see "V1-060 Invoice items" at the end of this file.

Issue accepts an optional Due Date override with a mandatory reason; without it, the
server applies the proposed Due Date (Lease Start Date plus five for Initial Rent, issue
date plus the configured days for one-time and final Utility Invoices).

Implementation status (migration `20261002_65`): the service boundary is delivered
without a new HTTP route. `PostgresInvoiceService.record_one_time_charge` records a
manual Damage charge (capability `damage_charges.bill`, one current inspection finding,
matching Lease and Customer) or Miscellaneous charge (capability `invoices.create`)
with an integer-cent amount, mandatory reason and text evidence reference; the existing
draft command then creates the DRAFT without a Due Date. `issue` accepts the optional
`due_date` and `due_date_reason` pair only for one-time charge Invoices; the pair is
part of the request digest only when present, so earlier issue replays are unchanged.
`set_one_time_charge_due_days` changes the Property setting (capability
`property.manage`, expected Property version, mandatory reason, audited). A route for
creating a one-time charge may be added to API-052 in the HTTP and UI slice. Missing
capability is an authorization failure; a reused charge identity with different intent,
or a finding already billed, is a conflict; a mismatched or superseded finding, a
backdated or misplaced Due Date, or an invalid shape is invalid.

A debit Adjustment on a fully paid line returns 409 with the stable error code `INVOICE_LINE_FULLY_PAID` and rule `BR-INV-044` (since slice 9d), so a client can tell staff to bill the missed amount as a one-time charge.
Service status (migration `20261003_66`): `PostgresInvoiceService.adjust` raises
`InvoiceLineFullyPaid` (a conflict) carrying `line_balance_usd_cents`; the existing route
already answers 409 for a conflict, and adding the balance to the response body belongs to
the HTTP and UI slice. Since migration `20261003_67` a credit beyond the remaining line
balance succeeds and its result carries `adjustment_effect` with
`customer_credit_usd_cents`, the new Credit ids, `returned_to_customer_credit_usd_cents`
and the released sources; an exact replay returns the same body. A credit beyond the
line's adjusted obligation remains invalid. A
credit Adjustment reports any amount recorded as Customer Credit. Neither accepts a Due
Date field; both use the Invoice Due Date.

## API-053 — Invoice Lines

Lines are created only through approved draft/generation services and include type,
description, exact amount/currency, source type/id, calculation evidence, and
sequence. A generic API cannot attach an unsupported fee, penalty, or category.

## API-091 — Late-payment Decision and Charge

- `GET /invoices/{invoice_id}/late-payment-review`
- `POST /invoices/{invoice_id}/late-payment-decision`
- `GET /invoices/{invoice_id}/late-payment-decision`
- `GET /late-payment-charges/{charge_id}`
- `POST /late-payment-charges/{charge_id}/corrections`
- `POST /late-payment-charges/{charge_id}/reductions` (V1-056 slice 11g-2, DL-086)

The review endpoint returns the authoritative overdue balance at assessment, exact
default 10% proposal, calculated default amount, prior-decision state, and blocking
conditions without posting a Charge. Since migration `20261004_68` an Initial Rent Invoice
reports the blocking condition `INITIAL_RENT_NO_LATE_PAYMENT` and its final decision is
rejected as a conflict; existing decisions and Charges are unchanged. The unpaid Initial
Rent management alert (`app.unpaid_initial_rent_alert_page`, capability
`rent_nonpayment.read`) is delivered at service level only
(`PostgresEnforcementContext.initial_rent_alerts`) and, since V1-055 slice 9c, through
`GET /properties/{id}/initial-rent-unpaid-alerts` (keyset `limit` and `cursor`, read only; it opens no case
and records no Notice).

Lease signing and move-in service status (migration `20261005_69`): `PostgresLeaseService.sign`
accepts an optional `reservation_id` (part of the request digest only when present) and
completes that Reservation and occupies the Unit at signing; `PostgresMoveInService.record_lease_move_in`
begins Occupancy for such a Lease. Exposing `reservation_id` on the signing route and the new
move-in route belongs to the HTTP and UI slice.

Unpaid Initial obligation termination (migration `20261005_70`): the termination context
accepts basis `UNPAID_INITIAL_OBLIGATION` with governing reference `BR-LEASE-005`.
`PostgresUnpaidInitialTerminationService.resolve_never_moved_in` (capabilities
`leases.terminate`, `deposits.dispose`, `invoices.void`, `invoices.adjust`, plus
`property.manage` for CLEANING) and `credit_moved_in_initial_rent` (`leases.terminate`,
`invoices.adjust`) are exposed since V1-055 slice 9c as `POST /properties/{id}/lease-terminations/{termination_event_id}/unpaid-initial-never-moved-in`
(`resolution_id`, `unit_status` `VACANT` or `CLEANING`, `unit_status_reason` only for CLEANING, `reason`) and
`POST /properties/{id}/lease-terminations/{termination_event_id}/unpaid-initial-moved-in-credit`
(`resolution_id`, `reason`). Both need an `Idempotency-Key`, answer 201 and replay exactly; a second resolution of the
same termination is refused as invalid. `POST /leases/{id}/terminate` now accepts the optional `context` object
(`basis`, `signed_lease_provision`, `approved_grounds`, `management_authorization_reference`, `evidence_reference`,
`notice_required` with `notice_id` and `notice_period_ends_on` or `notice_exception_reason`, and `warning_ids`); the
database refuses a fresh termination without it. The `termination_event_id` is the `event_id` sent with the termination. `GET /leases/{id}/timeline` also lists each follow-up as `lease.unpaid_initial_never_moved_in` or `lease.unpaid_initial_moved_in_credit` with the termination event as its source reference.

`GET /leases/{id}` (its first timeline page) and `GET /leases/{id}/timeline` also list Initial Rent Due Date overrides as `lease.initial_rent_due_date_override` (source reference: the Due Date) to an actor with `invoices.read` for the Lease's Property, and Rent-nonpayment events as `lease.rent_nonpayment_twenty_day_warning`, `lease.rent_nonpayment_thirty_day_serious_default`, `lease.rent_nonpayment_cure` or `lease.rent_nonpayment_authorized_follow_up` (source reference: the Rent-nonpayment case) to an actor with `rent_nonpayment.read` for that Property. They are merged into the same `occurred_at`, `event_id` order and cursor. An actor with only `leases.read` gets exactly the same items, pages and cursors as before, with no hint that other events exist.

The final-decision command is authorized and idempotent and accepts only
`CONFIRMED_DEFAULT`, `REDUCED`, or `WAIVED`. A REDUCED decision records the exact
approved USD amount below the calculated default amount. The approved monetary amount
is authoritative; the API must not force the effective reduced percentage into whole
basis-point precision. WAIVED requires zero, while CONFIRMED_DEFAULT requires the
calculated default amount.

Exactly one final decision may exist per applicable source Invoice. A positive final
amount creates the separate immediately payable Late-payment Charge represented by
DB-INV-008; a waiver creates no positive receivable. The Charge is not an Invoice,
Invoice line, Invoice category, Miscellaneous Charge, or source-Invoice balance.

Charge corrections use only DB-INV-009's authorized reduction/reversal mechanisms and
must not reopen, supplement, replace, or recalculate the final decision.

Amended by DL-076 (owner, 2026-10-20): no manual decision route; the charge is added by the 00:00 job. A route reduces or waives a charge with one of three fixed reasons and a required "What happened" text. Not built yet (V1-056 slice 11).

V1-056 slice 11g-1 (DL-085): the 00:00 charge pass runs inside the scheduled billing worker (`property_rental.late_payment_job`); it has no HTTP route. The manual decision route stays until slice 11g-3 removes it.

V1-056 slice 11g-2 (DL-086): `POST /api/v1/late-payment-charges/{charge_id}/reductions` under `late_payment.charge_correction` (CSRF, `Idempotency-Key`), body `{new_amount: {currency: USD, minor_units}, reason: WRONG_INVOICE | PAID_ON_TIME_RECORDED_LATE | OTHER_STAFF_MISTAKE, what_happened}` (1 to 500 characters, no white space at either end, no C0 or C1 control character other than tab, line feed and carriage return); `new_amount` 0 waives the charge. 200 with the charge read; each correction item has `reduction` (`reason_code`, `what_happened`, `released`, `customer_credit_ids`, `recorded_at`) or null. 409 `CONFLICT` with the charge state when the amount is not lower, the charge is waived, a Deposit application paid it, it was paid again meanwhile, or its Final Settlement is closed; 409 `CONFLICT` also after a detected deadlock or serialization failure on this route only (nothing was written; retry with the same `Idempotency-Key`); 409 `IDEMPOTENCY_KEY_REUSED` (the key space is shared with the corrections route); 422 for bad input; 404 for an unknown charge or a caller without the capability on its Property; 403 without CSRF, from another Origin or for an inactive actor; 503 when the database is unavailable. The corrections route stays until slice 11g-3 and answers 409 `CONFLICT` to a `REDUCTION_REVERSAL` of a reduction made by this route.

V1-056 slice 11g-3 (DL-087): from the Property's first finished automatic pass on, `POST /invoices/{invoice_id}/late-payment-decision` and `POST /late-payment-charges/{charge_id}/corrections` answer 409 `CONFLICT` with the current state (an exact repeat of an earlier request still gets its stored answer). The routes stay for that replay and for history reads; the GET routes and the reductions route are unchanged. Clients use the reductions route. Once a finished pass has covered the Invoice's charge day (the day after its Due Date), the review read lists the blocker `AUTOMATIC_CHARGE_ONLY` (`eligible: false`); from the first pass the charge read has `manual_corrections_open: false` (absent before).

# 17. Scheduled Billing Endpoints

## API-054 — Rent Generation Run

- `POST /properties/{property_id}/billing-runs/rent`
- `GET /billing-runs/{run_id}`

The command requires logical billing period/date and idempotency. The server selects
eligible Leases, uses the applicable signed Lease, creates one obligation/Invoice
per approved source/period, and returns generated/skipped/conflict/error items.

## API-055 — Utility Generation Run

- `POST /properties/{property_id}/billing-runs/utilities`

Run status uses the canonical `GET /billing-runs/{run_id}` resource declared by
API-054.

The server uses validated Readings, the Utility Rate effective on generation date,
and broken-Meter hierarchy. Pending future-basis charges remain unissued and
identified as pending.

## API-056 — System Job Invocation

Scheduled workers invoke the same command service with a system identity, durable
logical run key, Property-local business date, and capability-equivalent service
authorization. There is no unauthenticated scheduler bypass endpoint.

# 18. Payment Endpoints

## API-057 — Payment Resource

- `GET /properties/{property_id}/payments`
- `POST /properties/{property_id}/payments`
- `GET /payments/{payment_id}`

Creation confirms receipt and requires Customer, amount/currency, accepted method,
received timestamp, payer/reference evidence, and FX inputs where applicable. It
does not accept Allocations, Credit status, derived availability, or arbitrary
status. Payment resources expose immutable accepted-method code/name snapshots in
addition to any link to the current configurable Payment Method.

A third-party payer may be recorded without becoming the financially responsible
Customer. A third-party Payment must carry designated Invoice/Lease intent and may
not be spread across unrelated obligations.

Amended by DL-077 (owner, 2026-10-20): a new command receives a Payment and pays the ticked Invoices and late-payment charges in one database transaction (Payment, Receipt and Allocations as separate records). Not built yet (screen rebuild).

## API-058 — Exchange-rate Confirmation

For applicable Payment confirmation, the server retrieves or accepts only the
authorized fallback ABA-equivalent Sell reference, stores source/value/timestamp,
applies `1.005`, rounds the System Exchange Rate upward to whole KHR, calculates
payable, and rounds fractional final KHR upward. Responses expose all preserved
calculation facts.

## API-059 — Payment Allocation

- `GET /payments/{payment_id}/allocation-proposal`
- `POST /payments/{payment_id}/allocations`
- `GET /payments/{payment_id}/allocations`
- `POST /payment-allocations/{allocation_id}/reverse`

For a normal undesignated Customer Payment, the proposal uses oldest Due Date
first across applicable Invoices for that Customer, then Invoice issue/generation
order and stable identifier for ties. The proposal is not posted automatically.
Customer-designated intent may select its specified eligible Invoice; third-party
intent remains restricted to its designation.

Allocation is an explicit manual authorized command with an eligible Invoice or
separate Late-payment Charge target and exact amount. Authorized staff confirm/post the
proposal or permitted designation. The server transaction checks Customer/currency/
context eligibility, Payment availability, target outstanding balance, and concurrency.
A Late-payment Charge allocation reduces only that separate Charge and never the source
Invoice. Reversal creates a linked event.

Amended by V1-056 sub-slice 10h-1 (owner answers 3 and 4 to Q-2026-10-06-36): `POST
/payment-allocations/{allocation_id}/reverse` answers 409 (a conflict; the service text is "A
closed Final Settlement changes only through a post-settlement correction") for an allocation
that a closed Final Settlement relied on: one made at or before the closure on an obligation
of its Lease, or one a post-settlement correction wrote. Nothing is written; the allocation
changes only through a correction of that Settlement. Allocations made after the closure are reversed as before.

Amended by V1-056 sub-slice 10h-1 (owner answer (a) to Q-2026-10-17-120 point 2; review round
1): `POST /invoices/{invoice_id}/adjustments` on an Invoice whose Lease has no closed Final
Settlement (none yet, or one still open) also answers 409 (a conflict) when the credit Adjustment
would release an allocation
that a post-settlement correction of another Lease's closed Final Settlement wrote on that Invoice
(the new allocation of a `PAYMENT_MOVE` correction). Nothing is written; that allocation changes
only through a correction of the Settlement whose correction wrote it.

Amended by DL-077 (owner, 2026-10-20): the proposal is ticked on the Receive payment screen and saved with the Payment in one step; this route stays for money that waits and for paying again after a reversal. Not built yet (screen rebuild).

Amended by V1-056 slice 11d (2026-10-24): `POST /payment-allocations/{allocation_id}/reverse`
answers 409 `ALLOCATION_MOVED` and 409 `FINAL_SETTLEMENT_CLOSED` with their codes; see the
paragraph "V1-056 slice 11d" at the end of API-101.

V1-056 slice 11g-4 (DL-088; DL-076 answer 5): for a payer's own Payment that names nothing, `GET /payments/{payment_id}/allocation-proposal` also lists each open late-payment charge of the payer right after its own Invoice. A charge target has `late_payment_charge_id`, `target_customer_id`, `source_invoice_id`, the source Invoice's `due_date`, `issued_at` and `invoice_number`, `sequence`, `outstanding_usd_cents` and `amount_usd_cents`, and no `invoice_id` or `details`; `policy` is then `DUE_ISSUED_NUMBER_ID_CHARGE_AFTER_INVOICE/RENT_SERVICE_SOURCE_ORDER`. Posting the proposal unchanged (`mode: PROPOSAL`) writes the charge part as a direct charge allocation. A named or third-party Payment is proposed as before.

## API-060 — Payment Reversal

`POST /payments/{payment_id}/reverse` requires reason, expected current state,
authorization, and idempotency. It coordinates required downstream reversals,
including Allocations, Credit recognitions/applications, Deposit Receipts,
Deposit Applications/Dispositions, and any required DB-REFUND-002 verified return,
before it sets `REVERSED`; it then recomputes affected balances/statuses without
deleting history.

## API-092 — Receipt and Reprint

- `GET /payments/{payment_id}/receipt`
- `GET /receipts/{receipt_id}`
- `POST /receipts/{receipt_id}/reprints`

A confirmed Payment normally produces exactly one numbered immutable Receipt in the
same transaction. The Receipt acknowledges money received but does not allocate,
settle, recognize Credit, create a Deposit, or otherwise move value.

A reprint uses the same Receipt UUID and Receipt Number and records a separate
append-only reprint event with actor, timestamp, reason, and optional delivery
reference. Reprinting must never create another Payment, Receipt identity, or
money-received event. Payment reversal preserves the original Receipt as historical
evidence.

# 19. Customer Credit Endpoints

## API-061 — Credit Ledger

- `GET /customers/{customer_id}/credits`
- `GET /customer-credits/{credit_id}`
- `GET /customer-credits/{credit_id}/ledger`

Responses distinguish recognized source, available amount, applications,
reversals, and Refund dispositions from Payments and Deposits.

Customer Credit is maintained in USD accounting value. KHR-originated Credit also
preserves original KHR amount and exact receipt exchange-rate evidence; it does
not create a separate KHR Credit balance.

## API-062 — Recognize Credit

`POST /payments/{payment_id}/credit-recognitions` records payer-authorized Customer
Credit from eligible unallocated Payment value. It is not automatic and does not
use Payment Allocation.

`POST /customer-credits/{credit_id}/reverse` (`credits.reverse`) reverses a Customer Credit
whose value is fully available, returning it to its source Payment. Amended by V1-056 slice 7
(owner answers to Q-2026-10-05-18 and Q-2026-10-05-19) and sub-slice 8g (owner answer to
Q-2026-10-06-35): it answers 409 for a Credit released from a moved (`WRONG_UNIT_MOVE`)
allocation unless the Payment is a normal Customer Payment and the Credit belongs to its payer,
and for every Credit that a credit Adjustment released to a Customer other than the payer of its
source Payment. Such a Credit stays with its Customer: it is applied to that Customer's
obligations, or refunded to that Customer through a Refund draft (the `CREDIT_CUSTOMER` variant
when the Customer is not the payer; no route records that variant yet, see API-065). The payer's
own Credits are reversed as before.

## API-063 — Apply and Reverse Credit

- `POST /customer-credits/{id}/applications`
- `POST /credit-applications/{id}/reverse`

Commands require an eligible Invoice or separate Late-payment Charge target, exact
amount/currency, authorization, and idempotency; they revalidate Credit availability
and target outstanding balance transactionally. A Late-payment Charge application
reduces only that separate Charge and never the source Invoice.

Amended by V1-056 sub-slice 8e-2 (owner answer 3 to Q-2026-10-06-32): `POST
/credit-applications/{id}/reverse` answers 409 for a Credit application the Final Settlement
made (its `final_settlement_id` is set); such an application changes only through the
post-settlement corrections (slice 10). Other Credit applications and their reversals are
unchanged. The Final Settlement's Credit applications have no route; only the Settlement
confirm writes them.

Amended by V1-056 sub-slice 10h-1 (owner answers 3 and 4 to Q-2026-10-06-36 and the owner note
of 2026-10-16 on the 10f-2 report): the same route also answers 409 (a conflict; the service text is "A
closed Final Settlement changes only through a post-settlement correction") for an ordinary
Credit application that a closed Final Settlement relied on: one made at or before the
closure on an obligation of its Lease, or one a post-settlement correction wrote, such as an
Adjustment reversal correction's put-back. Nothing is written. Credit applications made after the closure are reversed as
before.

# 20. Refund Endpoints

## API-064 — Refund Resource

- `GET /properties/{property_id}/refunds`
- `GET /refunds/{refund_id}`

A Refund response includes Customer, authoritative source type/id, exact
amount/currency, applicable exchange facts, processed timestamp, actor, authorization,
and correction links. The API does not invent a business Refund status, pending/failed
state, or delivery method that is not defined by the authoritative model.

## API-065 — Create Refund

`POST /refunds` accepts only an API-supported eligible source and amount within
server-calculated availability. Supported source families are limited to those
approved upstream, including:

- Security Deposit received for a Property-caused Reservation cancellation;
- eligible unallocated Payment value;
- eligible Customer Credit;
- a Deposit Refund required by Final Settlement; and
- the active-Lease Pet Deposit Refund exception supported by a qualifying
  DB-LEASE-011 review under API-094.

All Refunds are paid and recorded in USD (DL-060), including eligible KHR-origin
Payment excess and Customer Credit. Use available recorded USD cents, not a KHR
remainder or new exchange rate. Preserve original source KHR/FX evidence for audit;
reject KHR Refund requests. An active-Lease Pet Deposit Refund requires the matching Pet Deposit
source and `pet_refund_review_id` and prohibits a Final Settlement link.

Amended by DL-069 and V1-056 slice 3a (2026-10-04): a Refund is a draft first
(BR-AUTH-010). `POST /refunds` validates and authorizes the request but records nothing
and answers 409 with error code `REFUND_DRAFT_REQUIRED`.

- `POST /refund-drafts` (capability `refunds.create`, `Idempotency-Key` required) takes
  the same body plus `refund_method_id` (an active configured Refund method) and
  `reference_note` (1 to 500 characters). It answers 201 with the pending draft and
  changes no balance and has no `Location` header (the draft read routes come later).
  The draft id is derived from the Property, the preparer, the Refund kind and the key,
  the same scope the one-call create used, so an exact repeat returns the same draft,
  even after the method or source changed, and a changed body with the same key is
  refused.
- `POST /properties/{property_id}/refund-drafts/{draft_id}/confirm` (capability
  `financial.approve`, `Idempotency-Key` required) creates the Refund under every
  earlier Refund rule and answers 201 with the same body as `GET /refunds/{id}`.
  The draft id is the idempotency identity: the `Idempotency-Key` header is required
  like on every financial command but is not stored, and an exact repeat by the same
  approver returns the original body; another approver gets 409. A stale draft is refused
  with 422 and stays pending: its amount is no longer available, its method was turned
  off, the payer of a Payment source now has unpaid Invoices or Late-payment Charges,
  or a Pet Deposit source is no longer qualified; when another confirmation takes the same value at the same moment, the
  loser may get 503 instead and its draft also stays pending.
  Amended by V1-056 sub-slice 8f (2026-10-06): a check violation at confirmation (SQLSTATE 23514;
  for example that competing confirmation, or a Credit Refund draft whose Credit belongs to a
  Customer other than the payer) or a unique violation (23505, a Refund id or number already
  taken) answers 409 instead of 503; the command rolled back and the draft stays pending. A lock
  timeout or a lost reply still answers 503.

V1-056 slice 11c (2026-10-24; owner answer of 2026-10-05: business-state refusals are
conflicts): on `POST /refund-drafts`, both confirm routes (this one and API-101 for drafts of
kind `REFUND`, Reservation outcome drafts included; the Reservation's own confirm route keeps its
422 until a later slice lines it up), `POST /refunds/{id}/verified-returns` and its reverse route, a named business-state
refusal answers 409 with its own code: `REFUND_METHOD_OFF` (at confirm),
`REFUND_AMOUNT_NOT_AVAILABLE`, `REFUND_PAYER_HAS_UNPAID`, `REFUND_PET_SOURCE_NOT_QUALIFIED` (these
four replace the 422 for a stale draft above), `REFUND_RECIPIENT_NOT_SIGNER` (at confirm),
`REFUND_RETURN_THROUGH_CORRECTION` (a Refund paid by a Final Settlement or a post-settlement
correction, or a Reservation Refund, corrected only there, was 422; a closed Final Settlement's
Pet Deposit Refund, was a plain 409), `REFUND_CREDIT_CUSTOMER_ONLY`, `REFUND_CREDIT_FOR_ANOTHER_CUSTOMER` (an
ordinary Credit draft for a Credit released to another Customer; prepare a `CREDIT_CUSTOMER`
draft), `REFUND_DEPOSIT_RECEIPT_REVERSAL_WAITING`, `REFUND_THROUGH_HELD_VALUE_CORRECTION`,
`REFUND_RETURN_REVERSAL_REFUSED` (the money of a return is no longer available to reverse; was
503), `REFUND_RETURN_ALREADY_REVERSED` (was 503), `DRAFT_ALREADY_DECIDED` and
`FINAL_SETTLEMENT_CLOSED`. Bad input answers 422 with its field: on `POST /refund-drafts` a
method that is off or unknown is `REFUND_METHOD_NOT_AVAILABLE` (`refund_method_id`) and a
recipient who is not a Signer is `REFUND_RECIPIENT_NOT_A_SIGNER` (`recipient_customer_id`); a
verified return above what the Refund still holds, or dated before the Refund or in the future, is
`REFUND_RETURN_EVIDENCE_NOT_EXACT` (`returned_amount_minor`, `returned_at`; was 503). "The
Primary Tenant needs no Signer agreement" stays 422. `POST /refund-drafts` also takes
`"variant": "CREDIT_CUSTOMER"` with `source_type` `CREDIT` and no recipient fields: a Credit that
a credit Adjustment released to a Customer other than the payer is refunded to that Customer
(BR-CREDIT-014, `refunds.create`). The draft id is derived from the Property, the preparer, the
variant and the Idempotency-Key, so one key used for an ordinary and a `CREDIT_CUSTOMER` draft
records two drafts, as for a USD and a Pet Deposit draft.

V1-056 slice 11c-1 (2026-10-24; migration `20270209_197`): `GET
/properties/{property_id}/refund-methods` answers the Refund methods a draft may name, turned-off
ones included (`id`, `code`, `display_name`, `active`, `seeded`, `updated_at`; BR-REFUND-014),
to a holder of `refunds.read`, `refunds.create` or `property.manage` of the Property (otherwise
a hidden 404). `GET /refund-sources/{CREDIT|PAYMENT}/{id}` adds `refund_variant`:
`CREDIT_CUSTOMER` for a Credit that a credit Adjustment released to a Customer other than the
payer, whose `recipient_customer_id` is then that Customer (BR-CREDIT-014), and `USD` otherwise.
`GET /refunds/{id}` adds `recovery` to each correction: for a `RECOVERED_BY_CHARGE` correction the
recovery charge (`refund_correction_id`, `refund_id`, `customer_id`, `lease_id` or null,
`amount_usd_cents`, `charge` `LEASE`, `EXTRA_CHARGE` or `NO_LEASE`,
`authorized_nonrecurring_obligation_id`, `invoice_id`, `invoice_number`, `invoice_status`,
`due_date`, `occurred_at`; the Invoice fields come from the charge's Invoice that is not VOID,
else its newest), otherwise null.

V1-056 slice 11h (2026-10-25; migration `20270214_202`; DL-089): the Refund method list is
also read with `settings.manage`. `POST /properties/{property_id}/refund-methods` (body
`refund_method_id`, `code` `^[A-Z][A-Z0-9_]{1,39}$`, `display_name` 1 to 120 characters with no
space at either end) adds a method that starts on (201, the method as in the list); a repeat of
the same body by the same person answers the method as it is now (another person gets
`REFUND_METHOD_ID_REUSED`). `POST
/properties/{property_id}/refund-methods/{refund_method_id}/state` (body `active`, a boolean)
turns a method off or on again (200, the method). Both need `settings.manage` of the Property
(otherwise a hidden 404), the Origin and the CSRF pair, and no Idempotency-Key (the client
chooses the id; a state change is a repeatable set). Refusals (409): `REFUND_METHOD_CODE_USED`
(`code`), `REFUND_METHOD_ID_REUSED` (`refund_method_id`), `REFUND_METHOD_LAST_ON` (at least one
method stays on); a change at the same moment answers 409 and the screen reads the list again.

A Pet Deposit Refund draft may add `recipient_customer_id` (another signed Signer of the
Lease) and `signer_agreement` (the written agreement of all Signers, 1 to 2,000
characters), always together (BR-REFUND-015, slice 3a-2); otherwise the Refund goes to
the Primary Tenant. The Customer Ledger books every Deposit Refund on the Deposit
owner's ledger and names the paid Signer in `source_audit.paid_to_customer_id`.

The Refund methods routes (BR-REFUND-014) and the Reservation Refund drafts come with
later V1-056 slices.

Amended by V1-056 slices 11c-1 and 11h (DL-089): the Refund methods routes are built (the list
read since 11c-1, adding and turning off or on since 11h).

V1-056 sub-slice 8f (BR-CREDIT-014): a Customer Credit that a credit Adjustment released to a
Customer other than the payer is refunded to that Customer through a `CREDIT_CUSTOMER` Refund
draft (service `RefundService.record_credit_customer_draft`, capability `refunds.create`). No
route records that draft yet (slice 11c); `POST /properties/{property_id}/refund-drafts/{draft_id}/confirm`
confirms it like any Refund draft. An ordinary Credit Refund draft for such a Credit is refused at
confirmation with 409.

Amended by V1-056 sub-slice 10h-1b (owner answers (b) to Q-2026-10-19-141 and (a) to
Q-2026-10-19-144): money that a post-settlement correction brought back into a Customer Credit (a
returned Refund recorded by a correction of a closed Final Settlement) leaves only through a
correction of that Settlement (a held-value Refund correction, which pays the Customer's open debt
on the Lease first). `POST /refund-drafts` for a Credit source, and the confirm route for a Credit
or `CREDIT_CUSTOMER` draft, answer 409 when those returns have money left and the amount is more
than the Credit's available value less what they have left; a draft refused at confirmation stays
pending. Money the Credit holds for other reasons stays refundable through these routes. `POST
/customer-credits/{credit_id}/reverse` answers 409 while those returns have money left in the
Credit.

## API-066 — Refund Correction

`POST /refunds/{id}/verified-returns` records only value demonstrably returned after
an erroneous completed Refund under DB-REFUND-002. It requires exact returned
amount/currency, return timestamp/method reference, reason, authorization, actor,
and idempotency. Returns of USD Refunds use exact USD cents, not KHR conversion;
partial returns restore exact positive cents and cumulative value cannot exceed the
Refund. Preserve source KHR/FX history without rewriting it. It creates no collection
right and never erases the original outbound event. Generic PATCH/DELETE is
prohibited.

Amended by V1-056 sub-slice 10c-2b-1 (migration `20261111_107`; owner answer 4 to the
sub-slice 10c-1b review record, an approved tightening): `POST /refunds/{id}/verified-returns`
and `POST /refunds/{id}/verified-returns/{correction_id}/reverse` answer 422 for a Refund paid
by a Final Settlement (sub-slice 8d, already so) or by a post-settlement correction. Such a
Refund is corrected only through a post-settlement `REFUND_RETURN` correction (DB-SETTLE-005,
DB-REFUND-002), which has no HTTP route until slice 11e; a return recorded by a correction is
never reversed.

Amended by V1-056 sub-slice 10c-2b-2b (migration `20261113_109`; owner answer 6 to
Q-2026-10-08-55, an approved tightening): once the Lease's Final Settlement is closed, both routes
answer 409 for a Pet Refund-review Refund (DL-053) of that Lease (the service maps the database's
P5S01 to a conflict). Its return is then recorded only through a `REFUND_RETURN` correction, and a
return recorded with one call before closure is no longer reversed. Before closure both routes
work as before.

# 21. Warning and Termination Records

## API-067 — Lease Violation Warning Records

- `GET /leases/{lease_id}/violation-warnings`
- `POST /leases/{lease_id}/violation-warnings`

Creation records the DB-LEASE-005 Lease-violation warning sequence, violation and
warning dates, description, governing Lease provision, communication evidence, actor,
and idempotency. It creates no fee, Rent-nonpayment milestone, or automatic
termination.

## API-068 — Termination Notices

- `GET /leases/{lease_id}/termination-notices`
- `POST /leases/{lease_id}/termination-notices`

Notice schema captures approved grounds, dates, source/Lease terms, evidence, actor,
and current effect. It does not itself grant unsupported forfeiture or Refund and does
not itself change Lease status.

## API-095 — Rent Nonpayment Cases and Events

- `GET /leases/{lease_id}/rent-nonpayment-cases`
- `POST /leases/{lease_id}/rent-nonpayment-cases`
- `GET /rent-nonpayment-cases/{case_id}`
- `GET /rent-nonpayment-cases/{case_id}/events`
- `POST /rent-nonpayment-cases/{case_id}/events`

Rent nonpayment is tracked separately from Lease-violation warnings. Opening a case is
an authorized/idempotent action tied to one applicable issued, non-VOID Rent Invoice
line for the same Lease and financially responsible Customer. The server preserves the
source Invoice, Rent line, Customer, Lease, and Due Date snapshot and must not open a
case from the total balance of a mixed-category Invoice.

The event command permits only the authoritative event kinds and prerequisites:
`TWENTY_DAY_WARNING`, `THIRTY_DAY_SERIOUS_DEFAULT`, `CURE`, and
`AUTHORIZED_FOLLOW_UP`. Posting rechecks remaining Rent from authoritative financial
applications. A 20-day warning requires positive remaining Rent and its required
Notice/document reference; a 30-day Serious Nonpayment Default requires positive
remaining Rent at the approved milestone. Cure and authorized follow-up preserve
history.

No Rent-nonpayment event automatically terminates the Lease, ends Occupancy, moves out
the Customer, changes Unit status, or creates Final Settlement. Any termination remains
a separate authorized Lease action.

Cases open only for recurring Rent Invoices. The case snapshot exposes `nonpayment_day_one`, the current day number and each
milestone date. A case opened after day 20 or day 30 is flagged for immediate staff
alert. Posting uses the day count under BR-LEASE-026.

# 22. Move-out and Final Settlement Endpoints

## API-069 — Move-out Record

- `GET /leases/{lease_id}/move-out`
- `POST /leases/{lease_id}/move-out`

The command records actual Move-out Date, Occupancy closure, final Readings,
inspection/final-charge source references, reason/evidence, and audit event. It does
not assert financial closure. Final validated Readings create the final Utility Invoice
off-cycle without duplicating a monthly-run period.

## API-070 — Final Settlement Resource

- `GET /properties/{property_id}/final-settlements`
- `POST /leases/{lease_id}/final-settlement`
- `GET /final-settlements/{settlement_id}`

Exactly one Final Settlement may exist per terminated Lease. Creation is idempotent
and transactionally unique. A closed resource exposes immutable
`closing_balance_due_usd_cents` separately from any later linked corrections and
current corrected financial position.

## API-071 — Settlement Preview

`POST /final-settlements/{id}/preview` returns server-calculated obligations,
Adjustments, applications, separate Security/Pet Deposit availability and proposed
dispositions, Customer Credit, resulting receivable/refundable amounts, and
blocking issues. Preview does not close or mutate the Settlement.

The calculation order follows the explicit DB-DEP-005 stages: finalize valid
charges; apply authorized Customer Credit first; apply Pet Deposit to authorized
pet-related Invoice lines under `PET_RELATED_FIRST`; permit explicitly authorized
Security Deposit applications under `SECURITY_EXPLICIT`; then permit any remaining
Pet Deposit to be explicitly applied to any valid remaining Settlement Invoice line
under `PET_REMAINDER_EXPLICIT`; record the remaining Customer balance; and explicitly
Refund remaining refundable Deposit balances.

Every Deposit target and amount is explicitly authorized. Payment FIFO and any
inferred Deposit-type FIFO or oldest-Due ordering are not reused for Deposit
applications. Every application, disposition, and Refund remains a separate event.

As built in V1-056 sub-slice 8b (migration `20261024_89`): the preview contents exist as a
service read, `FinalSettlementReadService.preview` over `app.final_settlement_preview`
(runtime role), for holders of `final_settlements.prepare` or `financial.approve` on the
Property; docs/004 DB-SETTLE-001 lists its contents and blocking issues. It proposes no
amounts: each DL-032 step shows what it may use. A pending draft blocks for every reader, but
its id, kind and variant are shown only to a `financial.approve` holder or a holder of the
draft's prepare capability. The route is built in slice 11e.

## API-072 — Settlement Actions

- `POST /final-settlements/{id}/deposit-applications`
- `POST /deposit-applications/{id}/reverse`
- `POST /final-settlements/{id}/deposit-refunds`
- `POST /final-settlements/{id}/close`
- `POST /final-settlements/{id}/corrections` to link an approved typed corrective
  event under DB-SETTLE-003

Each action is explicit, authorized, idempotent, and append-only. Close revalidates
all sources in one transaction, returns the immutable
`closing_balance_due_usd_cents` snapshot, and does not convert Deposits into ordinary
Invoice Credit before Settlement.

Amended by V1-056 sub-slice 8e-1 (owner answer 7 to Q-2026-10-05-20; migration
`20261027_92`): once a Lease's Final Settlement is closed, these existing routes answer 409
(conflict) for that Lease's obligations until the post-settlement corrections exist (slice
10): `POST /invoices/{invoice_id}/void`, `POST /invoices/{invoice_id}/adjustments`,
`POST /invoices/{invoice_id}/late-payment-decision`,
`POST /late-payment-charges/{charge_id}/corrections`,
`POST /properties/{property_id}/lease-terminations/{termination_event_id}/unpaid-initial-never-moved-in`
and `.../unpaid-initial-moved-in-credit`, and every route that adds a charge or an Invoice
with the Lease: `POST /properties/{property_id}/one-time-charges` (with the Lease),
`POST /properties/{property_id}/invoices` (a draft of a Lease charge),
`PATCH /invoices/{invoice_id}` (a draft corrected onto a charge of the Lease),
`POST /invoices/{invoice_id}/issue` (a draft with the Lease),
`POST /properties/{property_id}/leases/{lease_id}/final-utility-invoice` and
`.../utility-catch-up-invoice`. A draft with the Lease stays un-VOIDable: a draft that has a Due
Date gets 409, and a one-time-charge draft, which has no Due Date until it is issued, already
gets 422 from the earlier rule `invoices_due_date_issued`, open or closed. A scheduled Rent or
Utility run (`POST /properties/{property_id}/billing-runs/rent`
and `.../utilities`) records the Lease's item as `SKIPPED` with the diagnostic
`FINAL_SETTLEMENT_CLOSED` and can still succeed (owner answer 1 to Q-2026-10-06-33). Payments,
allocations, Payment reversals, Credit applications and their reversals stay open, except the
reversal of a Credit application the Final Settlement made (409, sub-slice 8e-2, API-063).

As built in V1-056 sub-slice 8e-3 (migration `20261029_94`): the close action exists as a service,
`FinalSettlementService.confirm(property, draft)` over `app.confirm_final_settlement_draft`, for a
`financial.approve` holder only. Under the draft-then-confirm model (BR-AUTH-010) one confirm of
the Settlement draft writes its Credit applications, Deposit applications and Deposit Refunds,
the closure snapshots and the closing balance, and closes the Settlement in one transaction; the
separate deposit-application and deposit-refund actions above are not built. A draft whose sources
changed is refused as stale (409) and stays pending; a blocking issue, a pending draft on a
Settlement source, a decided draft or a closed Settlement is 409; a missing or inactive approver
is 403; an exact repeat by the same approver returns the stored result. The route is built in
slice 11e.

V1-056 slice 11e-1 (2026-10-24; no migration; BR-SETTLE-001 to BR-SETTLE-017, BR-REFUND-014,
BR-REFUND-015, BR-CREDIT-006, BR-CREDIT-008, BR-DEP-027, BR-AUTH-010): the
Final Settlement routes. Decided by Claude under the owner's 2026-10-23 22:30 rule: the routes
carry the Property in the path like the other draft routes, and the preview is a `GET` because
it writes nothing; the list and the single read of API-070 and the separate deposit-application
and deposit-refund actions of API-072 are not built (the Settlement draft and its confirm replace
the actions; the start route returns the Lease's Settlement).

- `POST /properties/{property_id}/leases/{lease_id}/final-settlement`
  (`final_settlements.prepare`; others a hidden 404; Origin, CSRF, `Idempotency-Key`; a JSON
  body, sent as `{}` and ignored) opens the one Final Settlement of a terminated Lease, or returns
  the one that exists, open or closed: 201 when this call opened it (`created` true), else 200,
  with `id`, `lease_id`, `created`, `closed`, `closing_balance_due_usd_cents` and the dates.
- `GET /properties/{property_id}/final-settlements/{settlement_id}/preview`
  (`final_settlements.prepare` or `financial.approve`) answers the DB-SETTLE-001 preview:
  `settlement`, `lease`, `customers`, `deposits`, `steps`, `open_total_usd_cents`,
  `blocking_issues`, `information`, `ready` and `previewed_at`.
- `POST /properties/{property_id}/final-settlements/{settlement_id}/drafts`
  (`final_settlements.prepare`; Origin, CSRF, `Idempotency-Key`) records the Settlement draft and answers 201
  with the draft (kind and variant `FINAL_SETTLEMENT`). Body: `reason` (1 to 1,000 characters),
  `steps` (up to 200, in the DL-032 order; each `CUSTOMER_CREDIT` with `customer_credit_id`,
  `target_kind` `INVOICE_LINE` or `LATE_PAYMENT_CHARGE`, `target_id`, `amount_usd_cents` and an
  optional `customer_designation`; `PET_DEPOSIT_PET_DAMAGE`, `SECURITY_DEPOSIT` or
  `PET_DEPOSIT_REMAINDER` with `deposit_id`, `target_kind`, `target_id` and `amount_usd_cents`;
  `DEPOSIT_REFUNDS` with `deposit_id`, `amount_usd_cents`, `refund_method_id`, `reference_note`,
  `recipient_customer_id` and an optional `signer_agreement`) and an optional `pet_remainder`
  (`basis` `CUSTOMER_CHOICE` or `STAFF_REASON`, `staff_reason`, and `customer_choice` with
  `CUSTOMER_CHOICE` only). A `financial.approve` holder confirms it through
  `POST /properties/{property_id}/financial-drafts/{draft_id}/confirm`, which closes the
  Settlement in one transaction.
- Named refusals: 409 `FINAL_SETTLEMENT_LEASE_NOT_TERMINATED`, `FINAL_SETTLEMENT_RECORD_UNCLEAR`,
  `FINAL_SETTLEMENT_BLOCKING_ISSUES` (a closed Settlement is the preview's `SETTLEMENT_CLOSED`
  issue), `FINAL_SETTLEMENT_CLOSED` and, at record, `FINAL_SETTLEMENT_DRAFT_WAITING`; 422 on
  `steps` for a step that breaks a DL-032 rule (`FINAL_SETTLEMENT_STEP_ORDER`,
  `_CREDIT_OTHER_CUSTOMER`, `_CREDIT_FIRST`, `_CREDIT_RENT_FIRST`, `_CREDIT_NOT_AVAILABLE`,
  `_CREDIT_OVER`, `_DEPOSIT_NOT_USABLE`, `_DEPOSIT_WRONG_STEP`, `_DEPOSIT_OVER`,
  `_OBLIGATION_OVER`, `_TARGET_NOT_OPEN`, `_PET_DAMAGE_ONLY`, `_PET_DAMAGE_FIRST`,
  `_PET_REMAINDER_AFTER_SECURITY`, `_DEPOSIT_LEFT`, `_REFUND_WHILE_DEBT`,
  `_ONE_REFUND_PER_DEPOSIT`, `_REFUND_RECIPIENT`, `_SIGNER_AGREEMENT`,
  `_NO_AGREEMENT_FOR_PRIMARY`, `_REFUND_METHOD_OFF`, `_TOO_LARGE`) and on `pet_remainder`
  (`_PET_REMAINDER_CUSTOMER_ONLY`, `_PET_REMAINDER_REASON`, `_PET_REMAINDER_NO_STEP`). At the
  confirm the state codes apply; a step the plan now refuses, or a stale draft, answers 409
  `DRAFT_OUT_OF_DATE` (the draft stays pending: reject it and prepare a new one).

V1-056 slice 11e-2 (2026-10-24; no migration; BR-SETTLE-012, BR-SETTLE-013, BR-SETTLE-016,
BR-INV-044, BR-PAY-042, BR-CREDIT-006, BR-AUTH-010): the post-settlement correction routes with
no DL-032 plan, and the plain Adjustment reversal draft. Decided by Claude under the owner's
2026-10-23 22:30 rule: one route per correction kind under the Settlement, so each form is checked
on its own fields; the corrections with a DL-032 plan for released value (Refund, Late-payment
Charge Refund, pet classification, Refund return, held value Refund, forfeiture reversal, return
reversal, Deposit receipt correction) follow in slice 11e-3.

- Every route below is `POST`, needs Origin, CSRF and an `Idempotency-Key`, and answers 201 with
  the recorded pending draft; an exact repeat returns it, and a reused key with another body is
  409 `IDEMPOTENCY_KEY_REUSED`. The correction routes need `final_settlements.prepare` in the
  Property (others a hidden 404) and record a `SETTLEMENT_CORRECTION` draft; a `financial.approve`
  holder confirms it through `POST /properties/{property_id}/financial-drafts/{draft_id}/confirm`.
  Base: `/properties/{property_id}/final-settlements/{settlement_id}/corrections`.
- `/extra-charges` (variant `EXTRA_CHARGE`): `category` `MISCELLANEOUS_CHARGES` or
  `DAMAGE_CHARGES`, `description`, `amount_usd_cents`, `evidence_reference`, `reason` (up to 500
  characters), and the optional `inspection_damage_finding_id` (a Damage charge),
  `corrects_invoice_id`, `due_date` and `due_date_reason` (the last two together).
- `/charge-reductions` (variant `CHARGE_REDUCTION`): `invoice_id`, `invoice_line_id`,
  `amount_usd_cents`, `reason` (up to 500 characters).
- `/late-charge-reductions` (variant `CHARGE_REDUCTION`, target kind `LATE_PAYMENT_CHARGE`):
  `late_payment_charge_id`, `amount_usd_cents`, `reason`.
- `/returned-payments` (variant `RETURNED_PAYMENT`): `payment_id`, `reason`,
  `evidence_reference`.
- `/payment-moves` (variant `PAYMENT_MOVE`): `allocation_id`, `target_invoice_id`, `reason`,
  `source_acknowledgement`, `target_acknowledgement`.
- `/adjustment-reversals` (variant `ADJUSTMENT_REVERSAL`): `adjustment_id`, `reason`.
- `POST /properties/{property_id}/invoice-adjustments/{adjustment_id}/reversal-drafts`
  (`invoices.adjust`; body `reason`) records the plain `ADJUSTMENT_REVERSAL` draft of a credit
  Adjustment recorded by mistake before closure; a `financial.approve` holder confirms it through
  the same shared route.
- A Damage charge without its finding, a Miscellaneous charge with one, or a Due Date override
  without its reason (or the reverse) answers 422 on that field.
- Named refusals: 409 `CORRECTION_SETTLEMENT_NOT_CLOSED` on every correction route; 422 on the
  field that chose a wrong record (`CORRECTION_DAMAGE_TO_PRIMARY`, `_CORRECTED_INVOICE_NOT_OF_SETTLEMENT`,
  `_FINDING_NOT_CURRENT`, `_DUE_DATE_BEFORE_ISSUE`, `_REDUCED_INVOICE_NOT_OF_SETTLEMENT`,
  `_INVOICE_LINE_NOT_FOUND`, `_LATE_CHARGE_NOT_OF_SETTLEMENT`, `RETURNED_PAYMENT_NOT_FOUND`,
  `MOVE_CORRECTION_NOT_OF_SETTLEMENT`, `_ALLOCATION_NOT_FOUND`,
  `ADJUSTMENT_REVERSAL_NOT_OF_SETTLEMENT`, `ADJUSTMENT_REVERSAL_CORRECTION_NOT_FOUND`, and
  `PAYMENT_MOVE_TARGET_NOT_FOUND`, `_TARGET_SAME_UNIT`, `_TARGET_NOTHING_OWED` and `_TOO_LARGE` of
  slice 11d); 409 for a business state (`CORRECTION_FINDING_BILLED`,
  `_PAID_BY_DEPOSIT`, `_WOULD_RELEASE_PAID`, the `RETURNED_PAYMENT_` and `MOVE_CORRECTION_` state
  codes, the Payment return and Payment move state codes of slices 11c-3 and 11d, and
  `ADJUSTMENT_REVERSAL_NOT_CREDIT`, `_ALREADY_REVERSED`, `_INVOICE_NOT_ISSUED`,
  `_BY_RESOLUTION`, `_OF_CORRECTION`, `_THROUGH_CORRECTION`, `_ONLY_CHARGE_REDUCTION`,
  `_DRAFT_WAITING`, `_TOO_LARGE`). No answer shows database text.

V1-056 slice 11e-3 (2026-10-25; no migration; BR-SETTLE-008, BR-SETTLE-012, BR-SETTLE-013,
BR-REFUND-014, BR-CREDIT-008, BR-DEP-027, BR-AUTH-010): the post-settlement correction routes
with a DL-032 plan for the value they release, the Deposit receipt correction and the return
reversal. Decided by Claude under the owner's 2026-10-23 22:30 rule: one route per correction
kind, as in slice 11e-2; the plan uses the Final Settlement `steps` and `pet_remainder` format of
slice 11e-1, and both may be left out when the released value pays nothing.

- Every route is `POST` under
  `/properties/{property_id}/final-settlements/{settlement_id}/corrections`, needs
  `final_settlements.prepare` (others a hidden 404), Origin, CSRF and an `Idempotency-Key`, and
  answers 201 with the pending `SETTLEMENT_CORRECTION` draft. Every text of the correction form is
  1 to 500 characters; the plan's `staff_reason` is up to 1000 and its `customer_choice` and
  `signer_agreement` up to 2000, as in slice 11e-1.
  A `financial.approve` holder confirms it through the shared draft confirm.
- `/refunds` (variant `REFUND`): `invoice_id`, `invoice_line_id`, `amount_usd_cents`,
  `refund_method_id`, `reference_note`, `reason`, plan.
- `/late-charge-refunds` (variant `REFUND`, target kind `LATE_PAYMENT_CHARGE`):
  `late_payment_charge_id`, `amount_usd_cents`, `refund_method_id`, `reference_note`, `reason`,
  plan.
- `/pet-classifications` (variant `PET_DAMAGE_RECLASSIFICATION`): `invoice_id`,
  `invoice_line_id`, `pet_related` (true or false), `evidence_reference`, `reason`, plan.
- `/refund-returns` (variant `REFUND_RETURN`): `refund_id`, `returned_amount_usd_cents`,
  `returned_at` (an instant with its offset), `return_method_reference`, `evidence_reference`,
  `reason`, optional `new_refund_method_id` with `new_refund_reference_note` (together), plan.
- `/held-value-refunds` (variant `HELD_VALUE_REFUND`): `held_from_correction_id`, `reason`,
  `new_refund_method_id`, `new_refund_reference_note`, plan.
- `/forfeiture-reversals` (variant `FORFEITURE_REVERSAL`): `deposit_disposition_id`, `reason`,
  `evidence_reference`, `refund_method_id`, `reference_note`, plan.
- `/deposit-receipt-corrections` (variant `DEPOSIT_RECEIPT_CORRECTION`): `deposit_receipt_id`,
  `reason`, `evidence_reference`, optional `receipts` (at most 2, each `deposit_id`,
  `amount_usd_cents` and an optional `outcome` `DL_032` or `FORFEIT` with `outcome_reason`; each
  into a different Deposit), plan only with a new receipt.
- `/return-reversals` (variant `RETURN_REVERSAL`): `earlier_correction_id`, `reason`,
  `evidence_reference`; no plan.
- Named refusals: every plan route answers the closed-Settlement code, 409
  `CORRECTION_SOURCE_DRAFT_WAITING`, the Final Settlement state codes and the slice 11e-1 plan
  codes on `steps` or `pet_remainder`, plus 422 `CORRECTION_ONE_REFUND_CHOICE`,
  `_RETURNED_MONEY_PAYS_DEBT`, `_RELEASED_CREDIT_FIRST`, `_HELD_VALUE_OVER` (on `steps`),
  `_NEW_CUSTOMER_CHOICE` (on `pet_remainder`) and 409 `_STEP_OUTSIDE_SETTLEMENT`. An inactive or
  unknown Refund method is 422 `CORRECTION_REFUND_METHOD_OFF` on `refund_method_id` (refunds,
  late-charge refunds, forfeiture reversals), `CORRECTION_NEW_REFUND_METHOD_OFF` on
  `new_refund_method_id` (refund returns, held-value refunds), or the slice 11e-1
  `FINAL_SETTLEMENT_REFUND_METHOD_OFF` on `steps` where only a step names it. On
  `/deposit-receipt-corrections` a new receipt into a Deposit of no Lease or of another Lease
  that is not terminated is 422 `RECEIPT_CORRECTION_DEPOSIT_NOT_OF_LEASE` on `receipts`. Each
  route adds its own: 422 on the field that chose an unknown or unfit record (`CORRECTION_REFUND_OVER_CHARGE`, `_REFUND_OVER_PAID`,
  `_REFUNDED_LATE_CHARGE_NOT_OF_SETTLEMENT`, `_PET_LINE_NOT_DAMAGE`, `_PET_SAME`,
  `_REFUND_NOT_FOUND`, `_REFUND_NOT_RETURNABLE`, `_RETURN_OVER_REFUND`, `_RETURN_DATE`,
  `_RETURN_ONLY_NO_STEPS`, `_HELD_FROM_NOT_FOUND`, `_HELD_FROM_NOT_RETURN_ONLY`,
  `_FORFEITURE_NOT_FOUND`, the `RECEIPT_CORRECTION_` codes on `deposit_receipt_id`, `receipts`
  or `steps`, `RETURN_REVERSAL_NOT_FOUND`) and 409 for a business state
  (`CORRECTION_REFUND_RELEASES_NOTHING`, `_RETURNED_DEPOSIT_OFF_PATH`,
  `_HELD_VALUE_NOTHING_LEFT`, `_FORFEITURE_ALREADY_REVERSED`, `_FORFEITURE_OTHER_ACTIVE`, the
  other `RECEIPT_CORRECTION_` and `RETURN_REVERSAL_` codes; a return reversal the database cannot
  follow yet is `RETURN_REVERSAL_WAITS_FOR_OWNER`). At the shared confirm a correction draft
  keeps the plain answers for now. No answer shows database text.

V1-056 slice 11f (2026-10-25; no migration; no new route): the browser client of the slice 11
routes, `frontend/src/settlementClient.ts`, with the request forms in
`frontend/src/settlementForms.ts`, written from the routes' request models (a backend test fails
when they differ). Every command sends its `X-CSRF-Token` and, where the route takes one, its
`Idempotency-Key` (the cleaning rate and charge use their own `rate_id` and `charge_id`); the
hand-back resolution sends the Invoice version as `If-Match`; a financial draft, Final
Settlement or correction route also sends `X-Financial-Property-ID`. A refusal reaches the screen
with its `code`, `message`, `fields` (without the `body.` prefix of a plain form check),
`rule_ids` and `current_version`; a 503 or a network failure is a separate unavailable error.
Decided by Claude under the owner's 2026-10-23 22:30 rule: one new client module for the slice,
so the screen work changes no existing client.

# 23. Audit Endpoints

## API-073 — Record Audit

`GET /{resource-family}/{id}/audit-events` returns a paginated authorized event
timeline with actor/system, action, timestamp, prior/resulting state or linked
source, reason, and correlation identifier.

## API-074 — Global Audit Search

`GET /properties/{property_id}/audit-events` supports bounded filters for date,
actor, action, resource type/id, Customer, Unit, Lease, and correlation identifier.
Audit view/export requires dedicated capability.

Amended by DL-072 (owner, 2026-10-04): every audit search writes an audit event. By default the Owner and the Manager may search and export audit; Staff may not (configurable role bundles, OOD-SEC-001). Record timelines (API-073) keep today's access. Not built yet (V1-057).

## API-075 — No Audit Mutation

No ordinary API endpoint updates or deletes audit events.

# 24. Reports and Dashboard Endpoints

## API-076 — Dashboard

`GET /properties/{property_id}/dashboard` returns server-calculated, as-of-stamped,
currency-separated operational summaries derived from authoritative records. It
must not create new statuses or aggregate USD and KHR without an explicit approved
basis.

Amended by DL-072 (owner, 2026-10-04): totals are in USD, the accounting currency of DL-060, which is the approved basis; KHR is never added to USD. The cards are those of UI-023 as amended by DL-072, each with its as-of time and a link to its filtered list. Not built yet (V1-057).

## API-077 — Reports

`GET /properties/{property_id}/reports/{report_name}` supports only documented
reports from `003`/`006`, bounded parameters, pagination or controlled export, and
source/as-of metadata.

Amended by DL-072 (owner, 2026-10-04; answer 10 changed 2026-10-20 and 2026-10-21): all 9 reports of UI-088 are supported, with the overdue groups and the monthly money-collected summary of DL-072. Staff may read only reports 1, 2 and 7, without money totals. Ordinary report views write no audit event. Not built yet (V1-057).

## API-078 — Export Jobs

Large authorized exports may use:

- `POST /properties/{property_id}/exports`
- `GET /exports/{export_id}`

Jobs are scoped, audited, expire from temporary storage, and never expose secrets
or data outside authorization.

Amended by DL-072 (owner, 2026-10-04): exports are CSV only. A small export downloads at once and is not stored on the server; an export job is kept 24 hours and then deleted. Every export writes an audit event, and an audit export's event holds the SHA-256 fingerprint of its file. A Customer appears only with name, Unit and phone number. Not built yet (V1-057).

# 25. Administration Endpoints

## API-079 — Accounts

- `GET /properties/{property_id}/users`
- `POST /properties/{property_id}/users`
- `PATCH /users/{user_id}` for approved profile/disable actions
- `POST /users/{user_id}/revoke-sessions`

Account and session actions require administration capabilities and audit events.
Credentials are never returned.

Amended by DL-081 (owner answer (a) to Q-2026-10-21-152; login sub-slice L2b-1): `POST /properties/{property_id}/users` takes `account_class` (`manager` or `staff`) instead of `mfa_policy_class`; the class sets the MFA policy (Manager `required`, Staff `optional`) and the default role bundle, and no route creates an Owner account. Each account in a response also shows its `account_class` (`owner`, `manager`, `staff`, or null for an old account without a class) and `settings_access` (whether a Settings access grant is recorded; the Owner always has it).

## API-096 — Login, MFA, and Logout

The authentication surface supports local username/password login, standards-based MFA
enrollment and challenge, recovery-code challenge, logout, and authenticated session
inspection. Owner and Manager cannot obtain normal privileged access before required MFA
enrollment/challenge; Staff may authenticate without MFA unless enabled for that
account. Responses, timing, and rate limits resist guessing and account enumeration.
SMS authentication or recovery is not exposed.

Amended by DL-081 (login sub-slice L2c, owner answer (a) to Q-2026-10-22-169): sign-in looks a username up by the rule account creation uses: U+200B removed, NFC, spaces at either end trimmed, lower case; the wrong-try count uses the same form, so every spelling of one username is counted as one.

Amended by DL-081 (login sub-slice L2d, owner answer (a) to Q-2026-10-22-170): the sign-in lookup and the wrong-try count also tidy the typed username as account creation does: every space separator becomes an ordinary space, a run of spaces becomes one, and spaces at either end are removed, so "Sokha  Chan" typed with two spaces finds the account "sokha chan".

Amended by DL-081 (login sub-slice L3a-1): sign-in, the session read and sign-out on PostgreSQL are described under API-097.

Amended by DL-081 (login sub-slice L3b, the owner's wait rule): wrong sign-in tries are counted in the database (DB-AUTH-011). After 3 wrong tries in a row for one username the person waits 5 minutes; after 5 in a row 15 minutes; after that every 2 more wrong tries mean another 15-minute wait, until a correct sign-in clears the count. A source address with 20 wrong tries in 15 minutes waits 15 minutes. During a wait `POST /api/v1/auth/login` answers 429 with the generic `RATE_LIMITED` body, `Retry-After` (the seconds left) and `Cache-Control: no-store`, without checking the password; the try that starts a wait gets the same answer. The answers are the same whether or not the username exists. A correct password of an account that needs MFA neither adds to nor clears the count; it is checked again for a wait (under the locks of the count) before the MFA step, and the completed MFA challenge clears the count (L3c).

Amended by DL-081 (login sub-slice L3c-2a): an account that needs MFA (MFA policy `required`, or an active sign-in code) gets `mfa_required` when it has a sign-in code and `mfa_enrollment_required` when it has none (enrollment comes with L3c-2b), with a stored challenge and the `__Host-prm_preauth` cookie for 5 minutes. `POST /api/v1/auth/mfa/challenge` with `totp` checks the code for the current or the previous 30-second step of the database clock, each step once; a wrong code is a wrong try (401, or 429 with `Retry-After` when it starts a wait, and during a wait); the right code makes a session with `mfa_assurance` `totp`, clears the wrong-try count and answers no-store. A password change, a sign-in code reset or a disabled account after the password check refuses the code. Without the protection key file, and for `recovery_code` until L3c-2c, the challenge answers 503.

Amended by DL-081 (login sub-slice L3c-2b): with the `__Host-prm_preauth` cookie of `mfa_enrollment_required`, `POST /api/v1/auth/mfa/enrollment` sets up a new sign-in code once per sign-in and answers its standard `otpauth://totp/` link (issuer "Property Rental", the username as the account name, SHA-1, 6 digits, 30 seconds) with `Cache-Control: no-store`; a second call with the same cookie, an expired or used cookie, or an account that no longer needs a sign-in code answers 401, and a wait for wrong tries 429 with `Retry-After`. A later sign-in's set-up turns off a code that was never confirmed; a sign-in from before a password change sets up nothing (401). `POST /api/v1/auth/mfa/enrollment/confirm` checks the first code as the challenge does (the current or the previous 30-second step of the database clock; a wrong code is a wrong try, 401, or 429 when it starts a wait, and during a wait); the right code activates the sign-in code, makes a session with `mfa_assurance` `totp`, clears the wrong-try count, sets the session cookie, removes the pre-authentication cookie and answers no-store. A password change, a sign-in code reset, MFA no longer `required` or a disabled account after the password check refuses the code. Without the protection key file both answer 503. A session's `mfa_assurance` is `none` once the sign-in code it was proven with is turned off.

Amended by DL-081 (login sub-slice L6, Q-2026-10-24-187): the answer of `POST /api/v1/auth/mfa/enrollment` also holds `qr_code_svg`, the same `otpauth://totp/` link as an SVG QR code made on the server with the `qrcode` library (dark squares on a white background with a four-module quiet zone; no script, no link, no XML header), for the set-up screen to show as a picture. It is part of the one-time material (`no-store`). The issuer of the link is now "CHETANA Residence" (was "Property Rental"), so the authenticator app names the code as the sign-in screen does.

Amended by DL-081 (login sub-slice L6, Q-2026-10-24-187 point 18): `GET /api/v1/auth/recovery-codes` (the session cookie only; a read, so no Origin or CSRF pair) answers the account's live recovery-code set without its codes, `{"set_id", "created_at", "made_by", "usable_count"}` (`made_by` is `issued`, `regenerated` or `other`, the last for the server set-up and older services; `usable_count` counts the codes neither consumed nor invalidated), or `data: null` when the account has none, with `Cache-Control: no-store`. Any live session of the account may read it (a recovery-code session too); no session, or one that ended, answers 401. The id is the `prior_set_id` a regeneration names, so a person can replace a set whose codes they never saw. A client must not treat a 401 of the recovery-code routes as signed out.

Amended by DL-081 (login sub-slice L7a, Q-2026-10-24-188): a new recovery code is 12 symbols of Crockford's Base32 (digits and capital letters without I, L, O and U) from 60 random bits, shown as three groups of four such as `7KQ4-M2XD-9PRT`, in the answers of `POST /api/v1/auth/recovery-codes` and `POST /api/v1/auth/recovery-codes/regenerate` and in the bootstrap. Wherever a recovery code is checked (`POST /api/v1/auth/mfa/challenge`; the reauthentication factor still takes only `totp`), white space around it is removed; a code of this shape in ASCII letters and digits is then read in any case, with or without dashes and ASCII spaces, and with I or L read as 1 and O as 0; it is hashed in the same form. Any other text (such as a code made before L7a) is checked as given.

Amended by DL-081 (login sub-slice L3c-2c-2): `POST /api/v1/auth/mfa/challenge` also takes `recovery_code` (no protection key needed): the code, with white space around it removed, is compared with every usable code of the account (its live set, made no earlier than the sign-in code the challenge was made for, neither consumed nor invalidated, so codes from before a sign-in code reset never come back); a wrong code is a wrong try (kind `recovery_code`; 401, or 429 when it starts a wait, and during a wait); a try while another recovery-code try of the account, or a making of its codes, is running answers 401 without being checked or counted. The right code is consumed through the audited account recovery (every other session of the account is revoked), and the session has `mfa_assurance` `recovery_code`; it counts only while the sign-in code the challenge was made for is active (a new sign-in code after a reset does not bring it back) and while the code's set is live (replacing the codes ends it). A wait that starts during the try is met before the codes are checked, and a wrong code is counted before the next try of the account can start. A recovery code does not complete a set-up (`mfa_enrollment_required`), and a recovery-code session cannot get or replace recovery codes.

Amended by DL-081 (login sub-slice L4, Q-2026-10-24-185, decided by Claude under the owner's 2026-10-23 22:30 rule): a sign-in with a one-time password in its 24 hours answers `password_change_required` with the `__Host-prm_preauth` cookie for 10 minutes and no session. `POST /api/v1/auth/password-change` (Origin, the CSRF pair and that cookie; body `{"new_password"}`, at most 256 characters) sets the new password, ends every session of the account and continues as a sign-in: `mfa_required` or `mfa_enrollment_required` where MFA is needed, else the session. A new password against the rule answers `422 PASSWORD_RULE` ("Choose a password of 15 to 128 characters that is not a common password, not your name and not the one-time password.") and keeps the step open; the one-time password in another case or without its hyphens counts as the same. An ended, used or replaced step answers the generic `401`; a sign-in wait `429` with `Retry-After`; an unavailable database `503`. A one-time password after its 24 hours gets the generic sign-in refusal and counts as one wrong try. No answer or log holds a password.

## API-097 — Session Lifetime

Browser sessions enforce a 30-minute inactivity timeout and a 24-hour absolute lifetime.
Activity cannot extend the absolute expiry. Logout, password/MFA recovery, account
disablement, and material privilege reduction revoke applicable sessions. High-risk
administration may require recent password authentication or an additional factor.

Amended by DL-081 (login sub-slice L3a-1): `POST /auth/login`, `GET /auth/session` and `POST /auth/logout` run on PostgreSQL when `APP_DATABASE_URL` is set. The sign-in username is at most 128 characters. Every refused sign-in (wrong password, unknown, disabled or unclassified account, the per-process flood guard) answers the same `401`. An account whose MFA policy is `required` answers the phase `mfa_required` with no session; the MFA challenge, enrollment, reauthentication and recovery-code routes answer `503` (after their Origin, CSRF and cookie checks) until login sub-slices L3c and L3d. Any other account gets a session: the `__Host-prm_session` cookie holds a random token whose sha256 digest is the only thing stored. The session answer adds `display_name`. `GET /auth/session` answers only a live session (not revoked, before both expiries by the database clock, of an active classified account whose MFA policy is `optional` until login sub-slice L3c) and does not count as activity; `POST /auth/logout` revokes the session when it is not revoked and before both expiries, whatever the account's state (reason `logout`), and clears the cookies.

Amended by DL-081 (login sub-slice L3a-2): when `APP_DATABASE_URL` is set, every protected route takes its actor from the `__Host-prm_session` cookie: a live session (as for `GET /auth/session`) records its activity, which moves the idle expiry on (never past the absolute one), and the account's capabilities are read fresh from the database on every request, so a removed bundle or capability counts at the next request. No cookie or no live session answers `401`; a database error answers `503`. A revocation (sign-out or an Owner's change) that meets an activity a parallel request committed later records the activity's time and still ends the session (migration `20270127_184`).

Amended by DL-081 (login sub-slice L3d-1, owner answer (a) to Q-2026-10-21-157): `POST /api/v1/auth/reauthenticate` takes the password again and, for an account that needs MFA, a sign-in code (`second_factor` with `totp`; a recovery code is refused, as the owner's answer names the sign-in code); an account that needs no MFA gives the password alone. One reauthentication of an account runs at a time (another answers 401 at once, unchecked and uncounted). A wait for wrong tries answers 429 before any check; a wrong password or code is a wrong try of the username (401, or 429 when it starts a wait). The session cookie stays the same (Q-2026-10-24-183 point 5). The right answer records the reauthentication (the sign-in code's time step is used once), answers the session with `reauthenticated_at` and a new CSRF cookie, `Cache-Control: no-store`. Without the protection key file a sign-in code answers 503. The routes that need a recent reauthentication come with login sub-slice L3d-2.

Amended by DL-081 (login sub-slice L3d-1 review round 2, owner answer of 2026-10-24 to Q-2026-10-24-183, replacing "The session cookie stays the same"): the right answer also sets a separate reauthentication cookie `__Host-prm_reauth` (HttpOnly, Secure, SameSite=Strict, Path=/, Max-Age 900 seconds), and the server keeps only its sha256 digest; the routes of login sub-slice L3d-2 require it. `GET /api/v1/auth/session` shows `reauthenticated_at` only with that cookie for the same session, and sign-out clears it. A password-only reauthentication (an account that needs no MFA) within 60 seconds of the account's last password-only reauthentication answers 429 with `Retry-After`, before any password check.

Amended by DL-081 (login sub-slice L3d-2, Q-2026-10-24-184): a sign-in finished with the sign-in code (`POST /api/v1/auth/mfa/challenge` with `totp`) and a confirmed set-up of a sign-in code (`POST /api/v1/auth/mfa/enrollment/confirm`) also count as a reauthentication of the new session: they set the `__Host-prm_reauth` cookie as above, and `GET /api/v1/auth/session` with it shows `reauthenticated_at`. A sign-in with a recovery code does not. The routes that need a recent reauthentication are listed under API-080.

## API-098 — Recovery Codes

Recovery-code generation/presentation is available only in a protected authenticated
enrollment or regeneration flow, except for the one-time pre-authentication trust-root
operation governed by `API-100`. Codes are shown securely once, individually consumed,
not returned again, and reuse is rejected. Recovery actions are rate-limited,
enumeration-resistant, session-revoking where appropriate, and immutably audited.

Amended by DL-081 (login sub-slice L3c-2c-1): `POST /api/v1/auth/recovery-codes` answers 10 new recovery codes and their set id once, with `Cache-Control: no-store`, for a live session whose sign-in code was given in the last 15 minutes by the database clock while the account has no recovery-code set that is not invalidated (the first codes after the first sign-in code); otherwise 401. The Owner already has the bootstrap's set, whose id was never shown, so the Owner can replace it only once the set id can be read (login sub-slice L6). One account's codes are made once at a time, and at most 5 sets of an account in 15 minutes; a parallel or a sixth request answers 401. `POST /api/v1/auth/recovery-codes/regenerate` with the live set's id, for a live session whose sign-in code was given in the last 15 minutes by the database clock, invalidates that set (none of its codes works again) and answers 10 new codes once, no-store; another or an invalidated set id, or an older proof, answers 401 (sign in again). Codes are stored only as Argon2id verifiers; an account has at most one live set. Signing in with a recovery code comes with login sub-slice L3c-2c-2.

Amended by DL-081 (login sub-slice L3d-2b, Q-2026-10-24-184 point 8): `POST /api/v1/auth/recovery-codes` and `POST /api/v1/auth/recovery-codes/regenerate` also need the `__Host-prm_reauth` cookie of the same session, of a reauthentication with the sign-in code in the last 15 minutes (the session's latest; a sign-in with the sign-in code writes one), instead of the session's sign-in proof alone; a session cookie alone now answers 401, also in the first 15 minutes after a sign-in. A later reauthentication with the password and the sign-in code (`POST /api/v1/auth/reauthenticate`) opens the window again without a new sign-in. This replaces "a live session whose sign-in code was given in the last 15 minutes" and "or an older proof, answers 401 (sign in again)" of the L3c-2c-1 amendment.

## API-099 — Administrative Recovery

Authorized Owner administration may initiate controlled reset/recovery for Manager and
Staff accounts. Staff cannot reset/recover Owner or Manager credentials. This API does
not grant Manager recovery of Staff. Owner emergency recovery is server-side only and
is never an ordinary unauthenticated web endpoint.

Amended by DL-081 (login sub-slice L4, owner answers (a) to Q-2026-10-21-153 and Q-2026-10-23-180; technical points Q-2026-10-24-185, decided by Claude under the owner's 2026-10-23 22:30 rule): `POST /api/v1/users/{user_id}/administrative-recovery` takes `{"reset_mfa", "reason"}` (no typed password; the old `new_password` shape is refused) and answers the result with `one_time_password` (`value`, `expires_at`) once, with `Cache-Control: no-store`. Only the Owner account class may use it, only for an active Manager or Staff account, after the 15-minute reauthentication (L3d-2); every session of the account ends, and with `reset_mfa` its sign-in code, its recovery codes and its Settings access end too. Creating an account (API-079) answers the new account's first one-time password the same way, and turning off the MFA a Staff account had to use answers one too.

## API-100 — Initial Owner Bootstrap Exclusion

No public API or web route creates the first Owner. The protected server command-line
bootstrap is a deployment operation available only before any account or bootstrap closure
exists. It first validates the supplied password as 15–128 Unicode code points, then
NFC-normalizes it and revalidates the normalized result as nonempty and 15–128 code points.
The complete normalized value is locally blocklisted, hashed, and verified without truncation.
The operation permits spaces, paste, and
password managers, and imposes neither composition nor periodic-rotation rules. It rejects
locally blocked compromised, common, expected, and project-context values without sending a
candidate to an external service.

Bootstrap creates exactly 10 cryptographically random independently single-use recovery
codes. It presents them exactly once through the controlling TTY, never redirectable stdout,
arguments, ordinary environment variables, logs, state, compact state, or audit; persists
only protected verifiers; and requires explicit acknowledgement before commit. One absolute
monotonic ceremony deadline begins before TOTP confirmation and covers TOTP input,
recovery-code presentation and complete persistence writes, acknowledgement input, and commit
preparation. Writes, partial input, retries, and trickled input never reset or extend it.
Presentation, acknowledgement, or deadline failure rolls back the entire operation.
Initial Owner identity, password verifier, confirmed protected MFA enrollment, recovery-code
verifiers, immutable audit, and closure are one atomic PostgreSQL operation through a
dedicated least-privilege one-time database identity. The TOTP protection key enters only
through an already-open root-controlled descriptor or equivalent protected secret file,
never arguments, logs, repository or compact state, or ordinary environment variables.
Successful closure permanently revokes bootstrap mutation capability. Repeats fail closed
and create immutable secret-free rejection evidence.

## API-080 — Roles and Capabilities

- `GET /capabilities`
- `GET /properties/{property_id}/role-bundles`
- `POST /properties/{property_id}/role-bundles`
- `PATCH /role-bundles/{id}`
- `POST /users/{id}/role-assignments`

Role bundles map configurable names to capabilities. The API does not hard-code
business authority into a role title.

Amended by DL-074 (owner, 2026-10-04 and 2026-10-20): the deployment starts with default Owner, Manager and Staff bundles as configurable data (Owner: every capability; Manager: all daily work, approvals, reports, audit history, exports and the health page, no user or role administration; Staff: daily data entry only, no approvals, administration, audit or export). Settings access is its own capability, given per user; only the Owner account class gives or removes it, and the Owner always has it.

Amended by DL-081 (login sub-slice L1c): each Property gets its default bundles "Owner", "Manager" and "Staff" once, as editable data (docs/004 DB-AUTH-009). The Owner and Manager bundles hold every bundle capability; the Staff bundle holds the 31 approved daily-work capabilities only. `identity.manage_access` and `settings.manage` are in no bundle; they come from the Owner account class and the per-user grant.

Amended by DL-081 (owner answers (a) to Q-2026-10-21-158 and Q-2026-10-21-166; login sub-slice L2b-1): three more routes, each a browser mutation that needs `identity.manage_access` for the account and its Property and a reason (1 to 500 characters, with at least one visible character and no control character, line or paragraph separator or direction mark; otherwise `422`), and each writing an audit event:
- `POST /users/{id}/settings-access` gives the account Settings access (`settings.manage`); it returns the account.
- `POST /users/{id}/settings-access/remove` removes it; it returns the account.
- `POST /users/{id}/role-assignments/remove` removes one assigned bundle (`role_bundle_id`, a bundle of the same Property) from the account and ends the account's sessions; it returns the removed assignment.
The recent password check of Q-2026-10-21-157 is added to these routes, as to the other administration routes, by login sub-slice L3d.

Amended by DL-081 (login sub-slice L2b-2): the administration routes of API-079 and API-080 run on PostgreSQL through the audited Owner-only database functions. A refusal answers with a stable code and a fixed plain message, never database text: `403 FORBIDDEN` (not the Owner); `404` (unknown account or bundle, or another Property's account list, bundle list or history); `409` `CONFLICT`, `USERNAME_TAKEN`, `ROLE_BUNDLE_NAME_TAKEN`, `ROLE_BUNDLE_ALREADY_ASSIGNED`, `ROLE_BUNDLE_NOT_ASSIGNED`, `SETTINGS_ACCESS_ALREADY_GIVEN`, `NO_SETTINGS_ACCESS`, `SIGN_IN_CODE_REQUIRED` ("A Staff account gets Settings access only after it has set up its sign-in code."), `ACCOUNT_DISABLED`, `PROPERTY_NOT_READY`, `TRY_AGAIN` (the change met another change); `412 STALE_VERSION` (the `If-Match` version is old); `422` `INVALID_NAME`, `CAPABILITY_NOT_ASSIGNABLE`, `OWNER_ACCOUNT_NOT_CHANGED`, `ACCOUNT_WITHOUT_CLASS`, `NOT_MANAGER_OR_STAFF`, `NO_CHANGE`, `MANAGER_MFA_REQUIRED`, `VALIDATION_ERROR`. `GET /capabilities` lists the capabilities that can be put in a bundle. The API trims white space at either end of a name or username. Names are saved NFC, with each run of space separators inside made one space; a control character or line break inside a name is refused, not folded. A username is lower case and has no white space inside but the ordinary space. The Owner's reset (API-099) stays unavailable until login sub-slice L4.

Amended by DL-081 (login sub-slice L2c, owner answer (a) to Q-2026-10-22-169): before saving, the API removes U+200B (the invisible space that Khmer keyboards put between words) from a username, display name, audit name, bundle name and reason, and the length rules count the characters that are saved; so a username or bundle name that differs from another only by U+200B answers `USERNAME_TAKEN` or `ROLE_BUNDLE_NAME_TAKEN`. A name with any other hidden character listed in docs/004 DB-AUTH-007 and DB-AUTH-010 answers `422 INVALID_NAME` (U+0000 answers `422 VALIDATION_ERROR`; the API saves every name NFC). A reason also refuses U+00AD, U+034F, the Hangul fillers (U+115F, U+1160, U+3164, U+FFA0), U+17B4, U+17B5, U+180B to U+180F, U+2060 to U+206F, U+2800, the variation selectors U+FE00 to U+FE0E, U+FEFF, U+FFF0 to U+FFFB, U+1BCA0 to U+1BCA3, U+1D173 to U+1D17A and U+E0000 to U+E0FFF (`422`), and keeps U+200C and U+200D, which Khmer text uses, and the emoji variation selector U+FE0F.

Amended by DL-081 (login sub-slice L2d, owner answer (a) to Q-2026-10-22-170): odd and double spaces in a username, display name, audit name or bundle name are tidied, not refused: before the length rule the API makes every space separator (Unicode category Zs) an ordinary space, a run of spaces one, and removes spaces at either end, and the 128 limit counts the tidied name; so a username typed with a no-break space is saved with an ordinary space (and is `USERNAME_TAKEN` when that username exists). A tab, line break or other control character inside a name is still refused (`422 INVALID_NAME`); at either end it is trimmed, as before. A name made only of spaces answers `422 VALIDATION_ERROR`. The reason of the Owner's reset (API-099) is free text, not a name: its spaces are not tidied (only U+200B is removed) until login sub-slice L4 moves it to the reason rule.

Amended by DL-081 (login sub-slice L3d-2, owner answer (a) to Q-2026-10-21-157; technical points in Q-2026-10-24-184): `POST /properties/{property_id}/users`, `PATCH /users/{user_id}` when it disables the account or changes `mfa_policy_class` (a change of the names alone is not checked), `POST /properties/{property_id}/role-bundles`, `PATCH /role-bundles/{id}`, `POST /users/{id}/role-assignments`, `POST /users/{id}/role-assignments/remove`, `POST /users/{id}/settings-access` and `POST /users/{id}/settings-access/remove` need a reauthentication with the password and the sign-in code (API-097) of the same session in the last 15 minutes, shown by the `__Host-prm_reauth` cookie; `POST /users/{user_id}/revoke-sessions` does not. Without one the route answers `403 REAUTHENTICATION_REQUIRED` with the message "Please enter your password and sign-in code again, then try again." and changes nothing; the check comes first, and the capability check of the database functions still applies after it. The Owner's reset (`POST /users/{user_id}/administrative-recovery`, API-099) gets the same check when login sub-slice L4 builds it.

Amended by DL-081 (login sub-slice L3d-2 review round 1, Q-2026-10-24-184): the order is the route's capability, account or bundle and Property checks, then the reauthentication check, then the Owner check of the database functions; so for an account that is not the Owner but has no recent reauthentication, `403 REAUTHENTICATION_REQUIRED` replaces the `403 FORBIDDEN` of the L2b-2 amendment. A lock wait over 3 seconds answers `409 TRY_AGAIN`.

## API-081 — Operational Health

- `GET /health/live` provides minimal unauthenticated liveness.
- `GET /health/ready` provides minimal readiness.
- `GET /api/v1/operations/status` provides authorized detailed API/worker/job/
  migration/backup freshness without secrets.

Amended by DL-074 (owner, 2026-10-04): the detailed status is for the Owner and the Manager by default, through a capability in their bundles.

Built in V1-059 part A (2026-10-24; DL-081 Q-2026-10-21-158 (a)): `GET /api/v1/operations/status` needs a signed-in user (401) holding `operations.status.read` (403 otherwise; the Owner and Manager bundles hold it) and answers `Cache-Control: private, no-store` with `data`: `build_version`, `environment`, `generated_at`, `database` (`ok`, `unavailable` or `not_configured`), the `backup`, `offhost_daily`, `offhost_weekly`, `restore_test` and `migration` records (times, outcome, fixed failure code, backup name, schema revision), `last_check_at`, `schema_revision`, `scheduled_jobs` (last successful billing run attempt and Reservation expiration run), `telegram` (`configured`, `last_delivery_outcome`, `last_attempt_at`) and `warnings` (`code`, a fixed plain `message`, `critical`); and `meta.request_id`. It never shows a secret, a database address, a file path or a Customer detail. Without `APP_OPERATIONS_STATUS_DIRECTORY` the only warning is `operations_status_not_set_up`.

## API-101 — Financial Drafts: List, Detail, Reject, Withdraw and Confirm

Built in V1-056 slice 11b (2026-10-24; BR-AUTH-010, DL-069). Every draft kind (Refund, Deposit
forfeiture and its reversals, Payment move, Final Settlement and its corrections, returned
Payment, Adjustment reversal) is read and decided through these Property routes; each kind keeps
its own record and confirm routes.

- `GET /properties/{property_id}/financial-drafts?state=&limit=&cursor=`: drafts newest first.
  `state` is `PENDING`, `CONFIRMED`, `REJECTED` or `WITHDRAWN`; `limit` 1 to 100 (50); the
  cursor is bound to the Property and the state filter. A holder of `financial.approve` sees every
  draft; anyone else sees only drafts prepared under a capability they hold. With no draft
  capability the Property's drafts answer 404.
- `GET /properties/{property_id}/financial-drafts/{draft_id}`: one draft, with its state and
  decision. The decision result never carries the database transaction id.
- `POST /properties/{property_id}/financial-drafts/{draft_id}/reject` `{"reason"}`: only a
  `financial.approve` holder (others 404); it moves no money.
- `POST /properties/{property_id}/financial-drafts/{draft_id}/withdraw` `{"reason"}`: only the
  person who prepared the draft and still holds its prepare capability; anyone else 403
  `DRAFT_WITHDRAW_PREPARER_ONLY`. It moves no money.
- `POST /properties/{property_id}/financial-drafts/{draft_id}/confirm` `{}`: only a
  `financial.approve` holder (others 404). It calls the draft kind's own confirm command, which
  checks every rule again, and answers `{"draft", "result"}` with that command's result (never a
  database transaction id). The approver who confirmed a draft gets its first result again;
  anyone else, and anyone confirming a rejected or withdrawn draft, gets 409
  `DRAFT_ALREADY_DECIDED`. Other refusals: 409
  `DRAFT_OUT_OF_DATE` (the records changed after the draft was prepared: reject it and record it
  again), 409 `DRAFT_CONFIRM_REFUSED` (a business rule refuses it now), 409
  `DRAFT_CONFIRM_NOT_AVAILABLE` (a draft confirmed only inside another command, such as a return
  reversal's companion). The kind's own confirm routes stay.
- A Reservation Deposit draft (it names the Customer) is listed, shown and decided only with
  `reservations.read` as well, as on the Reservation's own draft routes.

Confirm, reject and withdraw need Origin, CSRF and `Idempotency-Key` (the draft id is the idempotency
identity; the key is not stored). A draft already confirmed, rejected or withdrawn answers 409
`DRAFT_ALREADY_DECIDED`; another refusal by the draft's rules answers 409
`DRAFT_DECISION_NOT_ALLOWED`. The reason is 1 to 1000 characters, trimmed. Answers are
`private, no-store`.

Refusals with a stable code (slice 11): a refused command whose cause staff need answers with
the API-013 envelope and a fixed `code` and `message`, never database text.

V1-056 slice 11d (2026-10-24; no migration; BR-PAY-042): the wrong-Unit Payment move draft.
`POST /properties/{property_id}/payment-allocations/{allocation_id}/move-drafts`
(`payments.allocations.reverse`; others a hidden 404; Origin, CSRF, `Idempotency-Key`; body
`target_invoice_id`, `reason` of up to 1,000 characters, and `source_acknowledgement` and
`target_acknowledgement` of up to 2,000 characters each: who acknowledged for each Customer, the
date and how) records a `PAYMENT_MOVE` draft of variant `WRONG_UNIT_MOVE` and answers 201 with
the draft. It moves nothing until a `financial.approve` holder confirms it through the confirm
route above. An allocation that a closed Final Settlement relied on moves only through a
`PAYMENT_MOVE` correction of that Settlement (slice 11e).

- Named refusals at record: 409 `PAYMENT_MOVE_NOT_INVOICE_ALLOCATION`,
  `PAYMENT_MOVE_PAYMENT_REVERSED`, `PAYMENT_MOVE_ALREADY_MOVED`,
  `PAYMENT_MOVE_RELEASED_BY_ADJUSTMENT`, `PAYMENT_MOVE_CREDIT_OR_REFUND_FIRST`,
  `PAYMENT_MOVE_VALUE_GONE`, `PAYMENT_MOVE_TARGET_TOO_LARGE`, `PAYMENT_MOVE_THROUGH_CORRECTION`,
  and `PAYMENT_MOVE_DRAFT_WAITING`; 422 on `target_invoice_id`:
  `PAYMENT_MOVE_TARGET_NOT_FOUND`, `PAYMENT_MOVE_TARGET_SAME_UNIT` and
  `PAYMENT_MOVE_TARGET_NOTHING_OWED`; 422 on both acknowledgements: `PAYMENT_MOVE_TOO_LARGE`
  (the acknowledgements and the correct Invoice's line split are over 16,000 bytes). An unknown
  allocation answers 404.
- At the confirm route the same business-state codes apply, except `PAYMENT_MOVE_DRAFT_WAITING`
  and `PAYMENT_MOVE_TOO_LARGE`, which only recording raises. A Final Settlement that closed after
  the draft was recorded answers `PAYMENT_MOVE_THROUGH_CORRECTION`. A correct Invoice with nothing
  left to pay, or a draft the database finds stale, answers 409 `DRAFT_OUT_OF_DATE` (the draft
  stays pending: reject it, and record a new draft if the move is still needed). Final Settlement
  correction drafts of variant `PAYMENT_MOVE` keep their plain confirm answers.
- `POST /payment-allocations/{allocation_id}/reverse` now answers 409 `ALLOCATION_MOVED` for an
  allocation a move created (it changes only through another move draft or a credit Adjustment)
  and 409 `FINAL_SETTLEMENT_CLOSED` for one a closed Final Settlement relied on; its other
  answers are unchanged.

## API-102 — Move-out Cleaning Charge, Hand-back Month and the Lease End Date Refusal

Built in V1-056 slice 11a (2026-10-24; BR-UNIT-014, BR-MOVEOUT-013, BR-RENT-030, BR-LEASE-031,
DL-065, DL-069, DL-075). Mutations need Origin, CSRF and, where named, `Idempotency-Key`; an
optional `X-Billing-Actor-ID` must name the signed-in person. Answers are `private, no-store`.

- `GET /properties/{property_id}/units/{unit_id}/cleaning-rate`: the Unit's current cleaning rate
  or `null` (`invoices.create` or `property.manage`, else 403).
- `POST /properties/{property_id}/units/{unit_id}/cleaning-rates` `{"rate_id",
  "expected_current_rate_id", "rate_usd_cents", "reason"}` (201): a new dated per-Unit rate in USD
  cents (0 or more), under `property.manage` until the DL-075 Settings screens move cleaning rates
  to Unit Type rate groups. `expected_current_rate_id` is required (null when the Unit has no rate);
  the rate id is the idempotency identity. A rate changed since the form was read answers 409
  `CLEANING_RATE_CHANGED`.
- `POST /properties/{property_id}/leases/{lease_id}/cleaning-charge` `{"charge_id",
  "expected_rate_id"}` (201, `invoices.create`): records the move-out cleaning charge from the rate
  shown; the Invoice draft is then created and issued through the Invoice routes. Refusals (409):
  `CLEANING_CHARGE_NOT_MOVED_IN`, `CLEANING_CHARGE_NEEDS_MOVE_OUT`,
  `CLEANING_CHARGE_ALREADY_RECORDED`, `CLEANING_RATE_NOT_SET`, `CLEANING_RATE_ZERO`,
  `CLEANING_RATE_CHANGED`. A Manager reduces it with a credit Adjustment and a reason (DL-065).
- `GET /invoices/{invoice_id}/hand-back-assessment` (`invoices.read` and `leases.read`, else 404):
  which BR-RENT-030 action applies to a monthly Rent Invoice (`VOID`, `CREDIT_ADJUSTMENT` or
  `KEEP`), the coverage (`HAND_BACK_MONTH` or `NEXT_MONTH`), the applied and outstanding cents and
  each line; no Lease, move-out or date identities. It changes nothing.
- `POST /invoices/{invoice_id}/hand-back-resolution` `{"action", "expected_outstanding_usd_cents",
  "reason"}` with `If-Match` and `Idempotency-Key`: `VOID` needs `invoices.void`,
  `CREDIT_ADJUSTMENT` needs `invoices.adjust` (else 404). The answer's ETag is the Invoice version
  the resolution recorded (a repeat with the same key answers the stored result). Refusals (409):
  `HAND_BACK_VOID_BLOCKED` (an Adjustment, Late-payment Charge or billing run not settled or
  reversed), `HAND_BACK_NOT_MONTHLY_RENT`, `HAND_BACK_INVOICE_NOT_ISSUED`,
  `HAND_BACK_NOT_EARLY_TERMINATION`, `HAND_BACK_NEEDS_MOVE_OUT`, `HAND_BACK_MOVE_OUT_UNCLEAR`,
  `HAND_BACK_MONTH_NOT_COVERED`, `HAND_BACK_ALREADY_RESOLVED`, `HAND_BACK_PAID_INVOICE_KEPT`,
  `HAND_BACK_ASSESSMENT_CHANGED`; the assessment read answers the same codes. A stale version
  answers 412.
- Amended by V1-056 slice 12a (migration `20270215_203`; DL-090): an Invoice with nothing applied
  and nothing outstanding (a credit Adjustment took it to zero) is assessed `KEEP`, not `VOID`;
  the resolution still refuses it and writes nothing, but its refusal code changes from
  `HAND_BACK_ASSESSMENT_CHANGED` to `HAND_BACK_PAID_INVOICE_KEPT`.
- On these routes a closed Final Settlement answers 409 `FINAL_SETTLEMENT_CLOSED` (BR-SETTLE-012),
  and a rate or charge id reused with different input answers 409 `IDEMPOTENCY_KEY_REUSED`.
- Lease draft, draft update, renewal and signing: an End Date that is not the last day of its month
  answers 422 `LEASE_END_DATE_NOT_MONTH_END` with `fields` `["end_date"]` (BR-LEASE-031).

# 26. Validation Rules

## API-082 — Relationship Validation

The server verifies Property scope and all cross-resource relationships. In
particular, Lease-associated Invoice Customer, Unit, obligation, period, and Lease
must be consistent.

## API-083 — Status Validation

Input enums are allowlisted from authoritative statuses. Unknown values return
`422`; the server never stores a value merely because the client sent it.

## API-084 — Date Validation

Dates are validated in Property-local context, including contractual non-overlap,
Reservation eligibility, period ordering, Rate effective dates, Reading chronology,
and move-in/out boundaries.

## API-085 — Financial Validation

Amounts must be positive/non-negative as defined by action, exact for currency,
and within server-calculated availability. Negative values do not substitute for
approved debit/credit event types.

## API-086 — Source Validation

Every financial line/event requiring a source has an allowed source type, stable
source identifier, and uniqueness rule. Free text cannot replace the source link.

# 27. Deletion and Retention

## API-087 — No Financial Delete

No DELETE endpoint exists for issued or confirmed financial records, Deposit
history, Settlement, or audit events.

## API-088 — Source-data Deactivation

Where upstream permits removal of unused draft/configuration data, the API uses a
specific deactivate/cancel action or DELETE only before any history/reference
exists. This specification does not grant a general deletion right.

# 28. Scheduled/System Authentication

## API-089 — Service Identity

Workers authenticate with a distinct service identity, restricted capabilities,
and Property scope. Human credentials are not embedded in jobs.

## API-090 — Job Audit

System actions record service identity, logical business date, schedule/run ID,
idempotency key, and outcome. Operators retry through an authorized operation,
not by altering job state directly.

# 29. Traceability

Because 003 defines an exact same-suffix bijection, every `BR-X-NNN` reference in
this section also cites and implements `PR-X-NNN`; a family wildcard or inclusive
range expands identically in both namespaces. Concrete `DB-*` references in endpoint
requirements identify the persistence requirement used by that operation.

| API area | Rules |
|---|---|
| Reservation | `BR-RES-*` |
| Lease/Occupancy/Move-in | `BR-LEASE-*`, `BR-OCC-*`, `BR-DEP-*` |
| Deposit/Pet | `BR-DEP-*` |
| Active-Lease Pet Deposit Refund | `BR-DEP-*`, `BR-REFUND-*` |
| Rent/Services | `BR-RENT-*`, `BR-SVC-*` |
| Utilities | `BR-UTIL-*` |
| Invoice | `BR-INV-*` |
| Late-payment Decision/Charge | `BR-INV-051` through `BR-INV-055`, `BR-LATE-*` |
| Payment/Allocation | `BR-PAY-*` |
| Receipt/Reprint | `BR-RECEIPT-*` |
| Customer Account Ledger | `BR-LEDGER-*` |
| Credit/Refund | `BR-CREDIT-*`, `BR-REFUND-*` |
| Rent Nonpayment | `BR-LEASE-026` through `BR-LEASE-030`, applicable `BR-PAY-*` |
| Termination/Move-out | `BR-LEASE-017` through `BR-LEASE-030`, `BR-MOVEOUT-*` |
| Settlement | `BR-SETTLE-*` |
| Money/FX | `BR-MONEY-*` |
| Audit/Authorization | `BR-AUDIT-*`, `BR-AUTH-*` |

# 30. RESOLVED OWNER DECISION

## OOD-API-001 — Authentication Integration

**Resolved question:** Which local or external authentication provider will production use?

**Resolution:** Production uses application-managed local username/password
authentication. The API keeps provider/library mechanics outside business endpoints and
retains capability enforcement independent of role names. See `DL-055`.

**Status:** Resolved by final Owner approval.

# 31. Completion Criteria

This API Specification is complete for Owner Review when:

- all requested resources and business actions have endpoints;
- schemas preserve mandatory Customer and optional Lease Invoice ownership;
- financial balances/statuses cannot be set directly;
- significant transitions use explicit authorized commands;
- validation, errors, pagination, idempotency, concurrency, and audit are defined;
- scheduled jobs use the same business services without bypass;
- no unsupported fees, penalties, statuses, Refund rights, Deposit uses, or
  termination behavior are exposed; and
- the resolved local-authentication policy is implemented without coupling business
  authorization to credential-library details.


### V1-055 unbilled Utility periods — service boundary — 2026-10-02

Since slice 9d it is exposed as `GET /properties/{id}/unbilled-utility-periods` (`limit` up to 50 and `offset`; read only; `private, no-store`). `PostgresUnbilledUtilityPeriodsService.read` (capability `utility.read`, read-only, at most 50 per page) lists finalized Utility periods that have no Invoice line and that no run will pick up: `period_id`, `unit_id`, `utility_type`, `start_date`, `end_date`, `consumption_quantity`, `lease_id`, `can_catch_up` and `gap_reason` (`LATE_AFTER_SUCCEEDED_RUN` or `NOT_MOVED_IN`). The catch-up command below accepts these periods; a late period is billed only by that explicit action.

Amended by DL-071 (owner, 2026-10-20; answer 18): before V1-060 the scheduled billing worker bills a `LATE_AFTER_SUCCEEDED_RUN` period by itself, and this list stays as a safety check; a `NOT_MOVED_IN` period is still billed only by the catch-up command. Not built yet (V1-056 slice 12).

As built in V1-056 slice 12b (DL-091): `ScheduledBillingWorker.run_once` runs a late Utility run for each date `app.scheduled_late_utility_candidates` lists, after the ordinary runs and within the same bound of runs per pass; a late run that fails is reported (`late_utility:error:`) and the late-payment charge pass still runs. `POST` of a billing run with a `utilities-late/` logical key is refused (only the worker starts one). A late run is visible in the billing run reads like any other run.

### V1-055 final Utility Invoice and catch-up Invoice — service boundary — 2026-10-02

`PostgresFinalUtilityInvoiceService` creates the final Utility Invoice of a departed Lease (command: Invoice identity, current final-input event, optional Due Date override with reason; capabilities `invoices.issue` and `utility.calculate`) and the catch-up Invoice for a period skipped as NOT_MOVED_IN (capability `invoices.issue`). Since slice 9d they are exposed as `POST /properties/{id}/leases/{lease_id}/final-utility-invoice` (`invoice_id`, `final_input_event_id`, optional `due_date` with `due_date_reason`) and `POST /properties/{id}/leases/{lease_id}/utility-catch-up-invoice` (`invoice_id`, `consumption_period_id`, optional `due_date` with `due_date_reason`). Both need an `Idempotency-Key`, answer 201 and replay exactly; a refusal carries the stable reason above as `error.code` (422 for invalid, 409 for conflict). Reasons are stable codes: `UTILITY_NOTHING_TO_BILL`, `UTILITY_UNRESOLVED_FINAL_INPUT`, `UTILITY_NOT_MOVED_IN`, `UTILITY_START_READING_MISSING`, `UTILITY_EARLIER_READING_NOT_FINALIZED`, `UTILITY_PERIOD_ALREADY_INVOICED`, `UTILITY_NOT_RESPONSIBLE`, `UTILITY_PERIOD_NOT_SKIPPED`. A second final Invoice for the same event, a superseded event or a period that already has a line is a conflict; exact replay returns the saved response.

Amended by DL-105 (V1-060 B6, 2026-10-28): when no Utility Rate of a billed kind is in effect on the generation date (BR-UTIL-015, BR-UTIL-029), for example before the first Rate starts, both routes answer 422 with the stable reason `UTILITY_RATE_NOT_IN_EFFECT` instead of the generic `VALIDATION_ERROR`. The service names the database refusal "Generation-date Utility Rate was not found" (SQLSTATE P0002) this way.

### V1-055 Utility baseline Reading — service boundary — 2026-10-02

`PostgresUtilityBaselineService` records and reads the Utility baseline of a SIGNED Lease that has no Occupancy; since slice 9d it is exposed as `GET` and `POST /properties/{id}/leases/{lease_id}/utility-baseline` next to the Meter and Reading resources (API-044 to API-046), with `limit` up to 20 and `offset` for the read. The command names the new event, an optional superseded event, the baseline date (on or before the Lease Start Date), a reason, an evidence reference and one item per applicable Meter, each referencing an existing validated Reading dated the baseline date. It never creates a Reading and uses the capability `utility_readings.record` (read: `utility.read`). Outcomes map as in the final-input service: unknown Lease or source is not found, malformed or rule-breaking input is invalid, changed sources and a second root are conflicts, reuse of an idempotency key with a different intent is a key-reuse conflict, and a missing capability on recording is an authorization failure. Exact replay returns the saved response.

### V1-055 move-out final Utility inputs — service boundary — 2026-09-29

`PostgresMoveOutFinalInputsService` records and reads final Utility inputs for a physical departure. Since slice 9d they are exposed as `GET` and `POST /properties/{id}/leases/{lease_id}/move-out-final-utility-inputs` under API-069 (`limit` up to 20 and `offset` for the read). The command intent names the new event, the current physical departure event, an optional superseded event, reason, authorization reference, evidence reference and one item per applicable Meter. Items reference existing Readings created through API-045 or approved broken-Meter estimates, or state an explicit unresolved reason. The command never creates a Reading. Service outcomes map as follows: unknown Property/Lease/source or missing capability on observation is not found; malformed, unsupported or contradicted items are invalid; changed sources, a superseded physical or correction source, a second root event and lock conflicts are conflicts; reuse of an idempotency key with a different intent is a key-reuse conflict; a missing capability on recording is an authorization failure. Exact replay returns the saved response. Responses state that no Reading or charge is created and that Utility and financial completion are not assessed.

### V1-058 Lease screen actions — 2026-10-25

`POST /leases/{lease_id}/sign` (API-038) also takes an optional `reservation_id`: the active Reservation this signing completes (DL-066). The database checks that it is ACTIVE, belongs to the same Unit and Primary Tenant and has not expired; it then completes the Reservation and links its Security Deposit to the Lease in the same step. Without it, signing a Lease whose Unit is Reserved is refused as before. `POST /leases/{lease_id}/cancel` (capability `leases.draft`, `If-Match`, browser mutation checks, `Idempotency-Key`) cancels a draft Lease with `event_id` and a `reason` of 1 to 500 characters (BR-LEASE-004); a signed Lease is never cancelled. `POST /leases/{lease_id}/move-in` (capability `reservations.complete`, `If-Match` with the Lease version) records the physical move-in of a Lease whose signing already completed its Reservation, with `event_id`, `actual_move_in_date`, 1 to 20 `occupants` (`occupancy_id`, `customer_id`) and a `reason`; it starts the Occupancies. Both return the Lease with its new `ETag`; without the capability the Lease is not found (404), as on the other Lease commands.

### V1-058 Final Settlement list read — 2026-10-25

`GET /properties/{id}/final-settlements` (API-071 family; `final_settlements.prepare` or `financial.approve`, else 404) lists the Property's Final Settlements, newest first, each as the start route shows it plus `pending_draft` (true while a FINAL_SETTLEMENT draft of it waits for a decision). The one query parameter `lease_id` limits it to that Lease; an unknown Lease is 404. It reads through `app.final_settlements_read` (migration `20270315_234`, runtime role only) and opens nothing, so the Move-out screens can show "Waiting for a Manager" and "Closed" without starting a Settlement. A Settlement of another Property or Lease in the answer is never shown (503).

### V1-058 Services and Service types in Settings — 2026-10-25

Read `GET /properties/{id}/service-settings` (`settings.manage`, `configuration.read` or `leases.draft`, else 403; no query values): `services` (each with names, type, `version`, rate today, the next rate, approval periods and how many drafted or signed Leases use it), `service_types` (names, `one_per_lease`, `version`, how many Services), `today` and `can_manage`. Changes need `settings.manage`, Origin and CSRF, and strict bodies: `POST /properties/{id}/services` (201; client id, English and Khmer names, type, monthly rate in USD cents, `starts_on` on the 1st; adds the first rate and an open approval period), `POST /properties/{id}/services/{service_id}` (names and type, with `version`), `POST /properties/{id}/service-types` (201), `POST /properties/{id}/service-types/{type_id}` (names and "Only one per Lease", with `version`) and `POST .../service-types/{type_id}/remove` (`version`). The same id with the same values answers the record again; other values give 409 `SETTINGS_ID_REUSED`. An old `version`, or a change that ran into another at the same moment, gives 409 `SETTINGS_OUT_OF_DATE`. A change that would leave a Lease with two Services of an "Only one per Lease" type gives 409 `LEASE_HOLDS_TWO_OF_TYPE`; removing a type that has Services gives 409 `SERVICE_TYPE_HAS_SERVICES`. Invalid values 422, unknown records 404. Migration `20270316_235`; every change is audited with `settings.manage`. Rates are never changed here (append-only `service_rates`). Billing still bills only the Service whose code is `TRASH_COLLECTION` (the first Service named "Trash Collection"); other Services are recorded but not billed yet.


V1-058 R7b-6d move-out cleaning rates (DL-075): `GET /properties/{id}/cleaning-settings` (`settings.manage`, `configuration.read` or `leases.draft`) answers the rates (not removed) with their Unit Type codes, every Unit Type of the Unit setup list with its Units count and rate id, and `can_manage`. `POST /properties/{id}/cleaning-rates` (201; client `cleaning_rate_id`, English and Khmer names, `rate_usd_cents` at least 1, `unit_types` codes), `POST /properties/{id}/cleaning-rates/{rate_id}` (the same fields with `version`; a Unit Type ticked here moves from its other rate) and `POST .../cleaning-rates/{rate_id}/remove` (`version`). A change that would leave a Unit Type with Units without a rate gives 409 `UNIT_TYPE_NEEDS_CLEANING_RATE`; replay, `SETTINGS_ID_REUSED` and `SETTINGS_OUT_OF_DATE` as for Services; a removed rate gives 404. Migration `20270317_236`; each save gives every Unit of its types the amount through its own cleaning rate chain.

### V1-060 Add occupant — 2026-10-28

`POST /leases/{lease_id}/occupants` (DL-102; capability `reservations.complete`, `If-Match` with the Lease version, browser mutation checks, `Idempotency-Key`; strict body) adds one person to a draft or a running Lease: `event_id`, `customer_id`, `occupancy_id` and `move_in_date` (both given after the move-in, both left out or null before it) and a `reason` of 1 to 500 characters. Before the move-in the person is planned and the Lease's `planned_occupant_customer_ids` and new `planned_occupants` (`customer_id`, `customer_name`) list them; after it their own Occupancy starts on `move_in_date`. It returns the Lease with its new `ETag`. Without the capability the Lease is not found (404); an old version gives 412; the same key with other values gives 409; a refused person or date (see DL-102) gives 422. The Lease timeline now also lists `lease.move_in` (the move-in of a Lease signed with its outcome record) and `lease.occupant_added`. Migration `20270327_246`.

### V1-060 Invoice items — 2026-10-28

`POST /properties/{property_id}/invoices/drafts` (DL-103; capability `invoices.create`, browser mutation checks, `Idempotency-Key`; no query values; strict body) records 1 to 20 typed items and their one Miscellaneous DRAFT in one step: `customer_id`, an optional `lease_id`, one `reason` and one `evidence_reference` (1 to 500 characters each) and `items`, each with a client `charge_id`, a `description` (1 to 1,000 characters), a whole `quantity` (1 to 9,999) and a whole `unit_price_usd_cents` (1 to 999,999,999). The server works out each amount as the quantity times the unit price. It answers 201 with the Invoice, `Location` and `ETag`; each line's `calculation_evidence` carries `quantity`, `unit_price_usd_cents`, `reason` and `evidence_reference`. `PUT /invoices/{invoice_id}/items` (`invoices.create`, `If-Match` with the Invoice version, browser mutation checks, `Idempotency-Key`) takes the same body plus a `change_reason` (1 to 500 characters) and replaces the items of a DRAFT made this way; an item sent with its saved `charge_id` and the same values, reason and approval keeps its charge, and any other item needs a new `charge_id`. It answers 200 with the Invoice and its new `ETag`. Without the capability the create route answers 403 and the edit route 404; a missing, malformed or old `If-Match` gives 412 (with the current version when it is old); the same key with other values gives 409 `IDEMPOTENCY_KEY_REUSED`; a reused or changed charge id gives 409; a body outside the rules, a Customer who is not the Lease's Primary Tenant, an issued Invoice or a Draft not made from typed items gives 422. Migration `20270328_247`.

### V1-060 Report broken meter — 2026-10-28

`POST /meters/{meter_id}/report-broken` (DL-104; capability `utility_meters.manage` for the Meter's Property, browser mutation checks, `Idempotency-Key`; no query values; strict body) takes `expected_version` (the Meter version, at least 1), `failure_date` and `reason` (1 to 500 characters, trimmed; blank is refused). It answers 200 with the Meter and its new `ETag`; the Meter's `failure_date` is the reported day, `current` stays true until the replacement, and `failure_report` holds `id`, `failure_date`, `reason`, `occurred_at` and `actor_id` (null on a Meter never reported broken, also in `GET /meters/{meter_id}` and the Meter list). Without the capability it answers 403; an unknown Meter 404; an old `expected_version` 412 with the current version; the same key with other values 409 `IDEMPOTENCY_KEY_REUSED`; a Meter already broken or replaced 409; a day before the Meter was put in or before its newest Reading, or after today in Phnom Penh, 422. The digest action is `REPORT_METER_FAILURE`. Migration `20270329_248`.

### V1-060 Sign Lease with its money — 2026-10-28

`GET /leases/{lease_id}/signing-preview` (DL-100; capability `leases.read`; no query values; `Cache-Control: private, no-store`) answers what is due at signing: the Initial Rent Invoice as the generator will make it (period, Due Date, Rent and Service lines and total, or the problem that stops it), the draft's `planned_security_deposit_usd_cents` and the Reservation's `held_security_deposit` (null unless the person has `deposits.read` or `reservations.read`). `PUT /leases/{lease_id}/planned-security-deposit` (DL-101; capability `leases.draft`, browser mutation checks; strict body `plan_id`, `required_usd_cents` of at least 1 and a `reason` of 1 to 500 characters) records the draft's Security Deposit and answers `planned_security_deposit_usd_cents`; since DL-108 a `plan_id` used again with another Lease, amount or reason answers 409 `PLANNED_DEPOSIT_SAVE_REUSED`.

`POST /leases/{lease_id}/sign-with-payment` (DL-108; capabilities `leases.sign`, `payments.record` and `payments.allocate` for the Lease's Property, else 404; `If-Match` with the Lease version, else 428; browser mutation checks; the financial Property header; one `Idempotency-Key` that is not nil; strict body) signs a draft Lease with its money in one database transaction (`app.sign_lease_with_payment`, migration `20270330_249`). The body has `signer_ids` (every Signer who has not signed, at most 100, no repeats), a `reason` of 1 to 500 characters without spaces around it, and `payment`: `payment_method_id`, `received_at`, `evidence_reference`, an optional `payer_intent_memo` and `amount` (`currency` USD, `minor_units` at least 1). The payer is the Lease's Primary Tenant, and the amount must be exactly the money due at signing (the Initial Rent Invoice and the Security Deposit still owed). It answers 201 with `lease_id`, `lease_version` (also the `ETag`), `signed_at`, `reservation_id`, `payment_id`, `receipt_id`, `receipt_number`, `invoice_id`, `invoice_number`, `rent_usd_cents`, `deposit_usd_cents`, `total_usd_cents`, `deposit_id` and `deposit_receipt_id`, with `Cache-Control: private, no-store`. A walk-in Lease's Security Deposit is made only for a person with `deposits.manage` (else 403 `SIGNING_NO_DEPOSIT_RIGHT`). The same key with the same request answers the stored response; with another request 409 `SIGNING_KEY_REUSED`. Refusals answer 409 with a stable reason, and nothing is saved: `SIGNING_TOTAL_CHANGED`, `SIGNING_SIGNERS_CHANGED`, `SIGNING_DEPOSIT_MISSING`, `SIGNING_NOT_DRAFT`, `SIGNING_TERMS_INCOMPLETE`, `SIGNING_END_DATE_NOT_MONTH_END`, `SIGNING_UNIT_OCCUPIED`, `SIGNING_UNIT_NOT_FREE`, `SIGNING_RESERVATION_ENDED`, `SIGNING_RESERVATION_NO_DEPOSIT`, `SIGNING_REFUSED`, `INITIAL_RENT_DUE_DATE_PASSED`, `INITIAL_RENT_SERVICE_PART_MONTH` and `PLANNED_DEPOSIT_BELOW_RECEIVED`. A changed Lease answers 412; a malformed body 422 and a malformed header 400; no answer from the database 503, after which the same request may be sent again with the same key. The DL-100 route `POST /leases/{lease_id}/initial-rent-invoice` and the DL-101 route `POST /leases/{lease_id}/planned-security-deposit/apply` are removed; their database functions are steps of the command. `POST /leases/{lease_id}/sign` (API-038) is unchanged.

Amended by DL-109 (V1-060 B7 second review, 2026-10-28; migration `20270331_250`): `POST /leases/{lease_id}/sign-with-payment` also answers 409 `SIGNING_RESERVATION_ENDED` when the draft names a Security Deposit that is not held for the Primary Tenant's active Reservation of the Unit, `SIGNING_DATES_TAKEN` when another signed Lease of the Unit covers the dates, and `SIGNING_PAYMENT_SOURCE_GONE` when the way of payment is no longer on or the Customer was not found. Any other error the command raised answers 409 `SIGNING_REFUSED`, and nothing was saved. 503 means only that the outcome is not known (a deadlock, a lock wait, a timeout, a lost connection or a failed commit), after which the same request may be sent again with the same key.

Amended by DL-109 (V1-060 B7 third review, 2026-10-28): `SIGNING_DATES_TAKEN` is only for the signed-Lease dates check (`leases_signed_period_exclusive`); another exclusion check answers `SIGNING_REFUSED`. `SIGNING_PAYMENT_SOURCE_GONE` also answers a way of payment switched off after the dialog opened, and its words say "switched off".

Amended by DL-110 (V1-061, owner 2026-10-29; migration `20270401_251`): `POST /leases/{lease_id}/sign` (API-038), which signed a Lease with no money, is removed and answers 404; `POST /leases/{lease_id}/sign-with-payment` is the only way to sign. `PUT /units/{unit_id}/rent-terms` (a Manager or the Owner of the Unit's Property, else 403; `If-Match` with the Unit version, else 412 on a stale one; browser mutation checks; strict body) sets `default_monthly_rent_usd_cents` (whole cents from 1 to 100000000, or null for none) and `required_service_ids` (at most 20 Services of the same Property, no repeats, else 422). It answers 200 with the Unit and its new `ETag`; every Unit answer now has both fields. Make Reservation, a new Lease draft, a draft Rent change and a renewal answer 403 `RENT_BELOW_UNIT_DEFAULT` (field `monthly_rent_usd_cents`) when the Rent is below the Unit's default Rent and the person lacks `rent.below_default`; a Lease draft from a Booking may keep the Booking's agreed Rent. A new Lease draft without every required Service of its Unit answers 409 `LEASE_REQUIRED_SERVICE_MISSING` (field `service_terms`).

Amended by DL-111 (V1-061, owner 2026-10-29; migration `20270402_252`): `POST /api/v1/leases/{lease_id}/occupancies/{occupancy_id}/move-out` (capability `reservations.complete` for the Lease's Property, else 404; `If-Match` with the Lease version, else 428; browser mutation checks; one `Idempotency-Key`; strict body `event_id`, `move_out_date`, `agreed_signer_customer_ids` (at most 100, no repeats) and a `reason` of 1 to 500 characters) ends one person's Occupancy and answers the Lease with its new `ETag`. Refusals: 409 `OCCUPANT_PRIMARY_TENANT`, 409 `OCCUPANT_LAST_SIGNER`, 409 `OCCUPANT_SIGNERS_MUST_AGREE` (a Joint Signer needs every other Signer named), 422 `OCCUPANT_MOVE_OUT_DATE` and 409 `OCCUPANT_NOT_LIVING_THERE`. The Lease timeline shows `lease.occupant_moved_out`.

Amended by DL-112 (V1-061, owner bug list 2026-10-29; migration `20270403_253`): `POST /properties/{property_id}/reservations/with-payment` takes the Make Reservation body without `payment_id` and with `payment` (`payment_method_id`, `received_at`, `evidence_reference`, optional `payer_intent_memo`, `amount` in USD exactly equal to `accepted_initial_deposit_usd_cents`, else 422). It needs `reservations.create` and `payments.record` (else 404), plus the rights Make Reservation already needs, and answers 201 with the Reservation, `payment_id` and `receipt_number`. `POST /api/v1/leases/{lease_id}/security-deposit/receive` takes `deposit_id`, optional `required_usd_cents` (only to make a walk-in Lease's Security Deposit, which needs `deposits.manage`), `receipt_id`, `reason` and `payment`; it needs `payments.record` and `payments.allocate` (else 404). A `deposit_id` that is not the Lease's Security Deposit answers 409; a new Security Deposit for a Lease that has one answers 409 `DEPOSIT_SECURITY_ALREADY_EXISTS`; the other Security Deposit and receipt refusals keep their codes. It answers 201 with the receipt, `payment_id`, `receipt_number` and the Security Deposit's money. Both save the Payment and the record that holds it in one database transaction, or nothing; the same `Idempotency-Key` with the same body answers the same records.
