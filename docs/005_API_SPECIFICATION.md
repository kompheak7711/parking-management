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
coordinates Reservation `COMPLETED` with the resulting Lease, Occupancy, Unit, and
continuing Security Deposit effects.

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

Lease-violation Warning, Termination Notice, and Move-out creation use only the
canonical API-067, API-068, and API-069 routes; API-038 defines no aliases for those
actions. Rent-specific nonpayment cases, 20-day warnings, 30-day Serious Nonpayment
Defaults, cures, and authorized follow-up use API-095 instead.

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

A debit Adjustment on a fully paid line returns 409 with the current line balance. A
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

The review endpoint returns the authoritative overdue balance at assessment, exact
default 10% proposal, calculated default amount, prior-decision state, and blocking
conditions without posting a Charge.

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

Allocation is an explicit manual authorized command with an eligible Invoice or
separate Late-payment Charge target and exact amount. Authorized staff confirm/post the
proposal or permitted designation. The server transaction checks Customer/currency/
context eligibility, Payment availability, target outstanding balance, and concurrency.
A Late-payment Charge allocation reduces only that separate Charge and never the source
Invoice. Reversal creates a linked event.

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

## API-063 — Apply and Reverse Credit

- `POST /customer-credits/{id}/applications`
- `POST /credit-applications/{id}/reverse`

Commands require an eligible Invoice or separate Late-payment Charge target, exact
amount/currency, authorization, and idempotency; they revalidate Credit availability
and target outstanding balance transactionally. A Late-payment Charge application
reduces only that separate Charge and never the source Invoice.

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

## API-066 — Refund Correction

`POST /refunds/{id}/verified-returns` records only value demonstrably returned after
an erroneous completed Refund under DB-REFUND-002. It requires exact returned
amount/currency, return timestamp/method reference, reason, authorization, actor,
and idempotency. Returns of USD Refunds use exact USD cents, not KHR conversion;
partial returns restore exact positive cents and cumulative value cannot exceed the
Refund. Preserve source KHR/FX history without rewriting it. It creates no collection
right and never erases the original outbound event. Generic PATCH/DELETE is
prohibited.

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

## API-096 — Login, MFA, and Logout

The authentication surface supports local username/password login, standards-based MFA
enrollment and challenge, recovery-code challenge, logout, and authenticated session
inspection. Owner and Manager cannot obtain normal privileged access before required MFA
enrollment/challenge; Staff may authenticate without MFA unless enabled for that
account. Responses, timing, and rate limits resist guessing and account enumeration.
SMS authentication or recovery is not exposed.

## API-097 — Session Lifetime

Browser sessions enforce a 30-minute inactivity timeout and a 24-hour absolute lifetime.
Activity cannot extend the absolute expiry. Logout, password/MFA recovery, account
disablement, and material privilege reduction revoke applicable sessions. High-risk
administration may require recent password authentication or an additional factor.

## API-098 — Recovery Codes

Recovery-code generation/presentation is available only in a protected authenticated
enrollment or regeneration flow, except for the one-time pre-authentication trust-root
operation governed by `API-100`. Codes are shown securely once, individually consumed,
not returned again, and reuse is rejected. Recovery actions are rate-limited,
enumeration-resistant, session-revoking where appropriate, and immutably audited.

## API-099 — Administrative Recovery

Authorized Owner administration may initiate controlled reset/recovery for Manager and
Staff accounts. Staff cannot reset/recover Owner or Manager credentials. This API does
not grant Manager recovery of Staff. Owner emergency recovery is server-side only and
is never an ordinary unauthenticated web endpoint.

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


### V1-055 move-out final Utility inputs — service boundary — 2026-09-29

No new HTTP route is delivered. `PostgresMoveOutFinalInputsService` records and reads final Utility inputs for a physical departure; wiring them into API-069 remains pending and must not add an endpoint outside API-068/069. The command intent names the new event, the current physical departure event, an optional superseded event, reason, authorization reference, evidence reference and one item per applicable Meter. Items reference existing Readings created through API-045 or approved broken-Meter estimates, or state an explicit unresolved reason. The command never creates a Reading. Service outcomes map as follows: unknown Property/Lease/source or missing capability on observation is not found; malformed, unsupported or contradicted items are invalid; changed sources, a superseded physical or correction source, a second root event and lock conflicts are conflicts; reuse of an idempotency key with a different intent is a key-reuse conflict; a missing capability on recording is an authorization failure. Exact replay returns the saved response. Responses state that no Reading or charge is created and that Utility and financial completion are not assessed.
