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

Business calendar dates use `date`. Audit, approval, posting, issuance, and processing instants use `timestamptz`. PostgreSQL stores instants in UTC; Property-local date calculation uses `properties.timezone_name`, an IANA timezone name.

## DB-TYPE-004 — Money

USD amounts use signed `bigint` integer cents and columns ending `_usd_cents`. KHR amounts use signed `bigint` whole riel and columns ending `_khr`. Original positive obligations and receipts have `CHECK (amount > 0)`; signed correction events may be positive or negative only where explicitly defined.

All Invoice and Customer Credit accounting values are USD. Binary floating-point types are prohibited for authoritative monetary or rate calculations.

## DB-TYPE-005 — Quantities and rates

Meter readings and consumption quantities use `numeric(20,6)`. Utility unit rates use `numeric(20,8)` USD per measured unit. The ABA reference rate may use `numeric(20,6)` KHR/USD; the marked-up System Exchange Rate is stored as whole `bigint` KHR/USD after upward rounding.

## DB-TYPE-006 — Text and JSON

Names, numbers, descriptions, reasons, and memos use `text`. `jsonb` is permitted for immutable audit before/after snapshots and calculation traces, but not as a substitute for a relational foreign key, monetary column, status, or supported category.

## DB-TYPE-007 — Standard provenance columns

Mutable aggregate tables contain `created_at timestamptz NOT NULL`, `created_by uuid NOT NULL`, `updated_at timestamptz NOT NULL`, and `updated_by uuid NOT NULL`. Append-only event tables contain `occurred_at timestamptz NOT NULL` and `actor_id uuid NOT NULL` instead. Actor UUIDs refer to the authenticated principal identity defined by the later Security Model; no user table is invented here.

## DB-TYPE-008 — No normal hard deletion

Operational history, issued or void Invoices, Payments, Allocations, Credits, Deposits, Refunds, rate history, Settlements, and audit events must not be physically deleted in normal workflows. Statuses and explicit events represent lifecycle changes.

---

# 4. Relationship Overview

```text
property 1 ── * unit
unit 1 ── * reservation * ── 1 customer
reservation 1 ── 0..1 resulting lease
reservation 1 ── 1 security deposit
unit 1 ── * lease * ── 1 primary-tenant customer
lease 1 ── * lease_signer * ── 1 customer
lease 1 ── * occupancy * ── 1 customer
unit 1 ── * utility_meter 1 ── * utility_reading
customer 1 ── * invoice
invoice * ── 0..1 lease
invoice 1 ── * invoice_line
customer 1 ── * payment 1 ── * payment_allocation * ── 1 invoice
reservation/lease ── deposit 1 ── * deposit_receipt
customer 1 ── * customer_credit
terminated lease 1 ── 1 final_settlement
financial source 1 ── * refund
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
| `timezone_name` | `text` | no | valid IANA timezone |
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

No Customer type/category column exists. Customer deletion is prohibited while historical records exist and is not a normal workflow.

**OPEN OWNER DECISION OOD-DB-001 (nonblocking):** Upstream rules do not define legal-name structure, contact-field validation, duplicate-person matching, or which contact field is mandatory. The columns above preserve the approved value objects without inventing those policies.

---

# 6. Reservation and Lease Tables

## DB-RES-001 — `reservations`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `unit_id` | `uuid` | no | FK `units(id) ON DELETE RESTRICT` |
| `customer_id` | `uuid` | no | FK `customers(id) ON DELETE RESTRICT` |
| `reservation_date` | `date` | no | actual business date |
| `agreed_monthly_rent_usd_cents` | `bigint` | no | positive; source for the 20% activation minimum |
| `original_expiration_date` | `date` | no | immutable |
| `effective_expiration_date` | `date` | no | current approved boundary |
| `status` | `text` | no | `ACTIVE`, `CANCELLED`, `MOVED_IN` |
| `resulting_lease_id` | `uuid` | yes | unique FK `leases(id)`; deferred because Lease is declared below |
| `cancellation_reason_code` | `text` | yes | required only when CANCELLED |
| `cancellation_responsibility` | `text` | yes | `CUSTOMER` or `PROPERTY` only when CANCELLED; reason records expiration separately |
| `cancelled_at` | `timestamptz` | yes | required only when CANCELLED |
| `moved_in_at` | `timestamptz` | yes | required only when MOVED_IN |
| provenance columns | as DB-TYPE-007 | no | |

Checks and indexes:

- `effective_expiration_date >= original_expiration_date`.
- `agreed_monthly_rent_usd_cents > 0`; activation verifies received Security Deposit is at least the half-up rounded 20% minimum.
- initial expiration is no more than 21 calendar days after `reservation_date`.
- cancellation fields are all absent unless CANCELLED and required when CANCELLED.
- `resulting_lease_id` and `moved_in_at` are required exactly when MOVED_IN.
- Partial unique index `UNIQUE (unit_id) WHERE status = 'ACTIVE'`.
- Index `(customer_id, reservation_date DESC)` and `(status, effective_expiration_date)`.
- Lifecycle transitions are enforced by a trigger: ACTIVE to CANCELLED or MOVED_IN only; terminal states cannot transition.

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
| `alternative_rent_due_terms` | `text` | yes | exact signed-Lease terms; null means approved standard day 5 |
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

## DB-LEASE-005 — `lease_violation_warnings`

Append-only: `id uuid PK`, `lease_id uuid NOT NULL FK`, `warning_sequence smallint NOT NULL CHECK (> 0)`, `violation_date date NOT NULL`, `warning_date date NOT NULL`, `violation_description text NOT NULL`, `lease_provision text NOT NULL`, `communication_record text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `UNIQUE (lease_id, warning_sequence)`. The authorized violation-termination transaction verifies at least three documented warnings without inventing the underlying termination right.

