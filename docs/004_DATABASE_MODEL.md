# 004 - Database Model

**Project:** Property Rental Management System
**Document:** Database Model
**Version:** 1.0
**Status:** Owner Review
**Depends On:** `001_DOMAIN_MODEL.md`, `002_BUSINESS_RULES.md`, `003_PRODUCT_REQUIREMENTS.md`
**Database:** PostgreSQL
**Audience:** Product Owner, Software Architects, Backend Developers, Database Engineers, QA Engineers, Security Engineers

---

# 1. Purpose

This specification defines the authoritative PostgreSQL logical relational model for the Property Rental Management System. It translates the approved domain and business rules into tables, columns, types, nullability, keys, relationships, checks, uniqueness constraints, indexes, append-only financial events, audit persistence, and derived-value rules.

It does not add business policy. This model was derived from `001_DOMAIN_MODEL.md` and `002_BUSINESS_RULES.md`, then checked against the capabilities, workflows, quality requirements, and one-to-one detailed behavior in `003_PRODUCT_REQUIREMENTS.md`. A Product Requirement may refine required persistence behavior but may not override `001_DOMAIN_MODEL.md` or `002_BUSINESS_RULES.md` silently.

---

# 2. Authority and Requirement Conventions

## DB-GEN-001 — Upstream precedence

The model must conform to `001_DOMAIN_MODEL.md`, `002_BUSINESS_RULES.md`, and `003_PRODUCT_REQUIREMENTS.md`, in that order. Older unnumbered documents are not sources for this model.

## DB-GEN-002 — Stable database requirements

Every `DB-*` identifier in this document is a stable requirement. Renumbering or reusing an identifier for a different rule is prohibited.

## DB-GEN-003 — Logical names

Table and column names are normative logical PostgreSQL names. A migration may qualify them with an application schema, but it must not merge distinct business concepts or change cardinality.

## DB-GEN-004 — Enforcement classes

Each invariant is enforced by one or more of:

1. declarative PostgreSQL constraints;
2. partial or exclusion indexes;
3. a constraint trigger for cross-row or cross-table invariants; or
4. one serializable/row-locking application transaction when declarative enforcement is not possible.

An API-only pre-check is insufficient for an integrity invariant susceptible to concurrency.

## DB-GEN-005 — Extensions

`btree_gist` is required for exclusion constraints on UUID equality plus date-range overlap. UUID generation may use the platform-approved PostgreSQL UUID facility; callers may alternatively supply UUIDs.

---

# 3. Global Storage Conventions

## DB-TYPE-001 — Stable identity

Every entity and event uses `uuid` as its primary key. IDs are immutable and never reused.

## DB-TYPE-002 — Business identifiers

Human-readable numbers such as Invoice Number and Payment Number use `text`, are unique, immutable after official assignment, and do not replace UUID primary keys.

## DB-TYPE-003 — Dates and timestamps

Business calendar dates use `date`. Audit, approval, posting, issuance, and processing instants use `timestamptz`. PostgreSQL stores instants in UTC; Property-local date calculation uses
`properties.timezone_name`, constrained to the authoritative `Asia/Phnom_Penh` IANA
timezone.

## DB-TYPE-004 — Money

USD amounts use signed `bigint` integer cents and columns ending `_usd_cents`. KHR amounts use signed `bigint` whole riel and columns ending `_khr`. Original positive obligations and money-received amounts have `CHECK (amount > 0)`; signed correction events may be positive or negative only where explicitly defined.

All Invoice and Customer Credit accounting values are USD. Binary floating-point types are prohibited for authoritative monetary or rate calculations.

## DB-TYPE-005 — Quantities and rates

Meter readings and consumption quantities use `numeric(20,6)`. Utility unit rates use `numeric(20,8)` USD per measured unit. The ABA reference rate may use `numeric(20,6)` KHR/USD; the marked-up System Exchange Rate is stored as whole `bigint` KHR/USD after upward rounding.

## DB-TYPE-006 — Text and JSON

Names, numbers, descriptions, reasons, and memos use `text`. `jsonb` is permitted for immutable audit before/after snapshots and calculation traces, but not as a substitute for a relational foreign key, monetary column, status, or supported category.

## DB-TYPE-007 — Standard provenance columns

Mutable aggregate tables contain `created_at timestamptz NOT NULL`, `created_by uuid NOT NULL`, `updated_at timestamptz NOT NULL`, and `updated_by uuid NOT NULL`. Append-only event tables contain `occurred_at timestamptz NOT NULL` and `actor_id uuid NOT NULL` instead. Actor UUIDs refer to the unique local human account or service principal defined by the Security Model and the authentication-storage requirements below.

## DB-TYPE-008 — No normal hard deletion

Operational history, issued or void Invoices, Payments, Allocations, Credits, Deposits, Refunds, rate history, Settlements, and audit events must not be physically deleted in normal workflows. Statuses and explicit events represent lifecycle changes.

---

# 4. Relationship Overview

```text
property 1 ── * unit
unit 1 ── * reservation * ── 1 customer
reservation 1 ── 0..1 resulting lease
reservation 1 ── 1 security deposit
reservation 1 ── 1 reservation_deposit_acceptance
unit 1 ── * lease * ── 1 primary-tenant customer
lease 1 ── * lease_signer * ── 1 customer
lease 1 ── * occupancy * ── 1 customer
lease 1 ── * rent_nonpayment_case 1 ── * rent_nonpayment_event
unit 1 ── * utility_meter 1 ── * utility_reading
customer 1 ── * invoice
invoice * ── 0..1 lease
invoice 1 ── * invoice_line
invoice 1 ── 0..1 late_payment_decision 1 ── 0..1 late_payment_charge
invoice_line 1 ── * payment_allocation_detail * ── 1 payment_allocation ── 1 payment
late_payment_charge 1 ── * payment_allocation_detail
customer_credit 1 ── * customer_credit_application 1 ── * customer_credit_application_detail
payment 1 ── 1 receipt 1 ── * receipt_reprint
reservation/lease ── deposit 1 ── * deposit_receipt
terminated lease 1 ── 1 final_settlement
financial source 1 ── * refund
authoritative financial events ── read-only customer_account_ledger view
all significant records 1 ── * audit_event
```

## DB-REL-001 — Mandatory Invoice Customer, optional Lease

Every `invoices.customer_id` is `NOT NULL` and references exactly one Customer. `invoices.lease_id` is nullable and references at most one Lease. Lease association never substitutes for Customer ownership.

## DB-REL-002 — Lease-associated Invoice consistency

When `invoices.lease_id` is present, the Invoice Customer must be a financially responsible Lease Signer, its Unit and period/source facts must agree with that Lease, and the association may not later be added, removed, or replaced after issuance. Every Rent Invoice has a non-null applicable SIGNED Lease.

---

# 5. Property, Unit, and Customer Tables

## DB-PROP-001 — `properties`

Exactly one row exists per deployed database.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `name` | `text` | no | nonblank |
| `address_text` | `text` | yes | Property address |
| `timezone_name` | `text` | no | `CHECK (timezone_name = 'Asia/Phnom_Penh')` |
| `base_currency` | `text` | no | `CHECK (base_currency = 'USD')` |
| `one_time_charge_due_days` | `smallint` | no | default 7, `CHECK (BETWEEN 1 AND 90)`; calendar days added to the issue date of a one-time charge Invoice |
| provenance columns | as DB-TYPE-007 | no | mutable aggregate provenance |

A database constraint trigger rejects insertion when a Property row already exists. Property deletion is prohibited.

`one_time_charge_due_days` changes only through `app.set_one_time_charge_due_days`, which
follows the versioned Property update pattern (expected version, `updated_by`,
`updated_at`), requires the `property.manage` capability and writes an
`audit_events` row with the previous and resulting value and a mandatory reason. A
change applies to Invoices issued afterwards; issued Due Dates never change.

## DB-UNIT-001 — `units`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `property_id` | `uuid` | no | FK `properties(id) ON DELETE RESTRICT` |
| `unit_number` | `text` | no | nonblank |
| `floor` | `text` | no | attribute, not FK/entity |
| `unit_type` | `text` | no | `STUDIO`, `ONE_BEDROOM`, `TWO_BEDROOM`, `THREE_BEDROOM` |
| `status` | `text` | no | `VACANT`, `RESERVED`, `OCCUPIED`, `UNDER_MAINTENANCE`, `CLEANING`, `OUT_OF_SERVICE` |
| provenance columns | as DB-TYPE-007 | no | |

Constraints and indexes:

- `UNIQUE (property_id, unit_number)`.
- Index `units(property_id, status)`.
- Status is a stored operational summary; legal availability is derived under DB-DER-003.

## DB-CUST-001 — `customers`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `legal_name` | `text` | no | nonblank Customer Name |
| `phone_number` | `text` | yes | contact value |
| `email_address` | `text` | yes | contact value |
| `contact_address` | `text` | yes | contact value |
| `memo` | `text` | yes | |
| provenance columns | as DB-TYPE-007 | no | |

No Customer type/category column exists. Customer deletion is prohibited while
historical records exist and is not a normal workflow. Input validation and duplicate
matching remain a technical choice under TCD-DB-001; no unapproved mandatory contact
channel is introduced.

---

# 6. Reservation and Lease Tables

## DB-RES-001 — `reservations`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `unit_id` | `uuid` | no | FK `units(id) ON DELETE RESTRICT` |
| `customer_id` | `uuid` | no | FK `customers(id) ON DELETE RESTRICT` |
| `reservation_date` | `date` | no | actual business date |
| `agreed_monthly_rent_usd_cents` | `bigint` | no | positive; source for the normal 20% suggestion only |
| `original_expiration_date` | `date` | no | immutable |
| `effective_expiration_date` | `date` | no | current approved boundary |
| `status` | `text` | no | `ACTIVE`, `CANCELLED`, `COMPLETED` |
| `resulting_lease_id` | `uuid` | yes | unique FK `leases(id)`; deferred because Lease is declared below |
| `cancellation_reason_code` | `text` | yes | required only when CANCELLED |
| `cancellation_responsibility` | `text` | yes | `CUSTOMER` or `PROPERTY` only when CANCELLED; reason records expiration separately |
| `cancelled_at` | `timestamptz` | yes | required only when CANCELLED |
| `completed_at` | `timestamptz` | yes | required only when COMPLETED; transition instant after move-in succeeds |
| provenance columns | as DB-TYPE-007 | no | |

Checks and indexes:

- `effective_expiration_date >= original_expiration_date`.
- `agreed_monthly_rent_usd_cents > 0`; activation verifies active Deposit Receipts
  total exactly equals the explicitly accepted amount in DB-RES-003. Later receipts
  may satisfy the remaining full Deposit within five calendar days after the Lease
  Start Date. No comparison to a
  hard 20% minimum is permitted.
- initial expiration is no more than 21 calendar days after `reservation_date`.
- cancellation fields are all absent unless CANCELLED and required when CANCELLED.
- CANCELLED requires `resulting_lease_id IS NULL` and `completed_at IS NULL`.
- COMPLETED requires exactly one unique `resulting_lease_id` and non-null
  `completed_at`. ACTIVE may have zero or one resulting Lease while signing and
  move-in preparation are in progress, but `completed_at` remains null.
- Partial unique index `UNIQUE (unit_id) WHERE status = 'ACTIVE'`.
- Index `(customer_id, reservation_date DESC)` and `(status, effective_expiration_date)`.
- Lifecycle transitions are enforced by a trigger: ACTIVE to CANCELLED or COMPLETED
  only; both terminal states reject later transition. The COMPLETED transaction
  occurs when the resulting Lease becomes SIGNED and requires it to match the
  Reservation Unit and Customer relationship. It requires no Occupancy and no fully
  received Deposit. At transition the Reservation must remain unexpired on
  `effective_expiration_date`; Lease signing, Unit transition to `OCCUPIED`, and
  Reservation completion occur atomically under DB-TXN-002. A walk-in Lease has no
  Reservation. Historical Reservations completed at move-in remain valid. It never
  uses COMPLETED as a Lease or Occupancy status.

## DB-RES-002 — `reservation_extension_notices`

Append-only table.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `reservation_id` | `uuid` | no | FK `reservations(id) ON DELETE RESTRICT`, `UNIQUE` |
| `original_expiration_date` | `date` | no | snapshot |
| `previous_expiration_date` | `date` | no | snapshot |
| `new_expiration_date` | `date` | no | maximum 14 days after previous |
| `approved_at` | `timestamptz` | no | |
| `approved_by` | `uuid` | no | authorized actor |
| `reason_memo` | `text` | yes | |

The transaction inserting the Notice also updates `reservations.effective_expiration_date`. A deferred trigger verifies the Reservation was ACTIVE, unexpired, had fewer than 14 days remaining, had no prior Notice, and the stored snapshots match. Update/delete is prohibited.

## DB-RES-003 — `reservation_deposit_acceptances`

Immutable activation-threshold record: `id uuid PK`, `reservation_id uuid NOT NULL
UNIQUE FK reservations`, `suggested_rate_basis_points smallint NOT NULL CHECK (= 2000)`,
`suggested_amount_usd_cents bigint NOT NULL CHECK (>0)`,
`accepted_required_amount_usd_cents bigint NOT NULL CHECK (>0)`, `acceptance_kind text
NOT NULL CHECK IN ('NORMAL_SUGGESTION','AUTHORIZED_VARIANCE')`, `accepted_at
timestamptz NOT NULL`, `accepted_by uuid NOT NULL`, `reason text NOT NULL`,
`authorization_reference text NOT NULL`, and `calculation_trace jsonb NOT NULL`.

A constraint trigger recomputes the normal suggestion as 20% of the Reservation's
agreed monthly Rent using the approved USD-cent rule and verifies the stored suggestion
and trace. `AUTHORIZED_VARIANCE` is required exactly when the accepted amount differs
from the suggestion; the accepted amount may be below or above the suggestion. The row
does not change the full required Security Deposit in `deposits`. Update/delete is
prohibited so activation history cannot be rewritten.

### Signing outcome and signed-Lease move-in (migration `20261005_69`)

`lease_signing_outcomes` (one append-only row per Lease signed through
`app.sign_lease_with_reservation`) records the optional Reservation and holding deposit,
the Unit status before signing and `OCCUPIED` after it, the actor and the audit event.
Signing with a Reservation requires it ACTIVE, unexpired on the Asia/Phnom_Penh business
date, for the same Unit and Primary Tenant, and the Unit RESERVED; it completes the
Reservation and links its holding deposit to the Lease as the Security Deposit. A walk-in
signing occupies a VACANT, CLEANING or UNDER_MAINTENANCE Unit; a renewal of a predecessor on
an OCCUPIED Unit keeps it OCCUPIED; a RESERVED or OUT_OF_SERVICE Unit is rejected.
`lease_move_ins` and `lease_move_in_occupancy_links` record physical move-in for such
Leases through `app.record_signed_lease_move_in`, which only begins Occupancy and has no
payment gate. Leases signed before this migration keep `complete_reservation_move_in`.

### Unpaid Initial obligation termination (migration `20261005_70`)

Termination basis `UNPAID_INITIAL_OBLIGATION` requires governing reference `BR-LEASE-005`,
the signed clause reference, no warning letters, and, at termination time in
Asia/Phnom_Penh, a date after Lease Start plus five days with the Initial Rent or the
Security Deposit still unpaid. `unpaid_initial_termination_resolutions` (append-only, one per
termination event) records the cause `CUSTOMER_UNPAID_INITIAL_OBLIGATION`, the reason, the
actor and what was done. Never moved in: the Initial Rent Invoice is VOIDed when nothing
was applied or its unpaid lines are credited, and the Unit becomes VACANT or CLEANING with a
reason; the Pet Deposit and the COMPLETED Reservation are untouched. Since V1-056 slice 6
(migration `20261018_83`) the resolution no longer forfeits the Security Deposit: it stays
held until a forfeiture draft under rule `BR-LEASE-005`
(`lease_deposit_disposition_contexts.governing_rule` accepts it) is confirmed by a
`financial.approve` holder. Resolutions recorded before that migration keep the forfeiture
they recorded. Moved in: the Initial Invoice is kept and its Rent
is credited for the days after the termination date with BR-RENT-007 proration.

## DB-LEASE-001 — `leases`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `unit_id` | `uuid` | no | FK `units(id) ON DELETE RESTRICT` |
| `primary_tenant_id` | `uuid` | no | FK `customers(id) ON DELETE RESTRICT` |
| `status` | `text` | no | `DRAFTED`, `SIGNED`, `CANCELLED`, `TERMINATED` |
| `start_date` | `date` | yes | required before SIGNED |
| `end_date` | `date` | yes | required before SIGNED; greater than start |
| `monthly_rent_usd_cents` | `bigint` | yes | positive; required before SIGNED |
| `predecessor_lease_id` | `uuid` | yes | FK to prior non-overlapping Lease; unique when present |
| `signed_at` | `timestamptz` | yes | required when SIGNED/TERMINATED |
| `terminated_at` | `timestamptz` | yes | required when TERMINATED |
| `actual_termination_date` | `date` | yes | required when TERMINATED |
| `termination_reason` | `text` | yes | required when TERMINATED |
| provenance columns | as DB-TYPE-007 | no | |

Constraints and indexes:

- DRAFTED may transition only to SIGNED or CANCELLED; SIGNED only to TERMINATED; terminal states cannot transition.
- A deferred trigger requires the Primary Tenant to exist in `lease_signers` before SIGNED.
- A predecessor link requires the same Unit and a successor period beginning after
  the predecessor period. It records renewal lineage but infers no Deposit or
  financial transfer policy.
- Exclusion constraint using `daterange(start_date, end_date, '[]')`: `EXCLUDE USING gist (unit_id WITH =, daterange(...) WITH &&) WHERE (status = 'SIGNED')`. The same transaction changing to TERMINATED retains historical contractual dates but releases future exclusivity according to the approved actual termination process; application validation must still prevent invalid advance-billed periods.
- Index `(unit_id, status)` and `(primary_tenant_id, start_date DESC)`.
- No Lease column can override recurring Rent timing. Initial Rent is due seven
  calendar days after actual Move-in Date; recurring Rent is due on the fifth day of
  its billed calendar month. Non-recurring Invoice Due Dates retain their approved
  source in DB-INV-001.

The V1-055 termination command appends `lease_termination_contexts`, keyed by
and foreign-keyed to the exact existing `lease_commands.event_id`. It preserves
Property, actor, key, request digest, Lease/version, approved actual date, occurrence,
governing reference, reason and the complete signed-authority context. Required
context includes an explicit voluntary-early, Customer-violation or other signed-Lease
basis, signed provision, approved grounds, management authorization and source evidence.
Text is bounded and normalized consistently with the notice service.

Applicable notice evidence references the current same-Lease Notice and its context,
matching signed provision and grounds. Its documented period must have ended by the
actual termination date; no fixed period is assumed. An explicit signed-terms exception
is required when notice does not apply. Violation commands link at least three distinct
real general warning letters through `lease_termination_warning_sources`; dates,
signed provisions and communication remain required. Nonpayment milestones are not
substituted for these warning sources. Voluntary-early authority uses `BR-LEASE-021`
and an actual date before the original contractual End Date.

The context-bearing wrapper and existing termination function share the original
Lease/Unit locks, version/status/chronology checks and source-write protections.
Context, warning links, termination, original command and audit commit atomically.
The wrapper defers only its new context-to-command foreign key during the circular
insertion and validates it before returning, including for callers using immediate
constraints. Every new command requires matching context at the shared existing
termination boundary. The original eleven-argument entry point and unchanged absent-
context digest preserve exact historical replay; they do not admit fresh context-free
termination. Supplied context and every original command field remain exact replay
intent, with fresh active-human and Property checks at the wrapper.

The new context and warning-source rows are immutable. Runtime has only the narrow
command function, with no direct table or private-helper access. This stage performs no
Deposit disposition, invoice adjustment, physical Occupancy end, Unit-condition change
or Settlement completion; those remain separate authorized lifecycle actions.

## DB-LEASE-002 — `lease_signers`

Append-preserved once the Lease is SIGNED.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `lease_id` | `uuid` | no | FK `leases(id) ON DELETE RESTRICT` |
| `customer_id` | `uuid` | no | FK `customers(id) ON DELETE RESTRICT` |
| `signed_at` | `timestamptz` | yes | required before Lease SIGNED |
| `added_at` | `timestamptz` | no | |
| `added_by` | `uuid` | no | |

`UNIQUE (lease_id, customer_id)`. No responsibility percentage/amount column exists. Rows may be removed only while the Lease is DRAFTED and must be audit recorded; after signing they are immutable.

## DB-LEASE-003 — `occupancies`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `lease_id` | `uuid` | no | FK `leases(id) ON DELETE RESTRICT` |
| `customer_id` | `uuid` | no | FK `customers(id) ON DELETE RESTRICT` |
| `move_in_date` | `date` | no | actual business date |
| `move_out_date` | `date` | yes | actual physical end date |
| provenance columns | as DB-TYPE-007 | no | |

`CHECK (move_out_date IS NULL OR move_out_date >= move_in_date)`. Index `(lease_id, move_out_date)` and `(customer_id, move_in_date DESC)`. Absence of `move_out_date` means open occupancy. Occupancy has no debt/responsibility columns.

## DB-LEASE-004 — `termination_notices`

