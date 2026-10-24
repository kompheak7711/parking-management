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

Amended by DL-075 (owner, 2026-10-20): `one_time_charge_due_days` is the Settings "days after issue" for other Invoices; the move-out cleaning charge, move-out Damage Charges and the final Utility Invoice use a fixed 7 days. Settings also hold the reading day (default 24), the issue day (default 25), the Due Date day (default 5), each 1 to 28 with the issue day after the reading day, and the late-payment rate (a whole percent 0 to 10, default 10); these four start with the next billing month. Not built yet (screen rebuild).

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

Amended by DL-075 (owner, 2026-10-20): `unit_type` comes from the Unit Types Settings list instead of the four fixed values; Floors, Views, Kitchens and Room features are Settings lists too. An item used by a Unit cannot be removed. Not built yet (screen rebuild).

Amended by DL-078 (owner, 2026-10-20): new Unit columns: size in m², bedrooms, bathrooms, view, kitchen, Room features and notes (lists from DL-075), and a new append-only Unit inventory table (item, quantity, group Furniture, Appliances, Kitchen or Bathroom, dated History). `unit_number` cannot change after creation. One Unit photo is built in the later file storage step. Not built yet (screen rebuild).

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

Amended by DL-071 (owner, 2026-10-20; answer 11): a new Customer field "ID number / Passport number" (owner-approved personal data). A Customer with the same ID number as another Customer is refused, and staff use the existing Customer. The same phone number or email address as another Customer gives a warning and may still be saved through the existing `confirmed_distinct` flow. The ID number never appears in exports or in the top bar search. The ID number is required for every Customer, and two ID numbers are the same when they match after removing spaces and dashes and ignoring capital letters (owner, 2026-10-21). Not built yet (V1-059).

Amended by DL-078 (owner, 2026-10-20): new optional Customer columns: date of birth, gender (`FEMALE` or `MALE`) and nationality (owner-approved personal data, SEC-006). Not built yet (screen rebuild).

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

Amended by DL-075 (owner, 2026-10-20): the suggested rate is the Settings value (default 20 percent, 2000 basis points), read only for new Reservations; the `CHECK (= 2000)` changes with the screen rebuild.

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
Since V1-056 sub-slice 10e-2b-4f (migration `20270106_163`; owner answer (a) to
Q-2026-10-18-130) that old move-in counts only active receipts (no reversal) of the Security
Deposit and of each required Pet Deposit, dated by the move-in date, and requires at least the
current required total, adjustments included (BR-DEP-004); a Deposit holding more than a
decreased total is fully paid. A receipt dated after a past move-in date does not count, so
an increase recorded later cannot be met for that date.

### Unpaid Initial obligation termination (migration `20261005_70`)