## DB-LEASE-006 — `lease_pet_approvals`

Append-preserved terms record: `id uuid PK`, `lease_id uuid NOT NULL FK`, `approved_date date NOT NULL`, `deposit_required_by_signed_terms boolean NOT NULL`, `pet_description text NULL`, `approved_at timestamptz NOT NULL`, `approved_by uuid NOT NULL`. It records approved pet terms and the applicable signed-term fact; multiple approval records still cannot create more than the Lease's one optional Pet Deposit. It does not create a general Pet entity or a penalty policy.

## DB-LEASE-007 — `lease_service_terms`

Signed-term applicability relation: `id uuid PK`, `lease_id uuid NOT NULL FK`,
`property_service_id uuid NOT NULL FK`, `applicable_from date NOT NULL`,
`applicable_through date NULL`, `terms_reference text NOT NULL`, `recorded_at
timestamptz NOT NULL`, `recorded_by uuid NOT NULL`, and `UNIQUE (lease_id,
property_service_id, applicable_from)`. Dates remain within the Lease period. Rows
identify which configured Services apply; rates still come only from effective-dated
`service_rates`.

---

# 7. Utility and Rate Tables

## DB-UTIL-001 — `utility_meters`

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `unit_id` | `uuid` | no | FK `units(id) ON DELETE RESTRICT` |
| `serial_number` | `text` | no | nonblank |
| `utility_type` | `text` | no | `ELECTRICITY`, `WATER` |
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

Append-only: `id uuid PK`, `reading_id uuid NOT NULL FK`, `previous_value numeric(20,6) NOT NULL`, `corrected_value numeric(20,6) NOT NULL CHECK (>= 0)`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`. The effective reading value is the latest valid correction ordered by `occurred_at, id`; the original remains unchanged. If already billed, a correction cannot alter the issued Invoice and requires a linked Invoice Adjustment.

## DB-UTIL-005 — `utility_rates`

Append-only version table: `id uuid PK`, `property_id uuid NOT NULL FK`, `utility_type text NOT NULL CHECK IN ('ELECTRICITY','WATER')`, `rate_usd_per_unit numeric(20,8) NOT NULL CHECK (> 0)`, `effective_date date NOT NULL`, `notice_at timestamptz NOT NULL`, `notice_evidence text NOT NULL`, `source_memo text NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `UNIQUE (property_id, utility_type, effective_date)`. The Property-local date of `notice_at` must precede `effective_date`. The selected row is the one with greatest `effective_date <= invoice_date`; selection is snapshotted on the Invoice line.

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