Append-only: `id uuid PK`, `lease_id uuid NOT NULL FK`, `notice_date date NOT NULL`, `intended_termination_date date NULL`, `notice_text text NOT NULL`, `governing_lease_provision text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`. A Notice never updates Lease status automatically.

The V1-055 notice service preserves legacy rows and appends a one-to-one
`lease_notice_contexts` row for each new command: positive `expected_lease_version`,
approved grounds, signed-Lease notice-period terms, source evidence, communication,
authorization reference and reason. Notice periods are recorded from the signed Lease;
no fixed period is invented. Notice dates must be finite, not before signing and not
after recording in the Property timezone. An optional intended date is not before the
notice. The Lease must be SIGNED or TERMINATED; historical recording does not change
its current status, contractual dates, actual termination or Occupancy.

Corrections append a new Notice with a unique optional `supersedes_notice_id` foreign
key to the latest earlier Notice for the same Lease. Original notice rows and context
are immutable. Reads distinguish current notice-only evidence, superseded evidence and
legacy notice-only evidence without added context. None is an automatic termination
decision, Move-out, charge, forfeiture or Refund.

`lease_notice_commands` stores the exact Property/actor/key, Lease/Notice source,
request digest and intent, original response and completion time. Commands require a
fresh active human, matching Property and trusted `leases.terminate` capability;
`leases.read` permits bounded scoped history. Exact replay returns the original result
before rechecking changed Lease versions or correction eligibility. A common Lease
lock serializes evidence checks with lifecycle actions and competing corrections.
Notice, context, command receipt and audit write atomically. Application roles have
only narrow function entry points and cannot write the evidence tables directly.

All required notice evidence text is nonblank, bounded and free of leading or
trailing whitespace, using the same Unicode whitespace contract as the Python
service. Internal tabs, line breaks and other whitespace remain unchanged. The
private database validator covers direct commands, context constraints and linked
notice/provision checks; it grants no additional application entry point.

## DB-LEASE-005 — `lease_violation_warnings`

Append-only: `id uuid PK`, `lease_id uuid NOT NULL FK`, `warning_sequence smallint NOT NULL CHECK (> 0)`, `violation_date date NOT NULL`, `warning_date date NOT NULL`, `violation_description text NOT NULL`, `lease_provision text NOT NULL`, `communication_record text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `UNIQUE (lease_id, warning_sequence)`. The authorized violation-termination transaction verifies at least three documented warnings without inventing the underlying termination right.

## DB-LEASE-006 — `lease_pet_approvals`

Append-preserved terms record: `id uuid PK`, `lease_id uuid NOT NULL FK`, `approved_date date NOT NULL`, `deposit_required_by_signed_terms boolean NOT NULL`, `pet_description text NULL`, `approved_at timestamptz NOT NULL`, `approved_by uuid NOT NULL`. It records approved pet terms and the applicable signed-term fact; multiple approval records still cannot create more than the Lease's one optional Pet Deposit. It does not create a general Pet entity or a penalty policy.

## DB-LEASE-007 — `lease_service_terms`

Signed-term applicability relation: `id uuid PK`, `lease_id uuid NOT NULL FK`,
`property_service_id uuid NOT NULL FK`, `applicable_from date NOT NULL`,
`applicable_through date NULL`, `service_approval_period_id uuid NOT NULL FK`,
`terms_reference text NOT NULL`, `recorded_at
timestamptz NOT NULL`, `recorded_by uuid NOT NULL`, and `UNIQUE (lease_id,
property_service_id, applicable_from)`. Dates remain within the Lease period. Rows
identify which configured and Owner-approved Services apply; their dates must be
contained by the approval period. Rates still come only from effective-dated
`service_rates`.

## DB-LEASE-008 — `rent_nonpayment_cases`

Relational source for Rent-specific delinquency: `id uuid PK`, `lease_id uuid NOT NULL
FK`, `customer_id uuid NOT NULL FK`, `invoice_id uuid NOT NULL FK`, `rent_invoice_line_id
uuid NOT NULL UNIQUE FK invoice_lines`, `due_date_snapshot date NOT NULL`, `opened_at
timestamptz NOT NULL`, and `opened_by uuid NOT NULL`. The referenced line must be an
issued, non-VOID Rent line for the same Lease, Invoice, and financially responsible
Customer. The case is separate from `lease_violation_warnings`; it is not opened from
total mixed-Invoice balance.

`nonpayment_day_one date` is required for cases opened under the current count: the
first day of the billed month. New cases require a RECURRING Rent Invoice; an Initial
Rent Invoice never opens a case. It is null for cases recorded before the change. `due_date_snapshot` keeps its recorded meaning. Existing cases and events are
never rewritten.

## DB-LEASE-009 — `rent_nonpayment_events`

Append-only case history: `id uuid PK`, `rent_nonpayment_case_id uuid NOT NULL FK`,
`event_kind text NOT NULL CHECK IN ('TWENTY_DAY_WARNING','THIRTY_DAY_SERIOUS_DEFAULT',
'CURE','AUTHORIZED_FOLLOW_UP')`, `event_date date NOT NULL`, `remaining_rent_usd_cents
bigint NOT NULL CHECK (>= 0)`, `notice_document_reference text NULL`, `reason text NOT
NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, and
`authorization_reference text NULL`.

Partial unique indexes permit at most one TWENTY_DAY_WARNING and one
THIRTY_DAY_SERIOUS_DEFAULT per case. Posting locks and recomputes the current Rent-line
balance from active line-aware Payment Allocations, Customer Credit applications,
Adjustments, and permitted Final Settlement Deposit applications. A warning requires a
positive amount on day 20 and a serious default on day 30, counted in Asia/Phnom_Penh
calendar days from day one, the 1st of the billed month (BR-LEASE-026). Implementation
(migration `20261004_68`): `app.rent_nonpayment_day_zero(invoice)` returns the day before
the 1st for recurring Rent and null for Initial Rent, so an Initial Rent case can never
reach day 20 or 30; cases accept only recurring Rent lines, and an earlier Initial Rent
case accepts only CURE and AUTHORIZED_FOLLOW_UP. `due_date_snapshot` and `days_overdue`
keep their Due Date meaning. Recorded cases and events are unchanged. TWENTY_DAY_WARNING requires a Notice/document
reference; AUTHORIZED_FOLLOW_UP requires an authorization reference. CURE stores zero
after a warning or default; later authorized follow-up remains explicit. No event
changes Lease, Occupancy, Unit, Move-out, or Final Settlement state automatically.

Milestone eligibility uses `nonpayment_day_one` when present.

## DB-LEASE-010 — `lease_pet_departures`

Append-only operational event: `id uuid PK`, `pet_approval_id uuid NOT NULL UNIQUE FK
lease_pet_approvals`, `lease_id uuid NOT NULL FK`, `permanently_left_date date NOT NULL`,
`reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, and `actor_id uuid NOT NULL`.
A deferred trigger requires the approval and Lease to match. This event records only the
permanent departure fact; it neither ends the Lease nor by itself authorizes a Refund.

## DB-LEASE-011 — `pet_deposit_refund_reviews`

Append-only qualifying review: `id uuid PK`, `pet_departure_id uuid NOT NULL UNIQUE FK
lease_pet_departures`, `pet_deposit_id uuid NOT NULL UNIQUE FK deposits`,
`obligations_reviewed_usd_cents bigint NOT NULL CHECK (>=0)`, `review_findings text NOT
NULL`, `all_pet_obligations_resolved boolean NOT NULL CHECK (= true)`,
`resolution_reference text NOT NULL`, `reason text NOT NULL`, `reviewed_at timestamptz
NOT NULL`, `reviewed_by uuid NOT NULL`, and `authorization_reference text NOT NULL`.
The review transaction verifies the Pet approval, departure, Deposit, Customer, and
SIGNED Lease all match and recomputes the remaining refundable Pet Deposit. This review
may qualify an active-Lease Refund; it neither ends the Lease nor caps Customer
liability.

---

# 7. Utility and Rate Tables

## DB-UTIL-001 — `utility_meters`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `unit_id` | `uuid` | no | FK `units(id) ON DELETE RESTRICT` |
| `serial_number` | `text` | no | nonblank |
| `utility_type` | `text` | no | `ELECTRICITY`, `WATER` |
| `measurement_unit_code` | `text` | no | configured physical unit such as the production-approved electricity or water unit; immutable after first Reading |
| `description` | `text` | yes | |
| `installed_date` | `date` | no | |
| `failure_date` | `date` | yes | confirmed failure date when broken |
| `deactivated_date` | `date` | yes | null while this Meter is active |
| `memo` | `text` | yes | |
| provenance columns | as DB-TYPE-007 | no | |

Constraints:

- Partial unique index `UNIQUE (unit_id, utility_type) WHERE deactivated_date IS NULL`.
- `deactivated_date >= installed_date`; `failure_date >= installed_date` when present;
  and `failure_date <= deactivated_date` when both are present.
- A replacement transaction sets the failed Meter's `deactivated_date` to the
  replacement date. This model introduces no non-replacement deactivation command
  and stores no unapproved Meter status.
- Serial uniqueness is not asserted because upstream policy does not define whether serials are globally reusable.
- Index `(unit_id, utility_type, installed_date DESC)`.

## DB-UTIL-002 — `utility_meter_replacements`

Append-only: `id uuid PK`, `failed_meter_id uuid NOT NULL UNIQUE FK utility_meters`, `replacement_meter_id uuid NOT NULL UNIQUE FK utility_meters`, `replacement_date date NOT NULL`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `CHECK (failed_meter_id <> replacement_meter_id)`. A deferred trigger requires the same Unit and Utility Type, a confirmed failure date on the failed Meter, deactivation on the replacement date, and installation of the replacement Meter on that date.

## DB-UTIL-003 — `utility_readings`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `meter_id` | `uuid` | no | FK `utility_meters(id) ON DELETE RESTRICT` |
| `reading_date` | `date` | no | |
| `reading_value` | `numeric(20,6)` | no | `CHECK (reading_value >= 0)` |
| `validated_at` | `timestamptz` | yes | both validation fields null before validation; both set after validation |
| `validated_by` | `uuid` | yes | authorized validating actor |
| provenance columns | as DB-TYPE-007 | no | |

`UNIQUE (meter_id, reading_date)`. Index `(meter_id, reading_date DESC)` and a
partial index where `validated_at IS NULL`. A Reading may become a billing source
only after both validation fields are set. Invalid input is rejected rather than
persisted under an invented Reading status. A validated reading must be later than
the prior validated reading and not lower than it. Reading correction uses
DB-UTIL-004 rather than overwriting a historical validated value.

## DB-UTIL-004 — `utility_reading_corrections`

Append-only: `id uuid PK`, `reading_id uuid NOT NULL FK`, `previous_value
numeric(20,6) NOT NULL`, `corrected_value numeric(20,6) NOT NULL CHECK (>= 0)`,
`reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, and
`authorization_reference text NOT NULL`. The effective Reading value is the latest
valid correction ordered by `occurred_at, id`; the original remains unchanged.

The correction transaction locks the Meter's Reading sequence and requires
`previous_value` to equal the current effective value. The corrected value must remain
valid against both adjacent effective Readings, preserve Meter/Unit identity, and yield
nonnegative Consumption. Each affected finalized Consumption Period gets one
DB-UTIL-009 impact row. Payment or Invoice payment status is never the correction
boundary; JSON is supplementary trace only. Any quantitative anomaly threshold beyond
nonnegative/ordered readings is deployment-configured validation, not a new consumption
formula or substitute Reading.

## DB-UTIL-005 — `utility_rates`

Append-only version table: `id uuid PK`, `property_id uuid NOT NULL FK`, `utility_type text NOT NULL CHECK IN ('ELECTRICITY','WATER')`, `measurement_unit_code text NOT NULL`, `rate_usd_per_unit numeric(20,8) NOT NULL CHECK (> 0)`, `effective_date date NOT NULL`, `notice_at timestamptz NOT NULL`, `notice_evidence text NOT NULL`, `source_memo text NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `UNIQUE (property_id, utility_type, effective_date)`. The configured unit must match the applicable Meter. The Property-local date of `notice_at` must precede `effective_date`. The selected row is the one with greatest `effective_date <= invoice_date`; selection is snapshotted on the Invoice line.

## DB-UTIL-006 — `utility_consumption_periods`

Authoritative billing-source record.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `unit_id` | `uuid` | no | FK |
| `utility_type` | `text` | no | supported values |
| `start_date` | `date` | no | inclusive |
| `end_date` | `date` | no | inclusive, >= start |
| `start_reading_id` | `uuid` | yes | FK; required for ACTUAL |
| `end_reading_id` | `uuid` | yes | FK; required for ACTUAL |
| `calculation_kind` | `text` | no | `ACTUAL`, `BROKEN_METER_ESTIMATE` |
| `consumption_quantity` | `numeric(20,6)` | no | `CHECK (>= 0)` |
| `calculation_trace` | `jsonb` | no | immutable operands/result |
| `finalized_at` | `timestamptz` | no | |
| `finalized_by` | `uuid` | no | |

- Actual periods require two readings of the same Meter and derive nonnegative consumption.
- Exclusion constraint prevents overlapping finalized periods for the same Unit and Utility Type.
- `UNIQUE (unit_id, utility_type, start_date, end_date)`.
- Update/delete after finalization is prohibited.

## DB-UTIL-007 — `broken_meter_estimates`

One-to-one finalized estimate detail: `id uuid PK`, `estimation_case_id uuid NOT NULL
UNIQUE FK broken_meter_estimation_cases`, `consumption_period_id uuid NOT NULL UNIQUE FK`,
`basis_kind
text NOT NULL CHECK IN ('LATEST_THREE_HISTORICAL','ALL_AVAILABLE_HISTORICAL_ONE_OR_TWO',
'FIRST_COMPLETE_FUTURE_ZERO_HISTORY')`, `historical_actual_period_count_at_selection
smallint NOT NULL CHECK (>= 0)`, `total_basis_consumption numeric(20,6) NOT NULL CHECK
(>=0)`, `total_basis_days integer NOT NULL CHECK (>0)`, `weighted_daily_average
numeric(20,10) NOT NULL CHECK (>=0)`, `estimated_consumption numeric(20,6) NOT NULL
CHECK (>=0)`, `authorization_reason text NOT NULL`, `authorized_at timestamptz NOT
NULL`, `authorized_by uuid NOT NULL`, `calculation_trace jsonb NOT NULL`.

## DB-UTIL-008 — `broken_meter_estimate_basis_periods`

Append-only junction: `broken_meter_estimate_id uuid NOT NULL FK`,
`basis_consumption_period_id uuid NOT NULL FK`, `basis_order smallint NOT NULL CHECK
(>0)`, PK `(broken_meter_estimate_id, basis_consumption_period_id)`, unique
`(broken_meter_estimate_id, basis_order)`. Deferred validation requires same Unit
and Utility Type, complete ACTUAL basis periods, and exactly:

- the latest three historical periods when three or more exist;
- all available historical periods when exactly one or two exist; or
- the first complete future actual period only when zero historical periods existed.

It rejects comparable-Unit, arbitrary, omitted one/two-period, or non-deterministically
selected basis data and reconciles the junction count to the stored basis kind and
historical-count snapshot.

## DB-UTIL-009 — `utility_reading_correction_impacts`

Append-only correction-impact junction: `id uuid PK`, `reading_correction_id uuid NOT
NULL FK`, `consumption_period_id uuid NOT NULL FK`, `previous_consumption_quantity
numeric(20,6) NOT NULL CHECK (>=0)`, `corrected_consumption_quantity numeric(20,6) NOT
NULL CHECK (>=0)`, `billing_effect_kind text NOT NULL CHECK IN
('PRE_ISSUANCE_INPUT','POST_ISSUANCE_NO_AMOUNT_CHANGE','POST_ISSUANCE_ADJUSTMENT')`,
`invoice_line_id uuid NULL FK`, `source_invoice_id uuid NULL FK`,
`calculated_difference_usd_cents bigint NULL`, `invoice_adjustment_id uuid NULL UNIQUE
FK`, `calculation_trace jsonb NOT NULL`, and `UNIQUE (reading_correction_id,
consumption_period_id)`. Every adjacent finalized period affected by one Reading
correction gets a row; therefore one correction may reach multiple periods, lines,
Invoices, and Adjustments. The original period remains immutable and its effective
quantity is the latest impact ordered by correction `occurred_at, id`.

Pre-issuance impact prohibits all Invoice/Adjustment FKs and supplies the corrected
billing input. Post-issuance impact requires the matching Invoice line and Invoice; zero
difference prohibits an Adjustment, while a nonzero difference requires the linked
DB-INV-003 row with equal signed effect. This preserves the complete Reading → impact →
period → line → original Invoice → Adjustment chain regardless of payment status.

## DB-UTIL-010 — `broken_meter_estimation_cases`

Append-only/open-case source: `id uuid PK`, `failed_meter_id uuid NOT NULL FK`,
`replacement_meter_id uuid NOT NULL FK`, `unit_id uuid NOT NULL FK`, `utility_type text
NOT NULL`, `unmeasured_start_date date NOT NULL`, `unmeasured_end_date date NOT NULL`,
`historical_actual_period_count_at_open smallint NOT NULL CHECK (>=0)`, `opened_reason
text NOT NULL`, `opened_at timestamptz NOT NULL`, `opened_by uuid NOT NULL`, and
`authorization_reference text NOT NULL`. Meter/Unit/Utility identity and unmeasured
boundaries are immutable. When the historical count is zero, this row persists the
required waiting condition with no finalized estimate or basis row until the first
complete future ACTUAL period exists. Finalization then atomically creates DB-UTIL-007,
the one DB-UTIL-008 future-basis row, and the estimated Consumption Period. One/two and
three-or-more historical branches may finalize immediately using their exact bases.

## DB-UTIL-011 — `utility_baseline_events`, `utility_baseline_items`, `utility_baseline_commands`

Append-only evidence of the Utility baseline Reading that starts a Customer's Utility
responsibility (BR-UTIL-018, DL-067). An event is `id uuid PK`, `property_id`, `lease_id`
and `unit_id uuid NOT NULL FK`, `baseline_date date NOT NULL`, `reason` and
`evidence_reference text NOT NULL` (a note or document reference of at most 500
characters; no photo or file storage), `supersedes_event_id uuid NULL UNIQUE FK`,
`occurred_at timestamptz NOT NULL` and `actor_id uuid NOT NULL`. A partial unique index
allows one root event per Lease. Each item is one Meter applicable on `baseline_date`
(installed on or before it and not deactivated before it), with its validated Reading
dated `baseline_date`, copied with its value, version and validation time; the item
list must cover every applicable Meter exactly once. The commands table stores the
idempotency key, request digest, intent, response and audit event of each command.

- The Lease must be SIGNED with no Occupancy yet, and `baseline_date` must be on or before the Lease Start Date, never after it.
- A new baseline after switching on again supersedes the current one and must be dated later; a superseded event cannot be superseded again.
- A baseline is rejected when its boundary (`baseline_date + 1`) would split a finalized Utility Consumption Period or an open broken-Meter case of the Unit.
- Update, delete and truncate are rejected; runtime database roles have no table privilege and reach the history only through `app.utility_baseline_record` and `app.utility_baseline_read`.
- The command writes one audit event `utility.baseline.record` under the existing capability `utility_readings.record`. It creates no Reading, period or charge.

**Responsibility boundary.** For a Lease with a current baseline, the Customer's
responsibility starts on `baseline_date + 1`; the Lease Start Date and the move-in date are
no longer boundaries. The Property bears all consumption before that date, including between
tenants, cleaning and repair, and for a tenant who never moves in. A Lease without a
baseline keeps its Lease Start Date and move-in boundaries and every earlier result.

**Monthly Utility run.** The Utility run bills one run per distinct set of period dates, so the
first partial period after a baseline (`baseline_date + 1` to the first month-end Reading) is
billed by its own run with those exact dates. For a period of a baseline Lease with no
Occupancy, the run records a SKIPPED item with the diagnostic `NOT_MOVED_IN`; for a period no
Lease covers, `PROPERTY_BORNE_CONSUMPTION`. Both are accepted outcomes of a successful run.
A Lease without a baseline and without a qualifying Occupancy still records the earlier
`UTILITY_PERSISTENCE_P0002` error.

## DB-UTIL-012 — `utility_invoice_commands`

Append-only command history for the final Utility Invoice and the catch-up Utility Invoice
(BR-UTIL-021, DL-067): `property_id`, `actor_id`, `idempotency_key` (PK), `action` (`FINAL` or
`CATCH_UP`), `lease_id`, `invoice_id UNIQUE`, `audit_event_id UNIQUE`, `final_input_event_id`
(required exactly for `FINAL`, unique among `FINAL` rows so one final Invoice exists per final-input
event), `request_digest`, `request_intent`, `response_body` and `occurred_at`. Runtime roles have no
table privilege and call only `app.utility_final_invoice_create` and
`app.utility_catch_up_invoice_create` as `prm_financial`.

- **Final Invoice:** for a TERMINATED Lease that moved in, with a current Slice B final-input event whose every Meter is resolved, it creates the missing ACTUAL period for each READING item (start Reading: the Meter's latest period end Reading, else the Lease's current baseline Reading, else the first Reading of a Meter installed during the Customer's responsibility), then bills every period the Customer is responsible for that has no Invoice line, in one Utility Invoice with one line per period.
- **Catch-up Invoice:** bills one period the monthly run skipped as `NOT_MOVED_IN`, only once the Lease has an Occupancy.
- Both set Due Date rule `ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS` and source `BR-UTIL-021`, issue the Invoice through `app.issue_invoice` (issue date plus the Property's configured days in the Property time zone, or an authorized override with a mandatory reason, actor and timestamp, fixed once issued) and never touch a period that already has an Invoice line. A Lease that never moved in stays unbilled.

## DB-UTIL-013 — Utility run overlap and unbilled periods

`billing_runs_period_no_overlap` now applies to Rent runs only. A Utility run bills only periods whose
exact dates equal the run's dates and an Invoice line is `UNIQUE` per consumption period, so Utility runs
with overlapping dates (a partial period after a baseline and a calendar month) coexist and cannot double
bill. A period finalized after a successful run for the same dates, or skipped as `NOT_MOVED_IN`, is never
picked up again; `app.utility_unbilled_periods` lists it (reason `LATE_AFTER_SUCCEEDED_RUN` or
`NOT_MOVED_IN`, and whether it can be caught up) and staff bill it only with the explicit catch-up command
(`invoices.issue`, DB-UTIL-012). No run is created automatically.

---

# 8. Configured Service Tables

## DB-SVC-001 — `property_services`

Supported/configured Service identity: `id uuid PK`, `property_id uuid NOT NULL FK`,
`service_code text NOT NULL`, `display_name text NOT NULL`, `configured_at timestamptz
NOT NULL`, `configured_by uuid NOT NULL`, provenance columns, `UNIQUE (property_id,
service_code)`. A nonblank configured code is not itself billable and is never a
free-form Invoice category.

The initial production configuration contains Trash Collection. Internet and Monthly
Cleaning have no approved active period and must not be seeded or treated as currently
provided. A future Service identity may be configured without becoming billable; its
approval period may be created only after a separate authoritative Owner-approved
Service rule and explicit authorization, never merely because staff entered a code.

## DB-SVC-002 — `service_rates`

Append-only: `id uuid PK`, `property_service_id uuid NOT NULL FK`, `monthly_rate_usd_cents bigint NOT NULL CHECK (>0)`, `effective_date date NOT NULL`, `source_memo text NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `UNIQUE (property_service_id, effective_date)`. The applicable rate is selected by billing-period start and snapshotted on the Invoice line.

