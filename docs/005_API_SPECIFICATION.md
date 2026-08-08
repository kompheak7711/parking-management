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

Protected endpoints require the configured authenticated session or bearer
mechanism. Authentication failures return `401` without revealing account or
resource existence.

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
outstanding Invoice, unallocated Payment, Customer Credit, and Deposit-liability
summaries. Deposit and Credit are separate values.

# 11. Reservation Endpoints

## API-032 — Reservation Resource

- `GET /properties/{property_id}/reservations`
- `POST /properties/{property_id}/reservations`
- `GET /reservations/{reservation_id}`

Creation requires one Customer, one Unit, Reservation/Expiration dates, agreed
monthly Rent evidence, and approved Security Deposit receipt/input workflow. It
must satisfy `BR-RES-*` and create no Reservation Deposit type.

## API-033 — Reservation Commands

- `POST /reservations/{id}/extend`
- `POST /reservations/{id}/cancel`
- `POST /reservations/{id}/complete-move-in`

Commands require idempotency. `extend` records the Notice and new date under the
one-extension/14-day rules. `cancel` requires reason; expiration uses
`RESERVATION_EXPIRED` while status becomes `CANCELLED`. `complete-move-in`
coordinates `MOVED_IN` and related Lease/Occupancy/Deposit effects.

## API-034 — No Generic Reservation Status Patch

Clients cannot set `ACTIVE`, `CANCELLED`, or `MOVED_IN` through PATCH. Unsupported
`EXPIRED` is rejected.

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

## API-037 — Occupancy

- `GET /leases/{lease_id}/occupancies`
- `POST /leases/{lease_id}/occupancies`
- `POST /occupancies/{occupancy_id}/end`

Occupancy commands preserve actual move-in/out dates and do not grant signer
responsibility.

## API-038 — Lease Commands

- `POST /leases/{id}/sign`
- `POST /leases/{id}/renew`
- `POST /leases/{id}/terminate`

Warning, Termination Notice, and Move-out creation use only the canonical API-067,
API-068, and API-069 routes; API-038 defines no aliases for those actions.

Each action has an explicit schema, authorization, reason/evidence, idempotency,
and applicable rule references. Signing/renewal rechecks non-overlapping
contractual periods transactionally. End Date alone invokes none of these actions.

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

`POST /deposit-receipts/{id}/reverse` and
`POST /deposit-dispositions/{id}/reverse` create DB-DEP-007/DB-DEP-008 linked
correction events and never rewrite originals.

# 14. Service Rate Endpoints

## API-043 — Service Rates

- `GET /properties/{property_id}/service-rates`
- `POST /properties/{property_id}/service-rates`
- `GET /service-rates/{rate_id}`

Only approved fixed recurring Internet and Trash Collection Service types are
accepted. Rates are effective-dated and historical records are not overwritten.
No generic one-time Service endpoint is authorized.

# 15. Utility Meter and Reading Endpoints

## API-044 — Meters

- `GET /units/{unit_id}/meters`
- `POST /units/{unit_id}/meters`
- `GET /meters/{meter_id}`
- `POST /meters/{meter_id}/replace`

Installation/replacement accepts Unit, Utility Type, physical identity, dates, and
required boundary evidence. It preserves replacement chain and rejects overlapping
active assignments.

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

When fewer than three complete historical actual periods exist, preview/generation
returns a structured `PENDING_FUTURE_ACTUAL_BASIS` result until one complete future
actual period for the same Unit and Utility Type exists. The API accepts no
arbitrary estimate, substitute Unit, or one/two-period historical substitution.
With three or more histories it uses the three most recent complete periods
preceding the affected period.

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

## API-053 — Invoice Lines

Lines are created only through approved draft/generation services and include type,
description, exact amount/currency, source type/id, calculation evidence, and
sequence. A generic API cannot attach an unsupported fee, penalty, or category.

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

Allocation is an explicit manual authorized command with Invoice and amount.
Authorized staff confirm/post the proposal or permitted designation. Server
transaction checks Customer/currency/context eligibility, Payment availability,
Invoice outstanding balance, and concurrency. Reversal creates a linked event.

## API-060 — Payment Reversal

`POST /payments/{payment_id}/reverse` requires reason, expected current state,
authorization, and idempotency. It coordinates required downstream reversals,
including Allocations, Credit recognitions/applications, Deposit Receipts,
Deposit Applications/Dispositions, and any required DB-REFUND-002 verified return,
before it sets `REVERSED`; it then recomputes affected balances/statuses without
deleting history.

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

## API-063 — Apply and Reverse Credit

- `POST /customer-credits/{id}/applications`
- `POST /credit-applications/{id}/reverse`

Commands require eligible Invoice, exact amount/currency, authorization, and
idempotency; they revalidate Credit availability and Invoice outstanding balance
transactionally.

# 20. Refund Endpoints

## API-064 — Refund Resource

- `GET /properties/{property_id}/refunds`
- `GET /refunds/{refund_id}`

A Refund response includes Customer, source type/id, exact amount/currency,
method/reference, business/recorded timestamps, actor, status/event state defined
by data model, and correction/reversal links.

## API-065 — Create Refund

`POST /refunds` accepts only an API-supported eligible source and amount within
server-calculated availability. Supported source families are limited to those
approved upstream, including Property-caused Reservation Deposit Refund, eligible
Payment/Credit disposition, or Final Settlement result.