One-to-one detail for estimated periods: `consumption_period_id uuid PK/FK`, `failed_meter_id uuid NOT NULL FK`, `replacement_meter_id uuid NOT NULL FK`, `unmeasured_start_date date NOT NULL`, `unmeasured_end_date date NOT NULL`, `basis_kind text NOT NULL CHECK IN ('THREE_MOST_RECENT','FIRST_COMPLETE_FUTURE')`, `total_basis_consumption numeric(20,6) NOT NULL CHECK (>=0)`, `total_basis_days integer NOT NULL CHECK (>0)`, `weighted_daily_average numeric(20,10) NOT NULL CHECK (>=0)`, `estimated_consumption numeric(20,6) NOT NULL CHECK (>=0)`, `authorization_reason text NOT NULL`, `authorized_at timestamptz NOT NULL`, `authorized_by uuid NOT NULL`, `calculation_trace jsonb NOT NULL`.

## DB-UTIL-008 — `broken_meter_estimate_basis_periods`

Append-only junction: `estimate_consumption_period_id uuid NOT NULL FK`, `basis_consumption_period_id uuid NOT NULL FK`, `basis_order smallint NOT NULL CHECK (>0)`, PK `(estimate_consumption_period_id, basis_consumption_period_id)`, unique `(estimate_consumption_period_id, basis_order)`. Deferred validation enforces the three most recent complete historical actual periods when at least three exist; otherwise it requires exactly one complete future actual period for the same Unit and Utility Type under `BR-UTIL-027` or `BR-UTIL-028`.

---

# 8. Configured Service Tables

## DB-SVC-001 — `property_services`

`id uuid PK`, `property_id uuid NOT NULL FK`, `service_code text NOT NULL CHECK IN ('INTERNET','TRASH_COLLECTION')`, `display_name text NOT NULL`, `active boolean NOT NULL`, provenance columns, `UNIQUE (property_id, service_code)`. This is configured business data, not free-form Invoice entry.

## DB-SVC-002 — `service_rates`