## DB-SVC-003 — `property_service_approval_periods`

Append-preserved Owner-approved availability: `id uuid PK`, `property_service_id uuid NOT
NULL FK`, `effective_from date NOT NULL`, `effective_through date NULL`,
`approval_reference text NOT NULL`, `approved_at timestamptz NOT NULL`, `approved_by
uuid NOT NULL`, and `reason text NOT NULL`. Inclusive date ranges may not overlap for a
Service. An open period's `effective_through` may be set once through an audited,
authorized closure transaction; all other fields are immutable. A Lease Service Term
and every billed Service line must fall within one approval period.

---

# 9. Invoice Tables

## DB-INV-001 — `invoices`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `invoice_number` | `text` | no | unique, nonblank, never reused |
| `customer_id` | `uuid` | no | mandatory FK `customers(id) ON DELETE RESTRICT` |
| `lease_id` | `uuid` | yes | optional FK `leases(id) ON DELETE RESTRICT` |
| `primary_category` | `text` | no | `RENT`, `UTILITIES`, `SERVICE_CHARGES`, `DAMAGE_CHARGES`, `MISCELLANEOUS_CHARGES` |
| `status` | `text` | no | `DRAFT`, `UNPAID`, `PARTIALLY_PAID`, `PAID`, `VOID` |
| `invoice_date` | `date` | no | permanent on issuance |
| `due_date` | `date` | yes | null only while `status='DRAFT'` (CHECK); set at issuance and immutable afterwards |
| `billing_period_start` | `date` | yes | both or neither with end |
| `billing_period_end` | `date` | yes | inclusive, >= start |
| `rent_billing_kind` | `text` | yes | `INITIAL` or `RECURRING`; required exactly when the Invoice contains Rent |
| `original_total_usd_cents` | `bigint` | no | `CHECK (>= 0)`; immutable after issuance |
| `due_date_rule` | `text` | no | `INITIAL_RENT_LEASE_START_PLUS_FIVE`, `RECURRING_RENT_FIFTH`, `ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS`, or `GOVERNING_SOURCE`; historical rows keep `INITIAL_RENT_SEVEN_DAYS` or `GOVERNING_SOURCE` as evidence |
| `due_date_override_reason` | `text` | yes | required with `due_date_set_by` and `due_date_set_at` when an authorized user replaces the proposed Due Date; all three present or all absent |
| `due_date_set_by` | `uuid` | yes | actor who set the override |
| `due_date_set_at` | `timestamptz` | yes | time of the override |
| `due_date_source` | `text` | no | approved rule/event/document trace; never a Lease override |
| `issued_at` | `timestamptz` | yes | required unless DRAFT |
| `issued_by` | `uuid` | yes | required unless DRAFT |
| provenance columns | as DB-TYPE-007 | no | |

Constraints and indexes:

- `UNIQUE (invoice_number)` and `UNIQUE (id, lease_id)` to support consistency references.
- Rent requires non-null `lease_id`, period dates, and applicable SIGNED Lease.
- INITIAL Rent under the current rule references the signed Lease through `lease_id`;
  `source_occupancy_id` is null for new Initial Rent Invoices and retained on historical
  rows. Its proposed Due Date is the Lease Start Date plus five calendar days; a
  different Due Date requires the override columns. The Due Date is fixed once issued.
  One-time Damage, Miscellaneous and final Utility Invoices propose the issue date plus
  the Property's configured `one_time_charge_due_days`, seven by default. Its period begins on the Lease Start Date and ends at that month-end
  for days 1–20, or at the following month-end for days 21 or later.
- RECURRING Rent covers one complete calendar month and is due on that month's fifth
  day. The standard is policy, not an optional Lease term. Other obligations use only
  an approved `GOVERNING_SOURCE` Due Date.
- Invoice Customer/Lease consistency is enforced by deferred trigger against `lease_signers` and line sources.
- Lifecycle transitions follow BR-INV-015. UNPAID/PARTIALLY_PAID/PAID is reconciled to the derived balance after every financial application/reversal/Adjustment.
- Once issued, Customer, Lease association or absence, Invoice Number, date, category, period, due date/source, and original total are immutable.
- Index `(customer_id, status, due_date, issued_at, invoice_number)` supports deterministic FIFO; index `(lease_id, invoice_date)` where Lease is present.

## DB-INV-002 — `invoice_lines`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `invoice_id` | `uuid` | no | FK `invoices(id) ON DELETE RESTRICT` |
| `line_sequence` | `smallint` | no | `CHECK (>0)` |
| `category` | `text` | no | same supported category set |
| `description` | `text` | no | nonblank |
| `amount_usd_cents` | `bigint` | no | `CHECK (>0)` |
| `period_start` | `date` | yes | both/neither with end |
| `period_end` | `date` | yes | inclusive, >= start |
| `source_lease_id` | `uuid` | yes | FK |
| `utility_consumption_period_id` | `uuid` | yes | FK, unique when present |
| `utility_rate_id` | `uuid` | yes | FK |
| `property_service_id` | `uuid` | yes | FK |
| `service_rate_id` | `uuid` | yes | FK |
| `lease_service_term_id` | `uuid` | yes | FK proving configured Service applicability |
| `service_approval_period_id` | `uuid` | yes | FK proving Owner-approved Service availability |
| `authorized_obligation_id` | `uuid` | yes | FK for Damage/Miscellaneous source |
| `contractual_monthly_usd_cents` | `bigint` | yes | rent/service trace input |
| `billable_days` | `smallint` | yes | proration input |
| `calendar_days` | `smallint` | yes | 28..31 when present |
| `quantity` | `numeric(20,6)` | yes | utility input |
| `unit_rate_usd` | `numeric(20,8)` | yes | selected rate snapshot |
| `calculation_trace` | `jsonb` | no | exact operands, rounding, final result |
| `created_at` | `timestamptz` | no | |
| `created_by` | `uuid` | no | |

- `UNIQUE (invoice_id, line_sequence)`.
- Rent lines require source Lease, contractual monthly Rent, and period; the source Lease equals `invoices.lease_id`.
- Utility lines require consumption period, Utility Rate, quantity, unit-rate snapshot, and period.
- Service lines require configured Service, applicable Lease Service term, Service
  approval period, component-level applicable Service Rate(s), monthly rate snapshot(s),
  and period.
- A single-rate Service line stores the common `service_rate_id` and line snapshot. If
  day-21-or-later components select different effective rates, those line-level fields
  are null and every component's relational rate FK/snapshot in DB-INV-006 is required.
- Damage/Miscellaneous lines require one `authorized_nonrecurring_obligations` row;
  `calculation_trace` supplements and never replaces that relational source.
- Service line category remains SERVICE_CHARGES even on a primary RENT Invoice.
- Lines become immutable when their Invoice is issued.
- A GiST exclusion constraint on `source_lease_id` equality and inclusive `daterange(period_start, period_end, '[]')` overlap where `category='RENT'` prevents duplicate or overlapping Rent billing.
- A GiST exclusion constraint on `source_lease_id`, `property_service_id`, and inclusive
  `daterange(period_start, period_end, '[]')` overlap where
  `category='SERVICE_CHARGES'` prevents duplicate or overlapping Service billing.
- Unique `utility_consumption_period_id` prevents duplicate Utility billing.
- A deferred issuance trigger requires `invoices.original_total_usd_cents = sum(invoice_lines.amount_usd_cents)` and at least one line before an Invoice leaves DRAFT.
- Initial Rent and every applicable recurring-Service line share the Initial Invoice,
  complete approved coverage period, and seven-day Due Date. For move-in days 21 or
  later, each such line has two DB-INV-006 components: prorated move-in-month remainder
  and complete following month. Recurring generation resumes on the 25th before the
  first uncovered complete month. The existing Rent exclusion and Service uniqueness
  constraints reject overlap or duplicate coverage.

## DB-INV-003 — `invoice_adjustments`

Append-only financial event.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `invoice_id` | `uuid` | no | FK |
| `invoice_line_id` | `uuid` | no | FK; line belongs to the same Invoice |
| `adjustment_type` | `text` | no | `DEBIT`, `CREDIT` |
| `amount_usd_cents` | `bigint` | no | `CHECK (>0)` |
| `source_reference` | `text` | no | human-readable approved-source evidence; never sole identity when a typed source exists |
| `reason` | `text` | no | |
| `occurred_at` | `timestamptz` | no | |
| `actor_id` | `uuid` | no | |
| `authorization_reference` | `text` | no | |

An Adjustment changes current obligation by signed effect (`DEBIT` positive, `CREDIT` negative) without changing original Invoice/line values. Update/delete is prohibited.
Utility corrections link relationally through DB-UTIL-009; non-recurring obligation
identity remains on the source Invoice line. Any later modeled authoritative source must
use a typed FK/junction rather than relying on this narrative reference or JSON.

A new debit Adjustment requires its line's remaining balance to be positive at insertion,
checked under the Invoice lock. A new credit Adjustment's amount beyond the line's
remaining balance is recorded as Customer Credit in the same transaction. The final
late-payment decision acquires the same Invoice lock, so an Adjustment and the decision
are strictly ordered.

Implementation (migration `20261003_66`): `app.adjust_invoice` rejects a debit while
`app.invoice_line_outstanding(line)` is zero (`P4509`, message carries the line balance),
and `app.validate_invoice_adjustment_effect()` rejects a direct debit row whose line
balance before the debit is not positive at its `occurred_at`. Applied Payments and
applied Customer Credit both count as paid; a reversal of either restores the balance and
so reopens the line. No schema changes.

Implementation (migration `20261003_67`): a credit larger than the line's adjusted
obligation is rejected. For a credit beyond the line's remaining balance,
`app.adjust_invoice` reverses whole Payment allocations and Customer Credit applications
on that line, newest first, until the excess is covered, then records the Adjustment,
re-posts each reversed source minus the released part (same basis, designation and
other lines), and recognizes released Payment value as `customer_credits` of the
Invoice Customer. Value released from a Credit application returns to that Credit.
Reversals, replacements and recognized Credit all carry the reason "Invoice adjustment
credit excess". The append-only `invoice_credit_excess_releases` table links the
Adjustment, the reversed source, its replacement, the released cents and the Credit;
recognition skips the open-Invoice excess eligibility check only for such a linked row.
Original allocations, Payments, receipts, late-payment decisions and Charges and Rent
nonpayment records are never edited.

## DB-INV-004 — `invoice_void_events`

Append-only: `id uuid PK`, `invoice_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. The posting transaction verifies all active financial dependencies have been explicitly resolved and sets Invoice status VOID without deleting source records.

## DB-INV-005 — `authorized_nonrecurring_obligations`

Relational source for approved Damage or Miscellaneous charges: `id uuid PK`,
`customer_id uuid NOT NULL FK`, `lease_id uuid NULL FK`, `category text NOT NULL
CHECK IN ('DAMAGE_CHARGES','MISCELLANEOUS_CHARGES')`,
`inspection_damage_finding_id uuid NULL FK`, `description text NOT NULL`,
`authorized_amount_usd_cents bigint NOT NULL CHECK (>0)`, `source_reference text NOT
NULL`, `authorized_at timestamptz NOT NULL`, `authorized_by uuid NOT NULL`, and
`authorization_reference text NOT NULL`. Damage requires one inspection finding;
Miscellaneous prohibits it and requires another approved governing source in
`source_reference`.

`due_date_rule text NOT NULL DEFAULT 'GOVERNING_SOURCE'` distinguishes historical rows,
which keep their `governing_due_date` unchanged, from manual one-time charges
(`ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS`), recorded by `app.record_one_time_charge` with
`governing_due_date` null, `due_date_source='BR-INV-018'`, mandatory `reason` and text
`evidence_reference`, and a linked `audit_event_id`. Their Invoice DRAFT has no Due
Date; issue sets it to the Property-local issue date plus
`properties.one_time_charge_due_days`, or to an authorized date with a mandatory reason
recorded in the Invoice override columns (never before the issue date). Damage rows
must use the one-time rule and a Lease; a finding of a superseded inspection is not
billable. Invoice Customer/Lease/category/amount must equal the obligation,
and an obligation may be billed once. Pet-related use is derived only through the
linked finding's `pet_related` flag. This relation creates no new fee, penalty,
category, or charging right.

## DB-INV-006 — `invoice_line_calculation_components`

Immutable relational calculation detail: `id uuid PK`, `invoice_line_id uuid NOT NULL
FK`, `component_sequence smallint NOT NULL CHECK (>0)`, `component_kind text NOT NULL
CHECK IN ('PRORATED_MOVE_IN_MONTH','FULL_FOLLOWING_MONTH','FULL_RECURRING_MONTH',
'OTHER_APPROVED_COMPONENT')`, `period_start date NOT NULL`, `period_end date NOT NULL
CHECK (period_end >= period_start)`, `contractual_monthly_usd_cents bigint NULL CHECK
(>0)`, `service_rate_id uuid NULL FK service_rates`, `service_monthly_rate_usd_cents
bigint NULL CHECK (>0)`, `billable_days smallint NULL CHECK (>0)`, `calendar_days smallint NULL CHECK
(calendar_days BETWEEN 28 AND 31)`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, and
`calculation_trace jsonb NOT NULL`, with `UNIQUE (invoice_line_id,
component_sequence)`.

Components are not independent obligations: `invoice_lines.id` remains authoritative
line identity. A deferred issuance trigger requires non-overlapping component periods,
their inclusive union to equal the line period, and their amounts to sum to the line
amount. Initial Rent and recurring-Service lines require the exact one- or two-component
shape described above. Each Service component preserves and validates its own applicable
effective rate, including a rate change between the move-in remainder and following
month. Every Service component must lie within the parent line, one Owner-approved
Service period, the applicable Lease Service term, and its component rate's effective
period. This preserves the 27 July–31 August example without inventing a second Invoice
or business split.

### Termination Invoice reconciliation observation (V1-055)

`app.lease_termination_invoice_readiness(Property, Lease, actor, limit, after_line_id)`
is an additive STABLE, SECURITY DEFINER read with fixed `pg_catalog` search path.
The service requires both `leases.read` and `invoices.read` for the same Property
before connecting; the database freshly checks the active HUMAN and exact Lease
Property. A repeatable-read read-only transaction uses bounded connection, lock
and statement timeouts and UTC.

The observation identifies the original termination command, approved actual date,
signed monthly Rent and verified voluntary-early evidence. The command must match
the Lease occurrence, reason, Property, status and actual date. Any present signed
context must match all original command identity/digest fields and valid context
shape. Status or free text alone cannot establish the BR-RENT-024 full-month rule;
genuine pre-context historical commands remain readable.

UUID-keyset pages contain existing Lease Invoice lines from every category,
including DRAFT and VOID history. Original amounts, component periods/rates/amounts,
Invoice versions and relational source identities remain distinct from current
adjusted obligation, active Payment and Customer Credit application values,
outstanding balance and active Adjustment count. Reuse the existing protected
financial functions; never rewrite or recalculate the original charge. Components
remain detail of a line, not additional financial obligations.

The root `primary_tenant_id` identifies the Lease Primary Tenant; each Invoice
line retains its own actual `customer_id`, including another financially
responsible signed Lease Customer. Invoice Property and signed ownership follow
the existing source/issuance chronology checks, including legitimate never-issued
VOID history. Issued Rent/Service responses require original components with
compatible category/rate evidence; unissued history is not treated as completed
calculation evidence. PAID requires zero outstanding on every returned line;
UNPAID forbids active applications on that line. PARTIALLY_PAID or zero-adjusted
lines cannot establish whole-Invoice totals from a page.

Original Rent coverage is classified before, within, after, or spanning the final
and later months only for verified voluntary early termination. Other sources and
VOID history remain explicit. Coverage does not calculate an Adjustment amount,
declare services invalid, or authorize VOID. Invoice metadata versions alone are
not complete financial concurrency preconditions. Existing controlled commands
must still revalidate every applicable dependency under BR-INV-024.

Each page has at most100 lines and each line at most100 original components;
component overflow fails explicitly rather than omitting evidence. Each page is a
separate observation, with no whole-Lease total or cross-page snapshot guarantee.
`financial_completion_assessed` and `financial_dependencies_fully_assessed` are
always false. Controlled financial corrections, physical workflows, staff transport
and integrated V1-055 acceptance remain separate gates.

## DB-INV-007 — `late_payment_decisions`

One immutable final decision per applicable overdue Invoice: `id uuid PK`,
`source_invoice_id uuid NOT NULL UNIQUE FK invoices`, `customer_id uuid NOT NULL FK`,
`source_due_date date NOT NULL`, `overdue_balance_at_assessment_usd_cents bigint NOT
NULL CHECK (>0)`, `default_rate_basis_points smallint NOT NULL CHECK (= 1000)`,
`calculated_default_amount_usd_cents bigint NOT NULL CHECK (>= 0)`, `decision_outcome
text NOT NULL CHECK IN ('CONFIRMED_DEFAULT','REDUCED','WAIVED')`,
`approved_amount_usd_cents bigint NOT NULL CHECK (>= 0)`, `assessed_at timestamptz NOT
NULL`, `finalized_at timestamptz NOT NULL`, `finalized_by uuid NOT NULL`, `reason text
NOT NULL`, `authorization_reference text NOT NULL`, and `calculation_trace jsonb NOT
NULL`.

The approved monetary amount is authoritative. For a REDUCED decision, any effective
approved percentage is derived losslessly from `approved_amount_usd_cents` divided by
`overdue_balance_at_assessment_usd_cents` when needed; the database must not impose an
additional percentage precision or rounding restriction. The normal/default 10% remains
represented exactly by `default_rate_basis_points = 1000`.

A deferred trigger locks the source Invoice, verifies Customer and Due Date snapshots,
recomputes its remaining overdue balance and 10% default proposal at assessment, and
enforces outcome/amount consistency. WAIVED requires zero; CONFIRMED_DEFAULT requires
the calculated default amount; REDUCED requires a positive amount below the calculated
default amount. Once final,
the row cannot be repeated, replaced, supplemented, updated, or deleted.

## DB-INV-008 — `late_payment_charges`

Separate positive confirmed obligation: `id uuid PK`, `customer_id uuid NOT NULL FK`,
`source_invoice_id uuid NOT NULL UNIQUE FK invoices`, `late_payment_decision_id uuid
NOT NULL UNIQUE FK late_payment_decisions`, `original_amount_usd_cents bigint NOT NULL
CHECK (>0)`, `payable_at timestamptz NOT NULL`, `created_at timestamptz NOT NULL`, and
`created_by uuid NOT NULL`. It exists exactly when the final decision amount is
positive; Customer, source Invoice, amount, and confirmation instant must match that
decision. Original columns are immutable.

This table has no Due Date and is not an Invoice, Invoice line/category, or
Miscellaneous Charge. It never changes source Invoice principal, lines, balance, or
status and is not eligible to produce another late-payment decision or Charge.

## DB-INV-009 — `late_payment_charge_corrections`

Append-only correction/reversal history: `id uuid PK`, `late_payment_charge_id uuid NOT
NULL FK`, `correction_kind text NOT NULL CHECK IN ('REDUCTION','CHARGE_REVERSAL',
'REDUCTION_REVERSAL')`, `amount_usd_cents bigint NOT NULL CHECK (>0)`,
`reverses_correction_id uuid NULL UNIQUE FK late_payment_charge_corrections`, `reason
text NOT NULL`, `previous_obligation_usd_cents bigint NOT NULL CHECK (>= 0)`,
`resulting_obligation_usd_cents bigint NOT NULL CHECK (>= 0)`, `occurred_at timestamptz
NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`, and
`correlation_id uuid NOT NULL`. A reduction reversal must reference exactly
one active REDUCTION; other kinds prohibit that FK. Deferred validation prevents the
adjusted obligation from falling below zero or exceeding the immutable original
amount, verifies previous/resulting snapshots, and requires any now-excess Payment or
Credit applications to be explicitly reversed in the same correlated transaction. No
correction may supplement the final decision or create a new Charge.

## DB-INV-010 — `invoice_adjustment_reversals`

Append-only explicit reversal: `id uuid PK`, `invoice_adjustment_id uuid NOT NULL UNIQUE
FK invoice_adjustments`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`,
`actor_id uuid NOT NULL`, and `authorization_reference text NOT NULL`. It removes the
Adjustment's derived effect without changing the original Adjustment, Invoice, or line.
The transaction locks and recomputes the line/Invoice and rejects any resulting negative
balance or inconsistent application; status regression is derived under DB-DER-001.

