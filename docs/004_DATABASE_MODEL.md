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
| provenance columns | as DB-TYPE-007 | no | mutable aggregate provenance |

A database constraint trigger rejects insertion when a Property row already exists. Property deletion is prohibited.

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
  may satisfy the remaining full Deposit before move-in. No comparison to a
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
  requires the resulting Lease to be SIGNED, match the Reservation Unit and Customer
  relationship, have the successful actual move-in represented by Occupancy, and have
  the full current required Security Deposit received. Any applicable move-in Pet
  Deposit must likewise be fully received. At transition the Reservation must remain
  unexpired on `effective_expiration_date`; Occupancy creation, Unit transition to
  `OCCUPIED`, and Reservation completion occur atomically under DB-TXN-002. It never
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
positive amount at 20 calendar days after Due Date; a serious default requires a
positive amount at 30 calendar days. TWENTY_DAY_WARNING requires a Notice/document
reference; AUTHORIZED_FOLLOW_UP requires an authorization reference. CURE stores zero
after a warning or default; later authorized follow-up remains explicit. No event
changes Lease, Occupancy, Unit, Move-out, or Final Settlement state automatically.

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
| `due_date` | `date` | no | source recorded below |
| `billing_period_start` | `date` | yes | both or neither with end |
| `billing_period_end` | `date` | yes | inclusive, >= start |
| `rent_billing_kind` | `text` | yes | `INITIAL` or `RECURRING`; required exactly when the Invoice contains Rent |
| `original_total_usd_cents` | `bigint` | no | `CHECK (>= 0)`; immutable after issuance |
| `due_date_rule` | `text` | no | `INITIAL_RENT_SEVEN_DAYS`, `RECURRING_RENT_FIFTH`, or `GOVERNING_SOURCE` |
| `due_date_source` | `text` | no | approved rule/event/document trace; never a Lease override |
| `issued_at` | `timestamptz` | yes | required unless DRAFT |
| `issued_by` | `uuid` | yes | required unless DRAFT |
| provenance columns | as DB-TYPE-007 | no | |

Constraints and indexes:

- `UNIQUE (invoice_number)` and `UNIQUE (id, lease_id)` to support consistency references.
- Rent requires non-null `lease_id`, period dates, and applicable SIGNED Lease.
- INITIAL Rent requires Due Date exactly seven calendar days after the applicable
  Occupancy Move-in Date. Its period begins on Move-in Date and ends at that month-end
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
`source_reference`. Invoice Customer/Lease/category/amount must equal the obligation,
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

## DB-CREDIT-003 — `customer_credit_application_reversals`

Append-only: `id uuid PK`, `credit_application_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`.

## DB-CREDIT-004 — `customer_credit_reversals`

Append-only: `id uuid PK`, `customer_credit_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. It requires all applications and Refund commitments sourced from the Credit to be resolved explicitly.

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

## DB-DEP-005 — `deposit_applications`

Append-only Final Settlement financial event: `id uuid PK`, `deposit_id uuid NOT NULL FK`, `final_settlement_id uuid NOT NULL FK`, `invoice_id uuid NOT NULL FK`, `invoice_line_id uuid NOT NULL FK`, `application_stage text NOT NULL CHECK IN ('PET_RELATED_FIRST','SECURITY_EXPLICIT','PET_REMAINDER_EXPLICIT')`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `application_order integer NOT NULL CHECK (>0)`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`, `UNIQUE (final_settlement_id, application_order)`.

- Application is allowed only after Lease TERMINATED and before the Settlement's `closed_at` is set.
- Applicable Customer Credit is handled first. `PET_RELATED_FIRST` preserves Pet Deposit
  identity against pet-related Invoice lines before Security Deposit use.
  `SECURITY_EXPLICIT` then permits authorized management to select Security Deposit
  applications. `PET_REMAINDER_EXPLICIT` may finally apply remaining Pet Deposit to any
  valid remaining Settlement Invoice line, not only pet-related damage.
- Every stage and target is explicitly authorized. `application_order` records the
  actual sequence; neither Payment FIFO nor an inferred Deposit-type FIFO is reused.
- A deferred trigger matches PET stages to a Pet Deposit and SECURITY stage to a
  Security Deposit and verifies all prior-stage prerequisites from current balances.
- The line must belong to the Invoice and Settlement Lease. Application cannot exceed
  held refundable Deposit balance or the current Invoice-line obligation. A Deposit
  Application cannot target a separate Late-payment Charge.

## DB-DEP-006 — `deposit_application_reversals`

Append-only: `id uuid PK`, `deposit_application_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`.

## DB-DEP-007 — `deposit_receipt_reversals`

Append-only: `id uuid PK`, `deposit_receipt_id uuid NOT NULL UNIQUE FK`, `reason text
NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`,
`authorization_reference text NOT NULL`. Posting is prohibited while any dependent
Deposit disposition, application, or Refund remains active. It removes the receipt's
derived liability effect without altering the original receipt.

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

`closing_balance_due_usd_cents` is the post-application, post-disposition, and
post-Refund Customer receivable remaining at closure. A refundable amount is not
stored as a negative balance; it must be represented by its explicit Refund event.

## DB-SETTLE-002 — `settlement_invoice_items`

Append-preserved membership snapshot: `final_settlement_id uuid NOT NULL FK`, `invoice_id uuid NOT NULL FK`, `outstanding_at_inclusion_usd_cents bigint NOT NULL CHECK (>=0)`, `included_at timestamptz NOT NULL`, `included_by uuid NOT NULL`, PK `(final_settlement_id, invoice_id)`. It identifies source obligations without replacing them.

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
| `final_settlement_id` | `uuid` | yes | required for settlement Deposit refund |
| `pet_refund_review_id` | `uuid` | yes | required for active-Lease Pet Deposit Refund; FK `pet_deposit_refund_reviews` |
| `usd_accounting_value_cents` | `bigint` | no | `CHECK (>0)` |
| `refund_currency` | `text` | no | `USD` only (DL-060) |
| `refund_amount_minor` | `bigint` | no | positive USD cents, equal to `usd_accounting_value_cents` |
| `reason` | `text` | no | |
| `processed_at` | `timestamptz` | no | |
| `processed_by` | `uuid` | no | |
| `authorization_reference` | `text` | no | |

Exactly one of the three source FKs is non-null. Source Customer must match recipient
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
SIGNED it instead requires `pet_refund_review_id`, prohibits `final_settlement_id`, verifies
the review's recorded permanent departure and resolved pet obligations, and preserves explicit
authorization. An active-Lease Refund never applies Deposit value to an Invoice, does
not require or create Final Settlement, and does not limit Customer liability.

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

## DB-DER-005 — Customer Credit balance

Credit balance is recognition amount minus active applications and net Refund value
after DB-REFUND-002 correction effects, considering explicit reversals. It is always
USD, cannot be negative, and is not pooled with Deposit balances.

## DB-DER-006 — Utility consumption

Raw Utility Readings are authoritative measurements. Actual consumption is derived from consecutive validated effective readings of the same Meter and finalized into immutable `utility_consumption_periods` when it becomes a billing source. Broken-Meter estimates are explicitly stored with their basis and calculation.

## DB-DER-007 — Settlement balance

Before closure, Settlement net balance is derived from included DB-SETTLE-006
Invoice-line obligations and included separate Late-payment Charge balances, authorized
Payment Allocations and Credit Applications, permitted Invoice-only Deposit Applications,
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
seven calendar days after actual Move-in Date. The following implementation/configuration
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