Append-only: `id uuid PK`, `property_service_id uuid NOT NULL FK`, `monthly_rate_usd_cents bigint NOT NULL CHECK (>0)`, `effective_date date NOT NULL`, `source_memo text NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `UNIQUE (property_service_id, effective_date)`. The applicable rate is selected by billing-period start and snapshotted on the Invoice line.

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
| `original_total_usd_cents` | `bigint` | no | `CHECK (>= 0)`; immutable after issuance |
| `due_date_source` | `text` | no | signed Lease or governing event/document description |
| `issued_at` | `timestamptz` | yes | required unless DRAFT |
| `issued_by` | `uuid` | yes | required unless DRAFT |
| provenance columns | as DB-TYPE-007 | no | |

Constraints and indexes:

- `UNIQUE (invoice_number)` and `UNIQUE (id, lease_id)` to support consistency references.
- Rent requires non-null `lease_id`, period dates, and applicable SIGNED Lease.
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
  Rate, monthly rate snapshot, and period.
- Damage/Miscellaneous lines require one `authorized_nonrecurring_obligations` row;
  `calculation_trace` supplements and never replaces that relational source.
- Service line category remains SERVICE_CHARGES even on a primary RENT Invoice.
- Lines become immutable when their Invoice is issued.
- A GiST exclusion constraint on `source_lease_id` equality and inclusive `daterange(period_start, period_end, '[]')` overlap where `category='RENT'` prevents duplicate or overlapping Rent billing.
- Partial unique index `(source_lease_id, property_service_id, period_start, period_end) WHERE category='SERVICE_CHARGES'` prevents duplicate Service billing.
- Unique `utility_consumption_period_id` prevents duplicate Utility billing.
- A deferred issuance trigger requires `invoices.original_total_usd_cents = sum(invoice_lines.amount_usd_cents)` and at least one line before an Invoice leaves DRAFT.

## DB-INV-003 — `invoice_adjustments`

Append-only financial event.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `invoice_id` | `uuid` | no | FK |
| `adjustment_type` | `text` | no | `DEBIT`, `CREDIT` |
| `amount_usd_cents` | `bigint` | no | `CHECK (>0)` |
| `source_obligation` | `text` | no | approved source |
| `reason` | `text` | no | |
| `occurred_at` | `timestamptz` | no | |
| `actor_id` | `uuid` | no | |
| `authorization_reference` | `text` | no | |

An Adjustment changes current obligation by signed effect (`DEBIT` positive, `CREDIT` negative) without changing original Invoice/line values. Update/delete is prohibited.

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

---

# 10. Payment, Exchange, Allocation, and Credit Tables

## DB-PAY-001 — `payment_methods`

Configured data: `id uuid PK`, `code text NOT NULL UNIQUE`, `display_name text NOT NULL`, `accepted boolean NOT NULL`, provenance columns. Historical Payments retain the selected row and immutable method-code/name snapshots below even if the method is retired.

## DB-PAY-002 — `exchange_rate_records`

Append-only record selected at KHR confirmation or KHR Refund processing: `id uuid PK`, `reference_rate_khr_per_usd numeric(20,6) NOT NULL CHECK (>0)`, `markup_basis_points smallint NOT NULL CHECK (= 50)`, `system_rate_khr_per_usd bigint NOT NULL CHECK (>0)`, `rate_source text NOT NULL CHECK IN ('ABA_AUTOMATIC','ABA_EQUIVALENT_MANUAL','PAYMENT_CHANNEL_ACTUAL')`, `source_reference text NULL`, `applicable_at timestamptz NOT NULL`, `entered_by uuid NULL`, `calculation_trace jsonb NOT NULL`. Manual records require `entered_by`; System Rate must match markup and upward whole-KHR rounding unless the payment channel provides an authoritative actual settlement rate.

## DB-PAY-003 — `payments`

Append-only original receipt plus controlled receipt status.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK |
| `payment_number` | `text` | no | unique, immutable |
| `payer_customer_id` | `uuid` | no | FK Customers |
| `lease_id` | `uuid` | yes | optional intent/context FK |
| `designated_invoice_id` | `uuid` | yes | optional payer intent FK |
| `payment_date` | `date` | no | actual receipt date |
| `payment_method_id` | `uuid` | no | FK configured method |
| `payment_method_code_snapshot` | `text` | no | immutable |
| `payment_method_name_snapshot` | `text` | no | immutable display name at receipt |
| `received_currency` | `text` | no | `USD`, `KHR` |
| `received_amount_minor` | `bigint` | no | cents for USD, whole riel for KHR; positive |
| `usd_accounting_value_cents` | `bigint` | no | positive |
| `exchange_rate_record_id` | `uuid` | yes | required exactly for KHR |
| `payer_intent_memo` | `text` | yes | designation evidence |
| `status` | `text` | no | `RECEIVED`, `REVERSED` |
| `confirmed_at` | `timestamptz` | no | |
| `confirmed_by` | `uuid` | no | |

Original columns are immutable. Only status may change, and only through DB-PAY-006. Index `(payer_customer_id, payment_date DESC)` and partial index on RECEIVED.

## DB-PAY-004 — `payment_allocations`

Append-only event: `id uuid PK`, `payment_id uuid NOT NULL FK`, `invoice_id uuid NOT NULL FK`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `designation_kind text NOT NULL CHECK IN ('FIFO_PROPOSAL_CONFIRMED','CUSTOMER_DESIGNATED','THIRD_PARTY_DESIGNATED')`, `designation_memo text NULL`, `posted_at timestamptz NOT NULL`, `posted_by uuid NOT NULL`, `authorization_reference text NOT NULL`.

Posting locks the Payment, Invoice, and relevant event rows; it rejects allocation above remaining Payment value or Invoice outstanding balance. FIFO proposals order by `due_date`, then `issued_at`, then `invoice_number`; posting remains manual. Update/delete is prohibited.

## DB-PAY-005 — `payment_allocation_reversals`

Append-only: `id uuid PK`, `payment_allocation_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. Active Allocation effect is original Allocation less its linked reversal (zero when reversed).

## DB-PAY-006 — `payment_reversals`