---

# 10. Payment, Exchange, Allocation, and Credit Tables

## DB-PAY-001 — `payment_methods`

Configured data: `id uuid PK`, `code text NOT NULL UNIQUE`, `display_name text NOT NULL`, `accepted boolean NOT NULL`, provenance columns. Historical Payments retain the selected row and immutable method-code/name snapshots below even if the method is retired.

## DB-PAY-002 — `exchange_rate_records`

Append-only System Exchange Rate record selected at KHR Payment confirmation;
not a new Refund conversion under DL-060: `id uuid PK`, `reference_rate_khr_per_usd numeric(20,6) NOT NULL CHECK
(>0)`, `markup_basis_points smallint NOT NULL CHECK (= 50)`, `system_rate_khr_per_usd
bigint NOT NULL CHECK (>0)`, `rate_source text NOT NULL CHECK IN
('ABA_AUTOMATIC','ABA_EQUIVALENT_MANUAL')`, `source_reference text NULL`, `applicable_at
timestamptz NOT NULL`, `entered_by uuid NULL`, `channel_actual_currency text NULL`,
`channel_actual_amount_minor bigint NULL CHECK (>0)`, `channel_actual_usd_value_cents
bigint NULL CHECK (>0)`, `channel_actual_rate_khr_per_usd numeric(20,6) NULL CHECK (>0)`,
`channel_transaction_reference text NULL`, `channel_confirmed_at timestamptz NULL`, and
`calculation_trace jsonb NOT NULL`. Manual ABA-equivalent records require `entered_by`;
every System Rate equals the ABA-equivalent reference × 1.005 rounded upward to whole
KHR. Any channel-actual value supplied by the accepted channel is preserved; presence
of any such value requires transaction reference and timestamp, while unavailable
values remain null rather than fabricated. Supplied values match and control the linked
Payment without overwriting the separately preserved System Rate. Preserve existing
historical exchange evidence; all new Refunds are paid and recorded in USD.

## DB-PAY-003 — `payments`

Append-only authoritative money-received record plus controlled reversal status.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `payment_number` | `text` | no | unique, immutable |
| `property_id` | `uuid` | no | immutable Property scope; intent sources must agree |
| `payer_customer_id` | `uuid` | no | FK Customers |
| `lease_id` | `uuid` | yes | optional intent/context FK |
| `payment_scope_kind` | `text` | no | `NORMAL_CUSTOMER` or `THIRD_PARTY_IDENTIFIED` |
| `identified_invoice_id` | `uuid` | yes | explicit third-party/customer intent FK when applicable |
| `identified_late_payment_charge_id` | `uuid` | yes | explicit Charge intent FK when applicable |
| `payment_date` | `date` | no | actual money-received business date |
| `payment_method_id` | `uuid` | no | FK configured method |
| `payment_method_code_snapshot` | `text` | no | immutable |
| `payment_method_name_snapshot` | `text` | no | immutable display name at Payment confirmation |
| `received_currency` | `text` | no | `USD`, `KHR` |
| `received_amount_minor` | `bigint` | no | cents for USD, whole riel for KHR; positive |
| `usd_accounting_value_cents` | `bigint` | no | positive |
| `exchange_rate_record_id` | `uuid` | yes | required exactly for KHR |
| `channel_transaction_reference` | `text` | yes | immutable authoritative payment-channel reference when one exists |
| `payer_intent_memo` | `text` | yes | designation evidence |
| `status` | `text` | no | `RECEIVED`, `REVERSED` |
| `confirmed_at` | `timestamptz` | no | |
| `confirmed_by` | `uuid` | no | |
| `authorization_reference` | `text` | no | immutable bounded confirmation authority |

Original columns are immutable. Only status may change, and only through DB-PAY-006.
Normal Customer scope limits default proposals to the payer Customer's applicable
obligations; any identified Invoice or Charge must belong to that Customer. Third-party
scope requires at least one identified Invoice, Lease, or Charge intent, validates its
Customer/Lease relationships, and prohibits spreading value across unrelated
obligations of payer or beneficiary.
Index `(payer_customer_id, payment_date DESC)` and partial index on RECEIVED.

Persistence uses an internal `payment_serialization_guards` row per Payment. Funding
and reversal update its MVCC revision before checking append-only active consumption,
so stale repeatable-read/serializable snapshots fail rather than double-consume value.
This row is coordination metadata, not financial truth, and application roles cannot
write it directly. Confirmed Invoice intent also serializes against draft source
correction; a draft cannot be reassigned to a different Customer/Lease after it is
referenced by an immutable Payment. Reversal timestamps cannot precede the latest
prerequisite Deposit receipt, receipt reversal, or applicable Refund correction.

## DB-PAY-004 — `payment_allocations`

Append-only authorized posting header: `id uuid PK`, `payment_id uuid NOT NULL FK`,
`target_customer_id uuid NOT NULL FK customers`, `proposal_batch_id uuid NULL`,
`between_invoice_sequence smallint NULL CHECK (>0)`,
`target_kind text NOT NULL CHECK IN ('INVOICE','LATE_PAYMENT_CHARGE')`, `invoice_id uuid
NULL FK`, `late_payment_charge_id uuid NULL FK`, `amount_usd_cents bigint NOT NULL CHECK
(>0)`, `between_invoice_basis text NOT NULL CHECK IN ('FIFO_PROPOSAL',
'CUSTOMER_DESIGNATED','THIRD_PARTY_DESIGNATED','DIRECT_LATE_PAYMENT_CHARGE')`, `within_invoice_basis text NOT
NULL CHECK IN ('RENT_THEN_RECURRING_SERVICES_PROPOSAL','CUSTOMER_DESIGNATED',
'OTHER_APPLICABLE_OBLIGATION','NOT_APPLICABLE')`, `customer_designation_reference text
NULL`, `selected_invoice_due_date date NULL`, `selected_invoice_issued_at timestamptz
NULL`, `selected_invoice_number_snapshot text NULL`, `proposal_generated_at timestamptz
NULL`, `proposal_trace jsonb NULL`,
`posted_at timestamptz NOT NULL`, `posted_by uuid NOT NULL`, and
`authorization_reference text NOT NULL`, with a partial `UNIQUE (payment_id,
proposal_batch_id, between_invoice_sequence) WHERE proposal_batch_id IS NOT NULL`.

Exactly one target FK is present and agrees with `target_kind`. For an Invoice target,
all DB-PAY-007 detail lines belong to that one issued Invoice. FIFO proposal provenance
preserves and verifies Due Date, then issuance timestamp, then Invoice Number in the
three relational snapshot columns; `proposal_trace` supplements those facts.
The within-Invoice proposal separately orders Rent before recurring Services and does
not reorder multiple Invoices. A valid Customer or third-party designation requires its
reference and may select the Invoice/Charge instead of FIFO, select a line/category
within an Invoice, or do both. For a Charge,
the Charge FK is the direct target and both Invoice-order fields are not applicable.
Target Customer must own the selected obligation and satisfy the Payment's normal or
third-party scope. A batch and sequence reconstruct one cross-Invoice proposal without
turning its within-Invoice ordering into between-Invoice policy.

Proposal batch/sequence, generated-at, relational Invoice-order snapshots, trace, and
detail proposed amounts are required exactly for a generated proposal. They are absent
for direct Customer/third-party designations and direct Charge posting, so the database
never fabricates proposal provenance.

Posting locks Payment and every target/detail row, rejects amount above remaining
Payment or target obligation, requires detail totals to equal header amount, and records
authorized confirmation. A generated proposal never posts or authorizes itself.
Update/delete is prohibited.

V1-056 slice 7 (migration `20261020_85`, BR-PAY-042): `between_invoice_basis` also allows `WRONG_UNIT_MOVE`. Only a confirmed wrong-Unit Payment move (DB-PAY-008), or a credit Adjustment's re-post of such an allocation, creates it; a deferred constraint trigger proves the link. It is exempt from the payer and third-party intent scope (BR-PAY-025 and BR-PAY-026 amendments), uses the proposal shape with the within-Invoice default order (BR-PAY-036), and is never reversed by the one-call allocation reversal (SQLSTATE P4904; owner answer to Q-2026-10-05-17): only another move or a credit Adjustment on its Invoice reverses it.

## DB-PAY-005 — `payment_allocation_reversals`

Append-only: `id uuid PK`, `payment_allocation_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. Active Allocation effect is original Allocation less its linked reversal (zero when reversed).

## DB-PAY-006 — `payment_reversals`

Append-only: `id uuid PK`, `payment_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. Posting requires all Allocations, payment-sourced Credit recognitions, and Deposit Receipts to be explicitly reversed and no unresolved completed Refund; it then sets Payment status REVERSED. Original Payment is unchanged. Its Receipt remains historical evidence of the original Payment and is not a balance consumer.

## DB-PAY-007 — `payment_allocation_details`

Append-only obligation attribution: `id uuid PK`, `payment_allocation_id uuid NOT NULL
FK`, `invoice_line_id uuid NULL FK`, `late_payment_charge_id uuid NULL FK`,
`obligation_kind text NOT NULL CHECK IN ('INVOICE_LINE','LATE_PAYMENT_CHARGE')`,
`invoice_line_category_snapshot text NULL`, `proposed_amount_usd_cents bigint NULL
CHECK (>0)`, `posted_amount_usd_cents bigint NOT NULL CHECK (>0)`,
`attribution_basis text NOT NULL CHECK IN ('RENT_FIRST_PROPOSAL','SERVICE_PROPOSAL',
'CUSTOMER_DESIGNATED','THIRD_PARTY_DESIGNATED','OTHER_CONFIRMED','DIRECT_LATE_PAYMENT_CHARGE')`, `detail_sequence
smallint NOT NULL CHECK (>0)`, and `calculation_trace jsonb NOT NULL`, with `UNIQUE
(payment_allocation_id, detail_sequence)` and uniqueness of a non-null obligation target
within the header.

Exactly one obligation FK is present. Invoice details use authoritative
`invoice_lines.id`; no duplicate obligation identity is created. All detail lines must
match the header target and Customer. The category snapshot is required only for an
Invoice line; a Late-payment Charge remains an obligation kind, never an Invoice
Category. A Charge allocation has exactly one Charge detail, reduces only that Charge,
and cannot exceed its remaining balance or affect the source Invoice.

## DB-PAY-008 — `payment_moves`

Append-only link of one confirmed wrong-Unit Payment move (BR-PAY-042, V1-056 slice 7, migration `20261020_85`): `id uuid PK`, `draft_id uuid NOT NULL UNIQUE FK financial_drafts`, `property_id`, `payment_id`, `source_allocation_id uuid NOT NULL UNIQUE FK payment_allocations`, `source_reversal_id uuid NOT NULL UNIQUE FK payment_allocation_reversals`, `source_reversed_by_move boolean NOT NULL`, `target_allocation_id uuid NOT NULL UNIQUE FK payment_allocations`, `source_invoice_id`, `target_invoice_id`, `moved_usd_cents bigint NOT NULL CHECK (>0)`, `source_acknowledgement` and `target_acknowledgement text NOT NULL` (1 to 2,000 characters: who acknowledged for each Customer, the date and how), `confirmed_at`, `confirmed_by`. Staff record a `PAYMENT_MOVE` draft under `payments.allocations.reverse` (`app.record_payment_move_draft`); a `financial.approve` holder confirms it (`app.confirm_payment_move_draft`), which in one transaction reverses the wrong Invoice allocation (unless the one-call reversal already did), posts the same Payment to the correct Invoice of another Unit and inserts this row; a deferred check requires the draft's CONFIRMED decision. The move is refused while the Payment has Customer Credit that is not reversed or a Refund that is not fully returned, and a draft is stale when the correct Invoice or the source changed. The Payment row and its Receipt never change. No runtime or financial role has table privileges. Update/delete is prohibited. The reversal and the new allocation share one instant, and one `payment_move.confirmed` audit event per move carries the draft id as its correlation id. The draft payload (both acknowledgements and the line split of the correct Invoice) must fit the 16,000-byte draft limit. The confirmation advances the correct Invoice's version even when its status is unchanged. A Customer Credit that a credit Adjustment released from a moved allocation is never reversed by the one-call Credit reversal unless the Payment is a normal Customer Payment and the Credit belongs to its payer (`customer_credit_reversals_moved_payment`, SQLSTATE P4904; owner answers to Q-2026-10-05-18 and Q-2026-10-05-19); otherwise it stays with its Customer. A Credit of a Customer other than the payer can be applied to that Customer's Invoices or Late-payment Charges, or refunded to that Customer through a `CREDIT_CUSTOMER` Refund draft confirmed by `financial.approve` (BR-CREDIT-014; V1-056 sub-slice 8f, migration `20261030_95`, DB-REFUND-001); the ordinary Credit Refund draft pays only a recipient who is both the Credit's Customer and the payer, so it is refused for such a Credit. A third-party payer's own Credit can still be refunded to the payer through a Refund draft.

## DB-CREDIT-001 — `customer_credits`

Append-only Credit recognition event: `id uuid PK`, `customer_id uuid NOT NULL FK`, `source_payment_id uuid NOT NULL FK`, `recognized_usd_cents bigint NOT NULL CHECK (>0)`, `customer_authorization_reference text NOT NULL`, `recognized_at timestamptz NOT NULL`, `recognized_by uuid NOT NULL`, `reason text NOT NULL`. Credit must belong to the payer Customer and cannot exceed unallocated, undisposed Payment value. Credit balance is derived. For a KHR-origin Payment, the source FK preserves original KHR amount, selected exchange record, USD recognition basis, and channel transaction facts without creating a KHR Credit balance.

## DB-CREDIT-002 — `customer_credit_applications`

Append-only authorized application header: `id uuid PK`, `customer_credit_id uuid NOT
NULL FK`, `target_kind text NOT NULL CHECK IN ('INVOICE','LATE_PAYMENT_CHARGE')`,
`invoice_id uuid NULL FK`, `late_payment_charge_id uuid NULL FK`, `final_settlement_id
uuid NULL FK`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `within_invoice_basis text
NOT NULL CHECK IN ('RENT_THEN_RECURRING_SERVICES_PROPOSAL','CUSTOMER_DESIGNATED',
'OTHER_APPLICABLE_OBLIGATION','NOT_APPLICABLE')`, `customer_designation_reference text
NULL`, `proposal_generated_at timestamptz NULL`, `proposal_trace jsonb NULL`,
`occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, and
`authorization_reference text NOT NULL`.

Exactly one target FK is present. Source Credit and target Customer must match. The
application cannot exceed Credit availability or target balance, and DB-CREDIT-005
details must sum to the header amount. A mixed Invoice uses the same Rent-first default
proposal, optional valid Customer designation, and explicit authorized confirmation as
Payment Allocation. A Charge application reduces only that Charge and never its source
Invoice. Proposal timestamps/traces and detail proposed amounts are required only when
the Rent-first proposal was generated and are absent for direct Customer designation or
direct Charge application.

As built in V1-056 sub-slice 8e-2 (migration `20261028_93`; owner answers to
Q-2026-10-06-32): `final_settlement_id` is a foreign key to `app.final_settlements` (its
earlier NULL-only CHECK is dropped; every earlier row stays NULL). A row with a
`final_settlement_id` records `authorization_reference = 'financial.approve'` and the
approver as `actor_id`; every other row records `credits.apply` (one CHECK). Only the
internal `app.post_final_settlement_credit_application` (no grant) writes such a row, for
one Customer Credit step of a `FINAL_SETTLEMENT` draft; the Settlement confirm calls it.
It writes the same header and detail shapes as the one-call Credit application: the
Rent-first proposal with its trace, the Customer's designation, a direct Late-payment
Charge, and on an Invoice without Rent or Service lines `OTHER_APPLICABLE_OBLIGATION` with
`OTHER_CONFIRMED` details. Its `id` is derived from the draft and the step
(`app.final_settlement_credit_application_id`) and its detail's `calculation_trace` names
the draft and the step. A source check before insert requires an open Settlement of a
terminated Lease, a time not before the Settlement started, a human approver, a target of
that Lease, no Deposit application or Settlement Refund yet, and an exact match with the
step of a draft that waits or is
confirmed by the same approver; a deferred check requires that draft CONFIRMED under
`financial.approve` by the same approver at commit and exactly one detail on the step's
obligation. All earlier Credit checks still run on these rows.

## DB-CREDIT-003 — `customer_credit_application_reversals`

Append-only: `id uuid PK`, `credit_application_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`.

V1-056 sub-slice 8e-2: a reversal of a Credit application that has a `final_settlement_id`
is refused (SQLSTATE `P5S01`, a conflict) before any other reversal check, for every writer;
it waits for the post-settlement corrections (slice 10). Other reversals are unchanged.

## DB-CREDIT-004 — `customer_credit_reversals`

Append-only: `id uuid PK`, `customer_credit_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. It requires all applications and Refund commitments sourced from the Credit to be resolved explicitly.

V1-056 slice 7: a reversal of a Credit released from a moved allocation is refused unless the Payment is a normal Customer Payment and the Credit belongs to its payer (DB-PAY-008, `customer_credit_reversals_moved_payment`).

V1-056 sub-slice 8g (migration `20261031_96`, owner answer to Q-2026-10-06-35, approved tightening): a reversal of any Credit that a credit Adjustment released to a Customer other than the payer of its source Payment (`app.credit_customer_refund_basis` is not NULL: the Credits that the `CREDIT_CUSTOMER` Refund draft pays, DB-REFUND-001) is refused for every writer with SQLSTATE `P4904` (BEFORE INSERT trigger `customer_credit_reversals_other_customer`, after the slice 7 refusal and before the Credit reversal checks). Such a Credit stays with its Customer: it is applied to that Customer's obligations or refunded to that Customer. Earlier reversal rows are unchanged.

## DB-CREDIT-005 — `customer_credit_application_details`

Append-only attribution: `id uuid PK`, `customer_credit_application_id uuid NOT NULL
FK`, `invoice_line_id uuid NULL FK`, `late_payment_charge_id uuid NULL FK`,
`obligation_kind text NOT NULL CHECK IN ('INVOICE_LINE','LATE_PAYMENT_CHARGE')`,
`invoice_line_category_snapshot text NULL`, `proposed_amount_usd_cents bigint NULL
CHECK (>0)`, `applied_amount_usd_cents bigint NOT NULL CHECK (>0)`,
`attribution_basis text NOT NULL CHECK IN ('RENT_FIRST_PROPOSAL','SERVICE_PROPOSAL',
'CUSTOMER_DESIGNATED','OTHER_CONFIRMED','DIRECT_LATE_PAYMENT_CHARGE')`, `detail_sequence
smallint NOT NULL CHECK (>0)`, and `calculation_trace jsonb NOT NULL`, with `UNIQUE
(customer_credit_application_id, detail_sequence)`. Exactly one target FK is present;
Invoice details use authoritative line identity and require their line category snapshot;
Charge details prohibit that category snapshot and match the header.

Customer Credit remains a USD Customer accounting balance, same-Customer only,
separate from Deposits and unallocated Payment, and never vendor Accounts Payable.

## DB-RECEIPT-001 — `receipts`

Immutable customer-facing acknowledgment: `id uuid PK`, `receipt_number text NOT NULL
UNIQUE`, `payment_id uuid NOT NULL UNIQUE FK payments`, `payer_customer_id uuid NOT NULL
FK customers`, `issued_at timestamptz NOT NULL`, `issued_by uuid NOT NULL`, and optional
immutable `identity_snapshot jsonb`. Payment and Customer must match. Receipt Number is
stable, immutable, and never reused. A confirmed Payment normally produces exactly one
business Receipt in the same transaction; the Receipt evidences but neither creates,
moves, allocates, nor settles value.

Only immutable identity/display facts that cannot be safely re-derived may be
snapshotted. Payment, Allocation, Credit, Deposit, and Charge amounts remain
authoritative in their own tables and are joined for display.

## DB-RECEIPT-002 — `receipt_reprints`

Append-only reprint event: `id uuid PK`, `receipt_id uuid NOT NULL FK`, `reprinted_at
timestamptz NOT NULL`, `reprinted_by uuid NOT NULL`, `reason text NOT NULL`, and
`delivery_reference text NULL`. Every reprint uses the same Receipt UUID and Number and
creates neither a Payment nor another receipt-of-money event. Refund remains its own
outbound event; no Refund Receipt table or document is introduced.