Termination basis `UNPAID_INITIAL_OBLIGATION` requires governing reference `BR-LEASE-005`,
the signed clause reference, no warning letters, and, at termination time in
Asia/Phnom_Penh, a date after Lease Start plus five days with the Initial Rent or the
Security Deposit still unpaid. Since V1-056 sub-slice 10e-2b-4f (migration `20270106_163`)
the Security Deposit is unpaid when its held value at the termination time is below its
required total recorded by that time (the first amount plus the required-amount adjustments
recorded at or before it, DB-DEP-003). `unpaid_initial_termination_resolutions` (append-only, one per
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
- No Lease column can override recurring Rent timing. The Initial Rent Due Date is
  proposed as the Lease Start Date plus five calendar days (BR-RENT-009, DL-064); recurring Rent is due on the fifth day of
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

V1-056 sub-slice 10i-1 (migration `20270114_171`): the routes send no termination time,
and the service passes the database's statement time, so a retry carries a new time; the
wrapper's replay therefore compares every saved field except the time, which the request
digest still binds (owner answer (a) to Q-2026-10-14-112 point 1). After the Lease and
Unit locks and its version and status checks, the termination also locks the Lease's
Deposits in id order (the closing confirm's Lease-then-Deposit order), before its
chronology, context and ground checks, so a Deposit receipt or a
required-amount adjustment saved beside a termination waits for it and reads the
terminated Lease, and a termination that comes second reads the committed adjustment
(owner answer (a) to Q-2026-10-18-133).
Because the termination time is the start of its statement and its locks come later, a
termination stamped with the database's time is refused (40001, "record it again") when a
Deposit balance event or a required-amount adjustment of the Lease is dated after that
time: it was saved while the termination waited, and the ground would not read it. A
required-amount adjustment is dated with `clock_timestamp()` after its Deposit lock, and the
Pet departure writer locks the Lease (FOR KEY SHARE) before its Pet Deposit, so it never holds
the Deposit while its foreign key waits for a terminating Lease (review round 1 of 10i-1).
`app.confirm_payment_return` still locks the Deposits it funded before its recovery Invoices
take the Lease key; it already met the termination on the `invoice-lease` key before 10i-1, so
a deadlock there (40P01) refuses one side and writes nothing (a slice 12 note).

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
- Serial uniqueness is not asserted because upstream policy does not define whether serials are globally reusable. Amended by DL-071 (owner, 2026-10-05; answer 12): `serial_number` is unique across all Meters of the Property, whatever the Utility Type, deactivated (replaced) Meters included, so a replaced Meter's serial is never used again. Where no serial is printed, staff enter a Property code (for example `EL-U101` or `WA-U101`), which is also unique. `measurement_unit_code` is kWh for electricity and cubic metres (m3) for water (answer 9). Not built yet (V1-059).
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

Amended by DL-075 (owner, 2026-10-20): a new Rate's `effective_date` is a reading day. Not built yet (screen rebuild).

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

Amended by DL-071 (owner, 2026-10-20; answer 18): before V1-060 the scheduled billing worker bills a `LATE_AFTER_SUCCEEDED_RUN` period by itself; `app.utility_unbilled_periods` stays as a safety check. A `NOT_MOVED_IN` period is still billed only by the explicit catch-up command. Not built yet (V1-056 slice 12).

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

Amended by DL-075 (owner, 2026-10-20): Services are added in Settings (Owner or Settings access, DL-074) with an English and a Khmer name and a Service type ("Only one per Lease" or "One or more per Lease"). Trash Collection is chosen by default on a new Lease. Not built yet (screen rebuild).

## DB-SVC-002 — `service_rates`

Append-only: `id uuid PK`, `property_service_id uuid NOT NULL FK`, `monthly_rate_usd_cents bigint NOT NULL CHECK (>0)`, `effective_date date NOT NULL`, `source_memo text NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `UNIQUE (property_service_id, effective_date)`. The applicable rate is selected by billing-period start and snapshotted on the Invoice line.

Amended by DL-075 (owner, 2026-10-20): a new rate's `effective_date` is the first day of a later month. Not built yet (screen rebuild).

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
- Amended by DL-071 (owner, 2026-10-20; answer 10): `invoice_number` is given only at issue, in the format `INV` + 2-digit year of the issue date in `Asia/Phnom_Penh` + 4-digit running number restarting each year (for example `INV260001`; 5 digits after 9999), never reused. A DRAFT Invoice carries only an internal draft reference, never printed and never shown to a Customer. This replaces the rule that every Invoice, DRAFT included, has an `invoice_number`. Not built yet (V1-059); recorded Invoices keep their numbers.

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
  complete approved coverage period, and the Due Date of the Lease Start Date plus five
  calendar days (BR-RENT-009). For Lease Start Dates on day 21 or later, each such line has
  two DB-INV-006 components: prorated start-month remainder and complete following month. Recurring generation resumes on the 25th before the
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

Relaxed in V1-056 sub-slice 10c-3b-1 (migration `20261117_113`; owner answer 2 to
Q-2026-10-09-66): a release row names exactly one of `invoice_adjustment_id` (now nullable) or
the new nullable `late_payment_charge_correction_id` (FK to `late_payment_charge_corrections`, ON
DELETE RESTRICT, indexed); the check `invoice_credit_excess_release_one_link` requires exactly one
(`num_nonnulls(...)=1`), and the reason is "Invoice adjustment credit excess" with an Adjustment
link or "Late-payment Charge correction credit excess" with a Charge correction link. A Charge
correction release is written only by a post-settlement `REFUND` correction of a Late-payment
Charge: its reversed allocation or Credit application targets that Charge with the same reason, the
release is at most what it applied, and released Payment value becomes Credit of the Charge's
Customer (BR-CREDIT-014; recognition finds that Customer through the Charge correction). Every
existing row keeps its Adjustment. The table stays append-only; the runtime and financial roles
keep their read grant and no role writes it.

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

V1-056 sub-slice 10b (migration `20261102_98`): after a Lease's Final Settlement closes, a
one-time charge with that Lease is written only by an `EXTRA_CHARGE` post-settlement
correction (`app.confirm_settlement_extra_charge`, DB-SETTLE-005), authorized by the
`financial.approve` holder who confirms it (`authorization_reference` `financial.approve`). It
uses the same one-time rule; its Customer is the Customer of the corrected Invoice, which may be
another signed Signer of the Lease, or the Primary Tenant (a Damage charge always the Primary
Tenant).

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

Amended by DL-076 (owner, 2026-10-20): no manual decision any more: the app adds the charge at 00:00 on the first day after the Due Date with a system actor as `finalized_by`, and the rate comes from Settings instead of `CHECK (= 1000)`. Not built yet (V1-056 slice 11).

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

Amended by DL-076 (owner, 2026-10-20): `payable_at` is the time the app adds the charge, and `created_by` is the system actor. Not built yet (V1-056 slice 11).

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

Amended by DL-076 (owner, 2026-10-20): reductions and waivers after a Customer complaint go in a new append-only table with one of three fixed reasons and a required "What happened" text; the amount only goes down, and paid money above the new amount becomes Customer Credit of the charge's Customer under BR-CREDIT-014, before or after closure. Not built yet (V1-056 slice 11).

## DB-INV-010 — `invoice_adjustment_reversals`

Append-only explicit reversal: `id uuid PK`, `invoice_adjustment_id uuid NOT NULL UNIQUE
FK invoice_adjustments`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`,
`actor_id uuid NOT NULL`, and `authorization_reference text NOT NULL`. It removes the
Adjustment's derived effect without changing the original Adjustment, Invoice, or line.
The transaction locks and recomputes the line/Invoice and rejects any resulting negative
balance or inconsistent application; status regression is derived under DB-DER-001.

The first writer, V1-056 sub-slice 10f-1 (migration `20261219_145`; owner answer 7 to
Q-2026-10-06-36 and the slice 10 entry of the plan): a mistaken credit Adjustment is reversed
through a `financial_drafts` row of the new kind `ADJUSTMENT_REVERSAL`, prepared under
`invoices.adjust` (the draft checks gain the kind and the preparer, also for a WITHDRAWN
decision, and the two capability-scoped draft reads accept nine preparer capabilities). Staff
record it (`app.record_adjustment_reversal_draft`, READ COMMITTED, one waiting draft per
Adjustment); its payload lists the Adjustment, its line's current unpaid amount (the reversal adds the
Adjustment's amount to it) and, for each
`invoice_credit_excess_releases` row of the Adjustment in written order, the Credit that holds the
released value, the part still available (0 for a reversed Credit, a Payment no longer received or
another Customer's Credit; earlier put-backs from the same Credit counted), the put-back (at most
the release and the line's unpaid rest) and the part that stays as debt on the line. A
`financial.approve` holder (a person, at READ COMMITTED) confirms it (`app.confirm_adjustment_reversal`):
the locks of the Credit writers (each released Credit's Payment, the Credits, then the Invoice and
its lines), the source again (a changed source is stale, P5S02, and the draft stays pending), the
decision, the reversal row (the draft's reason, the approver, `financial.approve`, a time later
than every financial event of the Invoice), the Invoice status and version, then each put-back as
a Credit application of that Credit to the Adjustment's line (`credits.apply`, the approver, the
Rent-first proposal of `app.credit_application_proposal` for its amount, a detail trace naming the
reversal and the release), all deferred checks at once, and one `invoice.adjustment_reversed`
audit event correlated with the draft. Refused (55000): a debit Adjustment, a reversed one, one on
an Invoice that is not issued or is VOID, one that a hand-back or unpaid-Initial resolution wrote, one linked to a post-settlement correction,
one whose Lease's Final Settlement is closed (sub-slice 10f-2), and, until the owner answers
Q-2026-10-16-118, a put-back that the Rent-first order would put on another line (a line before
the Adjustment's line in that order still owes, on any Invoice). No role may write this table directly; no table,
column or trigger changed. A pending `ADJUSTMENT_REVERSAL` draft does not block a Final
Settlement; after the closure it is stale.

As built in V1-056 sub-slice 10f-1b (migration `20261220_146`; owner answer (a) to
Q-2026-10-16-118 point 1; point 2 answered (a): an Adjustment a resolution wrote stays refused):
every put-back goes back on the Adjustment's own line with the label `PUT_BACK_BY_CORRECTION`
(DB-CREDIT-002) on the row and its one detail, with no Rent-first proposal, no designation and no
proposed amount, also when a line before it in the Rent-first order still owes; a put-back
restores what was there before and is not a new allocation. Its amount stays the release's
Credit still available, at most the release and the line's unpaid rest. The Rent-first refusal of
10f-1 (recorder and confirm) ends. Drafts recorded before this change whose put-back the
proposal placed on the line confirm unchanged in amount; only the label differs.

As built in V1-056 sub-slice 10f-2 (migration `20261221_147`; owner answer 7 to Q-2026-10-06-36,
answer (a) to Q-2026-10-16-118 and answer (b) to Q-2026-10-16-119): after the Lease's Final
Settlement is closed, the second writer of this table is the `ADJUSTMENT_REVERSAL` variant of the
`SETTLEMENT_CORRECTION` draft (DB-SETTLE-003, DB-SETTLE-005). A `final_settlements.prepare` holder
records it (`app.record_settlement_adjustment_reversal_draft`: READ COMMITTED, the reason 1 to
1,000 characters, an exact repeat replays, a reused id P5205, the `adjustment-reversal:` lock
shared with the draft above, refused while a draft of either kind for the Adjustment waits); a
`financial.approve` holder (a person, at READ COMMITTED) confirms it
(`app.confirm_settlement_adjustment_reversal`). The source (internal overload
`app.adjustment_reversal_source(property, adjustment, settlement)`) takes the releases and amounts
of the draft above and refuses (55000): a debit Adjustment, a reversed one, one on an Invoice that
is not issued, one a resolution wrote, one on an Invoice of another Lease, one a post-settlement
correction wrote unless it is a `CHARGE_REDUCTION` correction of this Settlement (its reversal
restores exactly the debt the reduction removed and puts nothing back), one recorded at or after
the closure without such a link, and an open Settlement (P0002 for a Settlement or Adjustment not
on the Property). The confirm takes the draft lock, the `adjustment-reversal:` lock, the
Settlement's draft lock, the Credit writers' locks and the Invoice and its lines, checks the
source again (stale P5S02, the draft stays pending), writes the decision and the correction header
through an internal overload of `app.begin_settlement_correction` that also stores the reversal
id, the put-backs and the debt in the decision, then links and writes the reversal and each
labelled put-back (as in 10f-1b, on the Adjustment's own line), the Invoice status and version,
all deferred checks at once, one `invoice.adjustment_reversed` audit event (correlated with the
draft) and one `final_settlement.correction.confirmed` event. The rest of each release stays as
debt on the Invoice Customer's ledger; no DL-032 step runs. The draft above, recorded before the
closure, is stale at its confirm after it (its source's refusal changed) and stays pending.

---

# 10. Payment, Exchange, Allocation, and Credit Tables

## DB-PAY-001 — `payment_methods`

Configured data: `id uuid PK`, `code text NOT NULL UNIQUE`, `display_name text NOT NULL`, `accepted boolean NOT NULL`, provenance columns. Historical Payments retain the selected row and immutable method-code/name snapshots below even if the method is retired.

Amended by DL-075 (owner, 2026-10-20): each method says whether it needs a reference; a method used on a Receipt is never deleted, only turned off; at least one method stays on. Not built yet (screen rebuild).

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

Amended by DL-071 (owner, 2026-10-05; answer 10 changed 2026-10-20): a Payment has one Receipt, and `payment_number` is that Receipt's `receipt_number` (for example `RCP260001`). This replaces the separate Payment Number (today `PAY-` followed by the Payment id). Not built yet (V1-059).

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

Append-only link of one confirmed wrong-Unit Payment move (BR-PAY-042, V1-056 slice 7, migration `20261020_85`): `id uuid PK`, `draft_id uuid NOT NULL UNIQUE FK financial_drafts`, `property_id`, `payment_id`, `source_allocation_id uuid NOT NULL UNIQUE FK payment_allocations`, `source_reversal_id uuid NOT NULL UNIQUE FK payment_allocation_reversals`, `source_reversed_by_move boolean NOT NULL`, `target_allocation_id uuid NOT NULL UNIQUE FK payment_allocations`, `source_invoice_id`, `target_invoice_id`, `moved_usd_cents bigint NOT NULL CHECK (>0)`, `source_acknowledgement` and `target_acknowledgement text NOT NULL` (1 to 2,000 characters: who acknowledged for each Customer, the date and how), `confirmed_at`, `confirmed_by`. Staff record a `PAYMENT_MOVE` draft under `payments.allocations.reverse` (`app.record_payment_move_draft`); a `financial.approve` holder confirms it (`app.confirm_payment_move_draft`), which in one transaction reverses the wrong Invoice allocation (unless the one-call reversal already did), posts the same Payment to the correct Invoice of another Unit and inserts this row; a deferred check requires the draft's CONFIRMED decision. The move is refused while the Payment has Customer Credit that is not reversed or a Refund that is not fully returned, and a draft is stale when the correct Invoice or the source changed. The Payment row and its Receipt never change. No runtime or financial role has table privileges. Update/delete is prohibited. The reversal and the new allocation share one instant, and one `payment_move.confirmed` audit event per move carries the draft id as its correlation id. The draft payload (both acknowledgements and the line split of the correct Invoice) must fit the 16,000-byte draft limit. The confirmation advances the correct Invoice's version even when its status is unchanged. A Customer Credit that a credit Adjustment released from a moved allocation is never reversed by the one-call Credit reversal unless the Payment is a normal Customer Payment and the Credit belongs to its payer (`customer_credit_reversals_moved_payment`, SQLSTATE P4904; owner answers to Q-2026-10-05-18 and Q-2026-10-05-19); otherwise it stays with its Customer. Exception since V1-056 sub-slice 10e-1a (migration `20261120_116`, DB-PAY-009): the confirm of a returned Payment reverses that Payment's moved allocation and such a Credit of that Payment in the same transaction. A Credit of a Customer other than the payer can be applied to that Customer's Invoices or Late-payment Charges, or refunded to that Customer through a `CREDIT_CUSTOMER` Refund draft confirmed by `financial.approve` (BR-CREDIT-014; V1-056 sub-slice 8f, migration `20261030_95`, DB-REFUND-001); the ordinary Credit Refund draft pays only a recipient who is both the Credit's Customer and the payer, so it is refused for such a Credit. A third-party payer's own Credit can still be refunded to the payer through a Refund draft.

As built in V1-056 sub-slice 10g (migration `20261222_148`): a row is also written by the `PAYMENT_MOVE` variant of a post-settlement correction (DB-SETTLE-005); its `draft_id` is then the `SETTLEMENT_CORRECTION` draft, and the row is written after that draft's CONFIRMED decision, in the same transaction. The insert check `app.validate_payment_move` accepts such a row only through `app.settlement_payment_move_allowed`: the move's approver confirmed the draft under `financial.approve` in this transaction (its top-level transaction id and decision time), the decision names this move's id, and the source reversal and the new allocation are linked to that correction. The slice 7 branch (a `PAYMENT_MOVE` draft still undecided) and every other check of the row are unchanged.

As built in V1-056 sub-slice 10g-2 (migration `20270107_164`; owner answer (a) to Q-2026-10-17-121): the move source has one body, the new internal `app.wrong_unit_move_source(property, allocation, target invoice, settlement correction)` (no grant). The slice 7 source `app.payment_move_source` calls it with false and keeps the blanket refusal above. The `PAYMENT_MOVE` correction's source calls it with true: there a Payment's Customer Credit that is not reversed, or its Refund that is not fully returned, refuses the move only when a credit Adjustment released any part of an allocation of this Payment on the wrong Invoice (an `invoice_credit_excess_releases` row whose reversed allocation is of this Payment and on the move's source Invoice), because the correction moves only the wrong allocation's own value, still on that active allocation. The Payment's Credit and Refunds and the Settlement's use of them do not change. No table, column, trigger or grant changed.

As built in V1-056 sub-slice 10h-1 (migration `20270108_165`; owner answers 3 and 4 to Q-2026-10-06-36 and point 2 of Q-2026-10-17-120): `app.payment_move_source` (whole-body replacement; same signature, settings and privileges) refuses (55000, "A closed Final Settlement relied on this allocation; move it through a correction of that Final Settlement") an allocation of the Property that `app.closed_settlements_relying_on_allocation` names (DB-SETTLE-005) and that was not reversed at or before that Settlement's closure (a Settlement did not rely on an allocation reversed before it closed, so that one keeps the slice 7 rules; review round 1, independent S1), before it calls `app.wrong_unit_move_source(...,false)`; the slice 7 recorder (both calls) and confirm refuse it, and the allocation reversal insert trigger of DB-SETTLE-005 is the backstop. The 10g source is unchanged.

## DB-PAY-009 — `payment_returns`

Approved by owner answers 2 and 3 to Q-2026-10-06-37 (2026-10-07); built in V1-056 sub-slice 10e.
Append-only record of one returned Payment (a bounced transfer): one row per returned Payment
with the Payment, the draft, the reason, the approver, `authorization_reference`
`financial.approve`, and the Settlement correction (DB-SETTLE-003) when there is one. With no
closed Settlement, a `payments.reverse` holder prepares a draft of the new kind `PAYMENT_RETURN`;
with a closed Settlement it is the `RETURNED_PAYMENT` correction variant under
`final_settlements.prepare`; only a `financial.approve` holder confirms either. The confirmation
reverses, in one transaction, the Payment's allocations, Credit applications, Credits and Deposit
receipts and then the Payment. The slice 7 and sub-slice 8g refusals and the sub-slice 8e-2
refusal accept such a reversal only when this row for that Payment was written earlier in the
same transaction by the internal writer (never a session setting). A returned Payment may reverse
its records on other Leases, but never a record that another Lease's closed Settlement relied on
unless that change is also a confirmed correction of that Settlement (DB-SETTLE-005, owner answer
5). No application role may write the table.

As built in V1-056 sub-slice 10e-1a (migration `20261120_116`): `id uuid PK`, `property_id`,
`payment_id uuid NOT NULL UNIQUE FK payments`, `draft_id uuid NOT NULL UNIQUE FK financial_drafts`,
`settlement_correction_id uuid NULL UNIQUE FK settlement_corrections` (NULL until sub-slice 10e-1b),
`reason` (1 to 1,000 characters, the draft's), `occurred_at`, `actor_id` (the approver),
`authorization_reference` (`financial.approve`). The evidence reference stays in the draft payload.
The `financial_drafts` checks gain the kind `PAYMENT_RETURN` and the preparer `payments.reverse`
(also for a WITHDRAWN decision), and the two capability-scoped draft reads accept eight preparer
capabilities instead of seven. A BEFORE INSERT check needs a received Payment of the Property and a
`PAYMENT_RETURN` draft of that Payment with the same reason; a deferred check needs that draft
CONFIRMED by the row's actor in the same transaction (the decision's transaction id, as DB-SETTLE-003)
and the Payment REVERSED at commit. Staff record the draft (`app.record_payment_return_draft`); its
payload lists every active allocation, every Credit recognized from the Payment that is not
reversed, with its active applications, and every active Deposit receipt. A `financial.approve` holder (a person, at READ
COMMITTED) confirms it (`app.confirm_payment_return`): in one transaction the decision, this row, the
Credit application reversals, the Credit reversals, the allocation reversals (each with the draft's
reason, the approver as actor, its table's own authorization string and a strictly increasing
instant), the Deposit receipt reversals through the existing receipt reversal (`deposits.correct`,
its command record and `deposit.receipt.reversed` audit event; stamped with the statement time, as
the sub-slice 8r confirm), the Payment reversal (authorization reference `financial.approve`) and one
`payment.return.confirmed` audit event whose correlation id is the draft id. Refused (55000): a
Payment that is not RECEIVED; a record that a closed Final Settlement relied on (an allocation or
Credit application on an obligation of that Lease made at or before the closure, a Final Settlement
Credit application, a record linked to a post-settlement correction or a Credit such a correction
released, a Deposit receipt of a Deposit of that Lease); a Refund paid from the Payment's value that
is not fully returned and a Deposit it funded with an active forfeiture or Deposit application
(open question Q-2026-10-10-72); a pending draft whose payload names the Payment or one of those
records. A draft whose sources changed is stale (P5S02) and stays pending; a Final Settlement closed
after the draft was recorded makes it stale. The slice 7 refusals and the sub-slice 8g refusal let a
reversal of that Payment's record through only while such a row of that Payment, confirmed in the
same transaction, exists (`app.payment_return_in_transaction`); the sub-slice 8e-2 refusal and the
receipt reversal's closure check are not relaxed for a `PAYMENT_RETURN` (a closed Settlement's
records pass only through a linked correction, sub-slice 10e-1b). After review round 1: a Credit
also counts as relied on when a Final Settlement or a correction used it, also when that use was
later reversed or released (a Settlement application, an application or its reversal or release
linked to a correction, a Refund of the Credit or a Refund correction linked to a correction); the
recorder, too, runs only at READ COMMITTED (55000); the confirm locks the targets of active records
only, in two passes as the Final Settlement confirm: first every Late-payment Charge in id order,
then every Invoice in id order, the Invoice targets and the Charges' source Invoices together (after
review round 2, owner answer to Q-2026-10-10-74). Known limit: a draft larger than the 16,000-byte
draft limit (a Payment with very many records) is refused (22023).

As built in V1-056 sub-slice 10e-1b (migration `20261121_117`; owner answers (a) to Q-2026-10-10-72
points 2 and 3): the `RETURNED_PAYMENT` variant of the `SETTLEMENT_CORRECTION` draft returns a
Payment whose records the closed Settlement relied on. Staff record it under
`final_settlements.prepare` (`app.record_settlement_returned_payment_draft`; the Payment and an
evidence reference of 1 to 500 characters, a reason of 1 to 500; READ COMMITTED; the same
one-waiting-draft lock per Payment as the `PAYMENT_RETURN` recorder); the payload stores the
sub-slice 10e-1a source plus the Settlement and the active Deposit applications and forfeitures of
every Deposit the Payment funded. A `financial.approve` holder (a person, at READ COMMITTED)
confirms it (`app.confirm_settlement_returned_payment`): the decision and the correction header,
then this row with `settlement_correction_id`, then, each linked to the correction
(DB-SETTLE-005) before it is written, the Credit application reversals (a Final Settlement or
correction Credit application passes the sub-slice 8e-2 refusals by the link), the Credit
reversals, the allocation reversals, the reversals of the funded Deposits' forfeitures (through
the existing reversal function, `deposits.correct`, the draft's evidence reference), their Deposit
application reversals (DB-DEP-006, `financial.approve`), their receipt reversals and the Payment
reversal, each with the draft's reason and the approver as actor, and one
`final_settlement.correction.confirmed` audit event. Every reversal except the forfeiture reversal
gets a strictly increasing instant after the correction header, and the Payment reversal is last;
the forfeiture reversal keeps the reversal function's statement time, so it is dated before the
header (as in sub-slice 10d) and before the Deposit application reversals. The receipt reversal is
written by the correction itself, with the same `deposits.correct`, command record and
`deposit.receipt.reversed` audit event as the receipt reversal function, because that function
stamps the statement time, which would date it before the Deposit application reversals. Each
funded Deposit ends empty, so there is no DL-032 step, and no charge is made for a kept Deposit's
amount. The receipt reversal's audit event keeps the statement time, so it is dated before its
row; read it through the correction's link, not by time. Refused (55000): a Payment that is not
RECEIVED; a Payment this Settlement did not rely on (the correction of the closed
Settlement that did, or else the `PAYMENT_RETURN` draft, returns it; since sub-slice 10e-4 this
correction also takes a Payment used on its Lease, below); a record that another closed
Final Settlement also relied on (a known limit: one correction belongs to one Settlement); a Refund
paid from the Payment's value that is not fully returned (until sub-slice 10e-1c); a funded
Deposit's forfeiture governed by another Lease; a funded Deposit's application of another Final
Settlement; a funded Deposit that would still hold money after the return (its held value plus its
active Deposit applications and forfeitures differs from the Payment's active receipts in it; a
Refund paid and fully returned cancels out, owner answer to Q-2026-10-10-77); a waiting draft that
names the Payment or one of its records. A draft whose sources changed is stale (P5S02) and stays
pending. The
BEFORE INSERT check of this table accepts a `PAYMENT_RETURN` draft with no correction or a
`RETURNED_PAYMENT` correction draft with the correction it confirms. The correction lock function
locks the Payment, its Credits, the targets of its active records (also outside the Lease) and its
funded Deposits in its id-ordered passes.

As built in V1-056 sub-slice 10e-1c (migration `20261122_118`; owner answer (a) to Q-2026-10-10-72
point 1, answers A, B and C to Q-2026-10-11-78, answer (a) to Q-2026-10-11-79): a Refund paid from
the returned Payment's value (a Refund of the Payment, of one of its Credits or of a Deposit it
funded) no longer blocks the return. The source of both returns gains `recoveries`
(`app.payment_return_recoveries`): every such Refund whose net value is above 0, with its recipient,
its net amount, the Lease its charge goes on and the charge form. The Lease is the Lease the money
came from when the recipient is its signed Customer (a Deposit Refund: the Deposit's Lease; a
Credit Refund: the Lease of the Invoice or Late-payment Charge whose release created the Credit,
none when that Invoice has no Lease, else the Lease the Payment names; a Payment Refund: the Lease
the Payment names), otherwise none. Both confirms write, right after this row and before the
reversals that need the value back, one charge and one `RECOVERED_BY_CHARGE` Refund correction
(DB-REFUND-002) per planned Refund, each dated after every event of its Refund and source: the
charge goes to the person who received the refund money for the exact net amount, a Miscellaneous
one-time charge (`authorized_nonrecurring_obligations`, `source_reference`
`refund-recovery:<refund id>`, `financial.approve`) and its Invoice, issued in the same call with
the Property's one-time charge Due Date days; on the Lease above (a second Signer is charged
directly, owner answer C) or with no Lease (owner answer B). Inside the `RETURNED_PAYMENT`
correction every record is linked (DB-SETTLE-005) before it is written, and a charge on the
Settlement's own Lease is that correction's `EXTRA_CHARGE`. The `PAYMENT_RETURN` confirm reverses
the receipt of a Deposit whose Refund it recovered through the shared receipt writer (DB-DEP-007),
dated after the recovery. Refused (55000) by the recorders, the confirms and the writer: a Reservation
outcome Refund (known limit, owner answer 1 to Q-2026-10-11-81); a Refund of a Deposit that also
holds another Payment's receipt (a guard, owner answer 2); a charge on a Lease whose closed Final
Settlement this return cannot correct (the `PAYMENT_RETURN` draft: any closed Settlement; a
correction: another Settlement's; this refusal stays; owner answer 3 to Q-2026-10-11-81 ends
instead the correction's "did not rely on" refusal for a Payment used on that Lease, sub-slice
10e-4, below); a source whose Refunds out differ from the planned recoveries.
Both confirms take the one-time charge recorder's Lease key lock for every Lease a recovery charge
goes on, in one id-ordered pass before any row lock (the correction also for its own Lease). The
`RETURNED_PAYMENT` write helper now runs the correction's source, digest (P5S02) and refusal check
itself. A waiting draft that names a recovered Refund counts as a waiting draft. The results list
the written recoveries (`recoveries`: the Refund, the person charged, the Lease or none, the amount,
the charge form `EXTRA_CHARGE`, `LEASE` or `NO_LEASE`, the obligation and the Invoice). Drafts
recorded before revision 118 are stale (their source gained `recoveries`) and are recorded again.

As built in V1-056 sub-slice 10e-2b-4e-1 (migration `20261231_157`; owner answer (a) to
Q-2026-10-18-127): the `PAYMENT_RETURN` draft no longer refuses a Refund of a shared Deposit (a
Deposit the returned Payment funded that also holds another Payment's active receipt). Its
recorder and confirm read `app.payment_return_draft_source`: the return source with the recoveries
of `app.payment_return_shared_deposit_recoveries` and, for each funded Deposit, `shared` and
`shortfall_usd_cents` (the returned Payment's active receipt less what the Deposit holds, never
below 0). A shared Deposit with a shortfall of 0 plans no recovery: its receipt is reversed through
the shared receipt writer while its Refund stays out, and the Refund is then paid from the other
Payments' money. A shortfall above 0 is charged back newest Refund first (`processed_at`, id,
descending), each Refund at most its net, with the same charge and `RECOVERED_BY_CHARGE` row as
above for that share (`amount_usd_cents` the share, `net_usd_cents` the Refund's net), and the
Deposit ends at 0. A shared Deposit whose Refunds not fully returned went to more than one person
keeps the shared refusal while its shortfall is above 0 (Q-2026-10-18-134 point 2), and a shared
Deposit with a Reservation outcome Refund or a charge on a closed Settlement's Lease keeps those
refusals, also with a shortfall of 0 (review round 1). The rule reads only what the Deposit holds,
not the order of events (owner answer (a)): when B's receipt paid a Refund before A's receipt came
in (a receipt into a Deposit whose Refund is out, recorded since sub-slice 10e-2b-4e-2b-2b ended
option (d); before that only after a dodge such as a verified return reversed after A's receipt)
and B bounces, nothing is charged and the Refund stays paid from A's money; the Deposit is then
short of its required total, as with any unpaid Deposit money. A Deposit the
returned Payment alone funded is unchanged (its shortfall is the nets of its Refunds, each
recovered whole). The insert check of the recovery row accepts a share only through
`app.payment_return_shortfall_recovery_amount` (inside a confirmed `PAYMENT_RETURN` of this
transaction whose Payment still has an active receipt in that shared Deposit, at most the
Deposit's shortfall before the row); a smaller sum is refused by the Deposit's held-history check
at the receipt reversal (DB-DEP-007). `app.payment_return_source` and `app.payment_return_recoveries`
are unchanged, so the `RETURNED_PAYMENT` correction, the receipt correction and the return
reversal still refuse a shared Deposit (sub-slice 10e-2b-4e-2, Q-2026-10-18-134 point 1). A
draft recorded before revision 157 whose Payment has an active Deposit receipt is stale (its source
gained the Deposit keys) and is recorded again; other drafts keep their digest.

Since V1-056 sub-slice 10e-2b-4e-2a (migration `20270101_158`; owner answers (a) to
Q-2026-10-18-134): the newest unreturned Refund's recipient pays first, before and after closure,
also when the Refunds went to two people (the 4e-1 two-recipient refusal ends). The
`RETURNED_PAYMENT` correction plans the shares of a shared Deposit's Refunds itself (newest use
first over its Refunds, applications and forfeitures; DB-DEP-007 note), and the recovery insert
check also accepts a share inside the confirmed `RETURNED_PAYMENT` correction that links the row,
at most the Deposit's shortfall before the row (`app.payment_return_shortfall_recovery_amount` is
bound to the return of the correction that links the row; a `PAYMENT_RETURN` has none). The
receipt correction (until sub-slice 10e-2b-4e-2b) and the return reversal still refuse a shared
Deposit. Since sub-slice 10e-2b-4e-2b-2a the same function also accepts a share inside the
confirmed `DEPOSIT_RECEIPT_CORRECTION` that links the row (DB-DEP-007 note); the return reversal
still refuses a shared Deposit.

As built in V1-056 sub-slice 10e-4 (migration `20261201_127`; owner answer (c) to Q-2026-10-11-81
point 3 and the owner answer to Q-2026-10-11-82): the `RETURNED_PAYMENT` correction also returns a
Payment that no closed Final Settlement relied on, when the Payment names the correction's Lease or
its money is used there: an active allocation of the Payment, or an active application of one of
its Credits that is not reversed, is on an Invoice of that Lease or a Late-payment Charge of such
an Invoice (since the Settlement did not rely on them, such uses came after closure), or a Refund
paid from its value is charged back on that Lease (`closed_final_settlement_id` of a recovery is
this Settlement). The way in through the named Lease has no time or use condition: a Payment that
names the Lease and was never used there also passes. The correction's source gains
`used_on_lease`; in this branch only a JSON `true` counts, a source without a `relied_on` key is
refused (55000), and a `relied_on` that is not a list cannot be read (22023), so both fail closed.
Nothing else changes: the records are reversed and linked as in 10e-1b, the debt comes back on its
obligations and stays with their Customers (BR-SETTLE-016), and each Refund out is charged back to
the person who received it by the 10e-1c rules unchanged: the charge goes on the Lease the money
came from (a Payment Refund: the Lease the Payment names; a Credit Refund: the Lease of the Invoice
whose release created the Credit, else the Lease the Payment names) when the recipient is its
signed Customer, an `EXTRA_CHARGE` when that Lease is this Settlement's, otherwise an ordinary
charge on that Lease or a charge with no Lease. So a Payment that names no Lease, used on this
Lease through an allocation, whose rest was refunded to the payer, gets a no-Lease charge
(Q-2026-10-13-98 asks the owner to confirm). With nothing refunded no charge is written. A Payment
whose records another closed Settlement relied on, and a recovery charged on another closed
Settlement's Lease, stay refused (the known limit of one correction per Settlement). The
`PAYMENT_RETURN` draft keeps refusing a Payment whose Refund would be charged on a closed
Settlement's Lease; its message now names the returned-Payment correction (the service still
reports the generic conflict until slice 11c). It still returns a Payment whose only use on a
closed Lease is an allocation or Credit application with nothing refunded (no closed Settlement
relied on it); the correction can return the same Payment with the records linked. Known limits: a
Payment used after closure on two closed Leases can be returned by either Settlement's correction
(unless a recovery is charged on one of those Leases; then only that Settlement's correction can),
which reverses and links the other Lease's records too (nothing either Settlement relied on
changes); a Payment with recoveries on two closed Settlements' Leases is refused by every
correction, although the `PAYMENT_RETURN` message points to a correction. Drafts of this variant
recorded before revision 127 are stale (their source gained `used_on_lease`) and are recorded
again.

## DB-CREDIT-001 — `customer_credits`

Append-only Credit recognition event: `id uuid PK`, `customer_id uuid NOT NULL FK`, `source_payment_id uuid NOT NULL FK`, `recognized_usd_cents bigint NOT NULL CHECK (>0)`, `customer_authorization_reference text NOT NULL`, `recognized_at timestamptz NOT NULL`, `recognized_by uuid NOT NULL`, `reason text NOT NULL`. Credit must belong to the payer Customer and cannot exceed unallocated, undisposed Payment value. Credit balance is derived. For a KHR-origin Payment, the source FK preserves original KHR amount, selected exchange record, USD recognition basis, and channel transaction facts without creating a KHR Credit balance.

## DB-CREDIT-002 — `customer_credit_applications`

Append-only authorized application header: `id uuid PK`, `customer_credit_id uuid NOT
NULL FK`, `target_kind text NOT NULL CHECK IN ('INVOICE','LATE_PAYMENT_CHARGE')`,
`invoice_id uuid NULL FK`, `late_payment_charge_id uuid NULL FK`, `final_settlement_id
uuid NULL FK`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `within_invoice_basis text
NOT NULL CHECK IN ('RENT_THEN_RECURRING_SERVICES_PROPOSAL','CUSTOMER_DESIGNATED',
'OTHER_APPLICABLE_OBLIGATION','NOT_APPLICABLE','PUT_BACK_BY_CORRECTION')` (the last value
since sub-slice 10e-3e, below), `customer_designation_reference text
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

As built in V1-056 sub-slice 10c-2a-2 (migration `20261106_102`; owner answer 1 to
Q-2026-10-07-42): the same writer also writes the Customer Credit steps of a post-settlement
correction's DL-032 plan (DB-SETTLE-005): it reads the step from the `SETTLEMENT_CORRECTION`
draft's `plan`, resolves its Credit key (an existing Credit, or the Credit that a Payment
allocation released by the same correction became, BR-CREDIT-014) and gives the row a fresh `id`,
linked (`customer_credit_application_id`) to the correction before it is written; the row keeps
the Settlement link and `financial.approve`, so its one-call reversal stays refused. For such a row
the source check needs the link to a correction of that Settlement confirmed in the same
transaction, the correction's approver (a person, active, `financial.approve`; 42501 otherwise),
a time not before the correction, a target of the Settlement Lease, no Deposit application or
Refund of the same correction yet (55000), and a matching Credit step of that correction's plan
with the basis BR-CREDIT-006 gives (23514); the deferred check needs the correction's draft
CONFIRMED by the same approver and pins the row to the plan step its detail names, once.

As built in V1-056 sub-slice 10e-3e (migration `20261207_133`; owner answers (b) to
Q-2026-10-13-104 and (a) to Q-2026-10-13-106): `within_invoice_basis` and the DB-CREDIT-005
`attribution_basis` also accept `PUT_BACK_BY_CORRECTION` ("put back by a correction"). A
`RETURN_REVERSAL` correction's Credit put-back (the part of a reversed Credit application that was
not the mistaken money, sub-slices 10e-3c to 10e-3d-2b) on an Invoice with Rent or Service lines
without a Customer designation carries it on the row and its detail, goes back on the reversed
application's own line with no Rent-first proposal, and is never a new allocation; every
put-back's detail `calculation_trace` names `restores_credit_application_id` (the step's restored
application is the stored source's `reapply` entry at the step's position). A designated part
keeps `CUSTOMER_DESIGNATED` and a Late-payment Charge `NOT_APPLICABLE`. Checks: a BEFORE INSERT
trigger (`app.validate_credit_application_put_back`) allows the label only on a row linked to a
correction of its Final Settlement confirmed in the same transaction, or on the re-posted rest
of a row that has it (the release re-post of migration 67, which a later `REFUND` correction's
confirm writes after closure, migration 100) (23514 otherwise), so an ordinary or Settlement Credit
application never carries it; the header and its details agree on it; the deferred check
(`app.settlement_correction_put_back_allowed`) needs, for a `RETURN_REVERSAL` correction, the
named application with one detail, the same Credit, target and line, a reversal linked to the
same correction, all put-backs naming it together at most its amount there, and the label exactly
on such an Invoice without a designation; for any other correction no restored application and
no label (23514). The sub-slice 10e-3d-2a Rent-first refusal and the sub-slice 10e-3c known limit
(a put-back the Rent-first proposal would put on another line) end.

As built in V1-056 sub-slice 10f-1b (migration `20261220_146`; owner answer (a) to
Q-2026-10-16-118 point 1): the pre-closure `ADJUSTMENT_REVERSAL` put-back (DB-INV-010) always
carries the label, on any Invoice, with no Final Settlement. The BEFORE INSERT trigger also
allows the label on a row with no Final Settlement that a confirmed `ADJUSTMENT_REVERSAL` decision
of the same transaction (its stored transaction id and a decision time not before the
transaction began) lists among its put-backs. A new deferred constraint trigger
(`customer_credit_applications_adjustment_put_back`, internal
`app.validate_adjustment_reversal_put_back` and `app.adjustment_reversal_put_back_allowed`)
checks each such listed row that is not the re-posted rest of a release: one detail; listed with
the same Credit, amount and release; the detail's trace names that decision's reversal and the
release; the release belongs to the reversed Adjustment and its Credit is the row's; the row is on
the Adjustment's Invoice and the detail on its line; all put-backs naming the release are together
at most the released amount (23514 otherwise). Rows no decision lists are left to the insert
trigger, which refuses every such row except the re-posted rest of a labelled row (a committed
10e-3e test writes such a row by hand with the insert trigger disabled to reach the agreement
check). The release re-post (migration 67) of a labelled put-back keeps the label on its rest, as
before.

As built in V1-056 sub-slice 10f-2 (migration `20261221_147`): the insert trigger, the deferred
trigger's filter and `app.adjustment_reversal_put_back_allowed` also accept the confirmed decision
of a `SETTLEMENT_CORRECTION` draft of the variant `ADJUSTMENT_REVERSAL` of the same transaction
(the same binding); for such a decision the allowed function also needs the put-back linked to
that correction (DB-SETTLE-005 `customer_credit_application_id`). The put-back still has no Final
Settlement, so the 8e-2 refusal of a Settlement Credit application reversal does not cover it:
after closure the ordinary Credit application reversal can still reverse it (as other Credit
applications made after closure, until sub-slice 10h decides which records count as existing at
closure).

## DB-CREDIT-003 — `customer_credit_application_reversals`

Append-only: `id uuid PK`, `credit_application_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`.

V1-056 sub-slice 8e-2: a reversal of a Credit application that has a `final_settlement_id`
is refused (SQLSTATE `P5S01`, a conflict) before any other reversal check, for every writer;
it waits for the post-settlement corrections (slice 10). Other reversals are unchanged.

## DB-CREDIT-004 — `customer_credit_reversals`

Append-only: `id uuid PK`, `customer_credit_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. It requires all applications and Refund commitments sourced from the Credit to be resolved explicitly.

V1-056 slice 7: a reversal of a Credit released from a moved allocation is refused unless the Payment is a normal Customer Payment and the Credit belongs to its payer (DB-PAY-008, `customer_credit_reversals_moved_payment`).

V1-056 sub-slice 8g (migration `20261031_96`, owner answer to Q-2026-10-06-35, approved tightening): a reversal of any Credit that a credit Adjustment released to a Customer other than the payer of its source Payment (`app.credit_customer_refund_basis` is not NULL: the Credits that the `CREDIT_CUSTOMER` Refund draft pays, DB-REFUND-001) is refused for every writer with SQLSTATE `P4904` (BEFORE INSERT trigger `customer_credit_reversals_other_customer`, after the slice 7 refusal and before the Credit reversal checks). Such a Credit stays with its Customer: it is applied to that Customer's obligations or refunded to that Customer. Earlier reversal rows are unchanged. Exception since V1-056 sub-slice 10e-1a (migration `20261120_116`, DB-PAY-009): the confirm of a returned Payment reverses such a Credit of that Payment in the same transaction.

## DB-CREDIT-005 — `customer_credit_application_details`

Append-only attribution: `id uuid PK`, `customer_credit_application_id uuid NOT NULL
FK`, `invoice_line_id uuid NULL FK`, `late_payment_charge_id uuid NULL FK`,
`obligation_kind text NOT NULL CHECK IN ('INVOICE_LINE','LATE_PAYMENT_CHARGE')`,
`invoice_line_category_snapshot text NULL`, `proposed_amount_usd_cents bigint NULL
CHECK (>0)`, `applied_amount_usd_cents bigint NOT NULL CHECK (>0)`,
`attribution_basis text NOT NULL CHECK IN ('RENT_FIRST_PROPOSAL','SERVICE_PROPOSAL',
'CUSTOMER_DESIGNATED','OTHER_CONFIRMED','DIRECT_LATE_PAYMENT_CHARGE',
'PUT_BACK_BY_CORRECTION')` (the last value since sub-slice 10e-3e, DB-CREDIT-002), `detail_sequence
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

Amended by DL-071 (owner, 2026-10-05; answer 10 changed 2026-10-20): `receipt_number` is `RCP` + 2-digit year of the confirmation date in `Asia/Phnom_Penh` + 4-digit running number restarting each year (for example `RCP260001`; 5 digits after 9999), never reused; it is also the Payment's `payment_number`. Not built yet (V1-059).

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

- SECURITY requires one Reservation, or for a walk-in Lease one Lease and no Reservation (DL-066; as built in sub-slice 10e-2b-4c below), prohibits pet approval, and `UNIQUE (reservation_id) WHERE deposit_type='SECURITY'`.
- PET requires one Lease and one approval whose terms require a Deposit; reservation
  is null; `UNIQUE (lease_id) WHERE deposit_type='PET'` and `UNIQUE
  (pet_approval_id) WHERE deposit_type='PET'` enforce the one optional Pet Deposit.
- A deferred transaction constraint requires exactly one Security Deposit for every Reservation and verifies that any later Lease is the Reservation's resulting Lease. No conversion or second Deposit is created.
- Required amount is a historical obligation; a change requires an explicit audited correction event rather than silent overwrite after receipt.

As built in V1-056 sub-slice 10e-2b-4c (migration `20261229_155`; owner answer (a) to
Q-2026-10-17-124 point 1): a SECURITY Deposit may also have a Lease and no Reservation, the walk-in
Lease's Security Deposit (`deposits_source_shape` gains that branch, relaxing). The deferred
source check (`app.validate_deposit_source`) requires, for such a row, a SIGNED Lease whose Primary
Tenant is the Deposit's Customer, signed through the new path with no Reservation (a
`lease_signing_outcomes` row with no Reservation, and no Reservation names the Lease as its
resulting Lease), not a renewal (no predecessor Lease; Q-2026-10-18-129), and no other Security
Deposit of that Lease; it also refuses linking a Reservation's Deposit to a Lease that already has
a walk-in Security Deposit (one Security Deposit per Lease; review round 1, because the old
Reservation move-in reads no signing outcome). The writer is
`app.create_lease_security_deposit(property, actor, idempotency key, request digest, deposit id,
lease id, required amount, reason, authorization)` (SECURITY DEFINER, `search_path=pg_catalog`,
EXECUTE only to `prm_financial`; the Deposit service's `create_lease_security_deposit` under
`deposits.manage`): the input (22023), the idempotency lock and the replay (action
`deposit.security.create` in `app.deposit_commands`, a relaxing widening of
`deposit_commands_action_check`), READ COMMITTED (55000), an active financial actor, the SIGNED
Lease of the Property locked FOR UPDATE (P0002 otherwise), then refused: a closed Final
Settlement (P5S01), a Lease not signed as a walk-in (55000), a renewal (55000), a Lease that
already has a Security Deposit (55000). The Customer is the Lease's Primary Tenant; the required
effective date is the business date of the Lease's signing in the Property's time zone; it writes
the `deposit.security.created` audit event and the command record. Later changes of the total use
the existing required-amount adjustment (`deposits.manage`). The BEFORE INSERT Reservation
continuity check (`app.validate_reservation_security_deposit`) returns at once for such a row.
Known limit (Q-2026-10-18-130): the unpaid-Initial termination ground, the old Reservation
move-in and the Reservation read API still read the first `required_usd_cents`, not the adjusted
total.

## DB-DEP-002 — `deposit_receipts`

Append-only: `id uuid PK`, `deposit_id uuid NOT NULL FK`, `payment_id uuid NOT NULL FK`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `UNIQUE (deposit_id, payment_id)`. The transaction prevents total allocations, active Deposit receipts, Credit recognition, and Refund commitments from exceeding Payment USD accounting value. This is not an Invoice Payment Allocation.

As built in V1-056 sub-slice 10e-2b-1 (migration `20261126_122`; owner answers (a), (a), (a) to
Q-2026-10-12-87): the key `UNIQUE (deposit_id, payment_id)` is replaced by a check in the insert
trigger `app.validate_deposit_receipt`: a Deposit holds at most one active (not reversed) receipt
from each Payment (23505); a reversed receipt stays in the history and no longer blocks a new one.
The check relies on the Deposit row lock (READ COMMITTED; a REPEATABLE READ writer fails on the
Deposit's serialization guard). A Security Deposit's first active receipt may differ from the
accepted amount only when a correction of the Lease's closed Final Settlement, confirmed in the
same transaction, links it (DB-SETTLE-005 `deposit_receipt_id`); all active receipts stay within
the required amount, which does not change. Writers: `app.create_reservation` (a new Security
Deposit) and the internal `app.write_correction_deposit_receipt`, called only by a
`DEPOSIT_RECEIPT_CORRECTION` confirm for a receipt its draft names, from the corrected receipt's
Payment; it is the only Pet Deposit receipt writer (until sub-slice 10e-2b-4b-2b, below) and
writes a `deposit.receipt.recorded` Deposit
audit event (stamped with the statement time, so dated just before its receipt row, as the
reversal event under DB-DEP-007). A Deposit the Property keeps (an active forfeiture) takes no
new receipt; see DB-DEP-007. Since sub-slice 10e-2b-2 (migration `20261127_123`) the writer also
requires its correction's decision confirmed in the same transaction by the same approver under
`financial.approve` (review-driven hardening of an internal function), and a correction that
writes the same receipt again into the same Deposit (the same Payment and amount) is refused
(owner answer 1 to Q-2026-10-12-89); see DB-SETTLE-005.

As built in V1-056 sub-slice 10e-2b-3 (migration `20261224_150`; owner answer 2 to Q-2026-10-12-89,
an approved tightening, and answer (a) to Q-2026-10-12-90): the table itself holds owner rule 3 for
Pet Deposits once the Lease's Final Settlement is closed. From then on
`app.validate_deposit_receipt` refuses every Pet Deposit receipt of that Lease (P5S01, "A closed
Final Settlement changes only
through a post-settlement correction", as the 8e-1 refusal) unless a correction of that Settlement,
confirmed in the same transaction, links it (DB-SETTLE-005 `deposit_receipt_id`); a correction of
another Lease's Settlement does not, and a correction confirmed in an earlier transaction cannot
link a receipt at all (the effect trigger refuses the link, 23514). It is the Pet branch's first
check, after the Payment source check, the Deposit row lock and the one-active-receipt check. The
8e-3 confirm locks the Settlement row and then every Deposit of the Lease and writes the closure
last; the receipt's earlier balance trigger locks the Deposit row first
(`app.serialize_deposit_state`), so at READ COMMITTED a receipt that waited for the Deposit row
reads a closure committed meanwhile, a REPEATABLE READ or SERIALIZABLE writer whose snapshot is
older than the closure fails on the Deposit's serialization guard (40001), and a receipt that held
the row first and committed makes the waiting confirm stale (P5S02). Before closure nothing changes;
Security Deposit receipts do not change.

As built in V1-056 sub-slice 10e-2b-4b-2b (migration `20261228_154`; owner answer to
Q-2026-10-12-92): a third writer, `app.record_lease_deposit_receipt(property, actor, idempotency
key, request digest, receipt id, deposit, payment, amount, reason, authorization)` (SECURITY
DEFINER, `search_path=pg_catalog` and `TimeZone` UTC, EXECUTE only to `prm_financial`; the Deposit
service's `record_receipt` under `payments.allocate`, no draft), records a receipt from a received
Payment into an existing Deposit of a signed or terminated Lease: a Pet Deposit receipt, or a later
Security Deposit receipt within the required amount. Order: the input (22023: nonzero ids, an
amount above 0, `payments.allocate`, a normalized reason of at most 1,000 characters, a 64-hex
request digest); the idempotency lock and the replay of an exact repeat (action
`deposit.receipt.record` in `app.deposit_commands`; a reused key with another body 23505);
READ COMMITTED (55000); an active financial actor (`app.assert_active_financial_actor`; the
service checks the Property scope and `payments.allocate`); P0002 for a Payment or Deposit
not of the Property; the locks in the insert triggers' order (`app.serialize_payment_state` and
the Payment row, then `app.serialize_deposit_state`); then refused: a Deposit with no Lease (55000;
a Reservation's Deposit before signing is sub-slice 10e-2b-4c), a closed Final Settlement of the
Deposit's Lease (P5S01, the 8e-1 message, for both Deposit types, read after the Deposit lock that
the closing confirm also takes), a Lease that is not SIGNED or TERMINATED (55000), an active
forfeiture of the Deposit (55000, reverse it first), a Payment confirmed for an Invoice or a
Late-payment Charge (55000; review round 1: such a Payment's value is allocated only to its
identified target, BR-PAY-024 and BR-PAY-026, as the allocation check requires; what is left after
that target may become Credit or a Refund, never a Deposit receipt: the whole Payment is refused,
Q-2026-10-18-128). The receipt's time is the database's: the later of `clock_timestamp()` and one
microsecond after the Deposit's latest balance event. Every check of
this table and of the Payment source still runs. It writes the receipt, the
`deposit.receipt.recorded` Deposit audit event (its id the receipt's, correlated by the idempotency
key) and the command record; its result is the Deposit snapshot with `deposit_receipt_id`,
`payment_id`, `amount_usd_cents`, `occurred_at` and `payment_available_usd_cents`. The command
action check `deposit_commands_action_check` also allows `deposit.receipt.record` (relaxing). With
Pet Deposit money now entering before closure through the app, the pay-back count's recovery rules
(sub-slices 10e-2b-4a to 10e-2b-4b-2a) apply on the real path; see DB-DEP-005.

As built in V1-056 sub-slice 10e-2b-4c (migration `20261229_155`; owner answers to Q-2026-10-17-124
points 2 and 3 and the owner note on DL-009): (1) a walk-in Lease's Security Deposit (DB-DEP-001)
has no accepted amount, so its first receipt may be any amount above 0, never above the required
total; no receipt of it may be dated before the Lease's signing (`app.validate_deposit_receipt`;
an unknown signing time reads as never). (2) `app.record_lease_deposit_receipt` also records a
second receipt into a Reservation's Security Deposit before signing, within the required total,
only while the Reservation is ACTIVE and its effective expiration date has not passed in the
Property's time zone (otherwise 55000, "The Deposit's Reservation is not active; this receipt is
not recorded here"); it locks the Reservation (FOR SHARE) before the Deposit, the order signing
uses, so a signing, cancellation or expiration waits for the receipt and a receipt that waited
reads the committed state (after a signing the Lease path runs); the Lease checks run only for a
Deposit with a Lease. (3) DL-009 as written covers the extra money: the Reservation outcome code
classifies all the money the Deposit holds, its active receipts; the outcome draft source
(`app.reservation_deposit_draft_source`), the outcome insert check
(`app.validate_reservation_financial_outcome`), the outcome writer
(`app.create_reservation_deposit_outcome`) and the outcome correction
(`app.correct_reservation_deposit_outcome`) count only receipts that are not reversed, and the
draft source no longer refuses a Deposit with a reversed receipt (review round 1: a bounced second
Payment's reversed receipt left the held money with no way out). A Customer-caused cancellation or
expiration forfeits all of it; a Property-caused cancellation refunds all of it. The cancellation
and the expiration (`app.cancel_reservation`, `app.expire_reservation`) and the Reservation read
API also report only active receipts as the Deposit's received amount (review round 2); the old
Reservation move-in still counts every receipt (Q-2026-10-18-130).

As built in V1-056 sub-slice 10e-2b-4d (migration `20261230_156`; owner answers of 2026-10-18 to
the 10e-2b-4b-2b report): `app.record_lease_deposit_receipt` no longer refuses a whole Payment
confirmed for an Invoice or a Late-payment Charge. After the Payment and Deposit locks and the
active-forfeiture refusal it (1) refuses (55000, "The Lease's termination ground keeps this
Deposit; this receipt is not recorded here") a receipt into a Deposit of a TERMINATED Lease whose
termination ground keeps that Deposit type (`app.lease_termination_forfeiture_rule`, the rule the
Final Settlement and the forfeiture drafts use), also after a forfeiture reversal, so money paid
after such a termination is recorded as a normal Payment and pays open Invoices or becomes Credit
(answer 3, option (a) of Q-2026-10-18-131; a Deposit the ground does not keep, such as the Pet
Deposit after voluntary early leaving, still takes receipts until closure); (2) from sub-slice
10e-2b-4d to sub-slice 10e-2b-4e-2b-2b (migration `20270104_161`) it refused (55000, "The Deposit
has a Refund that is not fully returned; this receipt is not recorded here") a receipt into a
Deposit with a Refund its corrections do not cover in full (`app.deposit_has_unresolved_refund`;
option (d) of Q-2026-10-18-127 until its option (a) was built); that refusal is removed, because
option (a) is built in the return before closure and in both corrections after closure, so a
receipt into a Deposit whose Refund is out is recorded again (before closure a Lease's Deposit has
such a Refund only as a Pet Refund-review Refund) and a later bounce of another Payment of that
Deposit charges back only its shortfall (DB-REFUND-002 note, DB-DEP-007); (3) for a Payment confirmed for an Invoice or a Late-payment Charge, runs the Credit
path's `app.assert_payment_excess_eligible` (the obligation tables in SHARE MODE NOWAIT; 23514
"Applicable obligations must be handled before excess disposition" while the named target, or a
Late-payment Charge of the named Invoice, has anything outstanding), so once the named target has
nothing outstanding the Payment's value left after it may go into the Deposit, within the Payment
availability bound (option (b) of Q-2026-10-18-128). As in the Credit path, the check comes after
the Payment and Deposit locks (review round 1: before it, the receipt held SHARE on the obligation tables while
it waited for the Payment, Reservation and Deposit locks, and could deadlock with the allocation
post or the Payment return confirm); its NOWAIT locks never wait. The Deposit service replays the
receipt command after 55P03 at most three times and then answers unavailable (DL-067).
Known limits (review round 2): the ground refusal reads the Lease status when the receipt is
recorded, and a termination locks the Lease, not its Deposits, so a receipt recorded while a
termination is still uncommitted is recorded, and a termination dated earlier than its entry
leaves receipts recorded in between (Q-2026-10-18-133); a TERMINATED Lease without exactly one
matching termination record refuses every receipt (22023, fail closed; the Final Settlement uses
the same rule); option (d) did not cover a second
receipt recorded while a Pet Refund draft was still pending (moot since option (d) ended).
Known limit (sub-slice 10e-2b-4e-2b-2b review round 1, security; Q-2026-10-19-137): a receipt
recorded into a Pet Deposit while its Pet Refund-review Refund is not fully returned cannot be
reversed before closure until that Refund is returned in full, because the receipt reversal check
refuses while the Deposit has such a Refund (55000, "Deposit receipt has active dependent
financial history"); a Payment that names no owed target (a Payment confirmed for an owed Invoice
or Late-payment Charge is refused by the excess check) and is recorded there by mistake stays in
the Deposit until the Refund comes back, the Payment's own return, a second Pet Refund-review
Refund under the same review (two people; it pays the Deposit owner) or the Final Settlement,
while the Rent it was meant for stays owed (Late-payment Charges and the DL-054 Warning Notice and
Serious Nonpayment Default can follow); after a termination whose ground keeps the Pet Deposit
(BR-DEP-022) that money is forfeited by a Lease Deposit forfeiture draft (`financial.approve`)
that the Settlement requires instead of refunded, and after closure the receipt correction fixes
it once any forfeiture is reversed by a `FORFEITURE_REVERSAL` correction (which itself runs the
DL-032 step on that money, so the receipt correction may then have to give back that
correction's uses; untested combined path, review round 3, security note 2). No route reaches the writer before slice 11, whose receipt route
waits for the owner's answer to Q-2026-10-19-137 (review round 2, security).
Ended by V1-056 sub-slice 10e-2b-4e-2b-3 (migration `20270105_162`; owner answer (a) to
Q-2026-10-19-137, narrowed by its review rounds 2 and 3: a wrong receipt must always be fixable by
two people): the two-person receipt reversal (the 8r draft: `deposits.correct` records,
`financial.approve` confirms) passes the unresolved-Refund refusal, in `app.reverse_deposit_receipt`
and in the trigger `app.validate_deposit_receipt_reversal`, when the internal
`app.deposit_receipt_reversal_after_refund_allowed` (no grant) holds: a `DEPOSIT_RECEIPT_REVERSAL`
draft of that receipt's Property and Deposit, confirmed by the reversal's actor since the
transaction began, names that receipt and that reversal (the reversal id is the reversal table's
key and a receipt is reversed once, so such a decision belongs to the 8r confirm that writes the
reversal); the Deposit's Lease has no closed Final Settlement; every Refund of the Deposit that is
not fully returned was processed strictly before the receipt; and from the receipt on the Deposit
held at least the receipt's amount at every balance time (`app.deposit_balance_events`), so no
later Payment return, correction, verified-return reversal or other payout relied on the
receipt's money. Every other refusal stays (an active forfeiture or Deposit application, a waiting
draft, a closed Final Settlement, the draft's stale check, the held history at 0 or more). A
receipt recorded before such a Refund, or one a later return relied on, stays refused; a return,
a correction and the owner-only one-call path gain nothing: `app.confirm_payment_return` passes a
fresh random reversal id to `app.reverse_deposit_receipt_v2` and the other returns and the
corrections write through `app.write_payment_return_receipt_reversal`, so no draft names their
ids; the one-call path (no application grant since migration 87) passes an id its caller chooses,
but an id a waiting draft of that Deposit names meets the waiting-draft refusal, one a waiting
draft of another Deposit, a withdrawn draft or a rejected draft names fails the CONFIRMED
condition, and one a confirmed draft names was already written by that confirm (the reversal
table's key). "Two people" is two capabilities: one person holding both `deposits.correct` and
`financial.approve` may record and confirm the draft (DL-069). A waiting `PAYMENT_RETURN` draft of
another Payment of the Deposit is made stale by such a reversal (its source digest covers the held
value).
V1-056 sub-slice 10e-2b-4e-1 (migration `20261231_157`; owner answer (a) to Q-2026-10-18-127)
did not change refusal (2): option (d) stayed until the corrections after closure were built
(review round 2: the owner's "(d) until (a) is built"; without it a receipt recorded while a
Refund is out, followed by a closure and a bounce, would have reached the then refused
`RETURNED_PAYMENT` correction; since sub-slices 10e-2b-4e-2a and 10e-2b-4e-2b-1 that correction
gives back a shared Deposit's shortfall, and sub-slice 10e-2b-4e-2b-2b ended (d)). A return before closure of a Payment of a Deposit that another
Payment also funded charges back only its shortfall (DB-REFUND-002 note, DB-DEP-007).

## DB-DEP-003 — `deposit_required_amount_adjustments`

Append-only: `id uuid PK`, `deposit_id uuid NOT NULL FK`, `adjustment_type text NOT NULL CHECK IN ('INCREASE','DECREASE')`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `effective_date date NOT NULL`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. Resulting required amount may not be negative. This table records only a valid governing Lease-term correction; it creates no right to change a Deposit.

A Deposit's required total is its first amount (`deposits.required_usd_cents`) plus these adjustments (BR-DEP-004). Since V1-056 sub-slice 10e-2b-4f (migration `20270106_163`; owner answer (a) to Q-2026-10-18-130) the internal `app.deposit_required_total_at(deposit, as_of)` (no grant) gives the total with the adjustments recorded (`occurred_at`) at or before a time, and every reader uses that total: the snapshot and the readers built on it (the termination readiness, the Deposit resource, the customer ledger), the receipt check, the Final Settlement, the BR-LEASE-005 ground (at the termination time), the old Reservation move-in and the Reservation read API (at the current time). `effective_date` is not read by these checks.

Since V1-056 sub-slice 10i-2 (migration `20270115_172`; owner answer (b) to Q-2026-10-19-138) the BR-LEASE-005 ground reads `app.deposit_ground_required_total_at(deposit, as_of)` instead (internal, no grant): the first amount, every DECREASE recorded at or before the time, and every INCREASE recorded at or before the time whose Asia/Phnom_Penh business date plus five days is before the business date of the time. An increase therefore counts for the ground only five days after its record (the ground itself already needs a termination date after Lease Start plus five days); every other reader keeps `app.deposit_required_total_at`. Since sub-slice 10i-1 a required-amount adjustment is dated with `clock_timestamp()` after its Deposit lock. Since sub-slice 10i-4a (migration `20270116_173`; owner answer (a) to Q-2026-10-20-148) the first amount of a Deposit created after its Lease's signing (every Deposit with no Reservation, that is every walk-in Security Deposit, whatever its timestamps say, because a create statement can start before a signing that commits while it waits; and a Reservation's Deposit whose `deposits.created_at` is later than `leases.signed_at` or whose Lease has no signing time) counts in that total only when the Asia/Phnom_Penh business date of its `created_at` plus five days is before the business date of the time, and reads 0 before; a Reservation's Deposit, created before signing, keeps its first amount at once. The adjustments keep the rule above, so for those five days the total can read 0 or less and the ground is only harder to meet.

## DB-DEP-004 — `deposit_dispositions`

Append-only non-refundable event: `id uuid PK`, `deposit_id uuid NOT NULL FK`, `amount_usd_cents bigint NOT NULL CHECK (>0)`, `governing_reservation_id uuid NULL FK`, `governing_lease_id uuid NULL FK`, `effective_date date NOT NULL`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`. Exactly one governing Reservation/Lease is required and must match the Deposit. It cannot exceed refundable held balance and is not an Invoice allocation.

As built in V1-056 sub-slice 10c-2b-2a (migration `20261112_108`): once the governing Lease's Final
Settlement is closed, a row is refused (P5S01) unless a correction of that Settlement links it
(none can yet), and the Lease forfeiture draft is refused at record; see DB-DEP-007.

As built in V1-056 sub-slice 10c-2b-6 (migration `20261125_121`): a Lease row is also refused
(23514) above the held value less the Pet Deposit's pay-back value, so no writer forfeits returned
Pet Refund-review money; see the 10c-2b-5 and 10c-2b-6 bullets under DB-DEP-005.

As built in V1-056 sub-slice 10e-2c (migration `20261128_124`): the first correction that links a
row is a `DEPOSIT_RECEIPT_CORRECTION` forfeiting a right receipt's money on the termination's
ground (DB-SETTLE-005 `deposit_disposition_id`), through the internal
`app.write_correction_deposit_forfeiture`; the row's `occurred_at` is after the new receipt (its
disposition context keeps the default `recorded_at`, the start of the confirm's statement), and
every insert check above runs; see the 10e-2c note under DB-SETTLE-005.

As built in V1-056 sub-slice 10e-2d (migration `20261223_149`): such a forfeiture takes only the
new money beyond the Pet Deposit's pay-back count, and the count holds only returned money the
Customer has not received yet (owner answers (a) to Q-2026-10-12-93 and (b) to Q-2026-10-17-122);
see the 10e-2d bullet under DB-DEP-005 and the 10e-2d note under DB-SETTLE-005.

As built in V1-056 sub-slice 10e-2b-4a (migration `20261225_151`): what a charge recovers of a
Pet Refund-review Refund adds to that count like a verified return (owner answer (a) to
Q-2026-10-17-123), so such a forfeiture takes less; see the 10e-2b-4a bullet under DB-DEP-005.

As built in V1-056 sub-slice 10e-2b-4b-1 (migration `20261226_152`): a recovery counts only while
its charge stands (owner answer (a) to Q-2026-10-17-125), so a forgiven recovery charge lets such a
forfeiture take more again; see the 10e-2b-4b-1 bullet under DB-DEP-005.

As built in V1-056 sub-slice 10e-2b-4b-2a (migration `20261227_153`): a forgiven recovery charge is
not restored while a forfeiture that relied on the lower count is active (owner answer (a) to
Q-2026-10-17-126); see the 10e-2b-4b-2a bullet under DB-DEP-005.

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
  Deposit, are refused (as amended by sub-slice 10c-2a-1: only while the application is not
  reversed, DB-DEP-006; and by sub-slice 10c-2a-3, owner answer to Q-2026-10-07-46: an Invoice
  Adjustment linked to a post-settlement correction of its Invoice's own Settlement, confirmed
  in the same transaction by that correction's approver under `financial.approve`, passes; every
  unlinked Adjustment stays refused; and by sub-slice 10c-3b-2, owner answer 1 to
  Q-2026-10-09-66: a Late-payment Charge correction linked to a post-settlement correction of its
  Charge's own Settlement, confirmed in the same transaction by that correction's approver under
  `financial.approve`, passes the same way; every unlinked Charge correction stays refused). The
  writer refuses an unknown target, and the writer and the
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
- As built in V1-056 sub-slice 10c-2b-5 (migration `20261123_119`; owner answer pay back to
  Q-2026-10-09-61, (a) to Q-2026-10-10-73, (A) and (b) to Q-2026-10-10-75, (a) to
  Q-2026-10-10-76): money of a Pet Refund-review Refund (DL-053) that comes back to the Pet
  Deposit is the Customer's pay-back money, whether the return was verified before or after the
  termination. The internal `app.lease_deposit_payback_count(deposit)` is a running count over
  the Pet Deposit's history: a verified return of a Pet Refund-review Refund adds what came back;
  a reversal of such a return and every Pet Refund-review Refund take it out first (never below
  0); a Settlement or correction Refund, its return and a `RECOVERED_BY_CHARGE` recovery do not
  count. `app.lease_deposit_payback_value(deposit)` is the smaller of that count and what the
  Deposit holds (0 for a Security Deposit, never NULL). The path gains the key
  `payback_usd_cents` (so the Settlement preview shows it), and a Deposit with a forfeiture
  ground whose held money is above 0 and all pay-back money is `DL_032`, also while its
  forfeiture stays active; `FORFEITURE_REQUIRED` only while it holds money beyond the pay-back
  value. Every reader of the path then applies and refunds that money as DL-032 value before and
  after closure (BR-SETTLE-008), with no change of its own. Approved tightening (Q-73 (a)): the
  Lease forfeiture source `app.lease_deposit_forfeiture_source` forfeits only the held money
  beyond the pay-back value and refuses (22023, "The Deposit holds nothing to forfeit") when
  nothing is beyond it; the disposition insert check is unchanged (up to the held value), and the
  one-call disposition stays owner-only (slice 6). None of the three new functions has a grant.
  `payback_usd_cents` changes the path only for a Deposit with a forfeiture ground; for a Pet
  Deposit with no ground or with every forfeiture reversed it is shown but has no effect (the
  path is `DL_032` anyway). Invariant the rule rests on: no money other than pay-back money
  reaches a Pet Deposit with an active forfeiture (today only returns of pay-back Refunds,
  reversals of applications of DL-032 money and forfeiture reversals can add money there); a
  later writer that adds other money to such a Deposit (for example sub-slices 10e-3, 10h and a
  Pet Deposit receipt writer such as the proposed 10e-2b, which would make a
  `RECOVERED_BY_CHARGE` row on a Pet Deposit possible) must keep it, or the count would class
  that money as pay-back money.
- As built in V1-056 sub-slice 10c-2b-6 (migration `20261125_121`; owner answer (a) to
  Q-2026-10-10-73 and owner answer 4 of 2026-10-12, an approved tightening): the Lease Deposit
  disposition insert check `app.validate_lease_deposit_disposition()` (DB-DEP-004) takes the
  same pay-back limit as the forfeiture source, so no writer, the owner-only one-call disposition
  included, forfeits returned pay-back money. After the held-value check (unchanged, still first:
  23514, "Lease Deposit disposition exceeds held refundable value") it refuses an amount above the
  held value less `app.lease_deposit_payback_value(deposit)` (23514, "Lease Deposit disposition
  would forfeit returned pay-back money"). The sentence above that the disposition insert check
  is unchanged held until this sub-slice. Only the check is patched in place; the forfeiture draft
  path is unchanged, because its source already takes exactly that amount.
- As amended in V1-056 sub-slice 10e-2d (migration `20261223_149`; owner answer (b) to
  Q-2026-10-17-122): the pay-back count holds only returned money the Customer has not received
  yet; money already paid out is not paid back again; one rule on every path. The new internal
  `app.lease_deposit_payback_count_as(deposit, returned_refund, returned_amount, without_payouts)`
  (no grant) is the 10c-2b-5 running count with one more kind of event: every payout of the
  Deposit that is not undone takes pay-back money out first, in the same time order (at the same
  moment returns come first): each Deposit application not reversed (only the Final Settlement and
  its corrections write them) and each Refund of the Deposit other than a Pet Refund-review Refund,
  less what came back to the Deposit for it (its Refund corrections' source effect: verified
  returns net of their reversals, and a `RECOVERED_BY_CHARGE` recovery, which charges the money
  back). So a returned Settlement Refund puts its pay-back part back. Forfeitures and their
  reversals are not payouts. Pet Refund-review Refunds and their returns, return reversals and
  recoveries count exactly as before. `returned_refund` and `returned_amount` count a return about
  to be written (a Pet Refund-review Refund's at the end, as before; another Refund's lowers its net
  payout); `without_payouts` leaves every payout out. `app.lease_deposit_payback_count(deposit)`
  now returns `app.lease_deposit_payback_count_as(deposit,NULL,0,false)`, and
  `app.lease_deposit_payback_after_return` uses the new function with the Refund and the amount;
  the pay-back value, the Deposit path (and its `payback_usd_cents`), the forfeiture source, the
  disposition insert check above and the receipt correction's forfeiture list follow it unchanged.
  Where nothing was paid out every result is as before. The 10c-2b-5 sentence that a Settlement or
  correction Refund, its return and a `RECOVERED_BY_CHARGE` recovery do not count held until this
  sub-slice.
- As amended in V1-056 sub-slice 10e-2b-4a (migration `20261225_151`; owner answer (a) to
  Q-2026-10-17-123): what a charge recovers of a Pet Refund-review Refund counts like a verified
  return of that Refund, so the Customer never both pays money back and loses it to a forfeiture.
  The Pet Refund-review part of `app.lease_deposit_payback_count_as` also adds each
  `RECOVERED_BY_CHARGE` row of such a Refund (the amount charged back; such a row is never
  reversed). With `without_payouts` (used only for a receipt correction's own corrected Deposit,
  by its targets and by the plan check) the count also adds, at the end, what is still to recover
  of each Pet Refund-review Refund of the Deposit (`app.refund_net_value_at(refund,'infinity')`,
  less a return about to be written, never below 0): that correction recovers by a charge every
  Refund of the Deposit that is not fully returned, after every other event of the Deposit, so the
  count it records equals the count its forfeiture writer and step read after its writes. The
  sentence above that Pet Refund-review recoveries count exactly as before held until this
  sub-slice. At the same moment and event order an addition to the count now comes before a
  subtraction (the "returns come first" rule), because a return reversal's charge-back of a
  returned Refund can be dated at the same instant as the return's `CORRECTION_REVERSAL`; so the
  result never depends on the random row ids. One exact-text patch; the functions that read the
  count follow it unchanged. Known limit (Q-2026-10-17-125): the count reads the recovery row,
  not whether its recovery charge still stands. (Ended by sub-slice 10e-2b-4b-1, below.)
- As amended in V1-056 sub-slice 10e-2b-4b-1 (migration `20261226_152`; owner answer (a) to
  Q-2026-10-17-125): a recovery counts as money that came back only while its charge stands. New
  internal `app.refund_recovery_standing_at(recovery, as_of)` (no grant): the least of the
  recovered amount and the adjusted obligation (never below 0) of each line of the recovery's
  charge (its `recovery_obligation_id`) on an Invoice issued by then and not VOID by then; a VOID
  Invoice with no void event counts as VOID at every time (fail closed); paid or unpaid, a charge
  that stands counts; a later credit forgives a DEBIT Adjustment of the line first. The Pet
  Refund-review part of `app.lease_deposit_payback_count_as` counts each recovery at its own time
  by what stands of its charge now (`'infinity'`), and another Refund's payout is undone by its
  recovery only as far as the charge stands now, from the Refund's time (sub-slice 10e-2d): one
  rule for both, as the answer says. A credit Adjustment, a `CHARGE_REDUCTION` or `REFUND`
  correction's linked Adjustment or a VOID makes the recovery count as if it had been that much
  smaller; an Adjustment reversal, a later DEBIT Adjustment of its line or the same charge billed again
  and issued makes it count again exactly as before, whatever was paid out in between (review round 1, both reviewers: the first
  build placed a forgiveness and a restoration at their own times, and the count's floor at 0
  then swallowed a forgiveness after a payout and added the restoration in full). The receipt
  correction's own-Deposit term (what is still to recover) is unchanged: a forgiven recovery
  leaves the Refund's net at 0, so that correction does not charge it back again. A receipt
  correction draft recorded before a forgiveness or a restoration is stale at its confirm (P5S02)
  when its forfeitures or its source change (the forfeitures are computed again under the locks);
  otherwise it confirms under the new count. One exact-text patch (two replacements);
  the functions that read the count follow it unchanged. With this rule a receipt correction of a
  Pet receipt can again forfeit the corrected receipt's own Pet Deposit on the termination ground
  (a forgiven review recovery lowers the count without changing what the Deposit paid). Known
  limit (Q-2026-10-17-126): a restoration after a forfeiture that the lower count allowed is not
  refused. (Ended by sub-slice 10e-2b-4b-2a, below.)
- As amended in V1-056 sub-slice 10e-2b-4b-2a (migration `20261227_153`; owner answer (a) to
  Q-2026-10-17-126 point 1): restoring a forgiven recovery charge is refused (55000, "A forfeiture
  recorded while this recovery charge was forgiven is still active; reverse the forfeiture first")
  while a forfeiture of the recovered Refund's Pet Deposit that relied on the lower count is
  active (not reversed); staff first reverse that forfeiture (the 6b draft before closure, a
  `FORFEITURE_REVERSAL` correction after it), then restore the charge. A restoration is a DEBIT
  Adjustment of the charge's line, the reversal of a credit Adjustment of that line (the 10f-1
  draft, the 10f-2 correction) or the same charge billed again and issued after a VOID: a DEBIT or a
  credit's reversal always, an issue only when another Invoice of the same obligation exists (the
  recovery's own charge is its obligation's first Invoice; a structural rule, review round 1). A
  forfeiture relied on the lower count when it was recorded at or after the charge's first issue,
  at a time when the charge stood lower than it stands after the restoration
  (`app.refund_recovery_standing_at` at the forfeiture's time against `'infinity'`); one recorded
  before the forgiveness never blocks, and a forgiveness stays open. New internal
  `app.refuse_recovery_charge_restoration(obligation)` and trigger function
  `app.validate_recovery_charge_restoration()` (no grant) and four deferred constraint triggers:
  `invoice_adjustments_recovery_restoration` (AFTER INSERT, DEBIT),
  `invoice_adjustment_reversals_recovery_restoration` (AFTER INSERT, the reversal of a credit
  Adjustment), `invoices_recovery_restoration_insert` (AFTER INSERT of an issued Invoice; every
  Invoice starts as a DRAFT today, so a defensive check) and `invoices_recovery_restoration_issue`
  (AFTER UPDATE OF `issued_at` when it becomes issued), so a recovery charge with no Lease is
  covered too. Every restoring writer runs `SET CONSTRAINTS ALL IMMEDIATE`, so the check runs
  inside that writer, which keeps its locks to commit: it takes `app.serialize_deposit_state` of
  the Pet Deposit (the lock every forfeiture insert takes through the Deposit balance event
  trigger) and then reads the forfeitures; a forfeiture timed at or after the restoring
  transaction's start committed while that transaction ran, so it counts as relying (fail
  closed). A forfeiture is timed by its statement's start, before it waits for the Deposit lock
  and reads the count, and a forgiveness takes no Deposit lock (review round 1): the new AFTER
  INSERT trigger `deposit_dispositions_recovery_standing` (function
  `app.validate_forfeiture_recovery_standing()`, no grant) refuses a Lease Deposit forfeiture of a
  Pet Deposit when a recovery charge of that Deposit stands lower now than at the forfeiture's
  time (a forgiveness dated after it is already visible) or was first issued after that time (a
  charge chained ahead of the clock, review round 2) (40001, "A recovery charge of this Pet
  Deposit changed after this forfeiture's time; record it again"), so the restoration check can
  trust the forfeiture's time. A narrower test (only a forfeiture that needed the lower
  count) would need the count at the forfeiture's time, which the count does not keep. The
  services show the refusal as a generic invalid command or conflict; slice 11 words it for staff.
- As built in V1-056 sub-slice 10c-2a-2 (migration `20261106_102`; owner answer 1 to
  Q-2026-10-07-41): after closure a Deposit application is still refused unless it is linked
  (DB-SETTLE-005 `deposit_application_id`, written first) to a post-settlement correction of its
  Settlement confirmed in the same transaction, written by that correction's approver, not before
  the correction, before any Refund of the same correction, and matching a Deposit step of that
  correction's plan (Deposit, stage, target and amount), each step at most once (a relaxing
  change; 23514 or 55000 otherwise). Such an application's `application_order` still follows the Settlement's last
  number, and its stage order is checked within that correction. Every other check stays (the
  DL-032 path, pet damage for the first Pet stage, the target's balance, the held balance and the
  chronology). The only writer is the shared DL-032 step of the correction
  (`app.post_settlement_correction_plan`, DB-SETTLE-005), through `app.post_deposit_application`.

## DB-DEP-006 — `deposit_application_reversals`

Built in V1-056 sub-slice 10c-2a-1 (owner answer 2 to Q-2026-10-06-36, which replaced plan Q15).

Append-only: `id uuid PK`, `deposit_application_id uuid NOT NULL UNIQUE FK`, `reason text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`, `authorization_reference text NOT NULL`.

- As built in V1-056 sub-slice 10c-2a-1 (migration `20261105_101`): `reason` is 1 to 1,000
  characters (as the application's), `actor_id` refers to a user account and
  `authorization_reference` is always `financial.approve`. No role may read or write the table; no
  UPDATE, DELETE or TRUNCATE. A BEFORE INSERT check (23514) needs the reversal linked
  (DB-SETTLE-005 `deposit_application_reversal_id`, written first) to a post-settlement correction
  of the application's Settlement confirmed in the same transaction, the correction's approver as
  `actor_id`, and `occurred_at` not before the closure or the correction and later than the latest
  event of the target and of the Deposit, not later than the clock plus 5 seconds; there is no
  other time limit. It locks the Deposit, then the Invoice or Late-payment Charge, as the Deposit
  application does; the reason follows the application's rule (22023 otherwise). At commit a
  deferred trigger refreshes the reversed line's Invoice status and version, as the application's
  own trigger does. One reversal per application: a partial
  release reverses the whole application, and the rest is a plain open obligation that only the
  correction's plan pays again, through the shared DL-032 step (sub-slice 10c-2a-2): by the
  Customer's Credit first when that Customer has Credit (Credit before Deposits), otherwise by a
  Deposit step.
  Once every Deposit application of a Deposit is reversed, `app.deposit_has_active_application`
  is false, so a receipt reversal draft of that Deposit is no longer held back by it (still a
  draft confirmed by `financial.approve`, 8r).
  Every reader counts only applications not reversed (DB-DER-004 held balance, the Invoice line
  value paid by Deposits as of a time, the Late-payment Charge application summary, the 8a-1
  refusal of changes to a Deposit-paid obligation); the latest event time of an allocation target
  counts the reversal. The Customer Ledger shows it as `DEPOSIT_APPLICATION_REVERSED`
  (DB-DER-010), and the Deposit history reads it through the bounded
  `app.deposit_application_reversal_history(property, deposit)` (runtime EXECUTE only). Writers:
  the Invoice-line `REFUND` confirm (sub-slice 10c-2a-3), the pet classification correction
  confirm (sub-slice 10c-2a-5) and the Late-payment Charge `REFUND` confirm (sub-slice 10c-3b-2);
  later correction writers (10e) will write it too. Since sub-slice 10e-1b the `RETURNED_PAYMENT`
  correction also writes it for every Deposit application of a Deposit the returned Payment funded
  (DB-PAY-009). Since sub-slice 10e-2 both the `RETURNED_PAYMENT` and the
  `DEPOSIT_RECEIPT_CORRECTION` corrections write it through the shared internal writer
  `app.write_correction_deposit_application_reversals` (the same rows, newest first).

## DB-DEP-007 — `deposit_receipt_reversals`

Append-only: `id uuid PK`, `deposit_receipt_id uuid NOT NULL UNIQUE FK`, `reason text
NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`,
`authorization_reference text NOT NULL`. Posting is prohibited while any dependent
Deposit disposition, application, or Refund remains active (the Refund part is narrowed by the
returns and corrections notes below and by sub-slice 10e-2b-4e-2b-3). It removes the receipt's
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

Since V1-056 sub-slice 10e-1b (migration `20261121_117`, DB-PAY-009): the `RETURNED_PAYMENT`
post-settlement correction writes the receipt reversal of every receipt of the returned Payment
itself, linked (DB-SETTLE-005 `deposit_receipt_reversal_id`), with the approver as actor,
`deposits.correct`, the same command record and `deposit.receipt.reversed` audit event, and a
time after the Deposit application reversals; the BEFORE INSERT check of this table still runs.
The audit event keeps the statement time, so it is dated before its row: read it through the link,
not by time.

Since V1-056 sub-slice 10e-1c (migration `20261122_118`): that receipt reversal is written by the
shared internal writer `app.write_payment_return_receipt_reversal` (the same records, command record
and audit event), which also checks that the receipt's Deposit belongs to the return's Property
(P0002) and that the reason is not blank (22023); the state checks stay the BEFORE INSERT check of
this table (owner check of 2026-10-11). The `PAYMENT_RETURN` confirm (DB-PAY-009) uses the same
writer for the receipt of a Deposit whose Refund it recovered, so the reversal is dated after the
recovery; its other receipts still go through the receipt reversal function.

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

As built in V1-056 sub-slice 10c-2b-2a (migration `20261112_108`; owner answer 5 to
Q-2026-10-08-55 and the answer to Q-2026-10-08-56, approved tightening): once the Lease's Final
Settlement is closed, the receipt reversal draft of that Lease's Deposit is refused at record and
a receipt reversal row is refused at insert (P5S01, a conflict) unless it is linked to a correction
of that Settlement confirmed in the same transaction. A receipt whose Payment bounced is fixed by
`RETURNED_PAYMENT` (10e); a receipt that is wrong while its Payment is real by
`DEPOSIT_RECEIPT_CORRECTION` (10e-2); until those exist such a receipt has no fix after closure
(both exist since sub-slices 10e-1b and 10e-2; the right receipt waits for sub-slice 10e-2b).
After review round 1 (owner answers 1 and 4 to Q-2026-10-08-59, approved tightenings): a receipt
reversal draft is recorded only at READ COMMITTED (55000); and once a Lease's Final Settlement is
closed, a Lease Deposit forfeiture draft is refused at record and a `deposit_dispositions` row at
insert (P5S01) unless a correction of that Settlement links it (no correction kind links a
forfeiture yet).
As built in V1-056 sub-slice 10c-2b-2b (migration `20261113_109`; owner answer to
Q-2026-10-08-60, an approved tightening): a Lease Deposit forfeiture draft is recorded only at
READ COMMITTED (55000), so its closure read sees every committed closure; an exact repeat of an
earlier request replays its draft before this check, as the receipt reversal recorder does.

As built in V1-056 sub-slice 10e-2 (migration `20261124_120`; owner answer (a) to Q-2026-10-08-56,
answers 1 and 3 to Q-2026-10-11-83, answer (a) to Q-2026-10-11-86): a Lease Deposit receipt that
is wrong while its Payment is real is fixed after closure by the `DEPOSIT_RECEIPT_CORRECTION`
variant of the `SETTLEMENT_CORRECTION` draft (`final_settlements.prepare` records,
`financial.approve` confirms). As linked records it recovers each Refund paid from the Deposit that
is not fully returned (a `RECOVERED_BY_CHARGE` row of DB-REFUND-002 and a charge of the exact net
amount to the person who received it, whose recovery check now also accepts this correction),
reverses the Deposit's applications newest first and then writes this table's row through the
shared writer `app.write_payment_return_receipt_reversal`; the Deposit ends empty. The freed amount
stays unallocated with the Payment (BR-CREDIT-002: Credit only with the payer's authorization);
there is no Payment reversal and no DL-032 step (without right receipts; see the sub-slice 10e-2b-1
paragraph under DB-SETTLE-005). Refused (55000): a receipt already reversed, of a
Deposit of another Lease, or of a Deposit with an active forfeiture (a `FORFEITURE_REVERSAL` first),
a Payment that is not RECEIVED (a guard), a Deposit application of another Final Settlement (a
guard), the 10e-1c recovery refusals, a Refund of the Deposit with no planned recovery, a Deposit
that would not end empty, and a waiting draft naming the receipt, the Deposit, its Payment or a
recovered Refund. **Known gap until sub-slice 10e-2b
(Q-2026-10-12-87):** no correction yet writes the right receipt (the right Deposit or amount).

As built in V1-056 sub-slice 8c (migration `20261025_90`, owner answer 4 to Q-2026-10-05-23):
both directions also see the Final Settlement draft. A pending `FINAL_SETTLEMENT` draft whose
payload lists the Deposit in `deposit_ids` (the Deposits it applies or refunds) refuses a new
receipt reversal draft of that Deposit and, through the receipt reversal guard, the reversal
itself; the decision trigger refuses the confirmation of such a Settlement draft while a receipt
reversal draft of one of its Deposits is pending. A receipt reversal draft that is already
pending blocks the recording of the Settlement draft through the preview's `PENDING_DRAFT`
issue. The Settlement draft recorder locks the Lease's Deposit rows in a fixed order after the
same per-Deposit advisory lock, so each recorder waits for the other and then sees its draft.

Since V1-056 sub-slice 10e-2b-4e-1 (migration `20261231_157`; owner answer (a) to
Q-2026-10-18-127): the refusal of a receipt reversal while the Deposit has a Refund that is not
fully returned is skipped only when `app.payment_return_shared_receipt_reversal_allowed` holds: a
confirmed `PAYMENT_RETURN` of this transaction (no correction) returns the receipt's Payment, and
another Payment has an active receipt in the Deposit. The active-forfeiture, active-application
and waiting-draft refusals, the closed-Settlement refusal and the held-history check stay, so the
return can reverse that receipt only when the Deposit then holds 0 or more (DB-REFUND-002 note).

Since V1-056 sub-slice 10e-2b-4e-2a (migration `20270101_158`; owner answers (a) to
Q-2026-10-18-134): after closure the `RETURNED_PAYMENT` correction of a shared Deposit (another
Payment also has an active receipt in it) gives back only the Deposit's shortfall (the returned
Payment's active receipt less what the Deposit holds, never below 0) from its uses still in force,
newest first (by time; a Refund before an application before a forfeiture at the same moment;
then the later application order; then id): a Refund that is not fully returned by a recovery
charge to its recipient (DB-REFUND-002), a Deposit application by its reversal with its kept part
written again as a new Deposit application of the same Deposit, stage and target, linked to the
correction (DB-SETTLE-005 `deposit_application_id`), and a forfeiture by its reversal with its kept
part forfeited again, linked (`deposit_disposition_id`). The plan is part of the draft's source
(`shared_deposits`, built by `app.settlement_returned_payment_shared(property, payment, source)`),
so its digest covers it; a `RETURNED_PAYMENT` draft recorded before this migration is stale at its
confirm (P5S02). This receipt reversal then skips the unresolved-Refund, active-forfeiture and
active-application refusals, but only for the return of the correction that links the reversal
and whose plan lists the Deposit; the held-history check stays. Refused (55000): an application's
kept part beside a forfeiture of that Deposit that stays active (a kept Deposit is never applied;
a known limit), and, until the owner answers Q-2026-10-18-135, a plan that charges back or reverses
a Refund or application of a Deposit with pay-back history (also when already paid out), or that
would end holding less than the Customer's pay-back count, while a forfeiture of it stays active
(also checked after the writes). The receipt correction of a shared Deposit is
sub-slice 10e-2b-4e-2b.

Since V1-056 sub-slice 10e-2b-4e-2b-1 (migration `20270102_159`; owner answer (a) to
Q-2026-10-18-135): a shared Deposit with the Customer's pay-back money beside an active
forfeiture (a pay-back count without payouts above 0, the condition of the refusal above) gives
back from its forfeitures first (newest first among them; the Property keeps less; nobody is
charged), and only the rest of its shortfall comes newest first from its Refunds and Deposit
applications. The forfeitures give back the least of what they keep and the returned receipt less
the held value plus the pay-back count with payouts, so no forfeiture that stays active keeps the
pay-back money: while a forfeiture stays active the Deposit ends holding at least that count (it
can give back more than the shortfall, for example 5,000 of a 6,000 forfeiture for a 1,000
shortfall when the Deposit held 4,000 of pay-back money, which it keeps); a forfeiture never gives
back more than it keeps. The plan's total is the greater of that part and the shortfall; every
other shared Deposit gives back exactly its shortfall as before. Each `shared_deposits` entry gains
`give_back_usd_cents`, `payback_first` and `payback_usd_cents` (so a `RETURNED_PAYMENT` draft
recorded before this migration whose Payment funded a shared Deposit is stale at its confirm,
P5S02). The record check takes exactly one plan entry per shared Deposit, and only for a shared
Deposit of the source; it reads the returned Payment's receipt and the held value live and
requires the entry's to equal them, requires a Deposit that is not plain to give back nothing,
and compares the entry's total with the total the rule gives on the live state (the receipt, the
held value, the active forfeitures and both pay-back counts, with the entry's own `plain` flag)
and with its give-backs; anything else is refused (55000, "A Deposit this Payment funded would
still hold money after the return"). The pay-back refusal above stays as defence in depth: no source the
database builds reaches it (a Deposit that is not plain is refused earlier by the Reservation
outcome refusal; a plain Deposit's total keeps the end held at or above the count while a
forfeiture stays); a hand-built source can still reach its end-held branch, which reads the
plan's total (a forfeiture list the database does not hold, or an entry marked not plain with no
uses), and is refused (fail closed). The receipt correction of a
shared Deposit and the end of option (d) are sub-slice 10e-2b-4e-2b-2 (built as 10e-2b-4e-2b-2a
and 10e-2b-4e-2b-2b).

Since V1-056 sub-slice 10e-2b-4e-2b-2a (migration `20270103_160`; owner answer (a) to
Q-2026-10-18-127 and answers (a) to Q-2026-10-18-134): the receipt correction
(`DEPOSIT_RECEIPT_CORRECTION`) of a receipt whose Deposit also holds another Payment's active
receipt gives back only that Deposit's shortfall (the corrected receipt less what the Deposit
holds, never below 0), newest first, from its Refunds that are not fully returned (a recovery
charge of the share to the recipient) and its active Deposit applications (reversed, the kept part
written again, linked), then reverses the receipt; the Deposit then holds only the other Payments'
money. Its source gains the shared planner's recoveries and its one `shared_deposits` entry
(`app.settlement_deposit_receipt_correction_shared(property, source)`); a one-Payment Deposit's
source and digest are unchanged. The record check requires exactly one entry, for the corrected
receipt's Deposit, whose give-backs total the shortfall on the live state (the receipt and the held
value read live; only Refunds and applications; a Deposit that is not plain gives back nothing);
otherwise 55000 ("The Deposit would not end holding only the other Payments' money after this
receipt correction"). An active forfeiture stays refused (staff reverse it with a
`FORFEITURE_REVERSAL` correction first). The shortfall recovery amount and the shared receipt
reversal check accept this correction too, bound to the correction that links the record,
confirmed in this transaction, whose stored source lists the Deposit (the reversal only of that
correction's own receipt, and never beside an active forfeiture); the kept-part check accepts that
correction's listed kept part (the Deposit application check requires the correction to be
confirmed in this transaction). Known limits (fail closed, 55000): with right receipts, a shared
Deposit that would still hold money after the correction (staff first pay it out with a
`HELD_VALUE_REFUND` correction), a right receipt into a shared Deposit with a pay-back count, a
plan Deposit step whose DL-032 stage comes before a kept application part, a plan Deposit step
equal to a kept part (the same Deposit, stage, target and amount; staff split the step), and a
plan Customer Credit step beside a kept part (staff first refund or apply the Customer's Credit,
or correct the receipt without new receipts); the last three are refused at record time, because the Deposit
application check keeps the stage order within a correction and would count an equal step as the
kept part, and the correction's Credit order check refuses Credit after its Deposit applications.
The end of option (d) is sub-slice 10e-2b-4e-2b-2b (migration `20270104_161`, DB-DEP-002).

Since V1-056 sub-slice 10e-2b-4e-2b-3 (migration `20270105_162`; owner answer (a) to
Q-2026-10-19-137): the refusal of a receipt reversal while the Deposit has a Refund that is not
fully returned is also skipped, in `app.reverse_deposit_receipt` and in this table's insert check,
for the two-person 8r reversal of a receipt, recorded strictly after every such Refund, whose
money no later balance event relied on (`app.deposit_receipt_reversal_after_refund_allowed`; the rule
and its conditions are in DB-DEP-002). The other refusals of the first paragraph stay.

## DB-DEP-008 — `deposit_disposition_reversals`

Append-only: `id uuid PK`, `deposit_disposition_id uuid NOT NULL UNIQUE FK`, `reason
text NOT NULL`, `occurred_at timestamptz NOT NULL`, `actor_id uuid NOT NULL`,
`authorization_reference text NOT NULL`. It restores the disposition's derived held
balance effect and never rewrites the original event.

As built in V1-056 sub-slice 10d: after the Lease's Final Settlement is closed, a reversal is
also written by a `FORFEITURE_REVERSAL` post-settlement correction (DB-SETTLE-005 link
`deposit_disposition_reversal_id`), with the correction's approver as actor and `deposits.correct`
as the reference, as the 6b draft confirm writes it; the authority is the linked correction
(`final_settlements.prepare` prepares, `financial.approve` confirms). Until sub-slice 10h the 6b
draft can still reverse a closed Settlement's forfeiture without the correction. Since sub-slice
10e-1b the `RETURNED_PAYMENT` correction writes it the same way for every active forfeiture of a
Deposit the returned Payment funded (owner answer (a) to Q-2026-10-10-72 point 2; DB-PAY-009).

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

Amended by V1-056 sub-slice 10c-2a-4 (migration `20261108_104`; owner answers to
Q-2026-10-07-44, Q-2026-10-08-49 and Q-2026-10-08-51): once the Lease's Final Settlement
is closed, a command or row with `supersedes_inspection_id` is refused with P5S01 before
anything is written. Both `app.move_out_inspection_record` and the insert trigger
`app.validate_move_out_inspection_source` read the Lease's `final_settlements` row
`FOR SHARE` after the Lease row lock (the confirm, the only writer of `closed_at`, locks
the Lease row `FOR UPDATE` before it closes the Settlement), so a supersede that waited
while the Settlement closed reads the closure. A supersede runs only at READ COMMITTED
(55000 otherwise, before and after closure), as the Settlement confirm and the correction
confirms require: a REPEATABLE READ or SERIALIZABLE snapshot older than the Settlement's
start would not see the Settlement row, and the Lease row lock raises nothing because the
start and the confirm never change that row. An inspection that supersedes
nothing is not checked: damage found after closure is a new inspection, and every
inspection that no other inspection supersedes stays current. The exact-repeat replay
stays first and writes nothing. The service maps P5S01 to a conflict. Known limit: an
inspection recorded after closure cannot be superseded either.

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
a Settlement Customer's Credit or Payment, or an allocation or target Invoice of the Lease, and,
since V1-056 sub-slice 10h-3 (migration `20270111_168`; owner answer (a) to Q-2026-10-17-120
point 3), for another Lease's waiting `SETTLEMENT_CORRECTION` draft of the variant `PAYMENT_MOVE`
whose correct Invoice is an Invoice of the Lease, a waiting `PAYMENT_RETURN` draft, or another
Settlement's waiting `SETTLEMENT_CORRECTION` draft of the variant `RETURNED_PAYMENT`, whose
Payment has an active allocation on an obligation of the Lease, an active Customer Credit held by
a Settlement Customer (with money left or not; fail closed), an active application of one of its
Credits on such an obligation or an active receipt into a Deposit of the Lease, and a waiting
`ADJUSTMENT_REVERSAL` draft of an
Adjustment on an Invoice of the Lease (its draft id, kind and variant only for a
`financial.approve` holder or a holder of the draft's prepare capability). Because every
post-settlement correction plan runs the same preview, such a waiting draft on a closed Lease's
sources also refuses that Settlement's correction steps (55000) until it is confirmed, rejected
or withdrawn (a Settlement's own `RETURNED_PAYMENT` correction draft is not listed for it);
since V1-056 sub-slice 10h-4a (migration `20270112_169`; owner answer 2 of 2026-10-20 to the
10h-3 report) also another Settlement's waiting `SETTLEMENT_CORRECTION` draft of the variant
`HELD_VALUE_REFUND` whose `customer_credit_id` is a Credit held by a Settlement Customer (a
Deposit held-value draft names no Credit and is not listed; a Settlement's own held-value draft
is not listed for it); since V1-056 sub-slice 10i-4c (migration `20270117_174`; owner answer (a)
to Q-2026-10-20-146) also another Settlement's waiting `SETTLEMENT_CORRECTION` draft of any
variant whose plan (`payload->'plan'->'steps'`, read only when an array) has a `CUSTOMER_CREDIT`
step on a Credit held by a Settlement Customer, or of the variant `REFUND` whose plan overlay
(`payload->'plan_overlay'->'credits'`, read only when an object) has a key that is such a Credit
(a released Payment allocation is keyed by its allocation and is not listed);
`ONE_TIME_CHARGE_NOT_INVOICED` for a one-time charge source of the Lease on
no DRAFT or issued, non-VOID Invoice that is still waiting to be billed (not one whose Invoice was
VOIDed and not one a draft correction replaced, read from `app.invoice_draft_revision_events`;
owner answer to Q-2026-10-05-27); `INVOICE_DRAFT_NOT_ISSUED` for an Invoice draft of the Lease.
`ready` is true when no blocking issue exists (owner answers to Q-2026-10-05-25). The key
`information` lists, without blocking, each one-time charge whose Invoice was VOIDed and that was
not billed again (`VOIDED_CHARGE_NOT_BILLED_AGAIN`, with its amount), so the approver sees it.
A VOIDed cleaning charge is listed there and still blocks through `CLEANING_CHARGE_MISSING`,
because the cleaning charge is required (BR-MOVEOUT-013) and a VOID lets it be billed again.
A Deposit counts as having a reversed forfeiture only through a disposition of its own Lease
(`governing_lease_id`); any active disposition still makes it `KEPT` (as amended by sub-slice
10c-2b-5: except when the Deposit holds money and every cent of it is pay-back money, which
follows `DL_032`).

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
Since V1-056 sub-slice 10h-4b (migration `20270113_170`; owner answer (a) to Q-2026-10-20-145
point 1) the function first refuses (55000, "An Invoice, Adjustment or Late-payment record is
written at READ COMMITTED") a write at any other isolation level, before any read and so before
every other trigger of these tables, on any row (also on a Lease with no Final Settlement and on
a row with no Lease): a snapshot older than a Settlement's start would not see the Settlement. No app path writes these tables at a
stricter level; the serialization guards of these tables still work for every READ COMMITTED
writer, which waits for the earlier writer's lock and is then refused.

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

As built in V1-056 sub-slice 10a (migration `20261101_97`; owner answers to Q-2026-10-06-36):
`correlation_id` is the `SETTLEMENT_CORRECTION` draft (unique, a foreign key to
`financial_drafts`), `authorization_reference` is `financial.approve` and `actor_id` the approver.
A BEFORE INSERT check needs the Settlement closed, `occurred_at` not before the closure and not
later than the clock plus 5 seconds (no time limit), the draft of the same Property under
`final_settlements.prepare` naming this Settlement with the same reason, and an active financial
actor. A deferred check lets a header commit only with its draft CONFIRMED by the same approver
under `financial.approve` in the same transaction (the decision carries the top-level transaction
id and was written after the transaction started; 42501 otherwise) and at least one effect. The
id is derived from the draft (`app.settlement_correction_id`). Only the internal `app.begin_settlement_correction` writes
a header (the decision first, then the header; 55000 while the Settlement is open). Append-only;
no application role may read or write the table (the backup role reads every table).

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

Amended by owner answer 2 to Q-2026-10-06-36 (2026-10-06): the links also include `invoice_id
uuid NULL FK` (an extra charge Invoice), `payment_reversal_id uuid NULL FK`,
`customer_credit_reversal_id uuid NULL FK`, `deposit_receipt_reversal_id uuid NULL FK` and
`deposit_application_id uuid NULL FK` (a Deposit application inside a correction, owner answer
4), and `deposit_application_reversal_id` refers to the new append-only table
`deposit_application_reversals`, written only by a correction.

As built in V1-056 sub-slice 10a (migration `20261101_97`): every link is a deferrable foreign key
(a writer links a record before it writes it) and unique (a record is the effect of at most one
correction); `CHECK (num_nonnulls(...)=1)`; an effect is accepted only for a correction confirmed
in the same transaction (its draft's CONFIRMED decision carries the top-level transaction id,
`pg_current_xact_id()`, and was written after the current transaction started); append-only; no
application role may read or write the table. The link `deposit_application_reversal_id` is added with its table in sub-slice 10c-2 (as built: sub-slice 10c-2a-1, migration `20261105_101`; deferrable, unique, inside the one-link check; the link functions are rebuilt with it). The context of each
linked record is checked by the variant writer that writes it (later sub-slices); whether a record
of another Lease may be linked (the correct Invoice of a wrong-Unit move, the other allocations of
a returned Payment) is answered below (owner answer 5 to Q-2026-10-06-37). The closed Settlement refusals of sub-slices 8e-1
and 8e-2 let a record through only when `app.settlement_correction_linked` finds it linked to a
correction of the same Settlement confirmed in the same transaction (an Invoice, an Adjustment, an
Adjustment reversal, a Late-payment Charge correction, a Settlement Credit application reversal);
VOID events, Late-payment Decisions and Charges and one-time charge records have no link and stay
refused (one-time charge records until sub-slice 10b, below).

Amended by owner answers 4 and 5 to Q-2026-10-06-37 (2026-10-07): the links also include
`authorized_nonrecurring_obligation_id uuid NULL FK` (the one-time charge record of an extra
charge, built in sub-slice 10b). Every record linked to a correction belongs to the Settlement's
Lease, with exactly two exceptions: the wrong-Unit move of a `PAYMENT_MOVE` correction may pay
another Lease's Invoice, and a returned Payment may reverse its own records on other Leases (its
allocations, Credit applications, Credits, Deposit receipts and its reversal). Neither exception
may change a record that another Lease's closed Settlement relied on, unless that change is also
a confirmed correction of that Settlement.

As built in V1-056 sub-slice 10b (migration `20261102_98`): the link
`authorized_nonrecurring_obligation_id` is a deferrable, unique foreign key like the others and
the one-link check covers it; the 8e-1 refusal lets a one-time charge record through when it is
linked that way. A deferred check refuses the commit while an Invoice linked to a correction is
not issued (23514; a positive check, so it also refuses when run before the Invoice is written).
The first variant writer is the `EXTRA_CHARGE` correction: Staff record a
`SETTLEMENT_CORRECTION` draft with `payload.variant` `EXTRA_CHARGE` under
`final_settlements.prepare` (`app.record_settlement_extra_charge_draft`; the reason is at most
500 characters because the one-time charge record keeps it); only a `financial.approve` holder
confirms it (`app.confirm_settlement_extra_charge`), which writes, linked in this order, a
Miscellaneous or Damage one-time charge record (authorized by the approver under
`financial.approve`, BR-INV-044) and its Invoice with the Lease and one line, issued in the
same call with the one-time charge Due Date (the issue date plus the Property's days, or the
override with its reason, never before the issue date). The Customer is the Customer of the
corrected Invoice when the draft names one (an issued, non-VOID Invoice of the Settlement's
Lease), otherwise the Primary Tenant; a Damage charge always goes to the Primary Tenant. A draft
whose sources changed (the closure, the Primary Tenant, the corrected Invoice, the finding) is
stale (P5S02) and stays pending. The confirm runs only at READ COMMITTED, locks the Lease row
after the Settlement draft lock, gives its records fresh ids (an exact repeat finds them through
the links) and never returns the decision's transaction id. The writer runs the deferred checks
inside itself (`SET CONSTRAINTS ALL IMMEDIATE`) once every linked record is written, as the
Invoice writers do. No Late-payment Charge follows: the 8e-1 refusal of Late-payment Decisions
stays.

As built in V1-056 sub-slice 10c-1a (migration `20261103_99`): the `CHARGE_REDUCTION` correction
removes a wrong charge that is still unpaid. Staff record a `SETTLEMENT_CORRECTION` draft with
`payload.variant` `CHARGE_REDUCTION` under `final_settlements.prepare`
(`app.record_settlement_charge_reduction_draft`: an issued, non-VOID Invoice of the Settlement's
Lease, one of its lines and an amount in cents of at most the line's unpaid rest; the reason is
at most 500 characters because the Adjustment keeps it); only a `financial.approve` holder
confirms it (`app.confirm_settlement_charge_reduction`), which writes, linked
(`invoice_adjustment_id`), a credit Adjustment of that line authorized by the approver under
`financial.approve`, with `source_reference` `settlement-correction:<correction id>`; the
Adjustment follows its Invoice's Customer (BR-INV-045). A reduction that would release paid
value is refused (a `REFUND` correction, sub-slice 10c-1b), and an Invoice that a Deposit
application paid stays refused (DB-DEP-005; sub-slice 10c-2; still refused after sub-slice
10c-2a-3, which corrects such an Invoice's lines only with a `REFUND`; since sub-slice 10c-3c-2
only a line that an active Deposit application paid and that has no unpaid rest). A draft whose line changed since it
was recorded (a Payment, a Credit, an Adjustment, the Invoice's issue state or Deposit
applications) is stale (P5S02) and stays pending. The confirm locks the Invoice before the
Settlement row (the order of the 8e-1 refusal), runs only at READ COMMITTED, gives the Adjustment
a fresh id, and its result never returns the decision's transaction id. The text
`settlement-correction:<correction id>` is a label, not a reserved key: an ordinary Adjustment of
an open Lease may carry the same text, so the link in this table, not the label, shows which
Adjustment a correction wrote.

As built in V1-056 sub-slice 10c-1b (migration `20261104_100`; owner answers to Q-2026-10-07-39):
the `REFUND` correction fixes a wrong charge that was paid. Staff record a
`SETTLEMENT_CORRECTION` draft with `payload.variant` `REFUND` under `final_settlements.prepare`
(`app.record_settlement_refund_draft`: an issued, non-VOID Invoice of the Settlement's Lease, one
of its lines, an amount in cents of at most the line's charge that releases paid value (otherwise
a `CHARGE_REDUCTION`), an active Refund method and a reference note of 1 to 500 characters; the
draft stores the sources it will release); only a `financial.approve` holder confirms it
(`app.confirm_settlement_refund`), which writes, each linked before it is written, the release of
the paid part in the order of the credit Adjustment excess (newest first: a Payment allocation is
reversed (`payment_allocation_reversal_id`), its unreleased rest re-posted
(`payment_allocation_id`) and the released value recognized as Customer Credit of the Invoice
Customer, BR-CREDIT-014; a Credit application is reversed (`credit_application_reversal_id`) and
its unreleased rest re-posted (`customer_credit_application_id`), so the value returns to its
Credit), the credit Adjustment (`invoice_adjustment_id`, authorized under `financial.approve`), and
one Credit Refund per released source (`refund_id`), paid to that Credit's Customer, with its row
in `settlement_correction_refund_details` (DB-REFUND-001). An unpaid part of the amount is removed
with it. The released Credits are not linked here: the Adjustment's
`invoice_credit_excess_releases` rows name them. A Settlement Credit application's reversal
passes the 8e-2 refusal because it is linked first; the reversal of a Credit application that
re-posts, directly or through earlier re-posts, the remainder of a Settlement Credit application
is refused (P5S01) unless it is linked to a correction of that Settlement confirmed in the same
transaction (approved tightening; such a row exists only through a correction). A draft whose
line or paying sources changed since it was recorded is stale (P5S02) and stays pending; a
Refund method deactivated after the draft is a conflict (55000). The confirm locks each source
Payment and then each source Credit in id order before the Invoice (the order of the allocation,
Credit and Refund writers; as amended by sub-slice 10c-2a-3: after the Lease row, all through the
step's lock function, below), runs only at READ COMMITTED and gives every record a fresh id. Its
`final_settlement.correction.confirmed` audit event names every released source, re-post,
released Credit and Refund. An Invoice that a Deposit application paid stays refused (sub-slice
10c-2; as amended by sub-slice 10c-2a-3: such a line is corrected, below).

As built in V1-056 sub-slice 10c-2a-2 (migration `20261106_102`; owner answers 1 and 3 to
Q-2026-10-07-41 and 1 and 2 to Q-2026-10-07-42): the shared DL-032 step after closure, for the
variants that release or hold Deposit value (10c-2a-3, 10c-2b, 10d); no variant uses it yet and no
role may call it. A correction draft that runs it keeps `plan` (the Settlement plan format of
DB-SETTLE-001's draft), `plan_overlay` (what the correction itself changes before the step: what
each obligation owes after the release, the value each released Credit gains, keyed by the Credit
or by the released Payment allocation, and the value each Deposit gets back) and `plan_result`.
The internal check `app.settlement_correction_plan_result` reads the closed Settlement as the
Settlement preview does, applies the overlay, refuses while a draft waits on a Settlement source,
and applies the Settlement plan rules plus three correction rules: when a Deposit holds money each
Customer's Credit pays that Customer's open debt first; a released Credit with value left needs its
Customer to owe nothing on the Lease; one Refund method, note, recipient and agreement. Inside its
correction, after the variant's release, `app.post_settlement_correction_plan` (READ COMMITTED,
under the step's locks) runs the check again on the real state, refuses a draft whose recorded
result differs in any field (P5S02), and writes the
Customer Credit applications, the Deposit applications and the Deposit Refunds, each linked to the
correction first with a fresh id. `app.lock_settlement_correction_plan` takes the step's locks in
the Settlement confirm's order, for a variant to call before `app.begin_settlement_correction`:
the draft and Settlement draft locks, the Lease row `FOR UPDATE` (the move-out inspection command
locks it too, so no inspection is superseded and no line stops being pet damage while the step
runs), the Credit steps' Payments and Credits, the Lease's Late-payment Charges and Invoices, the
Settlement row, then each Deposit's draft lock and row. Since sub-slice 10c-2a-6 (migration
`20261110_106`; owner answer 1 to Q-2026-10-08-52 and the answer to Q-2026-10-08-54), the step,
right after these locks and before it reads the plan and compares the result, also refuses (55000)
a `CUSTOMER_CHOICE` text for the remaining Pet Deposit that the confirmed Final Settlement or
another confirmed correction of the same Settlement recorded, for every variant that runs it; the
confirm rolls back and the draft stays pending.

As built in V1-056 sub-slice 10c-2a-3 (migration `20261107_103`; owner answers 1 and 2 to
Q-2026-10-07-41, 1 and 2 to Q-2026-10-07-42, 3 and 4 to Q-2026-10-07-44, and the answers to
Q-2026-10-07-46 and Q-2026-10-07-47): the `REFUND` correction of sub-slice 10c-1b also corrects a
line that a Deposit application paid, and every `REFUND` correction runs the shared DL-032 step
after its release (same function signatures, replaced in place). The release takes whole sources
newest first across Deposit applications, Payment allocations and Credit applications, only until
the paid part is covered (owner answer 2 to Q-2026-10-07-41). A released Deposit application is
reversed whole (`deposit_application_reversal_id`, DB-DEP-006, dated after the latest events of
the Invoice and of the Deposit) and its value goes back to its Deposit, never to Customer Credit;
the rest of a partly released Deposit application is paid again only as a step of the
correction's plan. Payment allocations and Credit applications are released as in 10c-1b: their
re-posted rests keep the amounts of every other line, so no other line changes how it is paid.
The draft request carries `plan` (the Settlement plan format: `steps` and `pet_remainder`; staff
choose every step); the recorder builds `plan_overlay` from the release (the internal
`app.settlement_refund_overlay`) and stores `plan_result` (sub-slice 10c-2a-2). Every Deposit
Refund step uses the draft's Refund method and note. A remaining Pet Deposit step with the
`CUSTOMER_CHOICE` basis needs a choice text other than the one the confirmed Settlement recorded
(owner answer 3 to Q-2026-10-07-44) and other than the one any earlier confirmed correction of that
Settlement recorded (review round 1); the database compares the recorded text only, when the draft
is recorded and again in the shared step at the confirm (sub-slice 10c-2a-6). At the BR-DEP-027
terminations the step's check still refuses
the staff basis. The confirm locks, in the 8e-3 order, the draft lock, the Settlement's draft
lock, the Lease row `FOR UPDATE` (owner answer 4 to Q-2026-10-07-44; 10c-1b as committed took no
Lease lock), then the step's locks (`app.lock_settlement_correction_plan`, which for a `REFUND`
draft also takes the released sources' Payments and then their Credits in its single id-ordered
Payment and Credit passes, together with the Credit steps', so Payments are always locked in id
order (review round 2), and the corrected Invoice `FOR UPDATE` in its id-ordered Invoice pass,
after the Late-payment Charges, so no Invoice is locked before a Charge, as the one-call writers
lock them (review round 1)). After the stale checks it writes the
release (the reversals, the credit Adjustment, the re-posted rests), refreshes the Invoice status,
runs `app.post_settlement_correction_plan` (Credit first, Deposit applications, Deposit Refunds),
and then writes one Credit Refund per released Payment allocation or Credit application only for
the value left in that Credit after the step, at most what this correction released to it (owner
answer 2 to Q-2026-10-07-42: a Customer with open debt on the Lease gets back only the rest; a
Customer with none gets the Refund as in 10c-1b; a correction may end with no Refund). The
`final_settlement.correction.confirmed` audit event also names the Deposit application reversals
and the step's Credit applications, Deposit applications and Deposit Refunds. The 8a-1 refusal
(DB-DEP-005) lets through only an Adjustment linked to a correction of its Invoice's own closed
Settlement, confirmed in the same transaction by that correction's approver under
`financial.approve` (the internal `app.settlement_correction_adjustment_allowed`; owner answer to
Q-2026-10-07-46), so the correction's Adjustment passes while Deposit applications the release
does not reach stay active, on the same line or on other lines of the Invoice. No line is paid
more than its new amount: the deferred Adjustment check already refuses a line whose outstanding
value at the Adjustment's time, Deposit applications included, is below zero. The
`CHARGE_REDUCTION` recorder (10c-1a) still refuses an Invoice that a Deposit application paid
(since sub-slice 10c-3c-2 only a Deposit-paid line with no unpaid rest).

As built in V1-056 sub-slice 10c-2a-5 (migration `20261109_105`; owner answer to
Q-2026-10-07-45): the effects gain the link `settlement_pet_classification_id` (a DB-SETTLE-007
record; deferrable, unique; the one-link check and the two link functions rebuilt). The variant
`PET_DAMAGE_RECLASSIFICATION` (recorder `app.record_settlement_pet_classification_draft` under
`final_settlements.prepare`, confirm `app.confirm_settlement_pet_classification` under
`financial.approve`, READ COMMITTED only) corrects the pet classification of one Damage line
billed from an inspection finding, in both directions. The confirm writes, each linked before it
is written: the DB-SETTLE-007 record; the reversal of the line's Deposit applications where the
corrected classification changes which Deposit should pay (to not pet damage, its
`PET_RELATED_FIRST` applications; to pet damage, its `SECURITY_EXPLICIT` applications while a Pet
Deposit of the Lease on the DL-032 path holds money; a `PET_REMAINDER_EXPLICIT` application stays); then the shared
DL-032 step with the draft's plan. The plan is checked at record under the corrected
classification (the step's overlay key `pet_damage`); the lock function takes the line's Invoice
`FOR UPDATE` in its Invoice pass. No Adjustment: the charge amount stays the same, and a Deposit
refunded at closure is not taken back, so the line may stay open debt.

As built in V1-056 sub-slice 10c-2b-1 (migration `20261111_107`; owner answer 4 to the 10c-1b
review record, answers 1, 2 and 4 to Q-2026-10-08-55): the variant `REFUND_RETURN` (recorder
`app.record_settlement_refund_return_draft` under `final_settlements.prepare`, confirm
`app.confirm_settlement_refund_return` under `financial.approve`, READ COMMITTED only) records
that the money of a correction's Credit Refund (a Refund with a
`settlement_correction_refund_details` row and a Credit source) came back. The draft names the
Refund, the returned amount (at most its net value), the return date (not before the Refund, not
in the future), the return method reference, the evidence, the DL-032 plan and, optionally, a new
Refund's method and reference note; a Deposit Refund step needs that method and note. The
confirm writes, each linked before it is written: the verified return (a DB-REFUND-002
`VALUE_CORRECTION` under `financial.approve`, link `refund_correction_id`), which gives the value
back to the Credit; the shared DL-032 step, in which the Credit first pays its own Customer's open
debt on the Lease (the step's rule for a Credit in the overlay); and, when asked for, one Credit
Refund to the same Customer of what is left in the Credit, at most the returned amount, with its
details row. Without a new Refund the rest stays as that Customer's Credit. The lock function
takes the returned Refund's Credit and its Payment in its id-ordered passes. The relaxed Credit
Refund check (`app.settlement_correction_refund_allowed`) also counts what the correction's own
returns gave back to the Credit. A Settlement Deposit Refund, a correction's Deposit Refund and a
Pet Refund-review Refund are refused by this variant until sub-slice 10c-2b-2.

As built in V1-056 sub-slice 10c-2b-2a (migration `20261112_108`; owner answer 3 to
Q-2026-10-07-42, answer 3 to Q-2026-10-08-55): `REFUND_RETURN` also returns a Final Settlement
Deposit Refund (8d) and a correction's Deposit Refund. The return gives the amount back to the
Deposit (DB-DER-004), never to Customer Credit. Without a new Refund the Deposit keeps holding it
and the draft has no DL-032 step (`runs_step` false; a plan is refused, 22023); a later correction
that runs the step must apply or refund it (BR-SETTLE-008), except a return-only Credit
correction under the hold rule below. With a new Refund the same correction runs the step on the
Deposit (overlay `deposits`), so the value first pays the Lease's open debt in
the DL-032 order and the plan's Deposit Refund step refunds the rest; only a Deposit on the DL-032
path may do so (55000 otherwise). The return check now binds the row's reason to the draft's too.
A Pet Refund-review Refund after closure is sub-slice 10c-2b-2b. After review round 1 (owner
answer 2 to Q-2026-10-08-59): a return-only correction of a Credit Refund records the overlay flag
`hold_deposits`, which the step keeps; with it the plan check lets a DL-032 Deposit keep returned
money that no open debt can take (no Security Deposit balance while debt stays open; no Pet
Deposit balance while pet damage stays open after the Pet Deposit's own step, or while other
debt stays open that the remaining Pet Deposit may pay by a staff decision); the returned Credit
still pays its own Customer's debt first.

As built in V1-056 sub-slice 10c-2b-2b (migration `20261113_109`; owner answer 6 to
Q-2026-10-08-55): `REFUND_RETURN` also returns a Pet Refund-review Refund (DL-053) of a Deposit of
the Settlement's Lease, paid while the Lease was signed. The return gives the amount back to the
Pet Deposit; return only, the Pet Deposit keeps holding it; with a new Refund the step runs as for
a Settlement Deposit Refund, only on the DL-032 path.

As built in V1-056 sub-slice 10c-2b-5 (migration `20261123_119`; owner answer (A) to
Q-2026-10-10-75 point 1): the returned-Refund plan checks the Deposit's path before the return is
written, so it also accepts a Pet Deposit whose held money after this return would be all
pay-back money (`app.lease_deposit_payback_after_return(deposit, refund, returned amount)`: the
count rises only when the returned Refund is a Pet Refund-review Refund). After a pet
noncompliance termination such money first pays the Lease's open debt in the DL-032 order and the
rest is refunded; a return-only correction leaves it held on the DL-032 path, and the
`HELD_VALUE_REFUND` form refunds it.

As built in V1-056 sub-slice 10c-2b-3 (migration `20261114_110`; owner answer 3 to Q-2026-10-07-42,
answers 1, 2 and 4 to Q-2026-10-08-55): the variant `HELD_VALUE_REFUND` refunds value that an
earlier return-only `REFUND_RETURN` correction of the same Settlement left; its draft names that
correction (`held_from_settlement_correction_id`, also in the confirm's audit event) and the new
Refund's method and reference note. A held Credit first pays its own Customer's open debt on the
Lease through the shared step; the new Refund is what is left in the Credit after the step, at most
what the earlier correction left (its return less the Credit applications its own step and the
linked held-value corrections wrote from that Credit, and less their Refunds from it, without
this correction's own records), to the Credit's Customer; the relaxed Credit Refund check counts that value for a Customer who did not
make the Payment. A held Deposit (only on the DL-032 path) first pays the Lease's open debt in the
DL-032 order and the plan's Deposit Refund steps refund the rest. Its effects are the step's Credit
and Deposit applications and its Refunds (DB-SETTLE-005); no new table or column. Owner answer 1 to
Q-2026-10-09-63: an earlier correction is named only while it still has value left (for a Deposit,
its return less the Deposit applications and Refunds from that Deposit written by the linked
held-value corrections), and the Credit or the Deposit must still hold value; the draft records the
Deposit's owner, and the confirm's audit event names the Deposit Refund's recipient and lists every
Deposit balance the step settled.

As built in V1-056 sub-slice 10c-2b-4 (migration `20261116_112`; owner answer to Q-2026-10-09-64, an
approved tightening): a `HELD_VALUE_REFUND` correction uses, in each Deposit, at most what its
earlier correction left there, the Lease debt it pays and the Refund together; a Deposit the earlier
correction returned nothing to gives it nothing, so a Credit correction uses no Deposit money.
It must use some of that value; the rest may stay held for a later correction that names the same
earlier correction (owner answer 1 to Q-2026-10-09-65), and BR-SETTLE-008 and the DL-032 order hold
for the money it uses; other held money stays held until a correction names the earlier correction
that returned it (or a correction that names none settles it, docs/010 known limit). While a Pet
Deposit keeps such money and pet damage stays open after its step, no Security Deposit step pays
that pet damage (DL-032, pet damage first). The draft's `plan_overlay` records the limit (`held_left`, a Deposit id to cents),
the shared step checks it, and a draft without it is stale at the confirm. No new table or column.

As built in V1-056 sub-slice 10e-3 (migration `20261129_125`; owner answer (a) to
Q-2026-10-08-57 and the Q-2026-10-11-78 rule): the variant `RETURN_REVERSAL` (recorder
`app.record_settlement_return_reversal_draft` under `final_settlements.prepare`, confirm
`app.confirm_settlement_return_reversal` under `financial.approve`, a person, READ COMMITTED only)
reverses a return that an earlier `REFUND_RETURN` correction of the same closed Final Settlement
recorded by mistake. The draft names that correction (`held_from_settlement_correction_id`) and
stores what the confirm will undo (`source`), so the approver sees each reversal and each charge
with its person and exact amount; one draft of a return waits at a time. The confirm undoes the
uses of the returned Refund's own source (its Credit, or its Deposit) by that correction and by
every `HELD_VALUE_REFUND` that names it: their active Credit applications from that Credit and
Deposit applications from that Deposit are reversed, newest first (links
`credit_application_reversal_id`, `deposit_application_reversal_id`); each of their Refunds from
that source with a net value is recovered by a charge of the exact net amount to the person who
received it and a `RECOVERED_BY_CHARGE` row (the sub-slice 10e-1c writer; an `EXTRA_CHARGE` on the
Lease when that person is its signed Customer, else a no-Lease charge); then the return is reversed
by a DB-REFUND-002 `CORRECTION_REVERSAL` row (link `refund_correction_id`). Records those
corrections wrote from any other Credit or Deposit stay. No DL-032 step: the debt that comes back
stays with its Customers (BR-SETTLE-016). Refused (55000): a return already reversed; a Refund to
recover that has its own return (reverse that return first); a Refund to recover paid to someone
other than the Deposit's own Customer (Q-2026-10-12-94, until the owner answers); uses to undo that
are more than the returned amount (a `REFUND_RETURN` with a new Refund also paid out money its
source already held; Q-2026-10-12-95, until the owner answers); a returned value another path used
(the source's value plus the undone uses is below the returned amount). The confirm also checks
that the stored draft names exactly what its source reads. A
reversed return leaves its earlier correction nothing (`app.settlement_held_deposit_value`,
`app.settlement_held_credit_value`), so a `HELD_VALUE_REFUND` naming it is then refused. No new
table or column.

Since V1-056 sub-slice 10e-3b (migration `20261130_126`; owner answers (a) to Q-2026-10-12-94 and
(a) to Q-2026-10-12-95), two of the refusals above are gone. A Refund to recover paid to an agreed
Signer who is not the Deposit's own Customer is charged back to that Signer, who received it. Uses
to undo that are more than the returned amount are no longer refused when the Refunds paid out at
least the returned amount: the Refunds paid out the returned money first, so the source state
shares the returned amount over them, the oldest first (`amount_usd_cents` is the share,
`net_usd_cents` the Refund's net), and the rest of each Refund stays paid. A Refund with no share
is not recovered, and every Credit or Deposit application stays (both application lists are
empty). The source names the totals (`uses`: `applied_usd_cents`, `refunded_usd_cents`,
`returned_refunds`). After such a reversal the Deposit or Credit holds what it held before it,
which is nothing for a Deposit, because the step of the reversed correction swept it; the left
value of an earlier return-only correction is not changed (a label that the holdings cap;
Q-2026-10-12-97). On that shared path, the reversal is still refused (55000) in two cases. First,
when a Refund of the uses has its own return, also one returned in full ("A Refund paid from the
returned value has its own return; reverse that return first"). Second, when the Refunds paid out
less than the returned amount, so the rest of it paid debt ("The returned money also paid debt
beyond what its Refunds paid out; reversing it waits for the owner"; Q-2026-10-12-96). Missing
totals are refused too ("The return reversal source is incomplete"). On the shared path the
source-value check always passes; the general check of the `CORRECTION_REVERSAL` row still
requires the source to hold the returned amount. The source still names `deposit_customer` for
each recovery; no check reads it since migration 126. A draft recorded before migration 126 becomes stale at its confirm (P5S02), because its
source shape changed.

Since V1-056 sub-slice 10e-3c (migration `20261202_128`; owner answer (a) to Q-2026-10-12-96), the
second refusal is gone. When the uses are more than the returned amount and the Refunds paid out
less than it, each Refund is charged back whole (its share is its whole net) and the rest of the
returned amount (that amount less the Refunds' nets) paid debt. The source then lists, newest
first, only the applications whose newer applications sum to less than that rest, each reversed
whole, and names in `reapply` the part of the last of them that was not returned money: its source
(`source_kind` `CREDIT` or `DEPOSIT`, `customer_credit_id` or `deposit_id`), the reversed
application (`application_id`, `reversed_usd_cents`), its obligation (`target_kind`, `target_id`; a
Credit application's one detail names its line), its stage (`application_stage`) or Customer
designation (`customer_designation`) and `amount_usd_cents`. `reapply` is a list with at most one
entry, empty in every other case (every listed application is reversed, as before). The recorder
stores a one-step `plan` built from it in the step format of the shared DL-032 step (the internal
`app.settlement_return_reversal_reapply_steps`, no grant; `{"steps": []}` when nothing is applied
again). Right after the `CORRECTION_REVERSAL` row (the source then holds the part) the confirm
applies the part again to the same obligation from the same source, linked before it is written: a
Credit through the Settlement Credit writer reading that step (link
`customer_credit_application_id`; the writer's basis rules apply), a Deposit through the Deposit
application writer with the reversed application's stage and target, numbered after the
Settlement's highest application number (link `deposit_application_id`; its check reads the same
step). The Refunds charged back and the debt owed again add up to the returned amount. The result
and the audit event name the part applied again (`reapplied`; a replay of an earlier confirmation
also returns `reapplied: []`), and the audit event is dated at the latest record. Refused (55000,
fail closed): a `reapply` that is not a list, has more than one entry, has an entry when the
Refunds covered the returned amount or the uses were within it, or whose entry is not a listed
application of the returned Refund's own Credit or Deposit with the same Credit or Deposit, the
same obligation kind and, for a Late-payment Charge or a Deposit's line, the same target (the
source lists a Credit application's Invoice, not its line), is 0 or is not below that application's
amount ("The part of a return reversal applied again is invalid"); a
reversal that would bring back more than the returned amount, or, with uses beyond it, less ("A
return reversal brings back only the returned amount"); the source-value check also requires the
source to hold the part after the return is reversed. The confirm accepts only a draft whose plan is
the one built from its source, whose payload has exactly the recorder's keys and whose Lease is the
Settlement's (P0002 otherwise).
No new table, column, constraint or trigger. A draft recorded before migration 128 becomes stale at
its confirm (P5S02, its source gained `reapply`); it also keeps a new draft of the same earlier
correction waiting, so staff reject it and record it again. Known limits (the confirm refuses, no
money moves; the reversal then waits until the state allows it): a Credit part on an Invoice with
Rent or Service lines and no Customer designation follows the Rent-first proposal for its amount
and is refused (23514) when an earlier line of that Invoice became open again since; a Deposit part
is refused when the Deposit's path is no longer DL-032 (for example a later forfeiture) or the line
is no longer pet damage for the first Pet Deposit stage; a Credit part is refused when the Credit's
Payment is no longer received.

Since V1-056 sub-slice 10e-3d-1 (migration `20261203_129`; owner answer (a) to Q-2026-10-12-97 and
its detail of 2026-10-13), what an earlier return-only correction has left counts every
correction's use of its money. The internal `app.settlement_returned_value_left(settlement, kind,
source, except)` (no grant) walks the Settlement's corrections oldest first (`occurred_at`, then
id), leaving out `except`, each with what it did at its own time. A correction's own returns into
the Credit or Deposit (its linked `VALUE_CORRECTION` rows) open its entry. What it drew from that
source is what it paid out (its linked applications from the source, its linked Refunds from it
and the returns it reversed, its linked `CORRECTION_REVERSAL` rows) less what it brought back
(its linked reversals of applications from the source and its linked `RECOVERED_BY_CHARGE` rows of
Refunds from it), never below 0, so a correction pays out the money it released first (a released
application's rest written again and the Refund of the released part are not new uses). For a
Deposit, its own receipts and forfeiture reversals also count as brought back, and its receipt
reversals and forfeitures as paid out (whole records); a correction that reverses the Credit takes
all the Credit still holds (review round 2). That draw
takes first from its own entry, then from the entry of the earlier correction it names (a
`HELD_VALUE_REFUND`, or a `RETURN_REVERSAL`, whose return reversal empties the named entry), then
from the other entries, oldest return first; the rest is the source's other money. It returns, per
entry, `returned_usd_cents`, `used_usd_cents`, `swept_usd_cents` (what went to a correction that
neither is it nor names it) and `left_usd_cents`. `app.settlement_held_deposit_value` and `app.settlement_held_credit_value`
now return that left value, so a sweep (the shared DL-032 step of a correction that does not name
the earlier correction) lowers it, and a `HELD_VALUE_REFUND` naming a correction whose money a
sweep paid out may use only what is left (refused when nothing is left: "Nothing the earlier
correction returned is left to refund"). A part a `RETURN_REVERSAL` applies again is money the
reversed correction already used, so it changes no left value (the reversal pays out exactly what
it brings back). A correction's own return is taken before the earlier ones, which keeps the count
in line with the 10e-3b and 10e-3c reversals (they charge back exactly that correction's own
returned amount). The order shows on the real path when a return-only Credit correction's own step
pays debt from a Credit that also holds an earlier return: X1 brings back 300, then X2 brings back
1,700 and its step pays 1,500, so X1 keeps 300 and X2 200 (oldest first would leave X1 nothing and
refuse its reversal). Only uses made by corrections of the Settlement count (for a Credit, since
sub-slice 10e-3d-2d-1, those of every Final Settlement that use it; see that paragraph), and
what the Credit or Deposit holds still caps every payout. Known limits (a left value can then be
more than the source holds; payouts stay capped, and the holdings checks refuse): ordinary Credit
spending (owner answer 2 to Q-2026-10-09-63); a correction of another Settlement (owner answer (a)
to Q-2026-10-13-100 point 2: counted from sub-slice 10e-3d-2d). Clipping a draw at 0 can leave a
left value lower than the returned
money the source still holds (the refusals then err on the safe side). A reversal of an earlier
return takes only that return's own left value: the `RETURN_REVERSAL` source names the earlier
correction's `swept_usd_cents` (until sub-slice 10e-3d-2a the check refused any value other than 0;
see the next paragraph) and refuses a missing or non-number one ("The return reversal source is
incomplete"; a fractional number fails its cast, 22P02). The source also names the earlier
correction's `left_usd_cents`, and the check refuses a reversal that would take more than it from
the source (the returned amount and the part applied again less the applications and recoveries it
undoes; "The returned value is no longer available; undo its other use first"), for example when a
Refund of the uses came back through a later return (reverse that later return first); a missing
or non-number left value is an incomplete source (review round 2). Every `RETURN_REVERSAL` draft
recorded before migration 129 is stale at its confirm (P5S02; its source gains two keys), and a
`HELD_VALUE_REFUND` draft recorded before it is stale when its left value changed. No new table,
column, constraint or trigger.

Since V1-056 sub-slice 10h-1b (migration `20270109_166`; owner answers (b) to Q-2026-10-19-141
and (a) to Q-2026-10-19-144), ordinary Credit spending is no longer a gap for Refunds and Credit
reversals: the money a return has left leaves the Credit through a Refund or a Credit reversal
only through a correction. The internal `app.credit_settlement_returned_value_by_settlement(credit)`
(no grant) gives, for each Final Settlement whose corrections linked a `VALUE_CORRECTION` of a
Refund from that Credit, the sum of `left_usd_cents` (each at least 0) of the return entries of
the Credit in that Settlement's walk, counting only that Settlement's own corrections' entries (the
walk also lists other Settlements' entries since sub-slice 10e-3d-2d-1; review round 1,
independent S1; each entry is counted once because every Settlement's walk of the Credit covers
the same corrections since migration 137), and `app.credit_settlement_returned_value_left(credit)`
(no grant) sums it, 0 when none did, and
`app.refuse_credit_refund_of_returned_value(credit, amount)` (no grant) raises P5S01 ("The Credit
holds money a post-settlement correction brought back; refund that money through a held-value
correction of that Final Settlement") when that sum is above 0 and the amount is more than
`app.credit_available_value(credit)` less it. The ordinary Credit Refund draft recorders
(`app.record_refund_draft`, variant `USD` with a `CREDIT` source; `app.record_credit_customer_refund_draft`)
call it after their current-state checks (an exact repeat still replays first), and
`app.confirm_refund_draft` calls it for a Credit source after it takes the Credit Refund locks
(`app.lock_refund_payment_source`: the Payment state guard, the Payment, then the Credit, the
order its writer takes next), so the transaction rolls back and the draft stays pending. Money the
Credit holds for other reasons stays refundable; a left value above what the Credit holds (Credit
applications outside a correction are still not counted) refuses every ordinary Refund of it. A
Refund draft waiting on the Credit also blocks the return-only correction's record (the
correction's waiting-draft check), so the confirm's refusal is the backstop for a draft that waited
while money came back. One exact-text replacement each; signatures, settings and privileges are
kept. A new BEFORE INSERT row trigger `customer_credit_reversals_returned_value` on
`app.customer_credit_reversals` (function `app.refuse_returned_credit_reversal()`, no grant;
Q-2026-10-19-144) takes the same Credit Refund locks first (`app.lock_refund_payment_source`, the
order of the insert check `app.validate_credit_reversal`, which runs after it) and raises P5S01
("A closed Final Settlement changes only through a post-settlement correction") unless, for every
Settlement whose returns into the Credit have money left, `app.settlement_correction_linked` finds
a correction of that Settlement confirmed in this transaction that links the reversal. Its name
sorts after the slice 7 and 8g P4904 triggers and before the insert check. So the one-call Credit
reversal cannot move that money back to its Payment, whose Payment Refund check reads only a named
Invoice or Late-payment Charge; the `RETURNED_PAYMENT` correction links each Credit reversal before
it writes it and still reverses the Credit; the ordinary `PAYMENT_RETURN` draft never reaches such
a Credit (its source refuses a Payment whose Credit has a Refund or Refund correction linked to a
correction). Only a returned Refund recorded by a correction counts: other value a correction puts
back into a Credit (for example a correction's reversal of a Credit application) is not counted.
Not changed: the Payment and Pet Deposit Refund drafts, Credit applications outside a correction,
the correction writers and the owner-only one-call `app.create_usd_refund`.

Since V1-056 sub-slice 10e-3d-2a (migration `20261204_130`; owner answer (a) to Q-2026-10-13-100
point 1): the count above is one internal walk, `app.settlement_returned_value_walk` (no grant),
which `app.settlement_returned_value_left` (same results) and the new
`app.settlement_returned_value_takes` (no grant) both read. For an earlier return-only correction E,
the takes are the records of each other correction S (neither E nor one naming E) that paid out
part of E's money: inside S the money S brought back pays out first, then S's Refunds from the
source, the oldest first, then S's applications from it, the newest first, and E's part of S's
draw falls on those records in that order. A `RETURN_REVERSAL` of E now undoes those parts too: a
Refund part is charged back to the person who received that Refund (a share, as for the own
uses), an application part reverses the application whole and applies the rest again to the same
obligation from the same Credit or Deposit (one part applied again per such application; the
confirm writes them in the source's order). The own uses are then undone against the part of E's
money they used (E's used less its swept part). The source names `swept` (the parts undone),
`swept_undone_usd_cents` and `swept_open`; the check refuses a source whose parts do not add up
to `swept_usd_cents` or are not listed exactly as recoveries, reversed applications and parts
applied again ("The return reversal source is incomplete"), and refuses each part it cannot undo
yet with its own message: an application reversed since ("A later correction changed a payment
made with this return's money; reversing it waits for sub-slice 10e-3d-2b"), the take of an S that
also reversed the Credit or a Deposit receipt ("... waits for sub-slice 10e-3d-2c"), a forfeiture
("A forfeiture kept this return's money; the return cannot be reversed"; owner answer (a) to
Q-2026-10-13-103 point 2), and any other (a reversed return, a Refund part more than the Refund's
net: "The returned value is no longer available; undo its other use first"). An S that also paid
out through one of those kinds is not split (fail closed). Review round 1: the parts applied again
are listed in the DL-032 stage order, then in the order their applications were first written; a
Credit part applied again without a Customer designation on the newer of two reversed applications
of an Invoice with Rent or Service lines is refused ("A part applied again on an Invoice with Rent
or Service lines would not follow the Rent-first order; reversing this return waits for the
owner", Q-2026-10-13-104; ended by sub-slice 10e-3e, DB-CREDIT-002); and when two or more own corrections paid out from the source and one of
them also took another return's money (the source's `shared_with_other_returns`), the reversal
waits for sub-slice 10e-3d-2b ("This return's own corrections also paid out another return's
money; reversing it waits for sub-slice 10e-3d-2b"). Review round 2 (owner answer (a) to
Q-2026-10-13-105): that flag must be there as true or false, as the other new keys must, else the
source is incomplete; and the confirm's loop over the parts applied again refuses any source kind
other than a Credit or a Deposit ("The return reversal source is incomplete"). The recovery
scope check accepts a Refund of another correction of the same Settlement that the draft's
source lists as a swept part. Every `RETURN_REVERSAL` draft recorded before migration 130 is
stale at its confirm (P5S02; its source gains four keys). No new table, column, constraint or
trigger.

As built in V1-056 sub-slice 10e-3d-2b-1a (migration `20261205_131`; owner answer (a) to
Q-2026-10-13-100 point 1): a part of E's money on an application that a later `RETURN_REVERSAL`
reversed and put back follows to that put-back. A return reversal's put-back is the reversed
application less exactly its own return's part, so every other return's part is in it with the
same amount. New internal `app.settlement_returned_value_successor(p_kind, p_application)`
(STABLE, SECURITY DEFINER, `search_path=pg_catalog`, no grant): the application itself while it
is active; after a `RETURN_REVERSAL` reversed it, the put-back that correction wrote for it (the
n-th entry of the stored source's `reapply` is the n-th application linked to that correction),
checked (the same Credit or Deposit, obligation and stage, the entry's amount, less than the
reversed application) and followed again through later return reversals; NULL for any other
change (a `REFUND` correction's release, a pet-damage reclassification, a reversal with nothing
put back) or a put-back that does not check. `app.settlement_return_reversal_source_state` lists
the part on the successor (its correction, id and amount), so the reversal reverses it whole and
puts its rest back; a part with no successor, or more than it, stays open ("A later correction
changed a payment made with this return's money; reversing it waits for sub-slice 10e-3d-2b").
Review round 1: the reversing correction and the put-back must belong to the application's own
Final Settlement, the stored source must list the application exactly once, and a Credit
application must have exactly one detail on each side; a followed part names the correction that
wrote the put-back (only a Refund part's correction is read by the recovery scope check, so
nothing else reads it). Known limit (review rounds 1 and 2, for sub-slice 10e-3d-2b-1b): on the
10e-3c pooled own path, when the reversed return's own correction also brought money back, its
put-back is the payment less that return's part only in amount, and the check that a followed part
is no more than the put-back is what keeps the result exact (else it stays open, fail closed). No
check, writer, lock or grant changes; no new table, column, constraint or trigger. (Sub-slice
10e-3d-2b-1b closes this known limit: such a source takes the walk path below. Today no
`REFUND_RETURN` or `HELD_VALUE_REFUND` writer links a record that brings money back, so the case
is not reachable and the walk-path condition is defensive.)

As built in V1-056 sub-slice 10e-3d-2b-1b (migration `20261206_132`; owner answer (a) to
Q-2026-10-13-100 point 1): the own uses of E (E's own correction and the `HELD_VALUE_REFUND`
corrections naming E) are placed by the walk, as the other corrections' uses are, when two or more
of them paid out from the source, when an own application from it was reversed since (for example
by another return's reversal), or when an own correction's draw starts after money it brought back
(defensive, see above). On that walk path each own correction's take of E's money sits on its
Refunds (the oldest first) and then on its applications (the newest first), after what it brought
back; a reversed application is followed to its successor (a part with none, or more than it,
stays open, for example after a `REFUND` correction's release: sub-slice 10e-3d-2b-2); a Refund
part more than the Refund's net now (a part of it came back) stays open; on the walk path the
pooled totals must still be there as numbers; the parts are listed, charged back and applied
again exactly as the other corrections' parts, and the pooled own lists of sub-slices 10e-3b and
10e-3c stay empty. Otherwise (at most one own correction paid out, none of its applications
reversed, nothing brought back) the pooled own path is unchanged, because there it places E's
money on the same records (a Refund whose net is below its amount there is refused on either
path, with a different message). New
internal `app.settlement_returned_value_parts(p_settlement, p_kind, p_source, p_earlier, p_swept)`
(STABLE, SECURITY DEFINER, `search_path=pg_catalog`, no grant) gives the record parts of the
other corrections' takes (`p_swept` true) or of the own takes (`p_swept` false);
`app.settlement_returned_value_takes` now returns its rows with `p_swept` true (same signature,
settings and privileges). The source gains `own_parts` and `own_open` (the shapes of `swept` and
`swept_open`; JSON null on the pooled path). `app.assert_settlement_return_reversal_allowed`
requires both keys, null or lists together; on the walk path it holds the own parts to the rules
of the other corrections' parts, requires their total to be exactly the part of the returned money
the own uses used, no record to be a part twice and every listed application, recovery and part
applied again to belong to a part, refuses an own part not undone yet with the message of its
kind, and skips the pooled-path checks (the Refund with its own return on the shared path, the one
own part applied again, and the `shared_with_other_returns` flag, which now refuses only a
pooled-path source). A `RETURN_REVERSAL` draft recorded before revision 132 is stale at its
confirm (P5S02). No writer, lock or grant changes; no new table, column, constraint or trigger.

As built in V1-056 sub-slice 10e-3d-2b-2 (migration `20261208_134`; owner answer (a) to
Q-2026-10-13-107 and the owner's acceptance of 2026-10-14 that a return reversal's put-back keeps
each part's place with the reversed return's money cut out): each part of E's money keeps its
place in its record (new internal `app.settlement_returned_value_placed`, the parts with their
offsets; `app.settlement_returned_value_parts` now returns its rows without the offset), and a
payment part is followed to the records that hold it now (this replaces, in the source, the
successor rule of sub-slices 10e-3d-2b-1a and 10e-3d-2b-1b above; new internal
`app.settlement_returned_value_follow`, STABLE, SECURITY DEFINER, `search_path=pg_catalog`, no
grant). An active payment holds the part itself. A payment a `RETURN_REVERSAL` R reversed passes
it to R's put-back (the n-th `reapply` entry is R's n-th linked payment, checked as in
`app.settlement_returned_value_successor`, the put-back of this Settlement), at its offset less the
stretches of R's reversed return before it; those stretches are that return's placed parts
followed up to the payments R reversed, must add up to the payment less the put-back and must not
overlap the part. A payment a `REFUND` correction or `PET_DAMAGE_RECLASSIFICATION` Q of the same
Settlement reversed is laid over Q's stream: Q's reversals of payments from the source, in effect
order, are what Q took back; Q's Refunds from the source (the oldest first), then its payments
from it (the newest first), pay it out in that order; a Q Refund the part overlaps holds that part
(charged back to its recipient), a Q payment is followed again. Everything else stops open
(`CHANGED_APPLICATION`, now "A later correction changed a payment made with this return's money
in a way this reversal cannot follow yet; reversing it waits for the owner"): an unknown payment,
offset or part, a part not inside its payment, more than 100 steps, a reversal by no correction,
another Settlement's correction or another kind, a put-back that does not check or whose cut does
not add up, a Q that also brought money back other than by reversing payments or also reversed
the Credit, a return or a receipt, or forfeited, a part past what Q paid out, and, while following
a reversed return's stretches, a change by a correction not strictly earlier than that reversal
(so the recursion ends). The source's `swept_state` sums the followed rows per own flag,
correction and record; a Refund part more than the Refund's net stays open. The recovery scope
`app.settlement_return_reversal_refund` also accepts a Refund the source lists in `own_parts` (a
relaxing change; the source is server-built and digest-checked at the confirm). A `RETURN_REVERSAL`
draft recorded before revision 134 whose source now differs is stale at its confirm (P5S02). No
writer, lock or grant changes; no new table, column, constraint or trigger.

As built in V1-056 sub-slice 10e-3d-2b-3 (migration `20261209_135`; owner answer (a) to
Q-2026-10-14-111): within the newest-first order of one correction's payments from a Credit or a
Deposit, a tie in time is broken by the order the correction wrote them
(`settlement_correction_effects.effect_sequence`, the higher the newer), then by the id; a Deposit
payment keeps `application_order` before it. The orders changed are the taking correction's
payments in `app.settlement_returned_value_placed`, the changing correction's payments in the
stream of `app.settlement_returned_value_follow`, and, in
`app.settlement_return_reversal_source_state`, the listed payments the reversal undoes and the
newest-first walk that chooses, on the pooled own path, the payments reversed whole and the part
applied again (relaxing exact-text patches; no refusal added). This is defence in depth: the
database already refuses two payments of one source at one time (a Credit application must be
later than every earlier event of its Credit, `app.validate_credit_application_source`; a Deposit
application later than the Deposit's latest balance event, `app.validate_deposit_application`, and
`application_order` is unique per Final Settlement, so a Deposit tie cannot happen on the real path;
by hand it needs that constraint dropped too, as the sub-slice 10e-3d-2c test does inside an always
rolled-back transaction), so no stored result changes. A list of the source function can hold payments of two or more
corrections, whose effect sequences are compared only on a time tie, and the id still decides any
tie left. Not changed (each already fixed by a stored or chronological order and never deciding
who pays or how much): the write order of a reversal's named Deposit application reversals, the
listing order of the parts applied again (stored in the draft), and the release order of a
`REFUND` correction. No writer, lock or grant changes; no new table, column, constraint or
trigger.

As built in V1-056 sub-slice 10e-3d-2c (migration `20261210_136`; owner answer (a) to
Q-2026-10-13-103 point 1, the Q-2026-10-11-78 rule): money of an earlier return-only correction E
that left the Credit or Deposit through a `RETURNED_PAYMENT` or `DEPOSIT_RECEIPT_CORRECTION`
correction C of the same Settlement (C's take through its Credit reversal or receipt reversal; a
stretch on a payment C reversed when C also reversed the source; a Refund part above its Refund's
net when C recovered at least that excess from the Refund and reversed the source) is a part of E's
own returned Refund R (record kind `RETURNED_REFUND`). E's `RETURN_REVERSAL` charges those parts,
summed in one recovery entry of R, to the person who received R (a DB-REFUND-002
`RECOVERED_BY_CHARGE` on R linked to the reversal, the sub-slice 10e-1c charge), and nothing else;
a part that cannot be followed stays open and is refused. The parts must add up to no more than R's
net once E's return is reversed. Write order: the `CORRECTION_REVERSAL` row first, then R's
charge-back with the same `occurred_at` (DB-REFUND-002 amendment, relaxing: the general Refund
correction check counts the charge-back of R that the same `RETURN_REVERSAL` draft lists as
available in the source and, when it covers the whole reversal, as standing for a source Payment
no longer received; and allows that one paired charge-back the reversal's time, never earlier and
no other row), because the deferred Credit and Deposit history checks group events by time and
R's net cannot go below 0. The charge-back is so dated a few microseconds before the charge
Invoice it names. Internal `app.settlement_return_reversal_charge_back` and
`app.settlement_return_reversal_paired_charge_back`; exact-text patches of the placed, follow,
source, refusal, recovery-scope, confirm, general Refund correction check and recovery writer
functions. No table, column, constraint, trigger, lock or grant change.

As built in V1-056 sub-slice 10e-3d-2d-1 (migration `20261211_137`; owner answer (a) to
Q-2026-10-13-100 point 2): a Customer Credit belongs to its Customer, not to a Lease, so a
correction's DL-032 step on the Customer's other Lease can apply it to the open debt there. For a
Credit, the walk behind every left value (`app.settlement_returned_value_walk`, read by
`app.settlement_returned_value_left`, `app.settlement_held_credit_value`, the placed function and
the `RETURN_REVERSAL` source) takes the corrections of the given Settlement and, of every other
Final Settlement, those with a linked record it reads for that Credit (a Credit application from
it or a reversal of one, a Refund from it, a return, return reversal or recovery of such a Refund,
a reversal of the Credit), all in one order by time and id; this ends the known limit "a
correction of another Settlement" above for a Credit. A Deposit belongs to one Lease, so its walk
does not change. A take of a return's money by a correction of another Final Settlement is one
open part of kind `OTHER_SETTLEMENT` (record id: that correction), none of its records listed for
undoing, and the return's `RETURN_REVERSAL` is refused before any other open part ("A correction
of another Lease's Final Settlement used this return's money; reversing it waits for sub-slice
10e-3d-2d-2"), until that sub-slice undoes the use on the other Lease with a companion correction
of its Settlement (owner answer (a) to Q-2026-10-13-103 point 3). Still not counted (the known
limit of ordinary Credit spending, owner answer 2 to Q-2026-10-09-63): a use of the returned Credit
by another Lease's own Final Settlement confirm, which is not a correction; what the Credit holds
still caps every payout. Counting in one time order can move the attribution of a later sweep by
this Settlement's own corrections to a later return (oldest return first): for example X1 and X2
each bring back 300, another Lease's correction uses 300 and then a correction of this Settlement
uses 300; X1's money is the other Lease's take (its reversal waits) and X2's is this Settlement's
(its reversal undoes that use). The move can also go the other way, to an older return of another
Lease's correction now in the walk: when that Lease's return Y came before this Settlement's
return X and a correction of this Settlement then uses the Credit, Y's money is taken first, so X
keeps its left value and Y's reversal waits for sub-slice 10e-3d-2d-2. Payouts stay capped by what
the Credit holds. The count is read again on every read, so records confirmed before migration
`20261211_137` are read with the new attribution; where that no longer matches a put-back made
earlier, the follow function stops at it (`CHANGED_APPLICATION`, fail closed), and a waiting
`RETURN_REVERSAL` or `HELD_VALUE_REFUND` draft whose source changed is stale at its confirm (P5S02).
Exact-text patches of the walk, placed and refusal functions; no table, column, constraint,
trigger, lock or grant change.

As built in V1-056 sub-slice 10e-3d-2d-2a (migration `20261212_138`; owner answers (a) to
Q-2026-10-13-100 point 2 and Q-2026-10-13-103 point 3): a `RETURN_REVERSAL` R whose earlier
return's money a correction of another Final Settlement B paid out through a Credit application
reverses that application whole and puts back the part that was not the return's money on its
own line, as for a correction of R's own Settlement, with every record on B linked to a companion
correction of B's Settlement. The companion is a `SETTLEMENT_CORRECTION` draft of B with the
variant `RETURN_REVERSAL_COMPANION`, its id derived from R's draft and B
(`app.settlement_correction_companion_id`), written by R's confirm with
`final_settlements.prepare` and R's reason, prepared and confirmed by R's approver in R's
transaction (its decision and header through `app.begin_settlement_correction`), so it is never
pending; its payload names R's draft and correction and carries B's slice of R's stored source
(`app.settlement_return_reversal_companion_source`: B's listed Credit applications and parts
applied again) and its put-back plan. B's own rules pass unchanged: the reversal of B's Credit
application and the put-back on B's line are linked to the companion, a correction of B confirmed
in the same transaction. R's source names the companions (`companions`: each other Settlement,
its Lease and Property, closed), the refusal function requires exactly one closed entry of the
same Property per other Settlement whose application is listed, R's result and audit event name
the companions, and each companion has its own audit event on B's Lease naming R, so B's
correction list and Lease history show which correction undid the payment. The walk treats a
companion as part of its reversal (companions are not walked; every sum reads the correction's
and its companions' effects), so R's net draw is what R really takes from the source and the
companion's time never ties R's (the companions are worked out from R's stored source, with no
scan of drafts). The Settlement a listed Credit application belongs to is its own
`final_settlement_id`, or, for an ordinary application such as the rest a `REFUND` correction
writes again, the Final Settlement of its target's Lease
(`app.settlement_credit_application_owner`); one with neither is refused as incomplete. Since R's
`reapply` also lists other Settlements' entries, the successor and follow functions rank only the
entries of R's own Settlement against R's linked put-backs. Every record of R and its companions
is dated after every companion header. A companion's audit event names the returned Refund's
recipient as its Customer, as R's does (for a Credit Refund, the Credit's own Customer, whose
debt on B the Credit paid). A draft already recorded at a companion's derived id (only by a
direct database caller; the routes derive draft ids from their idempotency keys) makes R's
confirm fail (23505): R stays pending, and staff reject or withdraw it and record it again with a
new idempotency key, which gives a new companion id. R's confirm takes the Settlement draft locks
of its own and every companion's Settlement in Settlement id order, then their invoice-lease
locks and Lease rows in Lease id order, before the lock function. Still refused: a take whose
correction also paid a Refund from the Credit (the `OTHER_SETTLEMENT` part; its charge-back
through the companion is sub-slice 10e-3d-2d-2b), another Settlement's Credit reversal or return
reversal (their existing messages), and B's own Final Settlement confirm's use of the Credit (not
counted until sub-slice 10e-3d-2d-2c, the owner answer (a) to Q-2026-10-15-113). Known limit
(fail closed): the follow function stops at a payment that a correction of another Settlement, a
companion included, changed (`CHANGED_APPLICATION`), so a later reversal of another return whose
money sat in such a payment is refused. A `RETURN_REVERSAL` draft recorded before migration
`20261212_138` has no `companions` key in its source and is stale at its confirm (P5S02).

As built in V1-056 sub-slice 10e-3d-2d-2b-1 (migration `20261213_139`; owner answers (a) to
Q-2026-10-13-100 point 2 and Q-2026-10-13-103 point 3): a take of a return's money by a correction
of another Final Settlement B that also paid a Refund from the Credit is placed on that
correction's records as any other take, so its application parts are undone through the companion
as above. A correction's draw covers, in order, what it brought back itself (the draw's offset), its
own return, then the return it names, before any other return's money, and its records are laid
out Refunds first, then applications, the newest first. Every Credit Refund writer caps its Refund
by one of those three (a `REFUND` correction by what it released, a `REFUND_RETURN` by its own
return, a held-value Refund by its named return's left value) or pays it from a Credit it creates
itself, so another return's money starts after its Refunds and lands on its applications (in the
committed case on the older 1,300 payment written again, at the end of the newest-first layout). A
part that falls on any record of a correction of another Final Settlement other than a Credit
application stays one open `OTHER_SETTLEMENT` part named by that correction, refused with its
existing message, so nothing is undone half; no real path through a take to it was found (the
Refund caps are enforced by the Refund writers, not by this function). For a Deposit source such a
take stays refused (and is unreachable: a Deposit's walk reads only its own Settlement's
corrections): each of its records is an open part, and a stretch no record covers fails the sum
check. A real path to another Settlement's Refund exists through the follow function: a return's
money on another Settlement's payment that a `REFUND` correction of that Settlement later changed
(the follow function stops there as `CHANGED_APPLICATION`, fail closed); following it into that
correction's Refund and payments, with the Refund's recipient charged on B's Lease when a signed
Customer of it (owner answer 4 of 2026-10-16), is sub-slice 10e-3d-2d-2b-2. A take by another
Settlement's correction that also reversed the Credit or a return is still refused, now with the
`CREDIT_REVERSAL` message or the general one instead of the `OTHER_SETTLEMENT` message. Exact-text
patches of the placed function only.

As built in V1-056 sub-slice 10e-3d-2d-2b-2 (migration `20261214_140`; owner answers (a) to
Q-2026-10-13-103 point 3 and Q-2026-10-13-107, owner answer 4 of 2026-10-16): the follow function
reads a changing correction of another Final Settlement B when the source is a Credit and its
variant is `REFUND` (an allow-list; B's return reversal, companion, bounced Payment, pet-damage
reclassification and every Deposit case still stop as `CHANGED_APPLICATION`), and follows the
stretch into its Refunds (the oldest first) and payments (the newest first) exactly as for a
`REFUND` correction of the reversal's own Settlement. A part on such a Refund is charged back to its
recipient on B's Lease when the recipient is a signed Customer of it, else on no Lease; the
recovery entry's `closed_final_settlement_id` is the Final Settlement of the charged Lease (one per
Lease). The source's `companions` also lists each other Settlement that owns a Refund part
(internal `app.settlement_refund_owner`, the Final Settlement of the correction a Refund is linked
to; no grant), and the companion's draft source gets the key `recoveries` (its Settlement's
charge-backs). The confirm writes those charge-backs linked to B's companion, so B's
closed-Settlement guards accept the charge on B's Lease; the companion's result entry and audit
event name them. The charge's obligation and Invoice audit events on B's Lease carry the return
reversal's evidence (variant `RETURN_REVERSAL` and its ids, which the recovery writer's share rule
reads) plus `companion_settlement_correction_id`; their correlation is the companion.
`app.refund_recovery_allowed` allows such a row inside a `RETURN_REVERSAL_COMPANION` of the
Refund's own Settlement confirmed by the same approver in this transaction whose return reversal,
confirmed in this transaction too, lists the Refund (`app.settlement_return_reversal_refund` now
accepts a swept Refund of a Settlement the source names as a companion); the row must still be
linked by every closed Final Settlement the Refund belongs to, and the recovery check's own
`RETURN_REVERSAL` branch takes only a Refund of no other Final Settlement (security review round
2), so a row linked to the reversal alone is refused twice over.
`app.settlement_return_reversal_recovery_amount` reads the companion's draft too, so
the charge-back may be a share of the Refund's net. The refusal function checks that the companions
also match the Refund parts' Settlements and that a charge-back of another Settlement's Refund
belongs to a listed companion and names that Settlement and its Lease, or no Lease and no
Settlement (fail closed; security review round 1); the `OTHER_SETTLEMENT` message, now given only
for a part on another Settlement's Refund reached through a take (no real path found), says that
reversing it waits for the owner. Another Settlement's bounced Payment cannot take the return's
money (its `RETURNED_PAYMENT` is refused while the first Settlement relies on the Credit); not
built.

As built in V1-056 sub-slice 10e-3d-2d-2c (migration `20261215_141`; owner answer (a) to
Q-2026-10-15-113): a use of a returned Credit by another Lease's own Final Settlement confirm (not
a correction) now counts too, which ends that case of the known limit in the 10e-3d-2d-1 paragraph
above (the rest of owner answer 2 to Q-2026-10-09-63 stays). A Final Settlement's own confirm
writes its Credit applications with `final_settlement_id` and no correction link (it pays no
Credit Refund). For a Credit, the walk takes each Final Settlement whose own confirm applied it as
a walker too, at the time of its first such application, in the one order by time and id with the
corrections; its id in the walk is the Final Settlement's (there is no correction); its draw is
the sum of those applications, and it takes the returns' money, the oldest first. It is a walker
only while some return's money is left at its place in the order, so a confirm before every
return into that Credit gives no row. Ordering a correction by its header time and a confirm by
its first application's time is sound because every correction that writes a record of the
Credit takes the Credit's row lock before its header (through
`app.lock_settlement_correction_plan`), and a confirm writes its applications under that lock,
each later than every earlier event of the Credit (review round 1 security note). The placed
function places such a take on that confirm's applications from the Credit, the newest first; a
part entry of the `RETURN_REVERSAL` source then carries the Final Settlement's id in
`settlement_correction_id`. The follow function takes a Credit application with no correction
link and a `final_settlement_id` as written by that Final Settlement (before, such a payment
stopped as `CHANGED_APPLICATION`). The return's reversal lists such an application for
undoing, names its Settlement as a companion, reverses it whole linked to the companion and puts
back any rest through the companion's step, as for another Settlement's correction (sub-slice
10e-3d-2d-2a); a later reversal of another return whose money sits in that put-back stops as
`CHANGED_APPLICATION` (the 10e-3d-2d-2a limit). A Deposit belongs to one Lease and its own
confirm comes before every correction of that Lease, so the Deposit walk does not change.

Known behaviour (owner answer (a) to Q-2026-10-16-115; follow-up test of sub-slice 10e-3d-2d-2c):
a confirm's Credit application that a `REFUND` correction of its own Lease later changed is
followed through the 10e-3d-2d-2b-2 allow-list, not refused, so the return's reversal charges
the money that correction refunded back to the person who received it, on that Lease, through
the companion. Two consequences are accepted as they are: the same mistaken money becomes a
different debt with or without that later `REFUND` correction (without it the line owes again;
with it a recovery charge on the closed other Lease), and the first Lease's approver alone
creates that debt on the other Lease (the companion is recorded and confirmed by the same
`financial.approve` actor in the same call).

As built in V1-056 sub-slice 10c-3a (migration `20261115_111`; owner answer to Q-2026-10-07-38): the
`CHARGE_REDUCTION` variant also reduces an unpaid Late-payment Charge of an Invoice of the
Settlement's Lease (draft `target_kind` `LATE_PAYMENT_CHARGE`, its own recorder and confirm). Its
effect is one Late-payment Charge correction (`late_payment_charge_correction_id`): `REDUCTION` of the
amount, or `CHARGE_REVERSAL` when the amount is the whole current obligation, with authorization
reference `financial.approve`, the draft's reason and the correction as its correlation. At most the
unpaid rest (the current obligation less the active applications) is reduced; a Charge that a
Deposit application paid (since sub-slice 10c-3c-2 only when it has no unpaid rest), a reversed
Charge and a Charge on a VOID Invoice are refused.

As built in V1-056 sub-slice 10c-3b-1 (migration `20261117_113`; owner answer to Q-2026-10-07-38
(b), owner answer 2 to Q-2026-10-09-66): the `REFUND` variant also takes a paid Late-payment Charge
(draft `target_kind` `LATE_PAYMENT_CHARGE`, its own recorder and confirm; the draft's `refund`
object also stores the Charge's source Invoice). Its effects are, in this order: each released
Payment allocation reversal (`payment_allocation_reversal_id`) and Credit application reversal
(`credit_application_reversal_id`), whole sources, newest first; one Late-payment Charge correction
(`late_payment_charge_correction_id`, `REDUCTION`, or `CHARGE_REVERSAL` for the whole current
obligation, authorization `financial.approve`); each re-posted rest on the same Charge
(`payment_allocation_id`, `customer_credit_application_id`); the shared step's records; and one
Credit Refund per released source (`refund_id`, with its `settlement_correction_refund_details`
row). Released Payment value becomes Customer Credit of the Charge's Customer (BR-CREDIT-014);
released Credit value returns to its Credit. These Credits have no link of their own: the release
rows of `invoice_credit_excess_releases` name the Charge correction and the Credit (DB-INV-003). A
Charge that a Deposit application paid was refused until sub-slice 10c-3b-2.

As built in V1-056 sub-slice 10c-3b-2 (migration `20261118_114`; owner answer 1 to Q-2026-10-09-66
and the owner answer to Q-2026-10-07-46): the Late-payment Charge `REFUND` also releases Deposit
applications on the Charge, newest first with the Payment allocations and Credit applications. A
released Deposit application is reversed whole by a Deposit application reversal (DB-DEP-006)
linked as an effect (`deposit_application_reversal_id`) in the release order, before the Charge
correction; its value goes back to its Deposit, never to Customer Credit, and only the shared
step's Deposit applications and Deposit Refunds (`deposit_application_id`, `refund_id`) apply or
refund it in the DL-032 order. A Deposit application the release does not reach stays and still
pays the Charge; the correction's own linked Charge correction passes the 8a-1 refusal through the
internal `app.settlement_correction_charge_correction_allowed` (owner answer to Q-2026-10-07-46).
No new table or column.

As built in V1-056 sub-slice 10c-3c-1 (migration `20261217_143`; owner answer 3 to
Q-2026-10-10-69 and answer (a) to Q-2026-10-10-70, an approved tightening): the 8a-1 refusal
(DB-DEP-005) calls two new internal overloads of the allow functions with the row's own values,
`app.settlement_correction_adjustment_allowed(invoice, line, adjustment, actor, source_reference)`
and `app.settlement_correction_charge_correction_allowed(charge, charge correction, actor,
correlation)`. Besides the earlier conditions, an Adjustment passes only when its
`source_reference` is `settlement-correction:<the correction>` and the correction's
`SETTLEMENT_CORRECTION` draft is a `CHARGE_REDUCTION` (key `reduction`) or `REFUND` (key `refund`)
with no `target_kind` naming exactly the Adjustment's Invoice and line; a Late-payment Charge
correction passes only when its `correlation_id` is the correction and the draft is a
`CHARGE_REDUCTION` or `REFUND` with `target_kind` `LATE_PAYMENT_CHARGE` naming exactly its Charge.
Every committed writer that links such a row meets both conditions (the `REFUND` confirms are
exercised by the real-path tests; the `CHARGE_REDUCTION` confirms, whose recorders still refuse a
Deposit-paid obligation, by reading until sub-slice 10c-3c-2). The old three-argument functions
stay, with no caller. No table, column, constraint, trigger, lock or grant change.

As built in V1-056 sub-slice 10c-3c-2 (migration `20261218_144`; owner answer (a) to
Q-2026-10-10-70): a `CHARGE_REDUCTION` correction (the Invoice-line form of 10c-1a and the
Late-payment Charge form of 10c-3a) accepts an obligation that a Deposit application partly paid,
within its unpaid rest: the current obligation less every active application, Deposit applications
not reversed included. The Deposit application stays; nothing is released and no money moves; a
reduction above the unpaid rest is refused ("The charge reduction would release paid value",
55000). An obligation that an active Deposit application paid and that has no unpaid rest keeps the
Deposit refusal ("A Deposit application paid this obligation at Final Settlement", 55000; owner
answer (a) to Q-2026-10-11-80). Two exact-text patches narrow the Deposit refusal in
`app.settlement_charge_reduction_plan` and `app.settlement_late_charge_reduction_plan` to that
case; each confirm runs the patched plan again under its locks, and the source digests hold the
Deposit applications of the obligation (the line's paid value and the Invoice's application count;
the Charge's application summary), so a Deposit change on the obligation between record and
confirm makes the draft stale (P5S02). While an active Deposit application is on the Invoice or
the Charge, the linked Adjustment or Charge correction passes the 8a-1 refusal only through the
hardened allow functions of 10c-3c-1 (the Adjustment's reference, or the Charge correction's
correlation, names the correction, whose draft names exactly that obligation); the new tests reach
both writers with an active Deposit application on the obligation. The old Invoice-line refusal
covered the whole Invoice (any Deposit application on any line, also a reversed one), so a line
that no active Deposit application pays, on an Invoice where another line is Deposit-paid, also
takes a reduction of its unpaid rest (the implementer's reading, confirmed in review round 1).
While a Deposit application pays part of a Charge, the amount is below the current obligation, so
the Charge correction is always a `REDUCTION`. No table, column, constraint, trigger, lock or grant
change.

As built in V1-056 sub-slice 10d (migration `20261119_115`; owner answer 4 to Q-2026-10-06-36,
answer 2 to Q-2026-10-10-71): the variant `FORFEITURE_REVERSAL` reverses a confirmed Lease Deposit
forfeiture (DB-DEP-008) of a Deposit of the Settlement's Lease after closure. Its draft names the
forfeiture, an evidence reference, the correction's Refund method and reference note and the DL-032
plan, and records the Deposit, its owner and the forfeited amount. Its effects are, in this order:
the forfeiture reversal (`deposit_disposition_reversal_id`), written through the existing reversal
function with the approver as actor and `deposits.correct`, as the 6b confirm writes it; then the
shared step's Credit applications, Deposit applications and Deposit Refund (with its
`settlement_correction_refund_details` row). The reversal puts the forfeited money back in the
Deposit on the DL-032 path, so each Customer's Credit first pays that Customer's own open debt, the
Deposit pays the Lease's open debt in the DL-032 order and only the rest is refunded
(BR-SETTLE-008). A forfeiture already reversed, or one whose Deposit has another forfeiture that
stays active, is refused. The reversal row and its `deposit.disposition.reversed` audit event are
stamped with the confirm's statement time, so they are dated just before the correction's decision
and header that link them; read them through the link, not by time. No new table or column.

As built in V1-056 sub-slice 10e-2b-1 (migration `20261126_122`; owner answers (a), (a), (a) to
Q-2026-10-12-87): the effects gain the link `deposit_receipt_id` (DB-DEP-002; deferrable, unique;
the one-link check and the two link functions rebuilt). After its 10e-2 writes (recoveries,
application reversals, the wrong receipt's reversal), a `DEPOSIT_RECEIPT_CORRECTION` whose draft
names right receipts (one or two, distinct Deposits of the Settlement's Lease, together at most the
corrected receipt) writes each, linked, from the same Payment's freed value, then runs the shared
DL-032 step with the draft's plan. The recorder checks that plan with an overlay of the
correction's effect: each obligation whose Deposit applications are reversed at its open amount
plus those applications, and `deposits_after`, each named Deposit's held value after the
correction (absolute; above 0 only for a Deposit on the DL-032 path); the confirm-time step checks
the recorded result on the real state. Refused (55000 unless named): an unknown Deposit (P0002), a
Deposit of another Lease, a kept Deposit, a Deposit with a forfeiture ground (until sub-slice
10e-2c, Q-2026-10-12-88), more than the corrected receipt frees, a Payment that cannot fund the
Deposit, another active receipt of the Payment in it, more than its required amount takes, a
correction that also charges a recovered Refund on this Lease (until sub-slice 10e-2b-2), a plan
that leaves new money unused. The money the receipts do not take stays unallocated with the
Payment (BR-CREDIT-002).

As built in V1-056 sub-slice 10e-2b-2 (migration `20261127_123`; the owner instruction of
2026-10-12 with the answers to Q-2026-10-12-88; owner answer 1 to Q-2026-10-12-89): a
`DEPOSIT_RECEIPT_CORRECTION` with right receipts may also charge back a Refund paid from the
corrected receipt's Deposit on this Lease. The recorder names each such recovery charge as a
placeholder line (`md5('deposit-receipt-recovery:' || draft || ':' || refund)::uuid`; the service
helper `deposit_receipt_recovery_line_id` computes the same id) in the plan overlay key
`new_obligations`: the line id to `{refund_id, customer_id, lease_id, amount_usd_cents}`, so the
draft shows the person and the exact amount and the plan may pay it. The shared plan check accepts
that key (each id a UUID string, the amount above 0 within the overlay limit, else 22023; another
Lease or an existing obligation 55000), counts each placeholder as open debt of its Customer
(never pet damage; no Rent-first proposal, as the real one-line Miscellaneous Invoice has none),
and counts the Credit of a placeholder Customer whom the preview does not name yet (a signed
Signer on no issued Invoice of the Lease) as the preview reads it once the charge's Invoice names
that Customer. At the confirm the shared step first runs the internal
`app.assert_settlement_correction_placeholder_lines` (P5S02, the draft stays pending): each
placeholder is a real recovery charge linked to the correction (its `RECOVERED_BY_CHARGE` row of
DB-REFUND-002) with the same Customer, Lease and amount, each names a distinct Refund, and every
recovery charge of the correction on the Lease has its placeholder; on the real path the source
digest and the recovery writer's own P5S02 check fire first. Then every step on a placeholder pays
the real line through the internal `app.settlement_correction_line_id` (the step's plan check,
its Deposit applications, the Credit step writer and the three checks that match a correction's
Credit or Deposit application with its plan step); any other target is unchanged. The plan lock
pass skips a placeholder line: it is written in the same transaction. The 10e-2b-1 refusal of such
a correction is lifted. Refused (55000, an approved tightening, also at the confirm): a receipt
correction that writes the same receipt again into the same Deposit (the same Payment and amount);
it must change the Deposit or the amount. The receipt writer `app.write_correction_deposit_receipt`
also requires its correction's decision confirmed in the same transaction by the same approver
under `financial.approve` (hardening, 10e-2b-1 review round 2). No table or column changes.

As built in V1-056 sub-slice 10e-2c (migration `20261128_124`; owner answers to Q-2026-10-12-88,
point 1 (b) and point 2 (c)): the effects gain the link `deposit_disposition_id` (DB-DEP-004 Lease
forfeiture; deferrable, unique; the one-link check and the two link functions rebuilt), so the
closed-Settlement check of the forfeiture insert (sub-slice 10c-2b-2a) passes a forfeiture that a
correction confirmed in the same transaction links. A right receipt into a Deposit whose
termination ground says the Property keeps it is no longer refused: when that Deposit was never
forfeited, the same correction forfeits the receipt's money on the ground (staff choose nothing);
when its forfeiture was reversed first, each right receipt item carries the staff's choice
`outcome` (`DL_032`, the 10e-2b path, or `FORFEIT`, forfeited again) with `outcome_reason` (1 to
500 characters; both or neither); any other Deposit takes no choice (55000). The draft stores the
forfeitures as `deposit_receipt_forfeitures` (Deposit, type, amount, ground rule, reason, basis
`TERMINATION_GROUND` or `STAFF_CHOICE`; only when there is one) and `deposits_after` leaves their
money out of the plan. The confirm computes the forfeitures again under the locks (P5S02 when they
differ, the draft stays pending) and, after the right receipts and before the shared DL-032 step,
writes each through the internal `app.write_correction_deposit_forfeiture` (no grant): only a
forfeiture its correction's draft names, only inside that correction's confirm; linked first, then
its disposition context and the forfeiture row (authorization reference `deposits.dispose` as the
tables require, the termination date as effective date, `occurred_at` after the receipt, the
approver as actor), a `deposit.disposition.recorded` Deposit audit event under `financial.approve`
correlated with the correction, and its Deposit command record; every Lease forfeiture insert
check runs. The context's expected Deposit state version is read just before the insert, so its
P5801 check cannot fire on this path; staleness is held by the source digest, the forfeiture
recompute and the writer's exact held-value check. A changed pay-back count, held value or kept
state usually meets the targets check first (55000; the draft stays pending as well).
Refused (55000): a forfeiture that would take other money than the new receipt's (the Deposit
would hold other money afterwards).
The result gains `deposit_disposition_ids`.
As built in V1-056 sub-slice 10e-2d (migration
`20261223_149`; owner answer (a) to Q-2026-10-12-93): a forfeiture takes only the new money beyond
the Deposit's pay-back count (the receipt less the smaller of the count and the receipt); the rest
stays in the Deposit as the Customer's pay-back money and follows DL-032 in the same correction's
plan (the overlay's `deposits_after` keeps it, and the plan check accepts such a Pet Deposit with
a ground, because after the correction it holds only pay-back money; the confirm-time step reads
the real path). When the count covers the whole receipt nothing is forfeited and the draft lists
no forfeiture for it; a staff choice `FORFEIT` is then refused (55000, "Nothing beyond the
Customer's pay-back money is left to forfeit; choose DL-032"). The forfeiture writer's exact check
(the Deposit holds the forfeited amount beyond its pay-back value) is unchanged.
With owner answer (b) to Q-2026-10-17-122 (same sub-slice), the count is the pay-back money the
Customer has not received yet (DB-DEP-005, 10e-2d bullet): a Pet Deposit whose pay-back money the
Final Settlement or a correction already applied or refunded has a count of 0, so its new receipt
is forfeited whole. The corrected receipt's own Deposit is counted without its payouts, because
this correction undoes them (the Deposit must end empty; a count that would still be too high fails
closed at the confirm, where the forfeiture writer's exact check and the step read the real
count): the targets read
`app.lease_deposit_payback_count_as(deposit,NULL,0,true)` for it, the overlay names it
(`corrected_deposit_id`, a string that `deposits_after` names; `app.settlement_correction_plan_result`
refuses any other value with 22023), and the plan check compares with the same count. The 10e-2c
sentence above, that a changed pay-back count usually meets the targets check first, still holds:
after closure the count changes only with a held change or a payout that the targets read again.

As built in V1-056 sub-slice 10f-2 (migration `20261221_147`; DB-SETTLE-005, DB-INV-010): the
`ADJUSTMENT_REVERSAL` variant links its `invoice_adjustment_reversals` row
(`invoice_adjustment_reversal_id`) and each labelled put-back (`customer_credit_application_id`, a
Credit application with no Final Settlement) to the correction before it writes them; the reversal is always its first effect. Its
decision also stores the reversal id, the put-backs and the debt that stays, which the 10f-1b
put-back checks read (DB-CREDIT-002). No table, column or effect kind changed.

As built in V1-056 sub-slice 10g (migration `20261222_148`; owner answer 4 to Q-2026-10-06-36 and
answers 1 and 5 to Q-2026-10-06-37): the `PAYMENT_MOVE` variant links the wrong allocation's
reversal (`payment_allocation_reversal_id`, its first effect) and the new allocation of the same
Payment to the correct Invoice (`payment_allocation_id`), which may be another Lease's Invoice
(the first exception of owner answer 5). The source allocation must be one this Settlement relied
on: an Invoice allocation of its Lease, not reversed, posted at or before the closure or linked to
a correction of this Settlement. An allocation that a correction of another Final Settlement
wrote (another Settlement's `PAYMENT_MOVE` target) is refused (55000) until the owner answers
Q-2026-10-17-120, so this correction never changes a record that another Settlement's correction
wrote (the condition of owner answer 5). The correct Invoice may belong to a Lease whose Final
Settlement is closed: the new allocation pays its remaining debt and its closure snapshot does not
change. No table, column or effect kind changed. Since sub-slice 10g-2 (migration
`20270107_164`; owner answer (a) to Q-2026-10-17-121) the Payment's Customer Credit or Refund
refuses this variant only when a credit Adjustment released part of an allocation of that Payment
on the wrong Invoice (DB-PAY-008).

V1-056 sub-slice 10h-1 (migration `20270108_165`; owner answers 3 and 4 to Q-2026-10-06-36,
answer 5 to Q-2026-10-06-37, Q-2026-10-07-39, the owner note of 2026-10-16 on the 10f-2 report
and point 2 of Q-2026-10-17-120): what a closed Final Settlement relied on is read by two new
internal functions (no grant), `app.closed_settlements_relying_on_allocation(allocation)` and
`app.closed_settlements_relying_on_credit_application(application)`: the closed Settlements of
the Lease of the record's Invoice (or of its Late-payment Charge's source Invoice) closed at or
after the record was made (`posted_at` or `occurred_at`), the Settlement of a Final Settlement
Credit application, and the Settlement of every correction whose effect links the record (the
definition of sub-slice 10e-1a). New BEFORE INSERT triggers
`a0_payment_allocation_reversals_relied_on` (`app.refuse_relied_on_allocation_reversal()`) and
`a1_customer_credit_application_reversals_relied_on`
(`app.refuse_relied_on_credit_application_reversal()`, named to run after the 8e-2 and 10c-1b
refusals, whose texts stay first for their records) refuse (P5S01, "A closed Final Settlement
changes only through a post-settlement correction") a reversal of such a record unless, for each
of those Settlements, `app.settlement_correction_linked` finds a correction of it confirmed in
this transaction that links the reversal (every correction writer links before it writes). Each
trigger first takes the insert check's own locks in its order (the payment state, the Payment,
for a Credit application the Credit, then the target), so a Final Settlement started or closed
during a lock wait is read after it (review round 1, security note 1). A record with no Final
Settlement on its Lease and no correction link then takes no Settlement lock; otherwise the
trigger takes the Settlement row of the target's Lease FOR SHARE (the 8e-1 order), so a running
Final Settlement confirm is waited for and its closure is then read. They cover every writer: the one-call reversals, the ordinary credit
Adjustment's release (which reverses before it writes the Adjustment), another Lease's `REFUND`
correction, and the slice 7 move. A record two closed Settlements relied on cannot be linked to
both and stays refused (Q-2026-10-17-120 point 1). The application services map P5S01 to a
conflict.

Since V1-056 sub-slice 10h-2 (migration `20270110_167`; owner answer (a) to Q-2026-10-19-143),
both triggers first refuse (55000, "A reversal of a Payment allocation or Credit application is
recorded at READ COMMITTED") a reversal written at any isolation level other than READ COMMITTED,
before any read, as the 8e-3 confirm does, so a snapshot taken before a Final Settlement started
cannot miss it. No application path writes a reversal at a stricter level. Owner answer 4 to
Q-2026-10-06-36 and answer 6 to Q-2026-10-10-69: a new BEFORE INSERT row trigger
`a0_deposit_disposition_reversals_final_settlement` on `app.deposit_disposition_reversals`
(`app.refuse_closed_settlement_forfeiture_reversal()`, no grant; it sorts before
`b_deposit_balance_source`) locks the Deposit row (the writers hold it already), then holds the
closed Settlement rows of the forfeiture's governing Lease and of the Deposit's Lease FOR SHARE,
and refuses (P5S01, the 8e-1 text "A closed Final Settlement changes only through a
post-settlement correction") a forfeiture reversal that a correction of each of them,
confirmed in this transaction, does not link (`deposit_disposition_reversal_id`; every
correction writer links first: the forfeiture reversal, returned-Payment and receipt
corrections). The Deposit lock orders it against a closing confirm: a Lease forfeiture's
governing Lease is its Deposit's Lease (`app.validate_lease_deposit_disposition`), and the 8e-3
confirm takes each Deposit of the Lease and its state guard before it closes and re-checks its
digest after that, so at READ COMMITTED the writer reads a closure committed during its wait,
and a confirm that waits for the writer finds its draft stale (P5S02); an open Settlement is not
locked, so there is no deadlock with a running confirm; a REPEATABLE READ or SERIALIZABLE writer
whose snapshot is older than the closure fails on the Deposit state guard (40001) in
`b_deposit_balance_source`. A correction of one closed Settlement that would reverse a
forfeiture of a Deposit whose other Lease has its own closed Settlement cannot link both and is
refused (fail closed, as for a record two Settlements relied on). The 6b source
`app.lease_deposit_reversal_source` (one exact-text replacement, after its already-reversed
check) refuses (P5S01) such a forfeiture, so the 6b recorder refuses at record and its confirm
(which calls the source after the Deposit lock) at confirmation; the draft stays pending. Since
V1-056 sub-slice 10h-4a (migration `20270112_169`; owner answer 1 of 2026-10-20 to the 10h-2
report) the same source first refuses (55000, "A Lease Deposit forfeiture reversal draft is
recorded and confirmed at READ COMMITTED") a call at any other isolation level, before any
read, so a snapshot older than a closure can neither record nor confirm a 6b draft; an exact
repeat of a recorded draft still replays first.

V1-056 sub-slice 10e-2b-4e-2a (migration `20270101_158`; owner answers (a) to Q-2026-10-18-134): a
`RETURNED_PAYMENT` correction of a shared Deposit links, besides its reversals and recoveries, the
kept parts it writes again: a Deposit application (`deposit_application_id`; the Deposit
application check accepts it through `app.settlement_shared_deposit_kept_application_allowed`, never
NULL: a `RETURNED_PAYMENT` draft whose stored source lists the same Deposit, stage, target and kept
amount, the listed application reversed by a reversal linked to this correction, once) and a
forfeiture (`deposit_disposition_id`; `app.write_correction_deposit_forfeiture` accepts a listed
kept part whose forfeiture this correction reversed, with the draft's reason; the forfeiture
table's held and pay-back limits stay). `app.settlement_returned_payment_result` gains
`deposit_application_ids` and `forfeiture_ids`. No table, column or effect kind changed (DB-DEP-007
note).

## DB-SETTLE-007 — `settlement_pet_classifications`

Added in V1-056 sub-slice 10c-2a-5 (migration `20261109_105`; owner answer to
Q-2026-10-07-45). The corrected pet classification of one Damage line after its Lease's Final
Settlement is closed, written only by a `PET_DAMAGE_RECLASSIFICATION` post-settlement correction.
The closed inspection record is never changed.

| Column | Type | Null | Rule |
|---|---|---:|---|
| `id` | `uuid` | no | PK; linked first by DB-SETTLE-005 `settlement_pet_classification_id` |
| `settlement_correction_id` | `uuid` | no | FK DB-SETTLE-003; unique (one record per correction) |
| `invoice_line_id` | `uuid` | no | FK; a `DAMAGE_CHARGES` line billed from a finding of a move-out inspection of the Settlement's Lease (a current one, or from sub-slice 10c-2a-7 also one superseded before closure), on an issued, non-VOID Invoice of that Lease |
| `pet_related` | `boolean` | no | the corrected classification; differs from the line's current one |
| `evidence_reference` | `text` | no | 1 to 500 characters |
| `reason` | `text` | no | 1 to 500 characters (the correction draft's reason) |
| `recorded_at` | `timestamptz` | no | not before the correction; later than the line's latest record; not later than the clock plus 5 seconds |
| `actor_id` | `uuid` | no | FK; the correction's approver |
| `authorization_reference` | `text` | no | `financial.approve` |

A BEFORE INSERT check (23514) locks the line's Invoice and needs the record linked in the same
transaction to its own correction of the line's own closed Settlement confirmed by its approver
(`app.settlement_correction_linked` and the effect row of `settlement_correction_id`), exactly as
that correction's `PET_DAMAGE_RECLASSIFICATION` draft prepared it (line, classification,
evidence, reason), a line billed from a finding of a current inspection (from sub-slice 10c-2a-7
also of one superseded before closure, below), and `recorded_at` later
than the line's latest record (review round 1). Append-only; no application role may read or
write it.
`app.invoice_line_is_pet_damage` reads the line's latest record (by `recorded_at`, then id)
before the inspection rule; records exist only after closure, so nothing before closure changes.

As built in V1-056 sub-slice 10c-2a-7 (migration `20261216_142`; owner answer (a) to
Q-2026-10-08-53): `app.settlement_pet_classification_line`, used by the recorder's plan and by the
insert check above, also accepts a line billed from a finding of a move-out inspection of the
Lease that was superseded; such an inspection was superseded before closure, because no
inspection of a Lease with a closed Final Settlement is superseded (sub-slice 10c-2a-4). Without a
record, `app.invoice_line_is_pet_damage` reads such a line as not pet damage (a finding's flag
counts only on a current inspection), so on a fresh line the same-classification refusal leaves
only the change to pet damage. The to-pet reversal rule is unchanged: the line's Security Deposit
applications are reversed only while a Pet Deposit on the DL-032 path holds money. After a to-pet
record, a later correction back to not pet damage passes by the latest-record rule (it corrects
the earlier correction; Q-2026-10-16-116). The recorder's refusal of a line that may not take the
correction now reads "A pet classification correction corrects only a Damage line billed from a
finding of a move-out inspection of this Lease" (55000, as before).

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

Amended by DL-071 (owner, 2026-10-20; answer 10): `refund_number` is given at confirmation, as `RFD` + 2-digit year of the confirmation date in `Asia/Phnom_Penh` + 4-digit running number restarting each year (for example `RFD260001`; 5 digits after 9999), never reused. A Refund draft carries only an internal draft reference, and staff no longer type a `refund_number`. Not built yet (V1-059).

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

As built (V1-056 sub-slice 10c-1b, migration `20261104_100`; owner answer 1 to Q-2026-10-07-39): a
post-settlement `REFUND` correction (DB-SETTLE-005) pays one Credit Refund per source it releases
(as amended by sub-slice 10c-2a-3, owner answer 2 to Q-2026-10-07-42: only for the value left in
that Credit after the shared DL-032 step, so none when the step used it all).
`settlement_correction_refund_details` (append-only; no role may read or write it), like
`final_settlement_refund_details`, records each such Refund's `refund_id` (PK, deferred FK so it
is written first), `settlement_correction_id`, the correction's `draft_id`, `refund_method_id`,
`reference_note` (1 to 500 characters) and `recorded_at`; a row is accepted only for a correction
confirmed in the same transaction with that draft and a Refund already linked to that correction,
and a deferred check needs its Refund processed by the correction's approver. The draft holds one method and one note, and
every Refund of the correction keeps them in its own row; the Refund row carries the recipient,
the Credit's Customer, which for every released source is the Invoice Customer (BR-CREDIT-014,
BR-CREDIT-008). The Refund row records `processed_by` the approver and `authorization_reference`
`refunds.create`, as every confirmed Refund draft. The general Refund source check and the
deferred `refunds_credit_customer_confirmed` check lift the payer rule also through
`app.settlement_correction_refund_allowed`: a Credit Refund paid to its Credit's Customer, with
its details row, processed by the correction's approver, linked (`refund_id`) to the correction
its details row names, confirmed in the same transaction, and, together with that correction's
other Refunds of that Credit, for at most what that correction's own Adjustment released to that
Credit. The Customer Ledger books it on the recipient in the `CREDIT` bucket, and the Refund
correction paths apply as for any Credit Refund.

As built (V1-056 sub-slice 10c-2a-2, migration `20261106_102`; owner answer 3 to
Q-2026-10-07-41): `settlement_correction_refund_details` gains `deposit_id` (nullable FK) and
`signer_agreement` (nullable, 1 to 2,000 characters; only with a Deposit), so a correction's
Deposit Refund keeps its Deposit and the written agreement of all Signers (BR-REFUND-015), as
`final_settlement_refund_details` does at the Settlement. The internal writer
`app.post_settlement_correction_deposit_refund` links the Refund to the correction, then writes
the details row and the Refund (`financial.approve`, processed by the correction's approver). The
table is unique on the correction and the Deposit (each Deposit refunded at most once per
correction), and its deferred check also needs the details to name the Refund's own Deposit (no
Deposit for a Credit Refund). The Final Settlement Deposit Refund source check hands a Refund whose correction details
name a Deposit to `app.assert_settlement_correction_deposit_refund_source`, which accepts only the
Refund of a correction confirmed in the same transaction, linked to it, processed by its approver,
matching a `DEPOSIT_REFUNDS` step of its plan, at most one per Deposit per correction, with the
8d rules (DL-032 path, no waiting receipt reversal or forfeiture draft, active method, the
BR-REFUND-015 recipient, the held amount, chronology, and no open Lease debt a Deposit could pay);
everything else stays refused. `app.settlement_correction_refund_allowed` (Credit Refunds) also
needs a details row that names no Deposit. One method, note, recipient and agreement per
correction draft (Q-41 answer 3). The one-call Refund corrections refuse such a Refund (8d).

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

As built in V1-056 sub-slice 10c-2b-1 (migration `20261111_107`; owner answer 4 to the 10c-1b
review record, an approved tightening): a Refund that a post-settlement correction paid (it has a
`settlement_correction_refund_details` row) is corrected only through another post-settlement
correction. The one-call verified return and the one-call reversal refuse it (P5202, through
`app.require_correctable_usd_refund`), and the BEFORE INSERT check refuses every row for it
(23514) except the verified return of its own `REFUND_RETURN` correction
(`app.settlement_refund_return_allowed`): a `VALUE_CORRECTION` under `financial.approve`, linked
to a correction of the Refund's own Final Settlement confirmed in this transaction, written by
that correction's approver, with the amount, return date, return method reference and evidence
its draft names, one return per correction. No one-call row reverses such a return; since sub-slice
10e-3 only a `RETURN_REVERSAL` correction does (below).

As built in V1-056 sub-slice 10c-2b-2a (migration `20261112_108`): the same pass applies to a
Final Settlement Deposit Refund (8d) and a correction's Deposit Refund, whose one-call
corrections stay refused; the check reads such a Refund's own Deposit for its lock and chronology,
and binds the row's reason to the draft's.

As built in V1-056 sub-slice 10c-2b-2b (migration `20261113_109`; owner answer 6 to
Q-2026-10-08-55, an approved tightening): once the Lease's Final Settlement is closed, a Pet
Refund-review Refund (DL-053) is corrected only through a post-settlement correction. The
one-call verified return and the one-call reversal of a return refuse it (P5S01, a conflict,
through `app.require_correctable_usd_refund`, after the Deposit lock; a REPEATABLE READ caller
whose snapshot predates the closure fails earlier on the Deposit guard, 40001), and the BEFORE INSERT check
refuses every row for it (P5S01) except the verified return of its own `REFUND_RETURN`
correction. So a return recorded with one call before closure is never reversed after closure,
also when a return-only correction leaves the Pet Deposit holding money (owner instruction of
2026-10-09). Before closure both one-call paths work as before.

Amended and built in V1-056 sub-slice 10e-1c (migration `20261122_118`; owner answer (a) to
Q-2026-10-10-72 point 1, a relaxing change): `correction_kind` also accepts `RECOVERED_BY_CHARGE`,
and the nullable unique column `recovery_obligation_id uuid FK authorized_nonrecurring_obligations`
names the charge that recovers the Refund (required exactly for that kind, CHECK
`refund_recovery_obligation_shape`). Such a row gives the Refund's whole net amount back to its
source on paper (the Payment, the Credit or the Deposit), so the returned Payment's reversals can
run; the Refund itself stays, because the money really left; no verified-return fields, no
reversed correction, `authorization_reference` `financial.approve`. The BEFORE INSERT check
(`app.refund_recovery_allowed`) accepts it only inside the confirmed return of the Refund's own
source Payment (directly, through one of its Credits, or through a receipt of the Refund's Deposit
not yet reversed) in this transaction, written by that return's approver, naming a charge created
in this transaction by that approver with `source_reference` `refund-recovery:<refund id>`, of the
same amount, to the Refund's recipient; for a Refund of a closed Final Settlement (its Deposit's
Lease, or paid by a correction) only when a correction of that Settlement links the row; otherwise
23514. Since sub-slice 10e-2 (migration `20261124_120`) it also accepts the row, with the same
charge conditions, inside a `DEPOSIT_RECEIPT_CORRECTION` confirmed by the same approver in this
transaction that links the row and whose receipt, not yet reversed, is in the Refund's Deposit.
Its audit action is `refund.recovered_by_charge`; the Customer Ledger shows it as
`REFUND_CORRECTED` (the readers of a source balance sum its effect with no change) and the Credit
history as `REFUND_RECOVERED_BY_CHARGE`. The Refund resource and the financial action context leave
the new column out, so their shape is unchanged (the staff screens accept exactly the existing keys);
the return results name the charge. No row reverses a recovery: a recovered Refund whose money later
comes back cannot take a verified return (its net is 0; a known limit).

Since sub-slice 10e-3 (migration `20261129_125`): the recovery check also accepts the row, with the
same charge conditions, inside a `RETURN_REVERSAL` correction confirmed by the same approver in
this transaction that links the row, for a Refund that the reversed return's correction or a
`HELD_VALUE_REFUND` naming it paid from the returned Refund's own Credit or Deposit and that the
draft's recorded recoveries name with the Deposit's own Customer as recipient. The general
check accepts a `CORRECTION_REVERSAL` row of a correction's return only inside its
`RETURN_REVERSAL` correction (`app.settlement_return_reversal_allowed`: the whole amount, the
draft's reason and evidence, `refunds.corrections.reverse`, the approver as actor, linked to that
correction of the Refund's own Settlement, confirmed in this transaction); a one-call reversal stays
refused. Its reversal branch now reads every Deposit Refund's source by `source_deposit_id` (the
Deposit's held value, no Payment status), so an over-reversal of any Deposit Refund is refused.

Since sub-slice 10e-3b (migration `20261130_126`; owner answers (a) to Q-2026-10-12-94 and (a) to
Q-2026-10-12-95): the recovery check's recorded recipient is the Refund's own recipient (an agreed
second Signer too), not only the Deposit's own Customer. Inside a `RETURN_REVERSAL` a
`RECOVERED_BY_CHARGE` row recovers exactly the amount the draft recorded for that Refund (the
internal `app.settlement_return_reversal_recovery_amount`, no grant; the draft must be confirmed in
this transaction by the correction's approver, who is the row's actor; a second recovery of the
same Refund in the same correction, or a draft that names the Refund more than once, is refused),
which can be a share below the net; the row's
resulting net is then the net less the share, so a partly recovered Refund keeps a net. Every other
recovery is still the whole net. The recovery writer takes an entry's `net_usd_cents` only inside a
`RETURN_REVERSAL`; for any other caller an entry whose amount is not the whole net is stale (P5S02).
Each recovery charge has its own source reference (the internal
`app.refund_recovery_source_reference`, no grant): the first is `refund-recovery:<Refund>` as
before, a later one adds its number (`:2`, ...; it counts the recoveries dated before the row, so
the check gives the same answer before and after the row is written), so the rest of a partly
recovered Refund can be
charged back by a later correction (for example the return of the Payment that funded its
Deposit) without breaking the obligation key (Customer, category and reference).

Since sub-slice 10e-3d-2c (migration `20261210_136`; owner answer (a) to Q-2026-10-13-103 point 1;
the DB-SETTLE-005 paragraph of that sub-slice gives the rule): inside a `RETURN_REVERSAL`, the
reversal of the earlier return counts the charge-back of the returned Refund that the same draft
lists as available in the source (internal `app.settlement_return_reversal_charge_back`, no grant)
and, when it covers the whole reversal, as standing for a source Payment that is no longer
received; that charge-back is a `RECOVERED_BY_CHARGE` of the returned Refund itself, in the
recovery scope when the draft names a `RETURNED_REFUND` part of it, written right after the
reversal with the reversal's exact `occurred_at` (internal
`app.settlement_return_reversal_paired_charge_back`, no grant: the general check accepts that one
paired row at the latest time; any other row at the latest time, or earlier, is still refused).

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

As built in V1-056 sub-slice 10c-2a-1 (migration `20261105_101`): the reversal of such an
application by a post-settlement correction (DB-DEP-006) is the event
`DEPOSIT_APPLICATION_REVERSED` (event order 76), with the same two components and the opposite
effect (the Deposit holds the amount again; the Invoice line or Charge owes it again); its
evidence names the reversal, the application, the Settlement, the stage, the Deposit owner, the
obligation's Customer and the reversal reason. The ledger page accepts it as a history filter.
Every earlier projection result is unchanged.

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

Account class (DL-081, login sub-slice L1a, migration `20270118_175`): the separate
append-only relation `user_account_classes` gives an account at most one class (`owner`,
`manager` or `staff`), which ties the Owner-only rights to the class, not to a role name. At
most one `owner` row exists (the bootstrapped Owner, classed by the bootstrap); an `owner` or
`manager` account requires MFA (`mfa_policy_class` `required`, checked when the class is given
and when the MFA policy changes); an MFA policy is lowered only at READ COMMITTED; a class, once
given, is never updated, deleted or truncated. An account without a class cannot sign in, does
not resolve for recovery and (from L1b) has no grants (fail closed). Only the migration owner
and the protected bootstrap give a class today; later, only reviewed definer functions.

## DB-AUTH-002 — Password credentials

Password credential rows store only a salted adaptive password-verifier encoding,
algorithm/work-factor metadata, change time, and lifecycle/audit provenance. Plaintext,
reversibly encrypted passwords, security questions, password values in audit snapshots,
and reusable bootstrap secrets are prohibited.

Amended by DL-081 (login sub-slice L4, Q-2026-10-24-185, decided by Claude under the owner's 2026-10-23 22:30 rule; migration 20270204_192): a one-time password is one append-only row (`app.one_time_passwords`: the account, the Owner, the reason, the issue time and its end 24 hours later on the database clock) and its Argon2id verifier on the account's password row, which names it (`one_time_password_id`) until the person chooses a new password. The change step is a 10-minute pre-authentication record with no session and no actor, completed once; each change is one append-only row. The runtime role reads only `one_time_password_id` of the password row (column grant) and never writes a password row: every write runs in `app.issue_one_time_password` or `app.change_one_time_password`, which take the `password-credential:` lock (the issue first takes `recovery-codes:`) and end every session of the account in the same step. The password itself is never stored or logged.

## DB-AUTH-003 — MFA and recovery-code state

MFA enrollment state and protected verifier material are stored separately from role
authority. Owner and Manager accounts cannot enter normal privileged operation until
required MFA enrollment is complete; Staff enrollment may be absent. Recovery codes
have independently verifiable one-time identities and consumed timestamps. If server
verification material is retained, it is non-reversible; usable recovery codes are
never stored in plaintext.
Amended by DL-081 (login sub-slice L3c-2a, migration `20270130_187`): a password-checked sign-in
of an account that needs MFA (MFA policy `required`, or an active sign-in code) writes one row of
`app.sign_in_mfa_challenges` with only the sha256 digest of the pre-authentication token, the
purpose (`challenge` or `enrollment`), for a `challenge` the active sign-in code of its own
account it was made for (checked at insert; it completes only with that code while active), the
sha256 digest of the password verifier that was checked and the wrong-try digests; it lasts 5
minutes by the database clock and changes only by one completion before that.
`app.totp_used_steps` keeps each used TOTP time step of an enrollment (append-only; the guard
locks the enrollment row; a step not after the last used one, after the current step of the
database clock, or of an enrollment that is not active is refused), so a sign-in code is used
once. The runtime role has column privileges only.
Amended by DL-081 (login sub-slice L3c-2c-1, migration `20270201_189`): an account has at most one
`app.recovery_code_sets` row that is not invalidated (the partial unique index
`recovery_code_sets_one_live_per_actor`); the API writes the first set (provenance
`auth-recovery-codes`) and a regenerated set (`auth-recovery-codes-regenerated`, after the prior
set is invalidated by the account itself), each with 10 Argon2id verifiers. The codes of an
invalidated set keep their own `invalidated_at` empty, so every check of a code also needs its
set not invalidated.
Amended by DL-081 (login sub-slice L3c-2b, migration `20270131_188`): a sign-in code set up at
sign-in is a `pending` row of `app.totp_mfa_enrollments` written by the account itself (provenance
`auth-mfa-enrollment`, the key identifier derived from the key file) and one row of
`app.sign_in_code_enrollment_starts` that ties it to its open `enrollment` challenge (append-only;
one per challenge and per sign-in code; the insert guard checks that the challenge is open and of
its own account, that the account is active, classified, with MFA `required` and no active
sign-in code, and
that the code is a new pending code of that account made since the challenge). The first right
code activates it (by the account itself). A later sign-in's set-up turns off a pending code
never confirmed (provenance `auth-mfa-enrollment-replaced`). The runtime role has column
privileges only.

## DB-AUTH-004 — Sessions and revocation

Durable session records contain only protected token identifiers/verifiers, user,
creation, last-activity, absolute-expiry, idle-expiry/recalculation data, revocation
time/reason, and audit provenance. They enforce a 30-minute inactivity timeout and
24-hour absolute lifetime. Password/MFA recovery, account disablement, and material
privilege reduction can revoke all applicable sessions promptly.
Amended by DL-081 (login sub-slice L3a-2, migration `20270127_184`): a revocation records the later
of its statement time and the session's last activity, so an activity that a parallel request
committed after the revoking statement started never makes the revocation fail
(`app.protect_browser_session_lifecycle` replaced with the same signature, owner, privileges and
attributes).
Amended by DL-081 (login sub-slice L3c-2a, migration `20270130_187`): a session made by a
completed sign-in code challenge gets one row of `app.browser_session_mfa_proofs` (the session,
the challenge, the method `totp` or `recovery_code`, the enrollment for `totp`; append-only; the
challenge must be completed and of the session's own account, the session not revoked and made
after the challenge, and a `totp` proof must name the challenge's own sign-in code with a step
used since the challenge). A session of an account that needs MFA counts as live (the session
read, the actor resolver and its activity write) only with that proof, and a `totp` proof counts
only while its sign-in code is active.
Amended by DL-081 (login sub-slice L3c-2b, migration `20270131_188`): the proof guard
(`app.check_browser_session_mfa_proof`, replaced with the same signature, owner and privileges)
keeps every earlier condition and also accepts a `totp` proof of a completed `enrollment`
challenge that names the sign-in code the challenge started, with a step of it used since the
challenge. The session's `mfa_assurance` is the proof's method only while the proof counts, else
`none`.
Amended by DL-081 (login sub-slice L3c-2c-2, migration `20270202_190`): a proof has a
`recovery_code_id` (unique, a foreign key to `app.recovery_codes`; present exactly for the method
`recovery_code`; insert and select privileges for the runtime role), and the proof guard
(replaced again, every earlier condition kept) needs, for `recovery_code`, a `challenge` (not an
`enrollment`) and a recovery code of a live set of the challenge's account, made no earlier than
the sign-in code the challenge was made for, consumed by that account since the challenge. A
`recovery_code` proof counts while the sign-in code its challenge was made for is active and the
code's set is live, so a sign-in code reset and a regeneration also end recovery-code sessions.
Amended by DL-081 (login sub-slice L3d-1, migration `20270203_191`): a session's high-risk
reauthentications are rows of `app.browser_session_reauthentications` (append-only; the method
`totp` with the sign-in code and its time step, at most one row per step, or `password` for an
account that needs no MFA; the insert guard checks a live session of the row's account, for
`totp` the account's active sign-in code with a step used since the row's transaction began, and
refuses `password` for an account that needs MFA); the session's `reauthenticated_at` is its
latest row's time.

Amended by DL-081 (login sub-slice L3d-1 review round 2, owner answer of 2026-10-24 to
Q-2026-10-24-183): each row also keeps `token_verifier`, the sha256 digest (32 bytes, one row per
digest) of the separate reauthentication cookie set by that reauthentication; the cookie itself
is never stored. A session shows `reauthenticated_at` only for the row of the cookie the browser
sends with it, so a copied session cookie alone shows none. This replaces "the session's
`reauthenticated_at` is its latest row's time".

Amended by DL-081 (login sub-slice L3d-2, Q-2026-10-24-184, no migration): a sign-in completed
with the sign-in code and a confirmed sign-in code set-up also write a `totp` row for the new
session (the step the sign-in used), in the same transaction. Each high-risk administration
action reads first, in its own transaction, the row of the request's reauthentication cookie for
the request's live session: method `totp`, not older than 15 minutes on the database clock, no
newer `totp` row of the session, and its sign-in code still the account's active one; the
session is held `FOR SHARE` until the action commits.

## DB-AUTH-005 — Recovery and bootstrap audit

Administrative recovery, emergency Owner recovery, MFA enrollment/reset/disablement,
credential reset, recovery-code use, session revocation, and initial Owner bootstrap
produce immutable security audit events without secrets. A database invariant or
equivalently strong transactional guard prevents initial-Owner bootstrap after the
initial Owner is established and prevents bootstrap from becoming an additional-Owner
backdoor.

Amended by DL-081 (login sub-slice L4): the Owner's reset, the first password of a new account and the one-time password given when a Staff account's required MFA is turned off each write one completed administrative row in the recovery audit and one `identity.account.one_time_password_given` event in the administration history, with the reason; a forced change writes one change row. None holds the password or its verifier. The old administrative mode of `app.perform_account_recovery` is refused; its emergency mode resets a sign-in code only together with a new password.

## DB-AUTH-006 — Capability catalog

Added by DL-081 (login sub-slice L1b-1, migration `20270119_176`). `capabilities` holds one
append-only row for every capability the server checks: its lower-case dotted identifier (at most
128 characters), its family (the part before the first dot), a description, its grant path, the
time it was added and its provenance. The grant path says how the capability can be given:
`bundle` (a role bundle may hold it), `per_user` (`settings.manage`, given to one user by the
Owner), `owner_class` (`identity.manage_access`, only the Owner account class has it) or
`service_principal` (`rent_nonpayment.evaluate`); `billing.generate` is a bundle capability.
The pair of identifier and grant path is unique, so a bundle relation can refer to bundle
capabilities only (enforced from L1b-2). Rows are never updated, deleted or truncated; a new
capability is a new row, a name is never renamed, and a description is never corrected (a new
catalog row needs a security review). The application keeps the same catalog in
`property_rental.access_control`; a unit test fails when a literal dotted string in the
application code is neither a catalog capability nor a listed label. The runtime role may only
read the catalog.

## DB-AUTH-007 — Role bundles, assignments and effective grants

Added by DL-081 (login sub-slice L1b-2, migration `20270120_177`). `role_bundles` holds the
current state of each configurable bundle of a Property: its id, Property, name (trimmed, 1 to
128 characters, no C0 or C1 control character and none of the listed invisible format
characters (U+00AD, U+061C, U+180E, U+200B to U+200F, U+202A to U+202E, U+2060 to U+206F,
U+FEFF, U+FFF9 to U+FFFB and the tag characters U+E0000 to U+E007F), unique per Property
whatever its capital letters) and version; a new bundle starts at version 1, an update may
change only the name and must raise the version by exactly 1, and a bundle is never deleted or
truncated. Amended by DL-081 (login sub-slice L2c, migration `20270126_183`, Q-2026-10-22-169
(a)): the check constraint `role_bundles_name_visible_check` also refuses U+034F, the Hangul
fillers (U+115F, U+1160, U+3164, U+FFA0), the invisible Khmer vowels U+17B4 and U+17B5, the
line and paragraph separators U+2028 and U+2029, U+180B to U+180F, U+2800, the variation
selectors U+FE00 to U+FE0F, U+FFF0 to U+FFF8, U+1BCA0 to U+1BCA3, U+1D173 to U+1D17A and U+E0080
to U+E0FFF, a space other than U+0020, two U+0020 in a row, and a name that is not NFC; the API
removes U+200B from a name before saving it (it stays refused here). The migration refuses to
run while a stored username is not NFC or holds U+200B; display names and audit names saved
before it are not checked again (bundle names are, when the constraint is added), and each
later change of a name meets the new check.
`role_bundle_versions` keeps every version with its name (written by a trigger with the bundle),
and `role_bundle_capabilities` keeps the complete capability set of every version: a capability
in a bundle must be a catalog capability with grant path `bundle` (a foreign key on the
capability and its grant path), so `settings.manage`, `identity.manage_access` and
`rent_nonpayment.evaluate` can never be in a bundle; capabilities are written only for the
bundle's current version and only by the transaction that wrote that version (its transaction
id and its start time, so a logical restore that lets a later transaction reuse an old id still
cannot add to a recorded version), so a recorded version never changes. `user_role_assignments` records each assignment of a bundle to an account
with the bundle's Property and the account that assigned it (null only for seeds); an account
has at most one active assignment of a bundle (checked under a lock, at READ COMMITTED only);
`user_role_assignment_removals` ends an assignment at most once, with a reason and the account
that removed it. The four history relations are never updated, deleted or truncated. The
definer function `actor_capability_grants(actor_id)` returns the effective capabilities with
their Property for an active, classified account only: the capabilities of the current version of
every actively assigned bundle, and `identity.manage_access` for every Property when the account
class is `owner`. A removed capability or assignment stops at the next read. The runtime role may
only execute that function; the writers (default bundles, administration) are reviewed definer
functions of later sub-slices.

## DB-AUTH-008 — Per-user Settings access

Added by DL-081 (login sub-slice L1d, migration `20270121_178`; owner answer (a) to
Q-2026-10-21-151). `user_capability_grants` records each grant of `settings.manage` (the only
capability stored there, with grant path `per_user`) to one account: the account, when, who gave
it, a reason and provenance; an account has at most one active grant (checked under a lock, at
READ COMMITTED only; a removal takes the same lock and also runs at READ COMMITTED only). `user_capability_grant_removals` ends a grant at most once, with when, who
and a reason. Both are never updated, deleted or truncated. Only the definer functions
`give_settings_access(owner, account, reason)` and `remove_settings_access(owner, account,
reason)` write them for the application: the acting account must be the active Owner account
class; a grant goes only to an active Manager or Staff account (the Owner always has Settings
access); a removal needs only an active grant, so the Owner can also remove the Settings access
of a disabled account, which then does not come back when the account is enabled again.
`actor_capability_grants` also returns `settings.manage` for every Property (the deployment has
one) to the Owner account class and to an active, classified account with an active grant, as it
returns `identity.manage_access`; a removal takes effect at the next read and
revokes nothing else. The runtime role may execute the two functions and the reader only.

Amended by DL-081 (owner rule of 2026-10-21; login sub-slice L1e, migration `20270123_180`):
`give_settings_access` refuses a Staff account whose MFA policy is not `required` or that has no
`active` sign-in code enrollment (`totp_mfa_enrollments`), with the plain message "a Staff
account gets Settings access only after it has set up its sign-in code"; a Manager needs no
enrollment check here, because its class always requires the code at sign-in. The reader gives
a Staff account's per-user `settings.manage` only while its MFA policy is `required` and it has
an `active` enrollment, so a sign-in code reset, a lowered MFA policy or a grant written another
way gives nothing; the grant row itself stays until the Owner removes it (Q-2026-10-21-165).
Both use the internal function `staff_sign_in_code_is_set_up(account)`, which no application
role may execute.

Amended by DL-081 (owner answer (a) to Q-2026-10-21-167, 2026-10-22; login sub-slice L2b-1,
migration `20270125_182`): the runtime role may no longer execute `give_settings_access` and
`remove_settings_access`, which write no audit event. It gives and removes Settings access only
through the audited `admin_give_settings_access` and `admin_remove_settings_access` of
DB-AUTH-010, which call them as their owner and write the audit event in the same transaction.

## DB-AUTH-009 — Default role bundles

Added by DL-081 (login sub-slice L1c, migration `20270122_179`; owner answers (a) to
Q-2026-10-21-150 and Q-2026-10-21-164, G7). `default_role_bundles` records, once per Property,
which three role bundles are its defaults (`owner_bundle_id`, `manager_bundle_id`,
`staff_bundle_id`, each a bundle of that Property, all different), when and with what provenance;
it is never updated, deleted or truncated. Only the definer function
`seed_default_role_bundles(property)` writes it, at READ COMMITTED under a per-Property lock: for
a Property that has no defaults yet it creates the bundles "Owner" and "Manager", which hold every
catalog capability whose grant path is `bundle` at that moment, and "Staff", which holds exactly
the 31 approved daily-work capabilities (DL-081), all at version 1; it assigns the Owner bundle to
the Owner-class account, if there is one, as a seed assignment; for a Property that already has
its defaults it returns their ids and changes nothing, so a later catalog capability is never
added to an existing bundle by itself. The bundles stay configurable data (DB-AUTH-007). The
migration seeds the Property that already exists; the Property setup calls the function in the
same transaction as `initialize_property`. The runtime role may execute the function only.

## DB-AUTH-010 — Account and role bundle administration

Added by DL-081 (login sub-slice L2a, migration `20270124_181`; API-079, API-080, owner answers
(a) to Q-2026-10-21-152, Q-156 and Q-165). Only the active Owner account class administers
accounts, role bundles, assignments and Settings access, through definer functions that the
runtime role may execute; each refuses any other acting account and any isolation level other
than READ COMMITTED, and each write function writes one immutable `audit_events` row (actor, action, target, reason,
non-secret previous and resulting state, correlation id, `identity.manage_access`) in the same
transaction. `admin_create_account` makes a Manager (MFA `required`) or Staff (MFA `optional`)
account with its class, its HUMAN identity and the class's default bundle of DB-AUTH-009, and no
password (the first password is the one-time password of the Owner's reset); never an Owner.
`admin_update_account` changes a Manager or Staff account's display name, audit name, MFA policy
or lifecycle (disable only) with its expected version, or disables an account without a class;
`user_account_changes` keeps every change (version, who, when, non-secret previous and resulting
state) and is never updated, deleted or truncated; an account's version is 1 plus its number of
changes. A username, display name or audit name is 1 to 128 characters with no space at either
end and none of the control and invisible characters that DB-AUTH-007 refuses in a bundle name.
Amended by DL-081 (login sub-slice L2c, migration `20270126_183`, Q-2026-10-22-169 (a)):
`app.assert_account_names` also refuses the characters and spaces that DB-AUTH-007's
`role_bundles_name_visible_check` adds, and a name that is not NFC, so every username an
administration function writes is NFC.
Amended by DL-081 (login sub-slice L2d, Q-2026-10-22-170 (a); no schema change): the API and the
flow tidy odd and double spaces in a name before calling these functions (every space separator
becomes U+0020, a run of them one, none at either end), so their space checks only refuse a caller
that skips the API; the sign-in lookup tidies the typed username the same way.
Session revocation (DB-AUTH-004): disabling revokes every unexpired session (`account_disabled`)
and keeps the account's assignments and Settings access as history (no function enables an
account again, and DB-AUTH-007 gives a disabled account nothing); raising a Staff account's MFA
policy to `required` revokes its sessions (`material_privilege_reduction`, provenance
`access-admin-mfa-required`); setting a Staff account's MFA policy to `optional` (MFA off, whatever
the policy was before) disables its sign-in code enrollment, revokes its sessions (`mfa_reset`)
when an enrollment was disabled, and removes its Settings access as a recorded removal with the
reason "sign-in code turned off"; an explicit revocation uses
`material_privilege_reduction` with provenance `access-admin-revoke-sessions` (the session table
has no closer reason); a role bundle update that takes a capability away revokes the sessions of
every active holder, and an assignment removal those of its account. Role bundles are created and
updated with only `bundle` grant-path capabilities and the expected version, each update writing
the complete set of its new version; assignments are made to an active account with a class (the
Owner included) and removed with a reason; Settings access is given and removed through the
functions of DB-AUTH-008 with the audit event added. Two definer reads give the Owner the account
list (class, version and recorded Settings access) and the bundle list (current capability set);
the runtime role has no privilege on the bundle, assignment, default bundle, Settings access and
account change relations.

## DB-AUTH-011 — Wrong sign-in tries and waits

Added by DL-081 (login sub-slice L3b, migration `20270128_185`; SEC-012, UI-109, DL-080 item 10 as
amended by the owner). Three append-only relations (UPDATE, DELETE and TRUNCATE refused):
`app.sign_in_wrong_tries` (one row per wrong try: the sha256 digests of the normalized username
and of the request source, the kind `password`, `sign_in_code` or `recovery_code`, the database
time), `app.sign_in_waits` (a username wait of 5 or 15 minutes or a source wait of 15 minutes,
with its start, its end and the try that started it) and `app.sign_in_try_clears` (a correct
sign-in of an active account clears its own username's tries up to the last one). The typed
username, the password and the source address are never stored as text; the keys are
pseudonymous sha256 digests without a key, so a list of names or the address range can be tried
against them (Q-2026-10-23-175). The count for a username is its wrong tries since the last clear: the 3rd
starts a 5-minute wait, the 5th a 15-minute wait, and every 2nd after that another 15-minute wait.
A source with 20 wrong tries in 15 minutes waits 15 minutes. Three definer functions, READ
COMMITTED only, are the runtime role's only access: `app.sign_in_wait_seconds` (the seconds left
of the longest active wait for the username or the source), `app.record_sign_in_wrong_try`
(records a try and starts a wait, or answers an active wait and records nothing) and
`app.clear_sign_in_wrong_tries` (answers an active wait and clears nothing, so a wait started by a
parallel try wins over a sign-in checked before it; clears only for the active account whose
normalized username gives the digest). Each takes the username lock and then the source lock, so
the wait read also waits for a wrong try being recorded. Because a correct sign-in clears only a
real account's count, an unknown username's count never clears; a patient guesser can compare
the two over days (Q-2026-10-23-176).

Amended by DL-081 (login sub-slice L3c-1, migration `20270129_186`, owner answer (a) to
Q-2026-10-23-175): when the API has the protected key file (`APP_TOTP_KEY_FILE`), the digests are
HMAC-SHA256 under a key derived from it with HKDF, so they can no longer be reversed by trying
names or addresses without the key; plain sha256 digests are used only in development and tests
(every other environment refuses to start with a database and no key file; `APP_ENVIRONMENT`
defaults to `development`, so a deployment must set it). Because the
database has no key, `app.clear_sign_in_wrong_tries` no longer compares the digest with the
account's username; it still clears only for an active account and answers an active wait
without clearing, and the application passes only the signed-in account's own digest. Rows
written before the key existed, or under an earlier key, no longer match, so the counts and waits
start again when the key is introduced or changed. Removing rows older than 30 days is on the
slice 12 list.

---

# 21. Deferred Technical and Configuration Decisions

No genuine Owner business-policy decision remains open in this Database Model. The
previous first-partial-month Due Date question is resolved upstream: Initial Rent is due
proposed as the Lease Start Date plus five calendar days, with an authorized override. The following implementation/configuration
choices must preserve
the normative model but do not reopen business policy:

- **TCD-DB-001 — Customer input quality:** choose legal-name/contact validation and
  duplicate-record matching controls without changing one-Customer identity or deleting
  history. No contact channel is made mandatory by this model. Amended by DL-071 (owner, 2026-10-20): an ID number already used by another Customer is refused; the same phone number or email address only warns (DB-CUST-001).
- **TCD-DB-002 — Refund delivery implementation:** delivery integration and transient
  technical delivery states may be designed later; only a successfully processed
  Refund is the approved business event persisted here.
- **TCD-DB-003 — Business-number generation:** configure formatting and sequence scope
  for Invoice, Payment, Receipt, and Refund Numbers while preserving uniqueness,
  immutability, and non-reuse. Amended by DL-071 (owner, 2026-10-20): the format is the type code (`INV`, `RCP`, `RFD`), the 2-digit year and a 4-digit running number per type and year, given at issue or confirmation; the Payment Number is its Receipt's number (DB-INV-001, DB-PAY-003, DB-RECEIPT-001, DB-REFUND-001).
- **TCD-DB-004 — Meter serial validation:** production configuration may enforce global
  or Utility-Type serial uniqueness when the source system guarantees that scope; the
  stable Meter UUID remains authoritative. Amended by DL-071 (owner, 2026-10-05): serial numbers are unique across all Meters of the Property (DB-UTIL-001).
- **TCD-DB-005 — Utility measurement configuration:** every Meter stores a nonblank
  production-configured unit code, and Utility Rate configuration uses the same unit.
  Electricity and Water fixtures cannot be finalized until their actual units/scales
  are configured; this is configuration, not a new charging rule. Amended by DL-071 (owner, 2026-10-05): the units are kWh for electricity and cubic metres (m3) for water.

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
| Authentication and account security | DB-AUTH-001..009 | SEC-001..003, SEC-009..018, SEC-020..022, SEC-071..075 | PR-CAP-009 |

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