An unallocated KHR excess refunded before Credit recognition uses the corresponding
original KHR excess. A later KHR Refund of USD Customer Credit uses the exchange
rate applicable to that Refund and preserves USD value, KHR value, rate, source,
and timestamp.

## API-066 — Refund Correction

`POST /refunds/{id}/verified-returns` records only value demonstrably returned after
an erroneous completed Refund under DB-REFUND-002. It requires exact returned
amount/currency, return timestamp/method reference, reason, authorization, actor,
and idempotency; cumulative value cannot exceed the Refund. It creates no collection
right and never erases the original outbound event. Generic PATCH/DELETE is
prohibited.

# 21. Warning and Termination Records

## API-067 — Warning Records

- `GET /leases/{lease_id}/warnings`
- `POST /leases/{lease_id}/warnings`

Creation records approved reason/category, sequence/evidence, dates, actor, and
idempotency. It creates no fee or automatic termination.

## API-068 — Termination Notices

- `GET /leases/{lease_id}/termination-notices`
- `POST /leases/{lease_id}/termination-notices`

Notice schema captures approved grounds, dates, source/Lease terms, evidence, actor,
and current effect. It does not itself grant unsupported forfeiture or Refund.

# 22. Move-out and Final Settlement Endpoints

## API-069 — Move-out Record

- `GET /leases/{lease_id}/move-out`
- `POST /leases/{lease_id}/move-out`

The command records actual Move-out Date, Occupancy closure, final Readings,
inspection/final-charge source references, reason/evidence, and audit event. It does
not assert financial closure.

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

The calculation order is: finalize valid charges; apply authorized Customer
Credit; apply Pet Deposit only to authorized pet-related damage; apply Security
Deposit to remaining authorized obligations using oldest-Due ordering where
applicable; record remaining Customer balance; and explicitly Refund remaining
refundable Deposit balances. Every application, disposition, and Refund remains a
separate event.

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

# 23. Audit Endpoints

## API-073 — Record Audit

`GET /{resource-family}/{id}/audit-events` returns a paginated authorized event
timeline with actor/system, action, timestamp, prior/resulting state or linked
source, reason, and correlation identifier.

## API-074 — Global Audit Search

`GET /properties/{property_id}/audit-events` supports bounded filters for date,
actor, action, resource type/id, Customer, Unit, Lease, and correlation identifier.
Audit view/export requires dedicated capability.

## API-075 — No Audit Mutation

No ordinary API endpoint updates or deletes audit events.

# 24. Reports and Dashboard Endpoints

## API-076 — Dashboard

`GET /properties/{property_id}/dashboard` returns server-calculated, as-of-stamped,
currency-separated operational summaries derived from authoritative records. It
must not create new statuses or aggregate USD and KHR without an explicit approved
basis.

## API-077 — Reports

`GET /properties/{property_id}/reports/{report_name}` supports only documented
reports from `003`/`006`, bounded parameters, pagination or controlled export, and
source/as-of metadata.

## API-078 — Export Jobs

Large authorized exports may use:

- `POST /properties/{property_id}/exports`
- `GET /exports/{export_id}`

Jobs are scoped, audited, expire from temporary storage, and never expose secrets
or data outside authorization.

# 25. Administration Endpoints

## API-079 — Accounts

- `GET /properties/{property_id}/users`
- `POST /properties/{property_id}/users`
- `PATCH /users/{user_id}` for approved profile/disable actions
- `POST /users/{user_id}/revoke-sessions`

Account and session actions require administration capabilities and audit events.
Credentials are never returned.

## API-080 — Roles and Capabilities

- `GET /capabilities`
- `GET /properties/{property_id}/role-bundles`
- `POST /properties/{property_id}/role-bundles`
- `PATCH /role-bundles/{id}`
- `POST /users/{id}/role-assignments`

Role bundles map configurable names to capabilities. The API does not hard-code
business authority into a role title.

## API-081 — Operational Health

- `GET /health/live` provides minimal unauthenticated liveness.
- `GET /health/ready` provides minimal readiness.
- `GET /api/v1/operations/status` provides authorized detailed API/worker/job/
  migration/backup freshness without secrets.

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
| Rent/Services | `BR-RENT-*`, `BR-SVC-*` |
| Utilities | `BR-UTIL-*` |
| Invoice | `BR-INV-*` |
| Payment/Allocation | `BR-PAY-*` |
| Credit/Refund | `BR-CREDIT-*`, `BR-REFUND-*` |
| Termination/Move-out | `BR-LEASE-017` through `BR-LEASE-025`, `BR-MOVEOUT-*` |
| Settlement | `BR-SETTLE-*` |
| Money/FX | `BR-MONEY-*` |
| Audit/Authorization | `BR-AUDIT-*`, `BR-AUTH-*` |

# 30. OPEN OWNER DECISION

## OOD-API-001 — Authentication Integration

**Question:** Which local or external authentication provider will production use?

**Current treatment:** The API specifies secure authentication properties and
capability enforcement independent of provider.

**Blocking:** No.

## OOD-API-002 — Exact Partial-period Rent Due Date

**Question:** If a first partial-month Rent Invoice is issued after that billed
month's recurring 5th-day due date, what exact Due Date applies?

**Current treatment:** The API returns and validates only the Due Date selected by
an authoritative rule or signed-Lease term. It does not invent a fallback. This
item remains open only if not resolved in `002_BUSINESS_RULES.md`.

**Blocking:** No for API structure; blocks final expected-value tests for that exact
scenario.

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
- genuine nonblocking provider/due-date questions remain explicit.