---

# 11. Deposit Tables

## DB-DEP-001 — `deposits`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `deposit_type` | `text` | no | `SECURITY`, `PET` |
| `customer_id` | `uuid` | no | FK |
| `reservation_id` | `uuid` | yes | FK |
| `lease_id` | `uuid` | yes | FK; added to same Security Deposit at resulting Lease |
| `pet_approval_id` | `uuid` | yes | FK; required for PET |
| `required_usd_cents` | `bigint` | no | `CHECK (>0)` |
| `required_effective_date` | `date` | no | |
| provenance columns | as DB-TYPE-007 | no | |

Constraints:

- SECURITY requires one Reservation, prohibits pet approval, and `UNIQUE (reservation_id) WHERE deposit_type='SECURITY'`.
- PET requires one Lease and one approval whose terms require a Deposit; reservation
  is null; `UNIQUE (lease_id) WHERE deposit_type='PET'` and `UNIQUE
  (pet_approval_id) WHERE deposit_type='PET'` enforce the one optional Pet Deposit.
- A deferred transaction constraint requires exactly one Security Deposit for every Reservation and verifies that any later Lease is the Reservation's resulting Lease. No conversion or second Deposit is created.
- Required amount is a historical obligation; a change requires an explicit audited correction event rather than silent overwrite after receipt.

## DB-DEP-002 — `deposit_receipts`

Append-only: `id uuid PK`, `deposit_id uuid NOT NULL FK`, `payment_id uuid NOT NULL FK`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `UNIQUE (deposit_id, payment_id)`. The transaction prevents total allocations, active Deposit receipts, Credit recognition, and Refund commitments from exceeding Payment USD accounting value. This is not an Invoice Payment Allocation.

## DB-DEP-003 — `deposit_required_amount_adjustments`

Append-only: `id uuid PK`, `deposit_id uuid NOT NULL FK`, `adjustment_type text NOT NULL CHECK IN ('INCREASE','DECREASE')`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `effective_date date NOT NULL`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. Resulting required amount may not be negative. This table records only a valid governing Lease-term correction; it creates no right to change a Deposit.

## DB-DEP-004 — `deposit_dispositions`

Append-only non-refundable event: `id uuid PK`, `deposit_id uuid NOT NULL FK`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `governing_reservation_id uuid NULL FK`, `governing_lease_id uuid NULL FK`, `effective_date date NOT NULL`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. Exactly one governing Reservation/Lease is required and must match the Deposit. It cannot exceed refundable held balance and is not an Invoice allocation.

### Lease Deposit command admission (V1-055)

The existing Lease Deposit disposition command serializes its Property, actor,
action and idempotency key before replay lookup. It freshly requires an active
human account before returning an original result and again after waiting for the
Deposit row lock before a new disposition. Python command inputs require a
positive exact integer USD-cent amount within PostgreSQL `bigint` and an exact
calendar date. Existing Property/Lease/date and held-balance checks remain in force.

A successful new disposition writes its source row, generic Deposit audit event
and command/result record atomically. A conflicting audit identity rolls back all
three. Exact successful retries return the original result, including after a
reversal; they do not create additional source, audit or command rows. The forward
56 migration replaces only the existing function body, preserving its signature,
owner and permissions and all historical rows. It does not backfill generic audit
events for dispositions already recorded by older versions.

This command-admission prerequisite creates no forfeiture right or new financial
policy. Explicit governing-rule/source and expected-version orchestration remains
a separate V1-055 acceptance requirement before the workflow is exposed.

### Financial observation revision (V1-055; DL-061)

The protected termination Deposit readiness read exposes `disposition_state_version`
as a positive PostgreSQL `bigint`. It is the existing Deposit metadata `version`
plus the number of required-amount adjustments and all immutable events in the
implemented Deposit balance stream: receipts, receipt reversals, dispositions,
disposition reversals, Refunds, verified returns and return-correction reversals.
An event and its reversal count separately even when net amounts return to their
previous values. Exact command replay and a rolled-back event do not advance it.

The revision and balances use the same read transaction snapshot. The helper is
private and the read takes no financial write lock or new permission. Existing
`deposit_snapshot` versions, command digests and original saved results remain
unchanged. The mutable `deposit_serialization_guards` counter is coordination
state, not this financial observation.

This is a read prerequisite, not expected-version posting enforcement. A later
fresh disposition command must acquire the existing Deposit/MVCC serialization
boundary and revalidate the observation together with the governing source and
rule before posting. Deposit applications and reversals are not implemented yet;
their acceptance must extend the authoritative balance stream and revision
invalidation. No future feature is covered merely by this read.

### Exact approved disposition context (V1-055; DL-062)

Every fresh Lease Deposit disposition requires the exact original termination event,
an explicit supported governing rule and the expected financial observation revision.
`lease_deposit_disposition_contexts` preserves these alongside the original Property,
actor, idempotency key/digest, Deposit, Lease, amount, effective date, reason and
authorization. Its append-only rows link both the disposition and original command.
The narrow financial-role wrapper commits context, source, audit and command together;
only the two circular foreign keys are deferred and validated before return.

BR-DEP-023 permits Security disposition from a matching approved original voluntary
BR-LEASE-021 termination before the contractual End Date. Pet remains separate.
BR-DEP-022 requires an original termination explicitly governed by that rule, with
matching signed Customer-violation authority and at least three genuine general
warning sources. A generic violation, text reason or current pet presence does not
establish that cause. Original source, Property, Lease, Customer and date must agree.

The command serializes identity and locks the active HUMAN, scoped Lease/source,
Deposit and existing MVCC guard before revalidating financial state. Required-amount
adjustment inserts also participate in that guard; the existing balance-event guard
and history-budget validation remain intact. Both net-zero histories and concurrent
changes under repeatable-read invalidate stale posting. This creates no new policy.

The existing entry point and Lease-disposition insert trigger require matching context
for fresh effects. Historical successful absent-context requests preserve their digest,
saved response and exact replay, including after reversal. Supplied context and every
original field remain exact retry intent. No historical backfill or source rewrite is
performed; runtime/bootstrap/public receive no new mutation or context-table access.
Expected-version conflicts require a fresh observation; they do not authorize retrying
with fabricated source or changed intent under an existing successful key.

This command stage does not complete Invoice reconciliation, physical Move-out,
Settlement applications, HTTP/staff workflows or whole-version acceptance. Future
applications/reversals must extend balance and financial revision invalidation.

## DB-DEP-005 — `deposit_applications`