Append-only: `id uuid PK`, `payment_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. Posting requires all Allocations, payment-sourced Credit recognitions, and Deposit Receipts to be explicitly reversed and no unresolved completed Refund; it then sets Payment status REVERSED. Original Payment is unchanged.

## DB-CREDIT-001 — `customer_credits`

Append-only Credit recognition event: `id uuid PK`, `customer_id uuid NOT NULL FK`, `source_payment_id uuid NOT NULL FK`, `recognized_usd_cents bigint NOT NULL CHECK (>0)`, `customer_authorization_reference text NOT NULL`, `recognized_at timestamptz NOT NULL`, `recognized_by uuid NOT NULL`, `reason text NOT NULL`. Credit must belong to the payer Customer and cannot exceed unallocated, undisposed Payment value. Credit balance is derived.

## DB-CREDIT-002 — `customer_credit_applications`

Append-only: `id uuid PK`, `customer_credit_id uuid NOT NULL FK`, `invoice_id uuid NOT NULL FK`, `final_settlement_id uuid NULL FK`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. Source Credit and Invoice Customer must match; amount cannot exceed Credit availability or Invoice outstanding balance.

## DB-CREDIT-003 — `customer_credit_application_reversals`

Append-only: `id uuid PK`, `credit_application_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`.

## DB-CREDIT-004 — `customer_credit_reversals`

Append-only: `id uuid PK`, `customer_credit_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. It requires all applications and Refund commitments sourced from the Credit to be resolved explicitly.

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

Append-only Final Settlement financial event: `id uuid PK`, `deposit_id uuid NOT NULL FK`, `final_settlement_id uuid NOT NULL FK`, `invoice_id uuid NOT NULL FK`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `application_order integer NOT NULL CHECK (>0)`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`, `UNIQUE (final_settlement_id, application_order)`.

- Application is allowed only after Lease TERMINATED and before the Settlement's `closed_at` is set.
- PET may apply only to an Invoice line sourced as authorized pet-related damage.
- SECURITY applies after authorized Credit and permitted Pet Deposit applications, using oldest Due Date and deterministic ties where Due Dates apply.
- It cannot exceed held refundable Deposit balance or Invoice outstanding balance.

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
Utility handling—is final, all required applications/dispositions/Refunds are
represented, and final balance is reconciled. A closed Settlement is never
reopened; correction uses linked events.

`closing_balance_due_usd_cents` is the post-application, post-disposition, and
post-Refund Customer receivable remaining at closure. A refundable amount is not
stored as a negative balance; it must be represented by its explicit Refund event.

## DB-SETTLE-002 — `settlement_invoice_items`

Append-preserved membership snapshot: `final_settlement_id uuid NOT NULL FK`, `invoice_id uuid NOT NULL FK`, `outstanding_at_inclusion_usd_cents bigint NOT NULL CHECK (>=0)`, `included_at timestamptz NOT NULL`, `included_by uuid NOT NULL`, PK `(final_settlement_id, invoice_id)`. It identifies source obligations without replacing them.

## DB-SETTLE-003 — `settlement_corrections`

Append-only linkage for an authorized post-closure correction: `id uuid PK`,
`final_settlement_id uuid NOT NULL FK`, `corrective_event_type text NOT NULL`,
`corrective_event_id uuid NOT NULL`, `reason text NOT NULL`, `occurred_at timestamptz
NOT NULL`, `actor_id uuid NOT NULL`, and `authorization_reference text NOT NULL`.
The referenced approved typed event carries the financial effect; this row preserves
its relationship to the closed Settlement without reopening or rewriting it.

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
| `usd_accounting_value_cents` | `bigint` | no | `CHECK (>0)` |
| `refund_currency` | `text` | no | `USD`, `KHR` |
| `refund_amount_minor` | `bigint` | no | cents for USD, whole riel for KHR; positive |
| `exchange_rate_record_id` | `uuid` | yes | required exactly for KHR except original KHR excess rule below |
| `original_khr_excess_amount` | `bigint` | yes | required for direct original-KHR-excess Refund |
| `reason` | `text` | no | |
| `processed_at` | `timestamptz` | no | |
| `processed_by` | `uuid` | no | |
| `authorization_reference` | `text` | no | |

Exactly one of the three source FKs is non-null. Source Customer must match recipient and available source value must not be exceeded. A direct Refund of KHR Payment excess preserves the corresponding original KHR amount and original receipt exchange record; a later Refund of USD Credit in KHR uses a new applicable Refund exchange record. Settlement Deposit Refunds remain separate by Deposit.

**OPEN OWNER DECISION OOD-DB-002 (nonblocking):** Upstream rules do not define Refund delivery methods or lifecycle states after the outbound event is processed. This model records only the completed Refund event and does not invent pending/failed statuses.

## DB-REFUND-002 — `refund_verified_returns`

Append-only verified-return event: `id uuid PK`, `refund_id uuid NOT NULL FK`,
`returned_usd_cents bigint NOT NULL CHECK (>0)`, `returned_original_currency text NOT
NULL`, `returned_original_amount_minor bigint NOT NULL CHECK (>0)`, `returned_at
timestamptz NOT NULL`, `return_method_reference text NOT NULL`, `reason text NOT
NULL`, `authorized_by uuid NOT NULL`, `created_at timestamptz NOT NULL`, and
`created_by uuid NOT NULL`. Currency/amount follow DB-TYPE-003 and must reconcile to
the Refund's preserved exchange facts. Active returned value may not exceed the
completed Refund. This records value actually returned after an erroneous completed
Refund; it neither erases the outbound event nor creates a collection right. A
Payment reversal that depended on the Refund is blocked until the full relevant
value is verified returned.

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

At minimum, audit events are written in the same transaction for Property/Unit status changes; Customer detail changes; Reservation activation, extension, expiration, classification, cancellation, release, and move-in; Lease signing, notices, warnings, termination, and Occupancy correction; Meter failure/replacement, Reading validation/correction, and estimate; all rate changes; Invoice draft correction, issuance, Adjustment, status change, and VOID; Payment confirmation, Allocation, reversals, Credit authorization/application, Deposit events, Refunds; and every Settlement step/closure/correction.

## DB-AUDIT-003 — Actor foreign key deferral

`actor_id` is logically mandatory but has no database FK until the authoritative Security Model defines principal persistence. Migrations must not point audit history to a speculative user table. Once defined, the FK must use `ON DELETE RESTRICT` or preserve an immutable actor identity snapshot.

---

# 14. Derived and Stored Information

## DB-DER-001 — Invoice obligation and balance

```text
adjusted obligation
= original issued Invoice total
+ active DEBIT Adjustments
- active CREDIT Adjustments