Append-only Final Settlement financial event: `id uuid PK`, `deposit_id uuid NOT NULL FK`, `final_settlement_id uuid NOT NULL FK`, `target_kind text NOT NULL CHECK IN ('INVOICE_LINE','LATE_PAYMENT_CHARGE')`, `invoice_id uuid NULL FK`, `invoice_line_id uuid NULL FK`, `late_payment_charge_id uuid NULL FK` (exactly the Invoice and line for `INVOICE_LINE`, exactly the Charge for `LATE_PAYMENT_CHARGE`), `application_stage text NOT NULL CHECK IN ('PET_RELATED_FIRST','SECURITY_EXPLICIT','PET_REMAINDER_EXPLICIT')`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `application_order integer NOT NULL CHECK (>0)`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`, `UNIQUE (final_settlement_id, application_order)`.

- Application is allowed only after Lease TERMINATED and before the Settlement's `closed_at` is set.
- Applicable Customer Credit is handled first. `PET_RELATED_FIRST` preserves Pet Deposit
  identity against pet-related Invoice lines before Security Deposit use.
  `SECURITY_EXPLICIT` then permits authorized management to select Security Deposit
  applications. `PET_REMAINDER_EXPLICIT` may finally apply remaining Pet Deposit to any
  valid remaining Settlement Invoice line or Late-payment Charge, not only pet-related damage.
- Every stage and target is explicitly authorized. `application_order` records the
  actual sequence; neither Payment FIFO nor an inferred Deposit-type FIFO is reused.
- A trigger matches PET stages to a Pet Deposit and SECURITY stage to a Security
  Deposit and keeps the stage order within a Settlement. The prior-stage prerequisites
  (the DL-032 order and the strict-order rules of owner answer 3 to Q-2026-10-05-20) are
  checked from current balances by the Settlement draft and its confirmation (V1-056
  sub-slices 8c and 8e), not by this trigger.
- The target must belong to the Settlement Lease: an Invoice line of an Invoice of that
  Lease, or a Late-payment Charge whose source Invoice belongs to that Lease. Application
  cannot exceed the held refundable Deposit balance or the target's current outstanding
  balance. A Deposit may pay a Late-payment Charge like any other debt (owner answer to
  Q-2026-10-05-20, 2026-10-05); `PET_RELATED_FIRST` targets only pet-related Damage
  Invoice lines.

- As built in V1-056 sub-slice 8a-1 (migration `20261021_86`): no role may write the table;
  the internal `app.post_deposit_application` is the only writer and records the
  `financial.approve` reference. A kept Deposit (a forfeiture ground in the termination record,
  or an active disposition) is refused. The order number only grows within a Settlement and
  the stages keep the DL-032 order. The application counts in every Invoice line, Invoice
  status, Late-payment Charge and Deposit held balance, including the Late-payment Charge
  balance in the Payment reversal and financial action contexts; VOID, Adjustments and
  Late-payment Charge corrections of a paid obligation, and a receipt reversal of the
  Deposit, are refused. The writer refuses an unknown target, and the writer and the
  record's trigger refuse an approver who is not a person. The Customer's choice and the
  staff reason for the remaining Pet Deposit (`PET_REMAINDER_EXPLICIT`, BR-SETTLE-017,
  BR-DEP-027, DL-013) are checked by the Settlement draft and its confirmation (V1-056
  sub-slices 8c and 8e), not by this table.
- As built in V1-056 sub-slice 8a-2 (migration `20261023_88`): the Customer Ledger shows each
  application (DB-DER-010), and the Deposit's own history reads the applications of one
  Deposit of one Property through the bounded `app.deposit_application_history(property,
  deposit)`; the runtime role executes that function only and has no table privilege.
- As built in V1-056 sub-slice 8b (migration `20261024_89`, owner answer to Q-2026-10-05-24):
  the kept-Deposit check of the record's trigger reads the Deposit's Settlement path from
  `app.lease_deposit_settlement_path(property, deposit)` and refuses every path except
  `DL_032`. `KEPT`: an active disposition exists. `FORFEITURE_REQUIRED`: the termination
  record gives a forfeiture ground, no forfeiture was ever confirmed and the Deposit holds money.
  `NOTHING_HELD`: the same, but the Deposit holds nothing (nothing to forfeit, apply or refund;
  no blocking issue). `DL_032`: no ground,
  or every confirmed forfeiture was reversed, so a Security Deposit whose forfeiture was
  reversed, or a Pet Deposit kept for pet noncompliance whose forfeiture was reversed, may now
  be applied (a relaxing change). The termination record lookup is the shared
  `app.lease_termination_forfeiture_rule(property, lease, deposit type)`;
  `app.lease_deposit_kept_rule` keeps its result and errors and delegates to it.

## DB-DEP-006 — `deposit_application_reversals`

Not built in V1-056 (plan Q15: post-settlement corrections are only an extra charge or a
Refund).

Append-only: `id uuid PK`, `deposit_application_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`.

## DB-DEP-007 — `deposit_receipt_reversals`

Append-only: `id uuid PK`, `deposit_receipt_id uuid NOT NULL UNIQUE FK`, `reason text
NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`,
`authorization_reference text NOT NULL`. Posting is prohibited while any dependent
Deposit disposition, application, or Refund remains active. It removes the receipt's
derived liability effect without altering the original receipt.

As built in V1-056 sub-slice 8r (migration `20261022_87`, owner answer to
Q-2026-10-05-22): a receipt reversal is a financial draft (kind `DEPOSIT_FORFEITURE`,
variant `DEPOSIT_RECEIPT_REVERSAL`, prepared under `deposits.correct`), and only
`app.confirm_deposit_receipt_reversal_draft` with the `financial.approve` reference
posts it, by running the earlier reversal function with the approver as actor; the
financial role no longer executes the one-call function. A reversal is also refused
while a `REFUND` or `DEPOSIT_FORFEITURE` draft for that Deposit is pending (its payload
names the Deposit or its Reservation); the Final Settlement drafts (V1-056 8c, 8e) must
extend this check. The row names the approver with the `deposits.correct` reference;
the draft decision records `financial.approve`.

As built in V1-056 sub-slice 8a-2 (migration `20261023_88`, owner answer 2 to
Q-2026-10-05-23, an approved tightening): the other direction too. While a receipt
reversal draft for a Deposit is pending, a trigger on `app.financial_draft_decisions`
refuses the confirmation (SQLSTATE 55000) of any `REFUND` or `DEPOSIT_FORFEITURE` draft
whose payload names that Deposit or its Reservation; recording such drafts stays allowed,
and the refused draft stays pending. A Lease forfeiture reversal draft and the receipt
reversal draft itself are not affected; a rejected or withdrawn receipt reversal draft no
longer holds anything back. When a receipt reversal draft and a Refund or forfeiture draft
of the same Deposit are both pending, each confirmation is refused, and only a rejection or
withdrawal of one of them lets the other be confirmed. The receipt reversal draft recorder
locks the Deposit row after its advisory lock, so no Refund or forfeiture confirmation
commits while a receipt reversal draft for the same Deposit is pending or still being
recorded (the Refund and Reservation Deposit confirmations lock that row; the Lease
forfeiture confirmation takes the same advisory lock). This relies on READ COMMITTED, the
isolation every confirmation uses: a statement after a lock wait takes a fresh snapshot.

As built in V1-056 sub-slice 8c (migration `20261025_90`, owner answer 4 to Q-2026-10-05-23):
both directions also see the Final Settlement draft. A pending `FINAL_SETTLEMENT` draft whose
payload lists the Deposit in `deposit_ids` (the Deposits it applies or refunds) refuses a new
receipt reversal draft of that Deposit and, through the receipt reversal guard, the reversal
itself; the decision trigger refuses the confirmation of such a Settlement draft while a receipt
reversal draft of one of its Deposits is pending. A receipt reversal draft that is already
pending blocks the recording of the Settlement draft through the preview's `PENDING_DRAFT`
issue. The Settlement draft recorder locks the Lease's Deposit rows in a fixed order after the
same per-Deposit advisory lock, so each recorder waits for the other and then sees its draft.

## DB-DEP-008 — `deposit_disposition_reversals`

Append-only: `id uuid PK`, `deposit_disposition_id uuid NOT NULL UNIQUE FK`, `reason
text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`,
`authorization_reference text NOT NULL`. It restores the disposition's derived held
balance effect and never rewrites the original event.

---

# 12. Move-out, Final Settlement, and Refund Tables

## DB-MOVEOUT-001 — `move_out_inspections`

Append-preserved operational source: `id uuid PK`, `lease_id uuid NOT NULL FK`, `inspection_date date NOT NULL`, `result_text text NOT NULL`, `completed_at timestamptz NOT NULL`, `completed_by uuid NOT NULL`, `authorization_reference text NOT NULL`. An inspection records evidence but creates no charge by itself.

## DB-MOVEOUT-002 — `inspection_damage_findings`

`id uuid PK`, `inspection_id uuid NOT NULL FK`, `description text NOT NULL`, `pet_related boolean NOT NULL`, `created_at timestamptz NOT NULL`, `created_by uuid NOT NULL`. If billed, an `authorized_nonrecurring_obligations` row and its Invoice line identify this finding relationally. No standard fee or damage amount is implied.

`authorized_nonrecurring_obligations.inspection_damage_finding_id` is a foreign key to
this table and is unique, so a finding is billed at most once. Completion checks that
the finding's inspection, Lease, Customer and Unit match the obligation and Invoice.
The amount is entered only by an actor holding the Damage-charge capability, with a
mandatory reason and evidence reference. Evidence is a bounded text reference; the
system stores no photo or file.

### Operational inspection evidence boundary (V1-055)

Forward migration60 implements DB-MOVEOUT-001/002 without changing physical
occupancy or financial obligations. Inspections additionally retain Property,
expected Lease version, evidence reference, reason and optional unique same-Lease
`supersedes_inspection_id`. Findings have immutable ordered identities, at most50
per inspection, with their parent inspection's actor and completion timestamp.
Empty findings are valid and do not imply financial completion.

The source service requires exact Property-scoped `leases.inspect` for recording
and `leases.read` for observations. No existing grant is enlarged. The database
freshly checks the active HUMAN and exact Lease Property, signed or terminated
Lease, expected Lease version, and an actual inspection date between Lease signing
and the current Property business date. Actor, Property, command-key and Lease
locks serialize validation and original/correction recording. Inspection alone
does not update the Lease version or invoke physical/financial writer triggers.

`move_out_inspection_commands` retains the Property/actor/key, exact intent/digest,
Lease and inspection identities, original response, completion time, and typed
audit-event identity. Deferred completion checks require the full finding set,
inspection, command and audit to agree atomically. The command defers only the
three new completion constraints while assembling those rows and makes them
immediate before returning. This supports either caller mode and same-transaction
corrections; unrelated constraint modes are unchanged. The three named constraints
remain immediate after a successful new command; replay does not change their mode.

Audit snapshots use a private immutable projection of inspection/finding identities,
dates, actor, status, ordered sequences, counts and explicit false effect flags.
The shared audit classifier and Property/Lease/Customer readers remain unchanged.
Full narratives, authorization/evidence references and original response data stay
in immutable inspection/finding/command source records without truncation. Audit
authorization evidence links the scoped capability to the inspection identity.
Completion checks bind both typed audit states and authorization linkage to the
original source, while command responses retain the full snapshot. A later
correction does not rewrite the original response or its recorded audit status. All three new tables reject
updates, deletion and truncation. Corrections append a new inspection/finding set
and explicitly supersede one current same-Lease inspection; original commands
continue to return their original response. Old findings are never repurposed.

Reads return at most20 inspections per page with current/superseded evidence,
up to50 findings each, and explicit false physical-departure, charge-creation and
financial-completion flags. Reads use repeatable-read read-only transactions;
recording uses read-committed transactions. Connection, lock and statement timeouts
are bounded and timestamps use UTC. Unknown database outcomes preserve the exact
original command for recovery; no automatic new command is inferred.

The existing DAMAGE_CHARGES prohibition remains until a separate stage installs
the complete typed authorized-charge/source relationship and bill-once semantics.
This inspection stage neither establishes amounts nor issues an Invoice, disposes
of a Deposit, records physical departure or completes Final Settlement. Physical
move-out/Utility responsibility, due-date attribution, staff transport and final
integrated V1-055 acceptance remain required.

### Physical departure foundation (V1-055)

Forward migration61 adds immutable `physical_move_out_events`,
`physical_move_out_occupancies` and `physical_move_out_commands`. An explicit
event records the actual physical date, a genuine same-Lease termination command,
expected Lease/Unit versions, confirmed condition, reason, authorization and
evidence reference. It names one to20 ended Occupancies and their exact previous
and resulting immutable revisions. Only named open Occupancies close; others stay
open. The Lease lifecycle, financial sources and Reservations remain unchanged.

The command requires Property-scoped `leases.move_out`; observations require
`leases.read`. Database functions freshly check active HUMAN identity and exact
Property. The existing role grants are unchanged. Writes use read committed;
observations use read-only repeatable read, with bounded timeouts and UTC.
Existing source advisory keys are acquired without waiting before deterministic
Lease/Unit/member row locks. Conflicting old lifecycle/source writers return a
bounded conflict; the command does not automatically retry.

Protected UNDER_MAINTENANCE/OUT_OF_SERVICE states remain. Other actual Occupancies
keep the Unit OCCUPIED; otherwise the explicitly confirmed CLEANING,
UNDER_MAINTENANCE or OUT_OF_SERVICE condition applies. Physical departure never
sets VACANT or overrides authoritative Reservation/Lease availability.

Corrections append one same-member successor to a current event with the same
termination source. Previous actual dates, revisions and original responses remain
permanent. An evidence-only successor has the same actual date, ended members and
confirmed condition as its predecessor. It preserves the current Unit status and
version, including readiness, Reservation or Lease changes made after the original
departure; it also preserves Occupancy dates and versions. Its event may therefore
record an unchanged current VACANT or RESERVED state without performing an
availability transition. Completion rejects availability results for initial or
substantive date/condition corrections and rejects any Unit transition for an
evidence-only successor. Genuine date/condition corrections retain the existing
protected-state and remaining-Occupancy rules. The command still checks current
actor, Property and all expected versions and uses the same bounded locks.

Each physical audit has an explicit Unit relationship equal to the source event's
Unit, checked by completeness. Existing Unit timelines and Unit-filtered Property
audit searches include original and correcting events without changing reader
authorization or the shared classifier. Historical Unit audit states retain the
canonical top-level `floor` key and original text value. Only Unit event decoding
and serialization classify that field as a bounded Unit label; existing secret
checks still apply. Other event types, nested fields and all other values keep
the existing classification rules. No stored audit row or source snapshot is
rewritten, and the common audit write policy is unchanged. Exact
Property/actor/key replay compares the complete intent and returns the original
response after a fresh identity check. Deferred completeness constraints validate
the full event/member/command/audit assembly before return in either caller mode.
Existing audit consumers receive classified typed state; full narratives and
original evidence remain on the immutable event.

All existing Invoice/Utility guards remain unchanged. Crossing an existing Utility
period or estimation case returns an explicit responsibility-boundary conflict and
rolls back every command effect. That conflict is not a completed reconciliation:
the connected Utility reconciliation and final reading/approved-estimate/charge
source relationships remain separate mandatory V1-055 work. Missing final inputs
remain `PENDING_RECONCILIATION`; `utility_completion_assessed` and
`financial_completion_assessed` are false and no charge is created. This foundation
does not complete Final Settlement, HTTP/staff integration or version acceptance.

### Final Utility input evidence (V1-055)

Forward migration63 adds immutable `move_out_final_input_events`,
`move_out_final_input_items` and `move_out_final_input_commands`. One event binds to
one current physical departure event of the Lease. For every Utility Meter of the
Lease's Unit that applies at the actual Move-out Date, the event records exactly one
item. A Meter applies when it was installed on or before that date and was not
deactivated before it. An item is one of:

- `READING`: an existing validated Utility Reading of that Meter dated on the actual
  Move-out Date. Its identity, date, value, version and validation time are copied
  as an immutable snapshot. The command never creates, changes or validates a Reading.
- `ESTIMATE`: an existing approved broken-Meter estimate whose case names the Unit,
  Utility type and Meter and whose estimated consumption period contains the actual
  Move-out Date.
- `UNRESOLVED` with an explicit reason: `MISSING_READING` (no Reading exists on that
  date), `READING_NOT_VALIDATED` (only an unvalidated Reading exists) or
  `BROKEN_METER_ESTIMATE_PENDING` (the Meter has a recorded failure date and no
  approved estimate covers that date). Each reason is checked against current Utility
  evidence and cannot be asserted against it.

Recording a complete correction appends a successor that names the current event of
the same Lease. A Lease has one root event. Earlier events, items, responses and
audit records are permanent, and later Reading corrections never rewrite a stored
snapshot; the read projection lists the Meters whose Reading has changed since it was
recorded. The physical departure event must still be current: after a physical
correction, evidence is recorded against the new event.

The command requires Property-scoped `leases.move_out`; observations require
`leases.read`. Database functions freshly check the active HUMAN identity and exact
Property. Only the financial role executes the command function and only the runtime
role executes the observation function; neither role has direct table privileges.
Writes use read committed with bounded timeouts, UTC, non-waiting advisory keys for the
Lease and its Unit's Utility types, and share locks on every referenced Meter and
Reading. Exact Property/actor/key replay compares the complete intent and returns the
original response. Deferred completeness constraints validate the event, item, command
and audit assembly, the applicable Meter set and every referenced source before return.
Update, delete and truncate are rejected.

The command creates no Reading, consumption period, Invoice, charge or Deposit
application. While any item is `UNRESOLVED` the status is `PENDING_RECONCILIATION`;
otherwise it is `INPUTS_RECORDED`. `utility_completion_assessed` and
`financial_completion_assessed` remain false, and the original physical event snapshot
is unchanged. The requirement that a boundary Reading be dated on the actual Move-out
Date and the inclusive Meter applicability window are implementation choices; the
canonical Utility and Move-out rules do not fix them and they await owner confirmation.

## DB-SETTLE-001 — `final_settlements`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `lease_id` | `uuid` | no | FK, `UNIQUE` |
| `started_at` | `timestamptz` | no | |
| `started_by` | `uuid` | no | |
| `closed_at` | `timestamptz` | yes | null until permanent closure |
| `closed_by` | `uuid` | yes | set exactly when `closed_at` is set |
| `actual_termination_date_snapshot` | `date` | no | |
| `move_out_date_snapshot` | `date` | yes | actual physical date if occupancy ended |
| `source_snapshot` | `jsonb` | yes | required and immutable at closure |
| `closing_balance_due_usd_cents` | `bigint` | yes | required and immutable at closure; `CHECK (>=0)` |

The Lease must be TERMINATED before creation. A null `closed_at` means financial
closure has not occurred; this is a technical condition, not a new business status.
Closure occurs once, only after every valid final charge—including unresolved
Utility handling and every applicable separate Late-payment Charge—is final, all
required applications/dispositions/Refunds are represented, and final balance is
reconciled. A closed Settlement is never reopened; correction uses linked events.

As built in V1-056 sub-slice 8a-1 (migration `20261021_86`): the table also stores
`property_id`; `app.start_final_settlement` (financial role, `final_settlements.prepare`
checked by the application) opens it; a guard allows only the single closure change
(all four closure columns together, identity columns unchanged) and refuses any change
of a closed Settlement and every delete.

As built in V1-056 sub-slice 8b (migration `20261024_89`): `app.final_settlement_preview(property,
actor, settlement, capabilities)` (runtime role; STABLE; the application checks
`final_settlements.prepare` or `financial.approve` and passes the reader's draft capabilities on
the Property; the database checks an active person and the Property; the service reads in a
read-only transaction) reads one Settlement and writes nothing. It returns the open Invoice lines and Late-payment Charges of
every issued, non-VOID Invoice of the Lease per Customer named on them (the Primary Tenant
first), each Customer's available Credit (`app.credit_available_value`) with what it may pay of
that Customer's obligations, every Lease Security and Pet Deposit with its held amount, ground,
forfeiture state and path (DB-DEP-005 note), the seven DL-032 steps in order with upper bounds
only (no amount is proposed; step 5 says whether the remaining Pet Deposit is the Customer's
choice only, at the three BR-DEP-027 terminations, or also the staff step with a reason everywhere
else, owner answer 2 to Q-2026-10-05-25),
and the blocking issues: `SETTLEMENT_CLOSED`; `FINAL_UTILITY_NOT_ISSUED` when the Primary Tenant
moved in and the current move-out is not recorded, its final Utility inputs are missing or
unresolved, or no final Utility Invoice was created although a final Reading has consumption not
yet in a period or a period of the Lease with consumption is on no Invoice;
`UTILITY_PERIOD_NOT_BILLED` for every Utility period the Lease is responsible for with consumption
and no Invoice line, whether or not the final Utility Invoice exists; `CLEANING_CHARGE_MISSING`
when the Customer moved in and out, the Unit's current cleaning rate is above zero or not set, and
no cleaning charge sits on an issued, non-VOID Invoice; `LATE_PAYMENT_DECISION_MISSING` for each
UNPAID or PARTIALLY_PAID Invoice whose Late-payment review is eligible; `FORFEITURE_NOT_CONFIRMED`
for a Deposit on the `FORFEITURE_REQUIRED` path; `PENDING_DRAFT` for a pending Refund, forfeiture
(including the reversal and receipt reversal variants) or Payment move draft on a Lease Deposit,
a Settlement Customer's Credit or Payment, or an allocation or target Invoice of the Lease (its
draft id, kind and variant only for a `financial.approve` holder or a holder of the draft's
prepare capability); `ONE_TIME_CHARGE_NOT_INVOICED` for a one-time charge source of the Lease on
no DRAFT or issued, non-VOID Invoice that is still waiting to be billed (not one whose Invoice was
VOIDed and not one a draft correction replaced, read from `app.invoice_draft_revision_events`;
owner answer to Q-2026-10-05-27); `INVOICE_DRAFT_NOT_ISSUED` for an Invoice draft of the Lease.
`ready` is true when no blocking issue exists (owner answers to Q-2026-10-05-25). The key
`information` lists, without blocking, each one-time charge whose Invoice was VOIDed and that was
not billed again (`VOIDED_CHARGE_NOT_BILLED_AGAIN`, with its amount), so the approver sees it.
A VOIDed cleaning charge is listed there and still blocks through `CLEANING_CHARGE_MISSING`,
because the cleaning charge is required (BR-MOVEOUT-013) and a VOID lets it be billed again.
A Deposit counts as having a reversed forfeiture only through a disposition of its own Lease
(`governing_lease_id`); any active disposition still makes it `KEPT`.

As built in V1-056 sub-slice 8c (migration `20261025_90`): `information` also lists each
one-time charge that a draft correction replaced (`CHARGE_REPLACED_BY_DRAFT_CORRECTION`, with its
amount, `replacement_authorized_obligation_id` from the latest such correction and that
charge's `replacement_lease_id`, which may be another Lease or none), without blocking (owner
answer to Q-2026-10-05-28). Staff record the Settlement draft with
`app.record_final_settlement_draft(property, actor, draft, settlement, plan, reason,
authorization)` (financial role; the application checks `final_settlements.prepare`; the database
checks an active person, the Property and the `final_settlements.prepare` reference). It writes a
`financial_drafts` row of kind `FINAL_SETTLEMENT` and nothing else; the confirm (8e) gives it its
effect. The plan holds the DL-032 steps in order: `CUSTOMER_CREDIT` (a Credit, a target Invoice
line or Late-payment Charge, an amount, and the Customer's designation as text or null), `PET_DEPOSIT_PET_DAMAGE`, `SECURITY_DEPOSIT` and
`PET_DEPOSIT_REMAINDER` (a Deposit, a target, an amount) and `DEPOSIT_REFUNDS` (a Deposit, an
amount, an active Refund method, a reference note of 1 to 500 characters, the recipient, and the
written agreement of all Signers of 1 to 2,000 characters when the recipient is another signed
Signer, never for the Primary Tenant), plus `pet_remainder` when step 5 is used: the Customer's
choice as text (who, the date, how) with the staff reason, or the staff reason alone, which is
refused at the three BR-DEP-027 terminations. `app.final_settlement_plan_result` (internal; the
confirm calls it again) checks the plan against the current preview: the preview must be
`ready`; the steps keep the DL-032 order; amounts are whole cents within what each obligation
still owes, each Credit has available and each Deposit holds; a Credit pays only its own
Customer's obligations; only a Deposit on the `DL_032` path that holds money is applied or
refunded, by the matching type, the first Pet step only on pet damage; every such Deposit ends
with nothing held (BR-SETTLE-008); and the strict order of the owner answer 3 to
Q-2026-10-05-20 and the owner answers to Q-2026-10-05-29: each Customer's Credit pays that
Customer's own open debt, up to what it can pay (the lower of the Credit available and that debt),
before any Deposit pays; on an Invoice with Rent or Service lines a Credit step without the
Customer's designation (who, the date, how; 1 to 500 characters) may pay only the first line that
still owes in the Credit proposal order, Rent then recurring Services then the other lines
(`app.final_settlement_rent_first_line`, BR-CREDIT-006); the Pet Deposit pays open pet damage before any other use or
Refund; and no Deposit is refunded while the Lease still has open debt that the Deposit could
pay (the Security Deposit always could; the Pet Deposit could except at a BR-DEP-027 termination,
where without the Customer's choice its rest is refunded and the debt stays); and the remaining
Pet Deposit (step 5) pays only debt still open after the Security Deposit has been used, by the
staff step or the Customer's choice: a plan is refused while a Security Deposit on the `DL_032`
path still holds money when step 5 starts (owner answer to choice (4a), built in sub-slice 8d,
migration `20261026_91`). Malformed input is
refused with 22023 and a plan the current Settlement does not allow with 55000. The draft payload
stores the steps, `pet_remainder`, the Lease, the termination ground, who may choose step 5,
`deposit_ids`, the open total and the expected closing balance in total and per Customer; its
`source_revision` is the SHA-256 digest of `app.final_settlement_source_state` (each Invoice of the
Lease with status, version, latest allocation event and open lines, each Late-payment Charge with
its remaining balance and latest event, the available Credit of every Customer of the Lease and
each Deposit's state version and held amount), computed in the same call as the plan check so both
read one snapshot (except the preview's Late-payment review, an earlier VOLATILE function that reads
its own snapshot: a Late-payment Charge finalized during the call changes the digest, so the draft
is stale at confirmation, which fails safe); the confirm recomputes it. One draft waits per
Settlement; an exact repeat replays and a reused draft id is refused (P5205); withdraw and reject
use the shared draft functions.

As built in V1-056 sub-slice 8e-1 (migration `20261027_92`, owner answer 7 to
Q-2026-10-05-20): once a Settlement is closed its obligations change only through a
post-settlement correction (BR-SETTLE-013; slice 10). `app.refuse_closed_final_settlement_change`
(SECURITY DEFINER, no grant) runs as the first BEFORE INSERT trigger
(`a0_<table>_final_settlement_closed`) on `invoice_void_events`, `invoice_adjustments`,
`invoice_adjustment_reversals`, `late_payment_decisions`, `late_payment_charges` and
`late_payment_charge_corrections` (through the Invoice or the Charge's source Invoice) and on
`invoices` and `authorized_nonrecurring_obligations` (a new row with the Lease), and as the
first BEFORE UPDATE OF `lease_id`, `status` trigger on `invoices`
(`a0_invoices_final_settlement_closed_update`) when a row gets a Lease or a DRAFT with a Lease
is issued (a draft correction or issue). For a Lease with a Final Settlement it locks the target
Invoice, then the Settlement row `FOR SHARE`, and refuses with SQLSTATE `P5S01` when the
Settlement is closed; a Lease without a Settlement takes no lock. So a change waits for a running
closure and is then refused, and a closure waits for a running change. A DRAFT may still become
VOID by UPDATE, but its VOID event is refused (owner answer 3 to Q-2026-10-06-33); a one-time-charge
draft without a Due Date cannot be VOIDed at all (`invoices_due_date_issued`). Payments,
allocations, Payment reversals, Credit applications and their reversals are not guarded by this
trigger (sub-slice 8e-2 refuses the reversal of a Credit application the Settlement made:
DB-CREDIT-003). A scheduled Rent or Utility run item locks the Lease's Settlement row
`FOR SHARE` and records a Lease whose Settlement is closed as `SKIPPED` with the diagnostic `FINAL_SETTLEMENT_CLOSED`
(owner answer 1 to Q-2026-10-06-33), an accepted outcome of a successful run.

As built in V1-056 sub-slice 8e-3 (migration `20261029_94`): a `financial.approve` holder
confirms a pending `FINAL_SETTLEMENT` draft with `app.confirm_final_settlement_draft(property,
approver, draft, authorization)` (financial role; `FinalSettlementService.confirm` checks
`financial.approve`; the database checks an active human approver and the `financial.approve`
reference). In one READ COMMITTED transaction it takes the Settlement draft lock, the Lease row,
the Payments and then the Credits of the Customer Credit steps, the Lease's Late-payment Charges
and then its Invoices in id order (`FOR UPDATE` where a step pays them, `FOR NO KEY UPDATE`
otherwise), the Settlement row, and each Deposit's draft lock and row in id order; then it checks
that the sources still have the draft's digest and runs `app.final_settlement_plan_result` again
(every blocking issue, pending drafts included, and the strict DL-032 order), refusing a draft
whose sources or result changed as stale (SQLSTATE `P5S02`; the draft stays pending). It writes
the decision first, then each Customer Credit step (`app.post_final_settlement_credit_application`,
draft order), each Deposit application (`app.post_deposit_application`, draft order, stage from
the step kind; the remaining Pet Deposit records its staff reason), each Refund in Deposit id order
(`app.post_final_settlement_deposit_refund`), with ids derived from the draft and the step or
Deposit (`app.final_settlement_deposit_application_id`, `app.final_settlement_refund_id`); it then
checks exactly one Credit application, Deposit application and Refund per step and that every
`DL_032` Deposit holds nothing, writes the closure snapshots (DB-SETTLE-002, 004, 006), closes the
Settlement once (`closed_at`, `closed_by`, `closing_balance_due_usd_cents`, and a `source_snapshot`
with the draft, its source revision, the termination ground, the Deposit ids, the written ids and
the current physical move-out) and writes one `final_settlement.closed` audit event whose
correlation id is the draft id. An exact repeat by the same approver returns the stored result. The
closing balance stays open on the ledger of the Customer named on each obligation; nothing is
written off. The 8a-1 closure guard now also refuses a closure whose `closed_by` is not an active
human account (42501; the database keeps no Property membership, the application checks
`financial.approve` on the Property) or whose `closed_at` is later than the clock plus 5 seconds,
the bound of the other Settlement writers (23514). The preview gains the
blocking issue `RENT_PERIOD_NOT_BILLED` for each recurring Rent month a Rent run would still bill
(`app.lease_is_billable_for_recurring_period`) with no non-VOID Rent Invoice of the Lease covering
it, read by `app.final_settlement_unbilled_rent_months`; a month whose Rent Invoice a BR-RENT-030
hand-back resolution VOIDed (the hand-back month or, after the 25th, the next month) does not
count, while a month VOIDed for any other reason does (owner answers 2 to Q-2026-10-06-33 and to
Q-2026-10-06-34, with its follow-up).

`closing_balance_due_usd_cents` is the post-application, post-disposition, and
post-Refund Customer receivable remaining at closure. A refundable amount is not
stored as a negative balance; it must be represented by its explicit Refund event.

## DB-SETTLE-002 — `settlement_invoice_items`

Append-preserved membership snapshot: `final_settlement_id uuid NOT NULL FK`, `invoice_id uuid NOT NULL FK`, `outstanding_at_inclusion_usd_cents bigint NOT NULL CHECK (>=0)`, `included_at timestamptz NOT NULL`, `included_by uuid NOT NULL`, PK `(final_settlement_id, invoice_id)`. It identifies source obligations without replacing them.

As built in V1-056 sub-slice 8e-3 (migration `20261029_94`; owner answer 4 to Q-2026-10-06-32):
the table also has `id uuid NOT NULL UNIQUE`, the key of DB-SETTLE-006. Only the Settlement confirm
writes it, while the Settlement is still open, one row per issued, non-VOID Invoice of the Lease
(whoever is named on it, paid ones included); `outstanding_at_inclusion_usd_cents` is what the
Invoice still owes after every Settlement application, `included_by` is the approver. Each
Invoice or Late-payment Charge snapshot row (a line row through its Invoice row) starts a deferred
check at commit: the Settlement is closed, every such Invoice and
Late-payment Charge of the Lease is included, each Invoice row equals the sum of its line rows, and
all rows together equal `closing_balance_due_usd_cents`. A closure that writes no snapshot row
starts no such check; the confirm, the only closure writer, compares the snapshot sum with the
closing balance itself before it closes. Rows are append-only and no role may read or write them.

## DB-SETTLE-003 — `settlement_corrections`

Append-only authorized post-closure correction header: `id uuid PK`,
`final_settlement_id uuid NOT NULL FK`, `reason text NOT NULL`, `occurred_at timestamptz
NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`, and
`correlation_id uuid NOT NULL`. It carries no financial amount itself and never reopens
or rewrites the Settlement; one or more DB-SETTLE-005 rows identify every typed event
that produces the corrective effect.

## DB-SETTLE-004 — `settlement_late_payment_charge_items`

Append-preserved heterogeneous-obligation snapshot: `final_settlement_id uuid NOT NULL
FK`, `late_payment_charge_id uuid NOT NULL FK`, `outstanding_at_inclusion_usd_cents
bigint NOT NULL CHECK (>=0)`, `included_at timestamptz NOT NULL`, `included_by uuid NOT
NULL`, PK `(final_settlement_id, late_payment_charge_id)`. The Charge Customer and
source Invoice Lease context must match the Settlement Customer/Lease. This table
includes the separate obligation for reconciliation without converting it into an
Invoice or `settlement_invoice_items` row.

As built in V1-056 sub-slice 8e-3 (migration `20261029_94`): written by the Settlement confirm for
every Late-payment Charge of the Lease's Invoices, with its remaining balance after every
Settlement application (0 when paid); the same deferred closure check as DB-SETTLE-002.

## DB-SETTLE-005 — `settlement_correction_effects`

Append-only relational linkage: `id uuid PK`, `settlement_correction_id uuid NOT NULL
FK`, `effect_sequence smallint NOT NULL CHECK (>0)`, `invoice_adjustment_id uuid NULL
FK`, `invoice_adjustment_reversal_id uuid NULL FK`, `payment_allocation_id uuid NULL FK`,
`payment_allocation_reversal_id uuid NULL FK`,
`customer_credit_application_id uuid NULL FK`, `credit_application_reversal_id uuid
NULL FK`, `deposit_application_reversal_id uuid NULL FK`,
`deposit_disposition_reversal_id uuid NULL FK`, `late_payment_charge_correction_id uuid
NULL FK`, `refund_id uuid NULL FK`, and `refund_correction_id uuid NULL FK`, with
`UNIQUE (settlement_correction_id, effect_sequence)`. Exactly one effect FK is non-null.
Its Customer/Lease/source context and correlation must match the Settlement correction.
This explicit one-of-FK design preserves enforceable source identity; a free-form event
type/UUID or JSON-only reference is prohibited.

## DB-SETTLE-006 — `settlement_invoice_line_items`

Immutable line-aware closure membership/snapshot: `id uuid PK`,
`settlement_invoice_item_id uuid NOT NULL FK`, `invoice_line_id uuid NOT NULL FK`,
`category_snapshot text NOT NULL`, `original_amount_usd_cents bigint NOT NULL CHECK
(>=0)`, `adjustment_net_usd_cents bigint NOT NULL`,
`payment_allocated_usd_cents bigint NOT NULL CHECK (>=0)`,
`credit_applied_usd_cents bigint NOT NULL CHECK (>=0)`,
`deposit_applied_usd_cents bigint NOT NULL CHECK (>=0)`, and
`closing_outstanding_usd_cents bigint NOT NULL CHECK (>=0)`, with `UNIQUE
(settlement_invoice_item_id, invoice_line_id)`. The line must belong to the parent
Invoice and Settlement Lease. Deferred closure validation reconciles each row to
DB-DER-001 and its header totals. This preserves mixed Rent/Service composition and
remaining Rent without making Settlement snapshots a new financial source.

As built in V1-056 sub-slice 8e-3 (migration `20261029_94`): the CHECK
`settlement_invoice_line_items_reconcile` requires `closing_outstanding` = original + adjustment
net − Payment − Credit − Deposit; an insert trigger requires every value to equal the line's
current derived values and the line to belong to the parent Invoice; the deferred closure check of
DB-SETTLE-002 reconciles the header totals at commit.

## DB-REFUND-001 — `refunds`

Append-only outbound financial event.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `refund_number` | `text` | no | unique, immutable |
| `recipient_customer_id` | `uuid` | no | FK |
| `source_payment_id` | `uuid` | yes | unallocated excess source |
| `source_customer_credit_id` | `uuid` | yes | Credit source |
| `source_deposit_id` | `uuid` | yes | Deposit source |
| `final_settlement_id` | — | — | not a column: a settlement Deposit Refund's Final Settlement is held in `final_settlement_refund_details` (owner answer 3 to Q-2026-10-05-31) |
| `pet_refund_review_id` | `uuid` | yes | required for active-Lease Pet Deposit Refund; FK `pet_deposit_refund_reviews` |
| `usd_accounting_value_cents` | `bigint` | no | `CHECK (>0)` |
| `refund_currency` | `text` | no | `USD` only (DL-060) |
| `refund_amount_minor` | `bigint` | no | positive USD cents, equal to `usd_accounting_value_cents` |
| `reason` | `text` | no | |
| `processed_at` | `timestamptz` | no | |
| `processed_by` | `uuid` | no | |
| `authorization_reference` | `text` | no | |

Exactly one of the three source FKs (`source_payment_id`, `source_customer_credit_id`, `source_deposit_id`) is non-null. Source Customer must match recipient
and available recorded USD source value must not be exceeded. A direct Refund of
eligible KHR-origin Payment excess and a Credit Refund are paid and recorded in USD;
neither calculates a KHR remainder nor creates a Refund-date exchange record.
Original KHR amounts and immutable Payment-confirmation exchange records remain
linked through the source chain for audit. DL-060 removes the proposed KHR-Refund
fields from the new model, not existing historical transaction or conversion evidence;
no historical record is rewritten or deleted. Settlement Deposit Refunds remain
separate by Deposit.

A Security Deposit Refund requires the Lease to be TERMINATED and the applicable Final
Settlement. A Pet Deposit Refund normally follows that path, but while its Lease remains
SIGNED it instead requires `pet_refund_review_id`, prohibits `final_settlement_id` (as built: has no
`final_settlement_refund_details` row), verifies
the review's recorded permanent departure and resolved pet obligations, and preserves explicit
authorization. An active-Lease Refund never applies Deposit value to an Invoice, does
not require or create Final Settlement, and does not limit Customer liability.

As built (V1-056 sub-slice 8d, migration `20261026_91`; accepted by the owner, answer 3 to
Q-2026-10-05-31): the `final_settlement_id` link is not a column of `refunds`; it is held in
`final_settlement_refund_details`, because every Refund
reader returns the whole Refund row and the frontend checks its keys exactly, so a new column
would change every Refund response. The `refunds` source-context check is relaxed: only a
Deposit Refund has a context (`source_lifecycle_event_id` for a Reservation or
`pet_refund_review_id` for an active-Lease Pet Deposit), at most one, and a Deposit Refund with
neither is a Final Settlement Deposit Refund, which the Refund source trigger refuses without its
details row. `final_settlement_refund_details` (append-only; no role may read or write it) records
each Settlement Deposit Refund's `refund_id` (PK, deferred FK so it is written first),
`final_settlement_id`, `deposit_id`, the `FINAL_SETTLEMENT` `draft_id`, `refund_method_id`,
`reference_note` (1 to 500 characters), `signer_agreement` (null, or 1 to 2,000 characters) and
`recorded_at`, with `UNIQUE (final_settlement_id, deposit_id)`: one Refund per Deposit per
Settlement. The only writer is `app.post_final_settlement_deposit_refund(property, actor,
settlement, draft, refund, deposit, amount, recipient, refund method, reference note, signer
agreement, reason)`, internal (no role may call it), which the Settlement confirm (8e) calls with
the approver; the Refund row records `authorization_reference = 'financial.approve'`. The Refund
source trigger calls `app.assert_final_settlement_refund_source` for every writer: the Settlement
is open (55000 otherwise) and its Lease TERMINATED; the approver is an active person (42501 for a
non-person); the Deposit is a Security or Pet Deposit of that Lease owned by the Primary Tenant and
on the `DL_032` settlement path; the details row matches; the method is active (55000); the
recipient is the Primary Tenant without an agreement, or another signed Signer of the Lease with
the agreement (BR-REFUND-015); the Refund is exactly a `DEPOSIT_REFUNDS` step (Deposit, amount,
recipient, method, note, agreement) of a `FINAL_SETTLEMENT` draft of that Settlement that is
pending or confirmed by the same approver, and a deferred check lets the Refund commit only when
that draft is CONFIRMED under `financial.approve` by the Refund's approver (BR-AUTH-010); the
writer locks the Settlement row, then the Deposit's draft lock (`lease-deposit-forfeiture:<deposit>`)
and row, and sets its two deferred checks back to DEFERRED before it writes, so an earlier
`SET CONSTRAINTS ALL IMMEDIATE` in the transaction does not stop it; the amount is within what the Deposit
holds; no Deposit receipt reversal draft or forfeiture (or forfeiture reversal) draft is pending
for the Deposit, also one recorded after the Settlement draft was confirmed (the owner's 8r rule,
answer to Q-2026-10-05-31; 55000); the time is after the Deposit's latest balance event and the
Settlement start; and no open
debt of the Lease (every issued, non-VOID Invoice and its Late-payment Charges, read as the
preview reads them) is left that a Deposit could pay (55000): a Security Deposit could pay any of
it; a Pet Deposit is refused while pet damage is open and, outside the three BR-DEP-027
terminations, while any debt is open; and any Deposit is refused while debt is open and a Security
Deposit of the Lease on the `DL_032` path still holds money. The general Refund audit books a
Settlement Refund on the Deposit's Property and Lease, the Customer Ledger books it on the Deposit
owner (slice 3a-2), and the Refund correction paths (`app.require_correctable_usd_refund` and the
correction trigger) refuse it: it is corrected only through a post-settlement correction (slice
10). A Deposit application of a Settlement is refused once that Settlement has a Refund
(BR-SETTLE-008: applications first).

As built (V1-056 sub-slice 8f, migration `20261030_95`; BR-CREDIT-014, owner answer to
Q-2026-10-05-19): a Customer Credit that a credit Adjustment released
(`invoice_credit_excess_releases.customer_credit_id`) and whose Customer is not the payer of its
source Payment (a third-party Payment, or a wrong-Unit move to another Customer; no other Credit
has a Customer other than the payer) is refunded to that Customer. The "source Customer must match
recipient" rule above holds for every Credit Refund; only the payer rule is lifted, and only for
such a Credit. Staff with `refunds.create` record a `REFUND` draft of variant `CREDIT_CUSTOMER`
(`app.record_credit_customer_refund_draft`, financial role) with a Refund method, a reference note
and the Credit's Customer as `recipient_customer_id`; the payload keeps `source_kind` `CREDIT` and
`source_id`, so the draft reads and the Final Settlement preview's pending-draft check see it. Any
other Credit is refused with SQLSTATE `P5206`. A `financial.approve` holder confirms it through
`app.confirm_refund_draft`, which calls the internal writer `app.post_credit_customer_refund` (no
role may call it): Payment, then Credit lock; the Credit checked again (`P5206`); the amount within
the available Credit (`P5202`, the draft stays pending); the Refund row (id
`app.credit_customer_refund_id(draft)`, `processed_by` the approver, `authorization_reference`
`refunds.create` as every confirmed Refund draft) and the approver's replay row; the confirm then
writes `refund_draft_details` and the decision and sets the deferred checks IMMEDIATE (the writer
first sets its own deferred check back to DEFERRED, so an earlier `SET CONSTRAINTS ALL IMMEDIATE`
in the transaction does not refuse a valid confirmation). The Refund
source trigger accepts a recipient other than the payer only through
`app.credit_customer_refund_allowed`: such a Credit, paid to its Customer, with a matching
`CREDIT_CUSTOMER` draft (Property, Credit, recipient, amount, reason and the derived Refund id)
pending or confirmed by the Refund's approver; the deferred constraint trigger
`refunds_credit_customer_confirmed` lets such a Refund commit only with that draft CONFIRMED under
`financial.approve` by the same approver and its `refund_draft_details` row (42501 otherwise). The
Customer Ledger books it on the recipient in the `CREDIT` bucket, as every Credit Refund, and the
existing backend Refund correction paths apply (the frontend action context still expects a Credit
Refund's recipient to be the payer; slices 11c and 11e change that before a screen shows one). The ordinary `USD` Credit Refund draft of such a Credit still
records, and its confirmation is refused by the source check (23514), which the service reports as a
conflict, as it does a unique violation (23505) at confirmation.

Refund delivery methods or operational pending/failed states are deferred technical
workflow choices. This logical model records only the approved completed Refund event
and does not invent business statuses.

## DB-REFUND-002 — `refund_corrections`

Append-only generic linked correction: `id uuid PK`, `refund_id uuid NOT NULL FK`,
`correction_kind text NOT NULL CHECK IN ('VALUE_CORRECTION','CORRECTION_REVERSAL')`,
`reverses_correction_id uuid NULL UNIQUE FK refund_corrections`,
`source_balance_effect_usd_cents bigint NOT NULL CHECK (<>0)`,
`source_balance_effect_original_minor bigint NULL CHECK (<>0)`,
`previous_net_refund_usd_cents bigint NOT NULL CHECK (>=0)`,
`resulting_net_refund_usd_cents bigint NOT NULL CHECK (>=0)`, `reason text NOT NULL`,
`evidence_reference text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid
NOT NULL`, and `authorization_reference text NOT NULL`. A reversal references exactly
one active prior correction; a non-reversal prohibits that FK. Under DL-060, verified
returns of USD Refunds are in USD cents, with original-minor and USD effects equal;
partial returns need no KHR conversion or rounding. Preserve exact source and return
evidence and all historical facts. Net corrected Refund value may
not fall below zero or exceed the immutable original Refund. This table implements only
an authorized linked Refund correction; it invents no delivery status, returned-funds
workflow, collection right, or new Refund right.

---

# 13. Audit Persistence

## DB-AUDIT-001 — `audit_events`

Append-only table.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `occurred_at` | `timestamptz` | no | event instant |
| `business_date` | `date` | no | Property-local event date |
| `actor_id` | `uuid` | no | authenticated principal |
| `action` | `text` | no | stable action name |
| `entity_type` | `text` | no | affected relational entity |
| `entity_id` | `uuid` | no | affected stable ID |
| `reason` | `text` | no | mandatory for every audited event |
| `authorization_reference` | `text` | yes | mandatory for authorized actions |
| `previous_state` | `jsonb` | yes | null for creation |
| `resulting_state` | `jsonb` | yes | null only when action has no resulting snapshot |
| `correlation_id` | `uuid` | no | groups coordinated transaction events |
| `source` | `text` | no | `UI`, `API`, `SCHEDULED`, `ADMINISTRATIVE` |

Indexes: `(entity_type, entity_id, occurred_at, id)`, `(actor_id, occurred_at DESC)`, `(correlation_id)`, and `(business_date)`. Update/delete is prohibited. Audit stores history but never replaces authoritative aggregate/event rows.

## DB-AUDIT-002 — Minimum audited actions

At minimum, audit events are written in the same transaction for:

- Property/Unit and Customer changes;
- Reservation activation-threshold acceptance, activation, extension, expiration,
  classification, cancellation, Unit release, and completion at successful move-in;
- Lease signing, notices, general violation warnings, termination, Occupancy correction,
  pet departure, and Pet-obligation review;
- 20-day Rent Nonpayment Warning, 30-day Serious Nonpayment Default, cure, and later
  authorized action;
- Meter failure/replacement, Reading validation/correction, estimate basis, all rate
  versions, Service approval periods, and Lease Service terms;
- Invoice draft correction, issuance, line component calculation, Adjustment, derived
  status reconciliation, VOID, late-payment assessment/proposal, final decision, Charge
  creation, and Charge correction/reversal;
- Payment confirmation, Receipt issue/reprint, allocation proposal, Customer
  designation, line/Charge attribution, authorized posting, and reversal;
- Customer Credit recognition, proposal/designation, detailed application, reversal,
  Deposit events, active-Lease Pet Deposit Refund, and other Refunds; and
- every Final Settlement inclusion, application, disposition, Refund, closure,
  correction, and Customer Account Ledger reconciliation exception.

## DB-AUDIT-003 — Actor foreign key deferral

`actor_id` is logically mandatory but has no database FK until the authoritative Security Model defines principal persistence. Migrations must not point audit history to a speculative user table. Once defined, the FK must use `ON DELETE RESTRICT` or preserve an immutable actor identity snapshot.

---

# 14. Derived and Stored Information

## DB-DER-001 — Invoice obligation and balance

```text
adjusted line obligation
= immutable Invoice-line amount
+ active line DEBIT Adjustments not reversed by DB-INV-010
- active line CREDIT Adjustments not reversed by DB-INV-010

line outstanding
= adjusted line obligation
- active Payment Allocation detail applied to the line
- active Customer Credit Application detail applied to the line
- active Final Settlement Deposit Application applied to the line

Invoice adjusted obligation = sum adjusted line obligations
Invoice outstanding balance = sum nonnegative line outstanding balances
```

VOID and DRAFT Invoices are excluded from receivable balances. Neither a line nor
Invoice balance may become negative. Invoice status is a stored query/workflow summary
that must reconcile after every application, reversal, Adjustment, or VOID to DRAFT,
UNPAID, PARTIALLY_PAID, PAID, or VOID under the approved lifecycle. A reversal may
regress PAID to PARTIALLY_PAID or UNPAID only as the consequence of current derived
obligations; no arbitrary manual regression is allowed. Separate Late-payment Charge
balances never enter this formula or affect source Invoice status.

## DB-DER-002 — Payment availability and allocation condition

```text
payment available value
= original USD accounting value
- active Payment Allocations
- active Deposit Receipts not reversed by DB-DEP-007
- Customer Credit recognitions not reversed
- net Refund value directly sourced from Payment after DB-REFUND-002 correction effects
```

Unallocated/partially allocated/fully allocated are derived conditions, not Payment statuses. Payment status stores only RECEIVED or REVERSED.

## DB-DER-003 — Unit availability

Legal availability is derived from ACTIVE Reservations, applicable SIGNED Lease coverage, open Occupancy, and blocking operational conditions. `units.status` is stored only as a coordinated operational summary and cannot independently authorize a Reservation, Lease, or move-in.

## DB-DER-004 — Deposit balances

```text
required amount = original required amount + active required-amount adjustments
received amount = sum active Deposit Receipts not reversed by DB-DEP-007
held refundable balance
= received
- active Dispositions not reversed by DB-DEP-008
- active Deposit Applications not reversed by DB-DEP-006
- net Refund value sourced from Deposit after DB-REFUND-002 correction effects
outstanding required amount = max(required amount - received amount, 0)
```

No authoritative current-balance column is stored on `deposits`.

### Termination Deposit readiness projection (V1-055)

`app.lease_termination_deposit_readiness(Property, Lease, actor)` is a STABLE,
fixed-search-path read boundary, available to the runtime and financial roles.
The typed read service requires both `leases.read` and `deposits.read` for the
same Property. The database rechecks the active human actor and Lease Property;
the service uses one read-only repeatable-read transaction with bounded timeouts.

The response contains an observation timestamp and at most the Lease's one
Security and one Pet Deposit. It uses `deposit_snapshot` for current required,
received, held and outstanding amounts, and reports active dispositions and
versions separately. USD amounts are exact integer cents. Invalid scope,
cardinality, identities, money or consequence labels fail closed in the service.

Only an original `lease.terminate` command matching the Lease, Property, actual
termination date, terminated timestamp and result identifies processed
termination. A voluntary BR-LEASE-021 command must precede the original End Date;
if a new termination context exists it must agree. Valid legacy command evidence
remains readable without inventing a context. Status or free-form reason alone
never proves voluntary termination or pet noncompliance.

Verified voluntary termination identifies Security as non-refundable under
BR-DEP-023, with explicit disposition currently pending only while positive held
cash remains. Pet remains separately settled under BR-DEP-024. Other or missing
evidence requires signed-terms review; this read does not invent a forfeiture
basis. Unterminated Leases have no termination consequence.

Zero currently held cash is an observation, never a permanent financial
completion flag. Outstanding liability remains distinct from received cash, and
later receipts, valid dispositions and correction/reversal events change the
next observation. `financial_completion_assessed` is always false. The projection
does not post money, authorize a disposition, complete Settlement or change
physical Occupancy. Explicit disposition command strengthening/orchestration and
remaining V1-055 workflows require their subsequent bounded stages and final
integrated acceptance.

## DB-DER-005 — Customer Credit balance

Credit balance is recognition amount minus active applications and net Refund value
after DB-REFUND-002 correction effects, considering explicit reversals. It is always
USD, cannot be negative, and is not pooled with Deposit balances.

## DB-DER-006 — Utility consumption

Raw Utility Readings are authoritative measurements. Actual consumption is derived from consecutive validated effective readings of the same Meter and finalized into immutable `utility_consumption_periods` when it becomes a billing source. Broken-Meter estimates are explicitly stored with their basis and calculation.

## DB-DER-007 — Settlement balance

Before closure, Settlement net balance is derived from included DB-SETTLE-006
Invoice-line obligations and included separate Late-payment Charge balances, authorized
Payment Allocations and Credit Applications, permitted Deposit Applications to Invoice
lines and Late-payment Charges,
and their reversals/corrections. Deposit Dispositions and Refunds are separate
Deposit-liability/outbound effects and closure prerequisites; they never reduce the
Customer receivable formula. `closing_balance_due_usd_cents` is stored only as the
immutable closure snapshot and must reconcile to authoritative obligation/application
events.

## DB-DER-008 — Reporting projections

Materialized views or cached projections are permitted for performance only when reproducible from authoritative tables, refreshable, and never accepted as command-side sources of truth.

## DB-DER-009 — Late-payment Charge balance

```text
adjusted Charge obligation
= immutable original Charge amount
- active REDUCTION or CHARGE_REVERSAL effects
+ active valid REDUCTION_REVERSAL effects