outstanding balance
= adjusted obligation
- active Payment Allocations
- active Customer Credit Applications
- active Final Settlement Deposit Applications
```

VOID and DRAFT Invoices are excluded from receivable balances. Outstanding balance is derived and must never be negative. It is not stored as an authoritative Invoice column. Invoice status is stored for workflow/querying but must equal the derived lifecycle condition.

## DB-DER-002 — Payment availability and allocation condition

```text
payment available value
= original USD accounting value
- active Payment Allocations
- active Deposit Receipts not reversed by DB-DEP-007
- Customer Credit recognitions not reversed
- net Refund value directly sourced from Payment after DB-REFUND-002 verified returns
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
- net Refund value sourced from Deposit after DB-REFUND-002 verified returns
outstanding required amount = max(required amount - received amount, 0)
```

No authoritative current-balance column is stored on `deposits`.

## DB-DER-005 — Customer Credit balance

Credit balance is recognition amount minus active applications and net Refund value
after DB-REFUND-002 verified returns, considering explicit reversals. It is always
USD, cannot be negative, and is not pooled with Deposit balances.

## DB-DER-006 — Utility consumption

Raw Utility Readings are authoritative measurements. Actual consumption is derived from consecutive validated effective readings of the same Meter and finalized into immutable `utility_consumption_periods` when it becomes a billing source. Broken-Meter estimates are explicitly stored with their basis and calculation.

## DB-DER-007 — Settlement balance

Before closure, Settlement net balance is derived from included outstanding obligations, authorized Credit Applications, Deposit Applications/Dispositions, Refunds, and Payments. `closing_balance_due_usd_cents` is stored only as the immutable post-Refund closure snapshot and must reconcile to source events.

## DB-DER-008 — Reporting projections

Materialized views or cached projections are permitted for performance only when reproducible from authoritative tables, refreshable, and never accepted as command-side sources of truth.

---

# 15. Transactional and Concurrency Constraints

## DB-TXN-001 — Coordinated transitions

Reservation activation, automatic expiration/cancellation and Unit release, Lease signing, move-in, move-out/termination, Invoice issuance, Allocation/Application posting, reversal, Payment confirmation, Deposit receipt, Refund, and Settlement closure execute atomically with their audit events.

## DB-TXN-002 — Reservation and Lease conflicts

Reservation creation locks the Unit and checks the partial unique constraint. Lease signing locks the Unit and relies on the exclusion constraint. Constraint violations reject rather than silently alter dates or statuses.

## DB-TXN-003 — Financial posting locks

A financial posting locks every affected source and target in stable UUID order, calculates availability from append-only active events, inserts the event, recomputes affected Invoice status, and writes audit history before commit.

## DB-TXN-004 — No negative or double-consumed value

Deferred constraint triggers verify at commit that no Invoice, Payment, Credit, Deposit, Utility period, or Refund source is over-applied, over-refunded, billed twice, or negative.

## DB-TXN-005 — Scheduled idempotency

Rent generation uses Lease plus rental period as its stable business key. Utility generation uses the finalized Utility Consumption Period. Service generation uses Lease, configured Service, and billing period. Unique indexes in DB-INV-002 make retries idempotent.

## DB-TXN-006 — Property-local scheduling

The 25th-day billing run, 5th-day due-date calculation, Reservation end-of-date expiration, and monthly Utility boundaries are calculated using `properties.timezone_name`; stored instants remain `timestamptz` and business dates remain `date`.

---

# 16. Immutability and Correction Matrix

| Record | Mutable window | Approved correction after finalization |
|---|---|---|
| Customer contact | current data may update | audit previous/resulting values |
| Reservation | approved lifecycle fields only | explicit transition/Notice plus audit |
| Lease | DRAFT fields before signing | termination or linked historical correction; never rewrite signed terms silently |
| Lease Signer | DRAFT only | preserve signed signer history |
| Occupancy | move-out/correction workflow | audited correction preserving prior value |
| Utility Reading | before validation | correction event; billed effect via Invoice Adjustment |
| Rate version | never after insertion | new effective-dated version |
| DRAFT Invoice/line | before issuance, audited | draft correction |
| issued Invoice/line | immutable | Adjustment, dependency reversal, or exceptional VOID |
| Payment | original receipt immutable | Payment Reversal |
| Allocation/Application | immutable | linked Reversal |
| Deposit receipt | immutable | DB-DEP-007 linked Deposit Receipt Reversal |
| Deposit disposition/application | immutable | DB-DEP-008/DB-DEP-006 linked Reversal |
| Credit recognition | immutable | linked application/reversal/refund |
| Refund | immutable completed event | DB-REFUND-002 verified-return event without rewrite |
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

`invoice_financial_position` exposes original total, active Adjustment total, active Payment/Credit/Deposit applications, adjusted obligation, outstanding balance, and reconciled status.

## DB-VIEW-002

`payment_financial_position` exposes original USD value, allocated value, Deposit-directed value, Credit-recognized value, directly refunded value, unallocated value, and allocation condition.

## DB-VIEW-003

`deposit_financial_position` exposes required, received, disposed, applied, refunded, held refundable, and outstanding required amounts separately by Deposit.

## DB-VIEW-004

`customer_credit_financial_position` exposes recognized, applied, refunded, reversed, and available USD values by Credit source and Customer.

## DB-VIEW-005

`lease_financial_position` aggregates issued non-VOID Invoice outstanding balances associated with the Lease without creating signer-specific debt shares.

## DB-VIEW-006

`unit_legal_availability` exposes authoritative blocking Reservation, Lease, Occupancy, and operational conditions alongside the stored Unit status.

---

# 19. Migration and Verification Requirements

## DB-MIG-001 — Forward-only migrations

Schema changes use reviewed, versioned, forward migrations. Migrations must not reset, recreate, or silently rewrite business history.

## DB-MIG-002 — Financial backfills

A backfill affecting financial, rate, Reading, or Settlement history must be deterministic, idempotent, reconcilable before/after, and audit documented. Destructive migration is prohibited without explicit Owner approval and a recovery plan.

## DB-TEST-001 — Constraint tests

Database integration tests must prove all checks, partial unique indexes, exclusion constraints, FKs, append-only protections, allowed transitions, and concurrency behavior.

## DB-TEST-002 — Reconciliation tests

Tests must independently recompute Invoice, Payment, Credit, Deposit, Lease, and Settlement balances from source events and compare them with statuses and closure snapshots.

## DB-TEST-003 — Mandatory Invoice relationship tests

Tests must prove that an Invoice cannot exist without a Customer; may exist without a Lease only under an approved non-Lease source; requires a Lease for Rent; and rejects inconsistent Lease Customer, Unit, period, or source context.

## DB-TEST-004 — Historical correction tests

Tests must prove that correction, reversal, VOID, disposition, and Refund workflows preserve the original rows and complete source chain.

## DB-TEST-005 — Date, rate, and rounding tests

Tests cover Property-local boundaries, leap years, inclusive proration, half-up USD-cent rounding, generation-date Utility Rate selection, whole-period Utility rate application, 0.5% System Exchange Rate markup, upward whole-KHR rate rounding, and upward final KHR payable rounding.

---

# 20. Open Owner Decisions

The following matters are not resolved by `001_DOMAIN_MODEL.md` or `002_BUSINESS_RULES.md`. They do not block this logical model and must not be guessed during implementation.

- **OOD-DB-001 — Customer identity/contact policy:** exact legal-name structure, contact validation, mandatory contact channel, and duplicate-person matching.
- **OOD-DB-002 — Refund delivery lifecycle:** delivery methods and whether operational pending/failed states are needed before the completed Refund event.
- **OOD-DB-003 — Business-number format:** format and sequencing scope for Invoice, Payment, and Refund Numbers. Uniqueness and immutability are already mandatory.
- **OOD-DB-004 — Meter serial uniqueness scope:** whether a physical serial number is globally unique, unique per Utility Type, or only informational.
- **OOD-DB-005 — Measurement unit metadata:** the approved physical unit/scale for Electricity and Water readings and Utility Rates. `numeric(20,6)` preserves exact values but does not name an unapproved unit. This does not block logical-schema review, but it blocks production Utility configuration and definitive fixture values.
- **OOD-BR-001 — First partial-month Rent Due Date:** the Due Date source for a first partial-month Rent Invoice issued after the billed month's 5th remains open. `invoices.due_date` and its governing-source trace remain explicit; the database defines no default for this case.

These are `OPEN OWNER DECISION`, not permission to introduce policy. None is resolved by `003_PRODUCT_REQUIREMENTS.md`; a later Owner decision must update the controlling numbered specifications before implementation assumes an answer.

---

# 21. Upstream Traceability Summary

| Database area | Business Rules | Product Requirements |
|---|---|---|
| single Property, Units | BR-PROP-001..003, BR-UNIT-001..013 | PR-CAP-001, PR-PROP-001..003, PR-UNIT-001..013 |
| Customers | BR-CUST-001..003 | PR-CAP-001, PR-CUST-001..003 |
| Reservations/extensions | BR-RES-001..022 | PR-CAP-002, PR-WF-001..003, PR-RES-001..022 |
| Leases, occupancy, move-in/out | BR-LEASE-001..025, BR-OCC-001..009, BR-MOVEOUT-001..012 | PR-CAP-003, PR-WF-003..005, corresponding detailed PR-* |
| Deposits | BR-DEP-001..025 | PR-CAP-002, PR-WF-001..006, PR-DEP-001..025 |
| Rent | BR-RENT-001..028 | PR-CAP-004, PR-WF-004, PR-RENT-001..028 |
| Utilities | BR-UTIL-001..032 | PR-CAP-004, PR-WF-004..005, PR-UTIL-001..032 |
| Services | BR-SVC-001..015 | PR-CAP-004, PR-WF-004, PR-SVC-001..015 |
| Invoices/Adjustments/VOID | BR-INV-001..050 | PR-CAP-004, PR-WF-004/007, PR-INV-001..050 |
| Payments/Allocations | BR-PAY-001..035 | PR-CAP-005, PR-WF-004/007, PR-PAY-001..035 |
| Credits | BR-CREDIT-001..012 | PR-CAP-005, PR-WF-004/006/007, PR-CREDIT-001..012 |
| Refunds | BR-REFUND-001..012 | PR-CAP-005, PR-WF-002/004/006/007, PR-REFUND-001..012 |
| Settlements | BR-SETTLE-001..015 | PR-CAP-006, PR-WF-005..007, PR-SETTLE-001..015 |
| Money/rates/time | BR-MONEY-001..013 | PR-CAP-005, PR-QUAL-006, PR-MONEY-001..013 |
| Audit/authorization | BR-AUDIT-001..010, BR-AUTH-001..009 | PR-CAP-007, PR-QUAL-001..007, corresponding detailed PR-* |

---

# 22. Completion Criteria

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