Charge remaining balance
= adjusted Charge obligation
- active Payment Allocation details targeting the Charge
- active Customer Credit Application details targeting the Charge
- active Deposit Applications targeting the Charge (DB-DEP-005)
```

Both values are derived, cannot be negative, and cannot exceed the immutable original
amount. Zero means satisfied without a mutable Charge status. No term in this formula
changes the source Invoice.

## DB-DER-010 — Customer Account Ledger projection

The Customer Account Ledger is a read-only relational projection over authoritative
events, not an editable table. It emits stable Customer, event timestamp/business date,
event kind, source-table/source-UUID, Invoice and line identity where applicable,
separate Charge identity where applicable, charged amount, Payment received,
application, Credit, Refund, Adjustment, Deposit-liability movement, and reversal
effects. Receipt issue/reprint may appear as presentation history with zero financial
effect.

Chronology is deterministic by business instant, stable event-kind order, and source
UUID. Current Customer position is recomputed from the same source formulas: Invoice
obligation composition, separate Charge balances, total owed, available Customer
Credit, unallocated Payment, and Security/Pet Deposit liabilities remain separately
identifiable. The projection is reconstructable and reconcilable; it is not a General
Ledger, Chart of Accounts, vendor Accounts Payable, or second source of financial truth.

As built in V1-056 sub-slice 8a-2 (migration `20261023_88`): each Final Settlement Deposit
application (DB-DEP-005) is the event `DEPOSIT_APPLIED` (event order 75, after Credit
applications and before dispositions). It has two components with the same evidence: the
Deposit owner's component reduces the Security or Pet Deposit held, and the component of
the Customer named on the Invoice or Late-payment Charge reduces that Invoice line or
Charge. When both are the same Customer the event has one header with both components;
when the Deposit pays another Signer's debt, each ledger shows its own component, and the
evidence names the Deposit owner, the Invoice Customer, the Settlement, the stage, the
order and the reason. Every earlier projection result is unchanged. The ledger page accepts
`DEPOSIT_APPLIED` as a history filter.

## DB-DER-011 — Remaining Rent obligation

Remaining Rent is the sum of current outstanding amounts for `invoice_lines.category =
'RENT'` after line Adjustments and active Payment, Credit, and permitted Deposit detail.
It is independent of recurring-Service and other mixed-Invoice line balances and is the
only financial amount used for the Rent-specific 20/30-day workflow.

---

# 15. Transactional and Concurrency Constraints

## DB-TXN-001 — Coordinated transitions

Reservation activation, automatic expiration/cancellation and Unit release,
Reservation completion with resulting Lease/Occupancy, Lease signing, move-in,
move-out/termination, Invoice issuance, late-payment final decision/Charge creation,
Allocation/Application posting, reversal, Payment confirmation/Receipt issue, Deposit
receipt, Refund, nonpayment event, and Settlement closure execute atomically with their
audit events.

## DB-TXN-002 — Reservation and Lease conflicts

Reservation creation locks the Unit and checks the partial unique constraint. Lease signing locks the Unit and relies on the exclusion constraint. Constraint violations reject rather than silently alter dates or statuses.

## DB-TXN-003 — Financial posting locks

A financial posting locks every affected source, header, relational detail, and target
in stable UUID order, calculates availability from append-only active events, inserts
the event, recomputes affected Invoice and/or Late-payment Charge positions, and writes
audit history before commit. Payment and Credit proposals are revalidated at posting;
proposal generation alone has no financial effect.

## DB-TXN-004 — No negative or double-consumed value

Deferred constraint triggers verify at commit that no Invoice line, Invoice, separate
Late-payment Charge, Payment, Credit, Deposit, Utility period, or Refund source is
over-applied, over-refunded, billed twice, or negative. Header/detail totals and all
same-Customer/source-target relationships must reconcile.

## DB-TXN-005 — Scheduled idempotency

Rent generation uses Lease plus rental period as its stable business key. Utility generation uses the finalized Utility Consumption Period. Service generation uses Lease, configured Service, and billing period. Unique indexes in DB-INV-002 make retries idempotent.

Initial Rent and Service generation uses Lease plus the complete initial coverage period
as the stable key. Day-21-or-later component rows do not create a second billable period.
Late-payment decisions use unique source Invoice; Charges use unique decision/source;
Receipt uses unique Payment; Rent nonpayment milestone indexes make scheduled retries
idempotent.

Recurring generation uses the existing approved final-month source predicate when a
recorded voluntary early termination falls inside the requested calendar month and
before the original contractual End Date. The exact immutable `BR-LEASE-021` command
must match the Lease termination occurrence, reason, status and actual date. Initial
coverage, including the day-21 rule, still excludes duplicate recurring periods.
The new Invoice records `BR-RENT-024` provenance and the existing fifth-day Due Date;
Rent remains the full contractual monthly amount, with only valid Service sources.
Later months and unsupported holdover coverage remain rejected. Existing issued
Invoices and exact command replays retain their original evidence and amounts.

This generation alignment does not itself authorize termination, apply Deposit
dispositions, settle balances, change physical Occupancy, or create an Adjustment.
Initial/final charge reconciliation and controlled corrections remain separate.

## DB-TXN-006 — Property-local scheduling

The 25th-day billing run, 5th-day due-date calculation, Reservation end-of-date expiration, and monthly Utility boundaries are calculated using `properties.timezone_name`; stored instants remain `timestamptz` and business dates remain `date`.

## DB-TXN-007 — Late-payment and nonpayment assessment snapshots

Assessment transactions lock the source Invoice and applicable line/application rows,
derive balances as of the Property-local instant, and persist the balance snapshots used
for the decision or notice. Late-payment assessment uses whole applicable source-Invoice
balance; Rent nonpayment uses only remaining Rent line obligation. Neither scheduled
detection posts a charge, terminates a Lease, or creates another business event without
its separately authorized transaction.

---

# 16. Immutability and Correction Matrix

| Record | Mutable window | Approved correction after finalization |
|---|---|---|
| Customer contact | current data may update | audit previous/resulting values |
| Reservation | approved lifecycle fields only | explicit transition/Notice plus audit; COMPLETED/CANCELLED remain terminal |
| Reservation Deposit Acceptance | never | immutable accepted threshold and authorization history |
| Lease | DRAFT fields before signing | termination or linked historical correction; never rewrite signed terms silently |
| Lease Signer | DRAFT only | preserve signed signer history |
| Occupancy | move-out/correction workflow | audited correction preserving prior value |
| Utility Reading | before validation | correction event; billed effect via Invoice Adjustment |
| Reading Correction | never | later authorized correction event; original chain retained |
| Rate version | never after insertion | new effective-dated version |
| DRAFT Invoice/line | before issuance, audited | draft correction |
| issued Invoice/line | immutable | DB-INV-003 Adjustment, DB-INV-010 Adjustment Reversal, dependency reversal, or exceptional VOID |
| Late-payment Decision/Charge | never | linked Charge correction/reversal; final decision retained |
| Payment | original money-received facts immutable | Payment Reversal |
| Receipt/Reprint | never | later Reprint event using same Receipt identity |
| Allocation/Application header and detail | immutable | linked header Reversal removes all detail effect |
| Deposit receipt | immutable | DB-DEP-007 linked Deposit Receipt Reversal |
| Deposit disposition/application | immutable | DB-DEP-008/DB-DEP-006 linked Reversal |
| Credit recognition | immutable | linked application/reversal/refund |
| Refund | immutable completed event | DB-REFUND-002 linked correction without rewrite |
| Rent Nonpayment Event | never | later Cure or authorized follow-up event |
| closed Settlement | immutable | linked post-closure financial corrections |
| Audit Event | immutable | later audit event, never overwrite |

## DB-IMM-001 — Database protection

Append-only tables reject `UPDATE` and `DELETE` through database privileges and protective triggers owned by a migration role unavailable to the application. Aggregate-column immutability after issuance/signing/finalization is enforced by triggers in addition to service validation.

---

# 17. Foreign-Key Delete Actions

## DB-FK-001 — Restrict historical deletion

All business and event FKs use `ON DELETE RESTRICT` (or default `NO ACTION`, deferred where coordinated insertion requires it). No financial, audit, Reservation, Lease, Occupancy, Meter, Reading, rate, or Settlement relationship uses `ON DELETE CASCADE` in production migrations.

## DB-FK-002 — Nullability is business cardinality

A nullable FK is permitted only where this specification explicitly states optionality. In particular, Customer ownership on Invoice is never nullable, while Invoice Lease association is nullable.

---

# 18. Required Supporting Views

Views are non-authoritative conveniences and must expose formulas transparently.

## DB-VIEW-001

`invoice_line_financial_position` exposes each authoritative line's original amount,
active debit/credit Adjustments, active Payment/Credit/Deposit detail, adjusted
obligation, outstanding amount, and obligation category. `invoice_financial_position`
rolls those rows to original total, adjusted obligation, outstanding balance, and
reconciled Invoice status.

## DB-VIEW-002

`payment_financial_position` exposes original USD value, allocated value, Deposit-directed value, Credit-recognized value, directly refunded value, unallocated value, and allocation condition.

## DB-VIEW-003

`deposit_financial_position` exposes required, received, disposed, applied, refunded, held refundable, and outstanding required amounts separately by Deposit.

## DB-VIEW-004

`customer_credit_financial_position` exposes recognized, applied, refunded, reversed, and available USD values by Credit source and Customer.

## DB-VIEW-005

`lease_financial_position` aggregates issued non-VOID Invoice line balances and
applicable separate Late-payment Charge balances associated with the Lease without
creating signer-specific debt shares. Its components remain queryable separately.

## DB-VIEW-006

`unit_legal_availability` exposes authoritative blocking Reservation, Lease, Occupancy,
and operational conditions alongside the stored Unit status.

## DB-VIEW-007

`late_payment_charge_financial_position` exposes immutable original amount, active
correction/reversal effects, Payment/Credit applications, adjusted obligation, remaining
balance, source Invoice, decision, Customer, and payability instant.

## DB-VIEW-008

`remaining_rent_obligation` exposes Rent-line balance independently from every mixed
Invoice's recurring-Service and other lines and provides the source for 20/30-day
nonpayment assessment.

## DB-VIEW-009

`customer_account_ledger` provides the deterministic chronological projection defined
by DB-DER-010. `customer_financial_position` reconciles total Invoice obligations,
separate Late-payment Charges, total owed, available Credit, unallocated Payment, and
Security/Pet Deposit liabilities without netting those concepts together.

## DB-VIEW-010

`utility_effective_readings` exposes each immutable original Reading, ordered correction
chain, effective value, affected Consumption Period, Invoice line, source Invoice, and
Adjustment linkage without rewriting any source row.

---

# 19. Migration and Verification Requirements

## DB-MIG-001 — Forward-only migrations

Schema changes use reviewed, versioned, forward migrations. Migrations must not reset, recreate, or silently rewrite business history.

## DB-MIG-002 — Financial backfills

A backfill affecting financial, rate, Reading, or Settlement history must be deterministic, idempotent, reconcilable before/after, and audit documented. Destructive migration is prohibited without explicit Owner approval and a recovery plan.

## DB-TEST-001 — Constraint tests

Database integration tests must prove all checks, partial unique indexes, exclusion constraints, FKs, append-only protections, allowed transitions, and concurrency behavior.

## DB-TEST-002 — Reconciliation tests

Tests must independently recompute Invoice lines/Invoices, separate Late-payment
Charges, Payments, Credits, Deposits, Customer position, Lease position, and Settlement
balances from source events and compare them with statuses, views, and closure
snapshots. Ledger totals must reconcile to these independent results under BR-AUDIT-011
and PR-AUDIT-011.

## DB-TEST-003 — Mandatory Invoice relationship tests

Tests must prove that an Invoice cannot exist without a Customer; may exist without a Lease only under an approved non-Lease source; requires a Lease for Rent; and rejects inconsistent Lease Customer, Unit, period, or source context.

## DB-TEST-004 — Historical correction tests

Tests must prove that correction, reversal, VOID, disposition, and Refund workflows preserve the original rows and complete source chain.

## DB-TEST-005 — Date, rate, and rounding tests

Tests cover Property-local boundaries, leap years, inclusive proration, half-up USD-cent rounding, generation-date Utility Rate selection, whole-period Utility rate application, 0.5% System Exchange Rate markup, upward whole-KHR rate rounding, and upward final KHR payable rounding.

## DB-TEST-006 — Reservation, initial billing, and Service tests

Tests cover only ACTIVE/CANCELLED/COMPLETED, terminal guards, 0..1 resulting Lease,
exactly one Lease for COMPLETED and none for CANCELLED, accepted Deposit threshold below,
equal to, and above the 20% suggestion, full Deposit at move-in, and immutable acceptance
provenance. Initial Rent and Service tests cover days 1, 20, 21, month-end, leap-year,
and the 27 July–31 August/3 August example; component sums, first uncovered month,
25th-day resumption, Due Dates, overlap rejection, and no Lease override are asserted.
Service tests prove only Owner-approved effective periods can bill; merely configuring
Internet, Monthly Cleaning, or another future code cannot create a billable line.

## DB-TEST-007 — Utility basis and Reading correction tests

Tests prove latest-three selection for three or more historical actual periods, all
available selection for exactly one/two, and first future period only for zero history.
They reject comparable Units and arbitrary basis periods. Reading tests cover
pre-issuance input correction, post-issuance no-amount-change history, post-issuance
Adjustment linkage, immutable originals, and identical behavior regardless of Invoice
payment status.

## DB-TEST-008 — Late-payment and detailed application tests

Tests prove the overdue boundary, one final decision, 10% proposal, confirmed/reduced/
waived branches, no automatic posting, no repeat/compounding/supplement/replacement,
separate Charge creation only for a positive amount, no Due Date, immutable original,
correction/reversal history, nonnegative remaining balance, and no source-Invoice effect.
Allocation/Credit tests cover FIFO/ties between Invoices, Rent-first only within one
mixed Invoice, Customer designation, proposal-versus-confirmation, line attribution,
direct Charge targeting, same-Customer guards, concurrent over-application, and full
reversal history.

## DB-TEST-009 — Receipt, nonpayment, Pet Refund, and Settlement tests

Tests prove one Receipt identity/Number per Payment, repeat reprints without a new
Payment or money event, and Receipt's zero balance effect. Rent tests assert separate
20-day Warning and 30-day Serious Default from remaining Rent only, cure history,
separation from generic violation warnings, and no automatic Lease/Occupancy/Unit/
Move-out/Settlement transition. Pet tests cover a SIGNED-Lease Refund after permanent
departure and obligation resolution while rejecting active Security Deposit Refund and
active-Lease Deposit application. Settlement tests include separate Charge membership
without turning it into an Invoice and keep Deposit targets Invoice-line-only.

## DB-TEST-010 — Currency and immutable-source tests

Tests prove Invoice/Credit accounting in USD; USD/KHR Payment facts; ABA Sell reference
times 1.005; upward whole-KHR System Rate and final payable rounding; permitted manual
ABA-equivalent fallback; Payment-confirmation rate snapshot; authoritative channel
transaction values; KHR-origin Credit provenance through Payment; USD-only Refunds
and exact-cent partial returns without Refund conversion (DL-060); and append-only/
restrict-delete protection for every new event table.

---

# 20. Authentication and Account Security Storage

## DB-AUTH-001 — Local human accounts

`user_accounts` stores an immutable UUID actor identity, unique normalized username,
display/audit identity, account lifecycle state, MFA-policy class, timestamps, and
provenance. Username uniqueness is enforced transactionally. Shared accounts and
external-provider identity as the normal login source are prohibited. Role/capability
assignments remain separate relations and do not become hard-coded username or role
checks.

## DB-AUTH-002 — Password credentials

Password credential rows store only a salted adaptive password-verifier encoding,
algorithm/work-factor metadata, change time, and lifecycle/audit provenance. Plaintext,
reversibly encrypted passwords, security questions, password values in audit snapshots,
and reusable bootstrap secrets are prohibited.

## DB-AUTH-003 — MFA and recovery-code state

MFA enrollment state and protected verifier material are stored separately from role
authority. Owner and Manager accounts cannot enter normal privileged operation until
required MFA enrollment is complete; Staff enrollment may be absent. Recovery codes
have independently verifiable one-time identities and consumed timestamps. If server
verification material is retained, it is non-reversible; usable recovery codes are
never stored in plaintext.

## DB-AUTH-004 — Sessions and revocation

Durable session records contain only protected token identifiers/verifiers, user,
creation, last-activity, absolute-expiry, idle-expiry/recalculation data, revocation
time/reason, and audit provenance. They enforce a 30-minute inactivity timeout and
24-hour absolute lifetime. Password/MFA recovery, account disablement, and material
privilege reduction can revoke all applicable sessions promptly.

## DB-AUTH-005 — Recovery and bootstrap audit

Administrative recovery, emergency Owner recovery, MFA enrollment/reset/disablement,
credential reset, recovery-code use, session revocation, and initial Owner bootstrap
produce immutable security audit events without secrets. A database invariant or
equivalently strong transactional guard prevents initial-Owner bootstrap after the
initial Owner is established and prevents bootstrap from becoming an additional-Owner
backdoor.

---

# 21. Deferred Technical and Configuration Decisions

No genuine Owner business-policy decision remains open in this Database Model. The
previous first-partial-month Due Date question is resolved upstream: Initial Rent is due
proposed as the Lease Start Date plus five calendar days, with an authorized override. The following implementation/configuration
choices must preserve
the normative model but do not reopen business policy:

- **TCD-DB-001 — Customer input quality:** choose legal-name/contact validation and
  duplicate-record matching controls without changing one-Customer identity or deleting
  history. No contact channel is made mandatory by this model.
- **TCD-DB-002 — Refund delivery implementation:** delivery integration and transient
  technical delivery states may be designed later; only a successfully processed
  Refund is the approved business event persisted here.
- **TCD-DB-003 — Business-number generation:** configure formatting and sequence scope
  for Invoice, Payment, Receipt, and Refund Numbers while preserving uniqueness,
  immutability, and non-reuse.
- **TCD-DB-004 — Meter serial validation:** production configuration may enforce global
  or Utility-Type serial uniqueness when the source system guarantees that scope; the
  stable Meter UUID remains authoritative.
- **TCD-DB-005 — Utility measurement configuration:** every Meter stores a nonblank
  production-configured unit code, and Utility Rate configuration uses the same unit.
  Electricity and Water fixtures cannot be finalized until their actual units/scales
  are configured; this is configuration, not a new charging rule.

---

# 22. Upstream Traceability Summary

The complete authoritative foundation contains 381 unique detailed Business Rules and
381 same-suffix detailed Product Requirements. Every family is represented below; the
high-level `PR-CAP-*`, `PR-WF-*`, and `PR-QUAL-*` references supplement rather than
replace detailed traceability.

| Database area | Database requirements | Business Rules | Product Requirements |
|---|---|---|---|
| Property and Units | DB-PROP-001, DB-UNIT-001, DB-DER-003, DB-VIEW-006 | BR-PROP-001..003, BR-UNIT-001..013 | PR-PROP-001..003, PR-UNIT-001..013, PR-CAP-001 |
| Customers | DB-CUST-001, DB-DER-010, DB-VIEW-009 | BR-CUST-001..003 | PR-CUST-001..003, PR-CAP-001 |
| Reservations | DB-RES-001..003, DB-TXN-001..002, DB-TEST-006 | BR-RES-001..022 | PR-RES-001..022, PR-CAP-002, PR-WF-001..003 |
| Leases | DB-LEASE-001..011, DB-TXN-002, DB-TXN-007, DB-TEST-009 | BR-LEASE-001..030 | PR-LEASE-001..030, PR-CAP-003, PR-WF-003..005 |
| Occupancy and Move-out | DB-LEASE-003, DB-MOVEOUT-001..002 | BR-OCC-001..009, BR-MOVEOUT-001..012 | PR-OCC-001..009, PR-MOVEOUT-001..012, PR-WF-003, PR-WF-005 |
| Deposits | DB-DEP-001..008, DB-RES-003, DB-LEASE-010..011, DB-REFUND-001..002, DB-DER-004 | BR-DEP-001..025 | PR-DEP-001..025, PR-CAP-002, PR-WF-001..006 |
| Rent and initial billing | DB-LEASE-001, DB-INV-001..002, DB-INV-006, DB-DER-011, DB-TXN-005..006 | BR-RENT-001..029 | PR-RENT-001..029, PR-CAP-004, PR-WF-004 |
| Utilities and Reading corrections | DB-UTIL-001..010, DB-INV-002..003, DB-VIEW-010 | BR-UTIL-001..032 | PR-UTIL-001..032, PR-CAP-004, PR-WF-004..005 |
| Configured recurring Services | DB-SVC-001..003, DB-LEASE-007, DB-INV-002, DB-INV-006 | BR-SVC-001..015 | PR-SVC-001..015, PR-CAP-004, PR-WF-004 |
| Invoices, lines, Adjustments, VOID, and late-payment decision persistence | DB-INV-001..010, DB-DER-001, DB-VIEW-001 | BR-INV-001..055 | PR-INV-001..055, PR-CAP-004, PR-WF-004, PR-WF-007, PR-WF-009 |
| Late-payment decisions and Charges | DB-INV-007..009, DB-DER-009, DB-VIEW-007, DB-TXN-007 | BR-LATE-001..006 | PR-LATE-001..006, PR-CAP-004, PR-WF-009 |
| Payments and line-aware Allocations | DB-PAY-001..007, DB-DER-002, DB-VIEW-002 | BR-PAY-001..040 | PR-PAY-001..040, PR-CAP-005, PR-WF-004, PR-WF-007..008 |
| Receipts and reprints | DB-RECEIPT-001..002 | BR-RECEIPT-001..006 | PR-RECEIPT-001..006, PR-CAP-005, PR-WF-008 |
| Customer Credit | DB-CREDIT-001..005, DB-DER-005, DB-VIEW-004 | BR-CREDIT-001..013 | PR-CREDIT-001..013, PR-CAP-005, PR-WF-004, PR-WF-006..008 |
| Customer Account Ledger | DB-DER-010, DB-VIEW-009, DB-TEST-002 | BR-LEDGER-001..007 | PR-LEDGER-001..007, PR-CAP-008, PR-WF-008..009, PR-QUAL-008 |
| Refunds | DB-REFUND-001..002, DB-LEASE-010..011 | BR-REFUND-001..013 | PR-REFUND-001..013, PR-CAP-005, PR-WF-002, PR-WF-004, PR-WF-006..007, PR-WF-009 |
| Final Settlement | DB-SETTLE-001..006, DB-DEP-005..006, DB-DER-007 | BR-SETTLE-001..015 | PR-SETTLE-001..015, PR-CAP-006, PR-WF-005..007 |
| Money, exchange, and rounding | DB-TYPE-004..005, DB-PAY-002..003, DB-REFUND-001, DB-TEST-005, DB-TEST-010 | BR-MONEY-001..013 | PR-MONEY-001..013, PR-CAP-005, PR-QUAL-006 |
| Audit and authorization | DB-AUDIT-001..003, DB-IMM-001, DB-TXN-001..007 | BR-AUDIT-001..011, BR-AUTH-001..009 | PR-AUDIT-001..011, PR-AUTH-001..009, PR-CAP-007, PR-QUAL-001..008 |
| Authentication and account security | DB-AUTH-001..005 | SEC-009..018, SEC-071..075 | PR-CAP-009 |

---

# 23. Completion Criteria

This Database Model is ready for Owner review when:

1. every specified table and column is internally consistent and traceable before migration design begins;
2. mandatory/optional cardinalities are unchanged;
3. every invariant has an explicit declarative or transactional enforcement mechanism and planned verification;
4. append-only and immutable-history protections are explicitly specified;
5. all financial views reconcile to source events;
6. no derived value has become a competing source of truth;
7. no older placeholder document has introduced policy; and
8. the completed `003_PRODUCT_REQUIREMENTS.md` conformance audit remains conflict-free, or any later change is reported rather than guessed.

---
