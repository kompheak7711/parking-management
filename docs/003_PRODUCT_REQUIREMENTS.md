# 003 - Product Requirements

**Project:** Property Rental Management System
**Document:** Product Requirements
**Version:** 1.0
**Status:** Owner Review
**Depends On:** `001_DOMAIN_MODEL.md`, `002_BUSINESS_RULES.md`
**Audience:** Product Owner, Business Analysts, Software Architects, Developers, QA Engineers

---

# 1. Purpose

This document defines the product capabilities, user workflows, functional requirements, non-functional product requirements, and acceptance expectations for the Property Rental Management System. It translates the authoritative domain in `001_DOMAIN_MODEL.md` and the operational policy in `002_BUSINESS_RULES.md` into testable product requirements without redesigning, renaming, relaxing, or extending either source.

**Shall** and **must** identify mandatory behavior. **May** identifies upstream-permitted behavior and creates no new obligation or right.

# 2. Authority and Governance

1. `001_DOMAIN_MODEL.md` governs concepts, terminology, relationships, invariants, lifecycles, scope, and exclusions.
2. `002_BUSINESS_RULES.md` governs policy, calculations, statuses, transitions, conditions, exceptions, and authorization requirements.
3. This document governs product capabilities, workflows, functional behavior, quality requirements, and acceptance expectations derived from those sources.
4. Each detailed `PR-*` shall be read with its traced `BR-*`. Section 8 reproduces the complete governing rule text so no condition, formula, exception, or prohibition is lost.
5. If a conflict is found, the upstream numbered specification controls pending correction. Unnumbered placeholders have no authority.
6. No implementation may infer a new feature, status, charge, fee, penalty, currency, exchange provider, estimation method, termination right, Refund right, role, permission, or authorization policy.
7. `PR-*` identifiers are stable: they shall not be renumbered or reused for a different requirement.

# 3. Scope

## 3.1 In Scope

The product shall support one Property's complete residential tenancy lifecycle: Property and Unit management; canonical Customers; Reservations; Security and conditional Pet Deposits; Leases, Occupancy, move-in, termination, and move-out; Utility Meters and Readings; Rent, Utility, service, damage, and miscellaneous Invoices; Payments and manual allocations; Customer Credit, Reversals, and Refunds; Final Settlement; and permanent operational, financial, and audit history.

## 3.2 Out of Scope

The product shall not provide multi-property portfolio management, commercial leasing, General Ledger or general accounting, Owner accounting, government tax reporting, banking integration, payroll, Human Resources, construction management, maintenance work-order management, procurement, inventory, automated Payment allocation, or smart-meter integration.

## 3.3 Specification Boundary

This document specifies externally observable business behavior. Database structures, API contracts, UI design, permission matrices, test implementation, security mechanisms, and deployment topology belong to later numbered specifications and shall conform without creating policy.

# 4. Users and Participation

The product shall represent a person once as a Customer and derive participation through relationships such as Reservation Customer, Primary Tenant, Lease Signer, Occupant, former tenant, or Payment payer. It shall not create permanent Customer types for these roles.

Property Management and authorized staff may initiate controlled actions where the Business Rules require authorization. This document neither names staff roles nor grants permissions; the later Security Model shall assign permissions without weakening `BR-AUTH-*`.

# 5. Product Capabilities

## PR-CAP-001 — Property, Unit, and Customer Management
The product shall manage exactly one Property, its Units and availability, and canonical reusable Customers while preserving history.
**Traceability:** `BR-PROP-001`–`BR-PROP-003`; `BR-UNIT-001`–`BR-UNIT-013`; `BR-CUST-001`–`BR-CUST-003`.

## PR-CAP-002 — Reservation and Deposit Management
The product shall support Reservation activation, holding, one authorized extension, end-of-date expiration, cancellation and responsibility classification, Deposit receipt and disposition, and coordinated move-in completion.
**Traceability:** `BR-RES-001`–`BR-RES-022`; `BR-DEP-001`–`BR-DEP-025`.

## PR-CAP-003 — Lease, Occupancy, Termination, and Move-out
The product shall support Lease drafting and signing, Primary Tenant and signer relationships, actual Occupancy, coordinated move-in, authorized termination, actual move-out, and operational Unit transition without fabricating tenancy terms.
**Traceability:** `BR-LEASE-001`–`BR-LEASE-025`; `BR-OCC-001`–`BR-OCC-009`; `BR-MOVEOUT-001`–`BR-MOVEOUT-012`.

## PR-CAP-004 — Billing and Invoices
The product shall generate deterministic Rent, configured fixed-service, Utility, damage, and miscellaneous charges and manage the complete Invoice lifecycle using only approved sources, categories, dates, rates, calculations, statuses, and corrections.
**Traceability:** `BR-RENT-001`–`BR-RENT-028`; `BR-UTIL-001`–`BR-UTIL-032`; `BR-SVC-001`–`BR-SVC-015`; `BR-INV-001`–`BR-INV-050`.

## PR-CAP-005 — Payments, Credit, and Refunds
The product shall record Payments, preserve currency and exchange facts, support authorized manual allocation, derive allocation condition, and process approved Credit, Refund, and Reversal events without rewriting sources.
**Traceability:** `BR-PAY-001`–`BR-PAY-035`; `BR-CREDIT-001`–`BR-CREDIT-012`; `BR-REFUND-001`–`BR-REFUND-012`; `BR-MONEY-001`–`BR-MONEY-013`.

## PR-CAP-006 — Final Settlement
The product shall coordinate final charges, Credit and Deposit application, Refund or balance due, permanent closure, and auditable correction for exactly one Settlement per terminated Lease.
**Traceability:** `BR-SETTLE-001`–`BR-SETTLE-015`.

## PR-CAP-007 — Authorization, Audit, and History
The product shall require explicit authorization for controlled actions and preserve permanent, reconstructable audit history.
**Traceability:** `BR-AUTH-001`–`BR-AUTH-009`; `BR-AUDIT-001`–`BR-AUDIT-010`; `BR-PROP-002`.

# 6. End-to-End User Workflows

## PR-WF-001 — Prepare and Reserve a Unit
An authorized user shall be able to identify a legally available Unit from authoritative facts, reuse or record one Customer, receive the minimum initial Security Deposit, and activate one Reservation. Conflicting availability or unmet activation conditions shall be rejected.
**Traceability:** `BR-UNIT-001`–`BR-UNIT-013`; `BR-CUST-001`–`BR-CUST-003`; `BR-RES-001`–`BR-RES-006`; `BR-DEP-001`–`BR-DEP-005`.

## PR-WF-002 — Extend, Cancel, or Expire a Reservation
The product shall grant only the eligible single extension with Notice history; cancel expiration at the local end-of-date boundary; classify the actual cause; preserve history; release the Unit; and perform only the required Deposit disposition or Refund.
**Traceability:** `BR-RES-007`–`BR-RES-012`; `BR-RES-015`–`BR-RES-022`; `BR-UNIT-010`; `BR-DEP-015`–`BR-DEP-019`; `BR-REFUND-004`.

## PR-WF-003 — Draft, Sign, and Move In
An authorized user shall be able to create the at-most-one resulting DRAFTED Lease, identify the Primary Tenant and signers, record contractual terms, sign only when valid, and complete move-in only after the Reservation, Unit, Lease, date, and Deposit conditions are met. Completion shall coordinate Reservation MOVED_IN, Unit OCCUPIED, opened Occupancy, and continuation of the same Security Deposit.
**Traceability:** `BR-RES-013`, `BR-RES-014`; `BR-LEASE-001`–`BR-LEASE-016`; `BR-OCC-001`–`BR-OCC-004`; `BR-DEP-005`–`BR-DEP-010`; `BR-UNIT-005`, `BR-UNIT-007`.

## PR-WF-004 — Operate and Bill an Active Tenancy
Authorized users shall be able to maintain actual Occupancy, approved pets and Deposits, recurring Rent and fixed services, Utility meters/readings/rates/approved estimates, Invoices, Payments, and manual allocations with full source and audit history.
**Traceability:** detailed `BR-OCC-*`, `BR-DEP-*`, `BR-RENT-*`, `BR-SVC-*`, `BR-UTIL-*`, `BR-INV-*`, `BR-PAY-*`, `BR-CREDIT-*`, and `BR-REFUND-*` requirements in Section 8.

## PR-WF-005 — Terminate and Move Out
An authorized user shall be able to act under the signed Lease, record actual termination and Move-out Dates, close Occupancy only after departure, set the Unit to its actual condition, capture final Utility handling and valid charges, and initiate Settlement. End Date alone shall not fabricate termination, move-out, renewal, holdover terms, Rent, fees, or penalties.
**Traceability:** `BR-LEASE-017`–`BR-LEASE-025`; `BR-MOVEOUT-001`–`BR-MOVEOUT-012`; `BR-OCC-005`, `BR-OCC-007`–`BR-OCC-009`; `BR-UNIT-008`, `BR-UNIT-011`.

## PR-WF-006 — Finalize Settlement
An authorized user shall be able to create the one required Settlement, finalize valid charges, apply Credit and Deposits in order, record each application separately, produce a balance or authorized Refund, and permanently close only after all prerequisites.
**Traceability:** `BR-SETTLE-001`–`BR-SETTLE-015`; `BR-DEP-014`, `BR-DEP-023`–`BR-DEP-025`; `BR-REFUND-007`.

## PR-WF-007 — Correct Without Rewriting History
Corrections shall use only the explicit modification, Adjustment, Reversal, Refund, replacement, disposition, or post-closure mechanism allowed by the governing rule and shall preserve the original fact and source chain.
**Traceability:** `BR-PROP-002`, `BR-PROP-003`; applicable `BR-UTIL-*`, `BR-INV-*`, `BR-PAY-*`, `BR-CREDIT-*`, `BR-REFUND-*`, `BR-SETTLE-013`, and `BR-AUDIT-*` detailed requirements.

# 7. Product-Wide Quality Requirements

## PR-QUAL-001 — Consistent Enforcement
The product shall enforce the same rules for UI, API, scheduled process, administrative workflow, and automated billing origins.
**Traceability:** all `BR-*`.

## PR-QUAL-002 — Deterministic Rejection
A violating action shall be rejected without silent input mutation.
**Traceability:** all `BR-*`; `002_BUSINESS_RULES.md` Section 14.

## PR-QUAL-003 — Financial Reconstructability
Every balance and result shall be reproducible from permanent source records, rates, allocations, applications, Adjustments, Reversals, Credits, Refunds, dispositions, and Settlement events.
**Traceability:** `BR-PROP-002`; all financial and audit rules in Section 8.

## PR-QUAL-004 — Historical Availability
Required operational, financial, rate, correction, and audit histories shall remain retrievable for reporting and audit.
**Traceability:** `BR-PROP-002`; `BR-CUST-003`; applicable history requirements in Section 8; all `BR-AUDIT-*`.

## PR-QUAL-005 — Authoritative Facts
Availability, occupancy, consumption, balances, allocation condition, and calculated summaries shall derive from authoritative records; a summary shall not authorize a conflicting action.
**Traceability:** `BR-UNIT-013`; `BR-UTIL-003`, `BR-UTIL-012`; `BR-INV-017`; `BR-PAY-008`–`BR-PAY-014`; `BR-SETTLE-002`–`BR-SETTLE-009`.

## PR-QUAL-006 — Date, Time, and Monetary Exactness
The product shall use actual business dates, configured local timezone boundaries, safe monetary arithmetic, and the exact specified precision, rounding stage, currency, exchange rate, proration, and payment-channel settlement rules.
**Traceability:** `BR-PROP-003`; `BR-MONEY-001`–`BR-MONEY-013`; every referenced calculation rule.

## PR-QUAL-007 — Coordinated Transitions
Move-in, automatic expiration cancellation, Reversal effects, move-out, and Settlement finalization shall not leave authoritative records in a partially contradictory state.
**Traceability:** `BR-RES-016`; `BR-LEASE-016`; `BR-PAY-012`, `BR-PAY-014`, `BR-PAY-029`; `BR-OCC-009`; `BR-MOVEOUT-002`–`BR-MOVEOUT-012`; `BR-SETTLE-011`, `BR-SETTLE-012`.

# 8. Detailed Functional Requirements

## 8.1 Interpretation and Acceptance Contract

Each detailed identifier maps one-to-one from `PR-<category>-<number>` to the same `BR-<category>-<number>`. **Normative product behavior** reproduces the governing rule text.

A detailed requirement is accepted only when applicable tests demonstrate:

1. **Permitted path:** valid preconditions and input produce the stated event, relationship, status, record, or result.
2. **Rejected path:** prohibited transitions, overlaps, values, dates, categories, associations, states, and unauthorized actions are rejected without silent mutation.
3. **Boundary path:** calendar, amount, sequence, count, overlap, rounding, due-date, effective-date, and timezone boundaries behave exactly as written.
4. **Historical path:** required original values, source links, Notices, rates, corrections, Reversals, Refunds, dispositions, applications, and audit facts remain retrievable and reconstructable.
5. **Channel consistency:** every supported initiating channel produces the same result.
6. **No policy expansion:** tests and implementation introduce no absent status, fee, right, exception, or authority.

A criterion applies when the detailed rule contains that behavior. A positive scenario alone is insufficient if rejection, boundary, calculation, authorization, or history obligations also exist.

## 8.2 Property Requirements

### PR-PROP-001 — Single Property

**Business-rule traceability:** `BR-PROP-001`

**Normative product behavior**

One deployed application manages exactly one Property.

The application must not allow users to:

- create a second Property
- switch between Properties
- assign a Unit to another Property

### PR-PROP-002 — Historical Records

**Business-rule traceability:** `BR-PROP-002`

**Normative product behavior**

Historical operational and financial records must not be physically deleted as part of normal business workflows.

Where a record is no longer active, the system must use its approved status or an
explicit historical event, such as:

- CANCELLED
- TERMINATED
- VOID
- REVERSED
- Meter replacement
- Move-out
- Refund

when such a status or event applies.

### PR-PROP-003 — Business Date Integrity

**Business-rule traceability:** `BR-PROP-003`

**Normative product behavior**

Business actions must use the date on which the underlying business event actually occurred.

Users must not alter historical dates merely to change:

- billing periods
- balances
- rates
- Reservation validity
- Lease duration
- Deposit eligibility

Any permitted correction to a historical date must be audited.

Scheduled business actions and end-of-date processing must use the Property's
configured local timezone. A business date remains in effect through the end of
that local calendar date unless a rule explicitly states otherwise.

## 8.3 Unit Requirements

### PR-UNIT-001 — Supported Unit Types

**Business-rule traceability:** `BR-UNIT-001`

**Normative product behavior**

A Unit may use only one of the following Unit Types:

- STUDIO
- ONE_BEDROOM
- TWO_BEDROOM
- THREE_BEDROOM

Commercial Unit is not supported.

### PR-UNIT-002 — Supported Unit Statuses

**Business-rule traceability:** `BR-UNIT-002`

**Normative product behavior**

A Unit may have only one current status:

- VACANT
- RESERVED
- OCCUPIED
- UNDER_MAINTENANCE
- CLEANING
- OUT_OF_SERVICE

### PR-UNIT-003 — Unit Number Uniqueness

**Business-rule traceability:** `BR-UNIT-003`

**Normative product behavior**

Each Unit Number must be unique within the Property.

### PR-UNIT-004 — Reservation Availability

**Business-rule traceability:** `BR-UNIT-004`

**Normative product behavior**

A new Reservation may be created only when the Unit is legally available to be reserved.

A Unit must not receive a second active Reservation while another Reservation is ACTIVE.

An ACTIVE Reservation always holds its Unit. A Reservation releases its Unit only
when it becomes CANCELLED or MOVED_IN through an approved business transition.

### PR-UNIT-005 — Lease Exclusivity

**Business-rule traceability:** `BR-UNIT-005`

**Normative product behavior**

A Unit may have only one SIGNED Lease covering any point in time.

The system must reject an attempt to sign a second Lease when another SIGNED Lease
for the same Unit has an overlapping contractual period.

### PR-UNIT-006 — Reserved Status

**Business-rule traceability:** `BR-UNIT-006`

**Normative product behavior**

When an ACTIVE Reservation successfully holds a Unit, the Unit status becomes:

```text
RESERVED
```

The Unit remains unavailable to another Reservation while that ACTIVE
Reservation holds it.

### PR-UNIT-007 — Occupied Status

**Business-rule traceability:** `BR-UNIT-007`

**Normative product behavior**

When move-in is completed, the Unit status becomes:

```text
OCCUPIED
```

### PR-UNIT-008 — Cleaning After Move-out

**Business-rule traceability:** `BR-UNIT-008`

**Normative product behavior**

After move-out, a Unit may be placed into:

```text
CLEANING
```

until it is ready for rental again.

Once cleaning is completed and no other blocking condition exists, the Unit may return to:

```text
VACANT
```

Move-out does not require the Unit to become VACANT immediately. Its status must
reflect its actual physical and operational condition.

### PR-UNIT-009 — Maintenance Availability

**Business-rule traceability:** `BR-UNIT-009`

**Normative product behavior**

A Unit in either:

```text
UNDER_MAINTENANCE
OUT_OF_SERVICE
```

must not be offered for a new Reservation unless an authorized user explicitly restores it to an available operational state.

Restoration must reflect the Unit's actual condition and must be audited. A
status change must not override an ACTIVE Reservation or SIGNED Lease.

### PR-UNIT-010 — Release After Reservation Cancellation

**Business-rule traceability:** `BR-UNIT-010`

**Normative product behavior**

When a Reservation becomes CANCELLED, including automatic cancellation caused by
expiration, that Reservation releases the Unit.

If no other Lease, maintenance, cleaning, or out-of-service condition blocks
availability, the Unit becomes VACANT.

### PR-UNIT-011 — Unit Status After Move-out

**Business-rule traceability:** `BR-UNIT-011`

**Normative product behavior**

When physical move-out is completed, the Unit must leave OCCUPIED status and
enter the status that reflects its actual condition, normally CLEANING.

The Unit may become VACANT only after it is ready for rental and no authoritative
Reservation or Lease record blocks availability.

### PR-UNIT-012 — Restoration From Unavailable Operational States

**Business-rule traceability:** `BR-UNIT-012`

**Normative product behavior**

A Unit may leave UNDER_MAINTENANCE or OUT_OF_SERVICE only through an authorized
restoration action confirming that the blocking condition has been resolved.

The resulting status must be determined from the Unit's actual readiness and its
authoritative Reservation and Lease records.

### PR-UNIT-013 — Authoritative Availability

**Business-rule traceability:** `BR-UNIT-013`

**Normative product behavior**

Unit status is an operational summary and must not become a competing source of
truth.

Legal availability must be validated from the Unit's ACTIVE Reservations,
SIGNED Leases, actual occupancy, and blocking operational conditions. A status
value alone must never authorize a conflicting Reservation, Lease, or move-in.

## 8.4 Customer Requirements

### PR-CUST-001 — Single Customer Entity

**Business-rule traceability:** `BR-CUST-001`

**Normative product behavior**

The system must use Customer as the canonical person record.

The system must not create separate permanent person entities for:

- Tenant
- Former Tenant
- Occupant
- Lease Signer
- Reservation Customer

These roles are established through relationships.

### PR-CUST-002 — Customer Reuse

**Business-rule traceability:** `BR-CUST-002`

**Normative product behavior**

An existing Customer record should be reused when the same person enters a new Reservation, Lease, Occupancy, Payment, or other business relationship.

The system should avoid unnecessary duplicate Customer records.

### PR-CUST-003 — Customer History

**Business-rule traceability:** `BR-CUST-003`

**Normative product behavior**

Changing current Customer contact information must not alter the historical meaning of previous:

- Reservations
- Leases
- Payments
- Occupancies
- financial records

## 8.5 Reservation Requirements

### PR-RES-001 — Reservation Is Mandatory

**Business-rule traceability:** `BR-RES-001`

**Normative product behavior**

A Unit must be reserved before move-in.

The system must not allow direct move-in to a Unit without an existing valid
ACTIVE Reservation.

### PR-RES-002 — One Customer per Reservation

**Business-rule traceability:** `BR-RES-002`

**Normative product behavior**

A Reservation contains exactly one Customer.

The Reservation Customer is the prospective Primary Tenant.

### PR-RES-003 — Reservation Statuses

**Business-rule traceability:** `BR-RES-003`

**Normative product behavior**

Reservation status may be only:

```text
ACTIVE
CANCELLED
MOVED_IN
```

The system must not introduce an EXPIRED Reservation status.

### PR-RES-004 — Initial Reservation Status

**Business-rule traceability:** `BR-RES-004`

**Normative product behavior**

A newly accepted Reservation begins in ACTIVE status only after all Reservation
activation conditions, including the minimum initial Security Deposit, are met.

### PR-RES-005 — Reservation Expiration Required

**Business-rule traceability:** `BR-RES-005`

**Normative product behavior**

Every ACTIVE Reservation must have a Reservation Expiration Date.

The Reservation remains valid through the entire Expiration Date in the
Property's configured local timezone.

### PR-RES-006 — Maximum Initial Reservation Period

**Business-rule traceability:** `BR-RES-006`

**Normative product behavior**

The initial Reservation Expiration Date must not be more than 21 calendar days
from the Reservation Date. A shorter initial period is permitted.

### PR-RES-007 — Reservation Extension Eligibility

**Business-rule traceability:** `BR-RES-007`

**Normative product behavior**

A Reservation may be extended only when:

- the Reservation is ACTIVE;
- it has not expired;
- fewer than 14 calendar days remain before its current Expiration Date;
- it has not previously been extended; and
- the extension is authorized.

### PR-RES-008 — Maximum Extension

**Business-rule traceability:** `BR-RES-008`

**Normative product behavior**

The single approved extension may add no more than 14 calendar days to the
existing Expiration Date.

The extension is calculated from the existing Expiration Date, not from the date
on which the extension is approved.

### PR-RES-009 — Extension Is Not a Status

**Business-rule traceability:** `BR-RES-009`

**Normative product behavior**

An extension does not change Reservation status. The Reservation remains ACTIVE
and continues holding its Unit.

The extension must be represented by a Reservation Extension Notice.

### PR-RES-010 — Extension History

**Business-rule traceability:** `BR-RES-010`

**Normative product behavior**

Every extension must preserve:

- original Expiration Date;
- immediately previous Expiration Date;
- new Expiration Date;
- extension approval date and time;
- authorized user; and
- reason or memo when provided.

The effective Expiration Date must not be changed without this Notice history.

### PR-RES-011 — Reservation Expiration

**Business-rule traceability:** `BR-RES-011`

**Normative product behavior**

At the end of the effective Expiration Date in the Property's configured local
timezone, an ACTIVE Reservation that has not become MOVED_IN and has no valid
approved extension automatically becomes CANCELLED.

The cancellation reason must be `RESERVATION_EXPIRED`. The Reservation history
must remain permanent, and the Unit must be released from that Reservation.

### PR-RES-012 — Reservation Cancellation

**Business-rule traceability:** `BR-RES-012`

**Normative product behavior**

Only an ACTIVE Reservation may be cancelled. Every cancellation must record its
reason and whether it is customer-caused, caused by expiration while the Property
could provide the Unit, or caused by the Property's inability to provide the
Unit as agreed.

A CANCELLED Reservation cannot later become ACTIVE or MOVED_IN.

### PR-RES-013 — Reservation Move-in Completion

**Business-rule traceability:** `BR-RES-013`

**Normative product behavior**

A Reservation may become MOVED_IN only when:

- the Reservation is ACTIVE and has not expired;
- the Lease is SIGNED;
- the Unit is ready for occupancy;
- the required Security Deposit is fully paid no later than completion of
  move-in;
- the applicable Pet Deposit is fully paid when a pet will be kept from the
  beginning of occupancy; and
- move-in has actually occurred.

### PR-RES-014 — Reservation to Lease Relationship

**Business-rule traceability:** `BR-RES-014`

**Normative product behavior**

A Reservation may result in at most one Lease.

The system must not create multiple resulting Leases from one Reservation.

### PR-RES-015 — Expiration Date Boundary

**Business-rule traceability:** `BR-RES-015`

**Normative product behavior**

Expiration is end-of-date processing. The Reservation remains valid through the
entire effective Expiration Date and must not be cancelled earlier that day.

### PR-RES-016 — Automatic Expiration Cancellation

**Business-rule traceability:** `BR-RES-016`

**Normative product behavior**

Automatic expiration performs the approved ACTIVE to CANCELLED transition,
records `RESERVATION_EXPIRED`, preserves history, and releases the Unit as one
coordinated business action.

### PR-RES-017 — Single Extension Limit

**Business-rule traceability:** `BR-RES-017`

**Normative product behavior**

An ACTIVE Reservation may be extended no more than once.

### PR-RES-018 — Extension Date Calculation

**Business-rule traceability:** `BR-RES-018`

**Normative product behavior**

An extension adds its approved number of calendar days to the existing
Expiration Date. It does not replace the original Reservation history.

### PR-RES-019 — No Second Extension

**Business-rule traceability:** `BR-RES-019`

**Normative product behavior**

After one Reservation Extension Notice has been approved, every attempt to grant
another extension must be rejected.

If move-in does not occur by the extended Expiration Date, the automatic
expiration rule applies.

### PR-RES-020 — Cancellation Responsibility Classification

**Business-rule traceability:** `BR-RES-020`

**Normative product behavior**

Cancellation responsibility must be based on the actual reason the Reservation
did not proceed. A Property-side inability to provide the Unit must not be
misclassified as customer-caused cancellation or expiration.

### PR-RES-021 — Customer-caused Cancellation or Expiration

**Business-rule traceability:** `BR-RES-021`

**Normative product behavior**

When the Customer voluntarily cancels for a Customer-attributable reason, or
allows the Reservation to expire while the Property remained capable of
providing the Unit as agreed, the Security Deposit received is non-refundable.

Waiting for expiration must not bypass the customer-caused cancellation policy.

### PR-RES-022 — Property-caused Cancellation

**Business-rule traceability:** `BR-RES-022`

**Normative product behavior**

When the Property cannot provide the reserved Unit as agreed, Property Management
must first coordinate with the Customer. The Customer may agree to wait or may
accept temporary accommodation in another Unit.

This rule creates no additional temporary-accommodation financial policy.

If the Customer rejects the delay or alternative and requests cancellation, the
Reservation must be cancelled and all Security Deposit received for that
Reservation must be refunded through an explicit Refund event.

## 8.6 Deposit Requirements

### PR-DEP-001 — Security Deposit Required for Reservation

**Business-rule traceability:** `BR-DEP-001`

**Normative product behavior**

A Reservation may become ACTIVE only after at least the minimum initial partial
Security Deposit has been received.

The business does not use a separate Reservation Deposit.

### PR-DEP-002 — Initial Security Deposit May Be Partial

**Business-rule traceability:** `BR-DEP-002`

**Normative product behavior**

The initial payment may be less than the total required Security Deposit, but it
must meet the approved minimum. More than the minimum may be paid.

Every receipt remains part of the same Security Deposit obligation.

### PR-DEP-003 — Minimum Initial Security Deposit

**Business-rule traceability:** `BR-DEP-003`

**Normative product behavior**

The minimum amount required to activate a Reservation is 20% of the agreed
monthly Rent.

```text
Minimum Initial Security Deposit
=
Agreed Monthly Rent × 20%
```

The final monetary result uses the approved monetary rounding rule.

Example:

```text
Agreed Monthly Rent:                  $500
Minimum Initial Security Deposit:     $100
```

This amount is Security Deposit, not a fee or separate Deposit type.

### PR-DEP-004 — Required Security Deposit Amount

**Business-rule traceability:** `BR-DEP-004`

**Normative product behavior**

Every Lease has a required total Security Deposit amount.

The exact required total is determined by the agreed Lease terms.

The system must distinguish:

```text
Required Security Deposit
Security Deposit Received
Security Deposit Outstanding
```

where:

```text
Outstanding
=
Required
-
Received
```

### PR-DEP-005 — Security Deposit Continues Into Lease

**Business-rule traceability:** `BR-DEP-005`

**Normative product behavior**

Any Security Deposit received during Reservation remains the same Security Deposit when the resulting Lease is signed and move-in occurs.

The receipt of money for a Deposit must be linked explicitly from the Payment to
the applicable Deposit liability and Deposit balance. This Deposit-receipt link is
not an Invoice Payment Allocation and does not require a Deposit Invoice.

The system must not:

- refund it and recollect it
- create a second deposit
- record a conversion transaction
- recognize it as rental income

### PR-DEP-006 — Remaining Deposit No Later Than Move-in Completion

**Business-rule traceability:** `BR-DEP-006`

**Normative product behavior**

The remaining required Security Deposit may be paid before move-in or at
move-in. It must be fully paid no later than completion of move-in.

Move-in must not be completed while any required Security Deposit remains
outstanding.

### PR-DEP-007 — Pet Deposit Conditional

**Business-rule traceability:** `BR-DEP-007`

**Normative product behavior**

Pet Deposit is required only when a pet is approved under the signed Lease and
the applicable Lease terms require that Deposit.

### PR-DEP-008 — No Pet Deposit Without Approved Pet

**Business-rule traceability:** `BR-DEP-008`

**Normative product behavior**

If no pet is being kept, a Pet Deposit must not be required merely because the
Customer might keep a pet in the future.

### PR-DEP-009 — Pet Deposit Is Liability

**Business-rule traceability:** `BR-DEP-009`

**Normative product behavior**

Pet Deposit must be recorded as a liability and not as:

- rent income
- service income
- damage income

### PR-DEP-010 — Pet Deposit Timing

**Business-rule traceability:** `BR-DEP-010`

**Normative product behavior**

When a Customer will keep an approved pet from the beginning of occupancy, the
Pet Deposit required by the applicable signed Lease terms must be fully paid
before or at move-in.

When a Customer introduces or acquires a pet later, the Customer must notify
Property Management. If the pet is approved and the applicable signed Lease terms
require a Pet Deposit, that Deposit must be paid before or when the pet begins
staying in the Unit.

### PR-DEP-011 — Deposit Held During Active Lease

**Business-rule traceability:** `BR-DEP-011`

**Normative product behavior**

Security Deposit and Pet Deposit are held during the active Lease.

They remain distinct liabilities with separately traceable balances.

### PR-DEP-012 — No Normal Deposit Refund During Active Lease

**Business-rule traceability:** `BR-DEP-012`

**Normative product behavior**

Security Deposit must not be refunded while the Lease remains SIGNED.

Pet Deposit must likewise remain held while its associated tenancy obligation remains active.

This rule does not prevent an explicit disposition required by an approved
non-refundable policy or an explicit Property-caused Reservation Refund before a
Lease begins.

### PR-DEP-013 — Deposits Are Not Monthly Payment Funds

**Business-rule traceability:** `BR-DEP-013`

**Normative product behavior**

A Customer must not use Security Deposit or Pet Deposit to pay ordinary monthly:

- Rent
- Utilities
- Internet
- Trash
- other current charges

while the Lease remains active.

The Customer cannot direct staff to treat a Deposit as an ordinary Payment, and
staff cannot allocate it to an ordinary Invoice before Final Settlement.

### PR-DEP-014 — Deposit Application During Final Settlement Only

**Business-rule traceability:** `BR-DEP-014`

**Normative product behavior**

Deposits may be applied only as part of the Final Settlement process after Lease termination.

An explicit forfeiture/disposition event under an approved non-refundable policy
is not an Invoice allocation and must remain separate from Final Settlement
application. This distinction does not create any new reason for forfeiture.

### PR-DEP-015 — Customer-caused Reservation Cancellation

**Business-rule traceability:** `BR-DEP-015`

**Normative product behavior**

When a Customer voluntarily cancels an ACTIVE Reservation for a
Customer-attributable reason, Security Deposit received is non-refundable. The
Unit is released, and the original Deposit and cancellation history are
preserved.

### PR-DEP-016 — Customer-caused Reservation Expiration

**Business-rule traceability:** `BR-DEP-016`

**Normative product behavior**

When the Property could provide the Unit as agreed but the Customer does not move
in and the Reservation expires without a valid extension, Security Deposit
received is non-refundable.

### PR-DEP-017 — Property-caused Reservation Refund

**Business-rule traceability:** `BR-DEP-017`

**Normative product behavior**

When the Property cannot provide the reserved Unit as agreed and the Customer
rejects the coordinated delay or alternative and requests cancellation, all
Security Deposit received must be refunded in full through explicit Refund
events. The original Deposit receipt remains unchanged.

### PR-DEP-018 — Explicit Forfeiture or Disposition Event

**Business-rule traceability:** `BR-DEP-018`

**Normative product behavior**

Every approved non-refundable Deposit outcome uses an explicit linked Deposit
forfeiture or disposition event. The event reduces the refundable Deposit balance
without deleting, rewriting, or silently reclassifying the original receipt.

### PR-DEP-019 — Disposition Audit

**Business-rule traceability:** `BR-DEP-019`

**Normative product behavior**

Each Deposit disposition records:

- amount;
- Deposit type;
- reason;
- governing Reservation, Lease, or business event;
- effective date;
- authorization; and
- complete audit history.

It must not be allocated to an ordinary monthly Invoice merely to make an
accounting balance work. This rule authorizes no new forfeiture circumstance.

### PR-DEP-020 — Pet Introduced After Move-in

**Business-rule traceability:** `BR-DEP-020`

**Normative product behavior**

A Customer who later wants to introduce or acquire a pet must notify Property
Management. If the pet is approved and the applicable signed Lease terms require
a Pet Deposit, that Deposit must be paid before or when the pet begins staying in
the Unit.

### PR-DEP-021 — Undisclosed or Unauthorized Pet

**Business-rule traceability:** `BR-DEP-021`

**Normative product behavior**

When an undisclosed or unauthorized pet is found, Property Management informs the
Customer of the violation. A Pet Deposit is required only if the pet is approved
and the applicable signed Lease terms require that Deposit. The Lease must not be
terminated immediately and automatically merely because the pet was discovered.

No additional pet penalty is created by this rule.

### PR-DEP-022 — Pet Noncompliance and Violation Termination

**Business-rule traceability:** `BR-DEP-022`

**Normative product behavior**

If the Customer refuses or fails to pay the required Pet Deposit, termination may
proceed only under the signed Lease and the three-warning-letter rule.

If the Lease is terminated for that violation, the applicable Security Deposit
and Pet Deposit are non-refundable according to the signed Lease and must be
resolved through explicit disposition events.

### PR-DEP-023 — Voluntary Early-termination Security Deposit

**Business-rule traceability:** `BR-DEP-023`

**Normative product behavior**

When voluntary early termination is processed under BR-LEASE-021, the Security
Deposit is non-refundable and is resolved through an explicit disposition event.

### PR-DEP-024 — Pet Deposit During Voluntary Early Termination

**Business-rule traceability:** `BR-DEP-024`

**Normative product behavior**

Voluntary early termination does not automatically make the Pet Deposit
non-refundable. It remains separately tracked through Final Settlement, may be
applied only to authorized pet-related damage, and is refundable to the extent
not validly applied or otherwise validly forfeited under an explicitly approved
rule.

### PR-DEP-025 — Remaining Refundable Deposit

**Business-rule traceability:** `BR-DEP-025`

**Normative product behavior**

Every remaining refundable Security Deposit or Pet Deposit balance after Final
Settlement must be returned through an explicit Refund event. Each Deposit type
and Refund remains separately traceable.

## 8.7 Lease, Move-in, and Termination Requirements

### PR-LEASE-001 — Lease Statuses

**Business-rule traceability:** `BR-LEASE-001`

**Normative product behavior**

Lease status may be only:

```text
DRAFTED
SIGNED
CANCELLED
TERMINATED
```

### PR-LEASE-002 — New Lease Status

**Business-rule traceability:** `BR-LEASE-002`

**Normative product behavior**

A newly created Lease begins as:

```text
DRAFTED
```

### PR-LEASE-003 — Valid Lease Status Transitions

**Business-rule traceability:** `BR-LEASE-003`

**Normative product behavior**

Only the following transitions are permitted:

```text
DRAFTED -> SIGNED
DRAFTED -> CANCELLED
SIGNED  -> TERMINATED
```

Reaching the contractual Lease End Date does not by itself perform the SIGNED to
TERMINATED transition. That transition occurs through the applicable authorized
termination and move-out process.

### PR-LEASE-004 — Drafted Lease Cancellation

**Business-rule traceability:** `BR-LEASE-004`

**Normative product behavior**

Only a DRAFTED Lease may be CANCELLED.

A SIGNED Lease must not be cancelled.

If a SIGNED Lease ends, it must be TERMINATED.

### PR-LEASE-005 — Signed Lease Termination

**Business-rule traceability:** `BR-LEASE-005`

**Normative product behavior**

Only a SIGNED Lease may be TERMINATED.

A DRAFTED Lease cannot be terminated.

Termination must record the approved actual termination date and its governing
signed-Lease or business event. A Termination Notice alone does not change Lease
status.

### PR-LEASE-006 — Primary Tenant Required

**Business-rule traceability:** `BR-LEASE-006`

**Normative product behavior**

Every Lease must have exactly one Primary Tenant before the Lease may become SIGNED.

### PR-LEASE-007 — Primary Tenant Must Sign

**Business-rule traceability:** `BR-LEASE-007`

**Normative product behavior**

The Primary Tenant must be included among the Lease Signers.

A Lease cannot become SIGNED if the Primary Tenant has not signed.

### PR-LEASE-008 — Lease Signer Minimum

**Business-rule traceability:** `BR-LEASE-008`

**Normative product behavior**

A Lease must have at least one Lease Signer before it may become SIGNED.

Because the Primary Tenant must sign, this minimum is always satisfied by the Primary Tenant when the Lease is validly signed.

### PR-LEASE-009 — Multiple Signers

**Business-rule traceability:** `BR-LEASE-009`

**Normative product behavior**

A Lease may contain multiple Lease Signers.

Every Lease Signer is jointly responsible for the full unpaid Lease obligation.

### PR-LEASE-010 — No Split Financial Responsibility

**Business-rule traceability:** `BR-LEASE-010`

**Normative product behavior**

The system must not assign individual debt percentages to Lease Signers.

For example, a Lease with two signers and an $800 balance must not be represented as:

```text
Signer A owes $400
Signer B owes $400
```

Instead, the Lease owes:

```text
$800 total
```

and each signer is jointly responsible for satisfying that balance.

### PR-LEASE-011 — Lease Signer May Be Non-Occupant

**Business-rule traceability:** `BR-LEASE-011`

**Normative product behavior**

A Customer may sign the Lease without living in the Unit.

Signing responsibility and physical occupancy are separate.

### PR-LEASE-012 — Lease Dates Required

**Business-rule traceability:** `BR-LEASE-012`

**Normative product behavior**

A Lease must define its contractual period before becoming SIGNED.

The Lease must have:

- Lease Start Date
- Lease End Date

These contractual dates remain historically identifiable after renewal,
termination, or move-out.

### PR-LEASE-013 — Lease End Date

**Business-rule traceability:** `BR-LEASE-013`

**Normative product behavior**

The Lease End Date must be later than the Lease Start Date.

The End Date is a contractual boundary, not an automatic month-to-month renewal
and not an automatic TERMINATED transition while occupancy continues.

### PR-LEASE-014 — One Signed Lease per Unit

**Business-rule traceability:** `BR-LEASE-014`

**Normative product behavior**

Before a Lease becomes SIGNED, the system must confirm that no other SIGNED Lease
has overlapping contractual coverage for the same Unit.

An approved signed renewal must not create overlapping contractual coverage that
violates this invariant.

### PR-LEASE-015 — Required Conditions Before Move-in

**Business-rule traceability:** `BR-LEASE-015`

**Normative product behavior**

Move-in may occur only when all required conditions are satisfied.

At minimum:

- Reservation is ACTIVE
- Lease is SIGNED
- Unit is not UNDER_MAINTENANCE
- Unit is not OUT_OF_SERVICE
- required Security Deposit is fully paid before or at move-in
- required Pet Deposit is fully paid before or at move-in when a pet will be kept
  from the beginning of occupancy
- move-in date is valid

### PR-LEASE-016 — Move-in Completion

**Business-rule traceability:** `BR-LEASE-016`

**Normative product behavior**

When move-in is completed:

- Reservation becomes MOVED_IN
- Unit becomes OCCUPIED
- Occupancy begins
- Security Deposit remains associated with the Lease

These actions represent one coordinated business transition.

The transition must not complete until all conditions in BR-LEASE-015 are true.

### PR-LEASE-017 — No Automatic Month-to-month Tenancy

**Business-rule traceability:** `BR-LEASE-017`

**Normative product behavior**

The Lease does not automatically continue as a month-to-month tenancy at its
contractual End Date. No new tenancy, holdover Rent, fee, penalty, or other charge
is created automatically.

### PR-LEASE-018 — No Automatic Termination at End Date

**Business-rule traceability:** `BR-LEASE-018`

**Normative product behavior**

Arrival of the contractual Lease End Date does not automatically change a SIGNED
Lease to TERMINATED while the Customer still occupies the Unit.

By that date, the Lease should normally have an approved signed renewal or
proceed through the applicable termination and move-out process.

### PR-LEASE-019 — Continued Occupancy Requires Management Action

**Business-rule traceability:** `BR-LEASE-019`

**Normative product behavior**

If the Customer remains after the Lease End Date without an approved signed
renewal, Property Management must take authorized action according to the signed
Lease. Until then, the actual Lease and Occupancy situation must remain recorded
accurately.

### PR-LEASE-020 — No General Early-termination Right

**Business-rule traceability:** `BR-LEASE-020`

**Normative product behavior**

A Customer does not have a general right to terminate a Lease before its
contractual End Date. Early termination is not normally permitted.

### PR-LEASE-021 — Processed Voluntary Early Termination

**Business-rule traceability:** `BR-LEASE-021`

**Normative product behavior**

If a Customer voluntarily leaves before the Lease End Date and Property
Management processes the early termination:

- the Lease terminates on the approved actual termination/move-out date;
- Rent for that calendar month is charged in full;
- applicable Utility, fixed Service, and other valid outstanding obligations
  remain due;
- the Security Deposit is non-refundable;
- no separate standard early-termination fee is created; and
- Rent is not generated for later months through the original End Date.

### PR-LEASE-022 — Termination Notice

**Business-rule traceability:** `BR-LEASE-022`

**Normative product behavior**

Where a Termination Notice applies, its content and notice period come from the
signed Lease. Recording a Notice does not itself change Lease status or fabricate
an actual Move-out Date.

### PR-LEASE-023 — Actual Termination Date

**Business-rule traceability:** `BR-LEASE-023`

**Normative product behavior**

A SIGNED Lease becomes TERMINATED only through the authorized process on the
approved actual termination date. That date and the governing event must remain
historically identifiable.

### PR-LEASE-024 — Violation Warning Minimum

**Business-rule traceability:** `BR-LEASE-024`

**Normative product behavior**

Property Management must issue at least three documented warning letters before
terminating a Lease for a Customer violation.

Each warning must identify the violation, date, Lease provision, communication,
and history. The undisclosed-pet process follows this rule if noncompliance
proceeds toward termination.

### PR-LEASE-025 — Signed-Lease Termination Authority

**Business-rule traceability:** `BR-LEASE-025`

**Normative product behavior**

A violation and the authority to terminate for it must come from the signed
Lease. The system must not invent a violation, penalty, fee, forfeiture, or
termination right.

## 8.8 Occupancy Requirements

### PR-OCC-001 — Occupancy Is Separate From Lease Signer

**Business-rule traceability:** `BR-OCC-001`

**Normative product behavior**

Occupancy identifies who physically lives in a Unit.

Lease Signer identifies who accepts contractual financial responsibility.

The system must not treat these as equivalent.

### PR-OCC-002 — Occupancy Customer

**Business-rule traceability:** `BR-OCC-002`

**Normative product behavior**

Every Occupancy record must identify one Customer.

### PR-OCC-003 — Occupancy Lease

**Business-rule traceability:** `BR-OCC-003`

**Normative product behavior**

Every Occupancy record must belong to one Lease.

### PR-OCC-004 — Move-in Date Required

**Business-rule traceability:** `BR-OCC-004`

**Normative product behavior**

An Occupancy record becomes active when the actual Move-in Date is recorded as
part of the coordinated move-in transition.

### PR-OCC-005 — Move-out Date

**Business-rule traceability:** `BR-OCC-005`

**Normative product behavior**

The Move-out Date remains empty while the Customer currently occupies the Unit.

When occupancy ends, the Move-out Date must be recorded.

The Move-out Date is the actual date physical occupancy ended and must not precede
the Move-in Date.

### PR-OCC-006 — Occupancy Does Not Create Debt

**Business-rule traceability:** `BR-OCC-006`

**Normative product behavior**

An Occupant who is not a Lease Signer does not become financially responsible merely by residing in the Unit.

### PR-OCC-007 — Occupancy Date Ordering

**Business-rule traceability:** `BR-OCC-007`

**Normative product behavior**

For a completed occupancy period:

```text
Move-in Date <= Move-out Date
```

Both endpoints are actual business dates. Corrections must preserve the previous
values and audit history.

### PR-OCC-008 — Occupancy After Lease End Date

**Business-rule traceability:** `BR-OCC-008`

**Normative product behavior**

If a Customer remains in the Unit after the contractual Lease End Date without an
approved signed renewal, Occupancy remains open and the Lease situation remains
represented accurately until Property Management takes authorized action under
the signed Lease.

The system must not fabricate move-out, automatic month-to-month tenancy,
automatic holdover Rent, penalties, fees, or a new tenancy.

### PR-OCC-009 — Coordinated Occupancy Closure

**Business-rule traceability:** `BR-OCC-009`

**Normative product behavior**

Occupancy closes only when physical occupancy has actually ended and an actual
Move-out Date is recorded through the move-out process.

Closing Occupancy must be coordinated with Lease termination, Unit status, final
Utility handling, and Final Settlement. Occupancy history must never be deleted.

## 8.9 Rent Billing Requirements

### PR-RENT-001 — Monthly Rent

**Business-rule traceability:** `BR-RENT-001`

**Normative product behavior**

Rent shall be charged on a monthly basis.

The agreed monthly Rent is defined in the applicable signed Lease agreement. A
different contractual Rent requires an applicable new or renewed signed agreement
for the future period; it must not be created by editing an Invoice.

### PR-RENT-002 — Rent is Billed in Advance

**Business-rule traceability:** `BR-RENT-002`

**Normative product behavior**

Rent shall always be billed in advance.

Each recurring Rent Invoice represents the upcoming rental period rather than the period already occupied.

Example:

| Invoice Date | Rental Period              |
| ------------ | -------------------------- |
| 25 July      | 1 August – 31 August       |
| 25 August    | 1 September – 30 September |

### PR-RENT-003 — Standard Rental Period

**Business-rule traceability:** `BR-RENT-003`

**Normative product behavior**

For active Leases, the normal rental period shall follow the calendar month.

A standard monthly Rent Invoice covers:

- the first calendar day of the month, through
- the final calendar day of the same month.

### PR-RENT-004 — One Rent Invoice Per Rental Period

**Business-rule traceability:** `BR-RENT-004`

**Normative product behavior**

Only one Rent Invoice may exist for the same Lease and rental period.

The business shall reject duplicate rent billing for an already billed rental period.

Example:

**Valid**

- Lease A
- Rent Invoice
- 1 August – 31 August

**Invalid**

- Lease A
- Second Rent Invoice
- 1 August – 31 August

### PR-RENT-005 — First Partial Month

**Business-rule traceability:** `BR-RENT-005`

**Normative product behavior**

When the Primary Tenant moves into a Unit after the first day of a calendar month,
the first Rent Invoice shall be prorated.

The first rental period begins on the official Move-in Date and ends on the last calendar day of that month.

Example:

Move-in Date:

- 10 July

First Rental Period:

- 10 July
- through
- 31 July

The next recurring Rent Invoice begins on:

- 1 August

### PR-RENT-006 — Actual Calendar Day Proration

**Business-rule traceability:** `BR-RENT-006`

**Normative product behavior**

Prorated rent shall always be calculated using the actual number of calendar days in the affected month.

The business shall never use:

- fixed 30-day months,
- fixed 31-day months,
- average monthly day calculations,
- simplified daily-rate assumptions.

Examples:

| Month                  | Days Used |
| ---------------------- | --------- |
| January                | 31        |
| February (Normal Year) | 28        |
| February (Leap Year)   | 29        |
| April                  | 30        |

### PR-RENT-007 — Proration Basis

**Business-rule traceability:** `BR-RENT-007`

**Normative product behavior**

Prorated Rent is calculated directly as:

```text
Monthly Rent × Inclusive Billable Calendar Days
------------------------------------------------
Actual Calendar Days in the Billing Month
```

The intermediate daily rate must not be rounded. Only the final monetary result
is rounded to the nearest USD cent using half-up rounding.

### PR-RENT-008 — Automatic Invoice Generation

**Business-rule traceability:** `BR-RENT-008`

**Normative product behavior**

Recurring Rent Invoices shall be generated automatically on the 25th day of the
current calendar month in the Property's configured local timezone.

The generated invoice represents the upcoming month's rental period.

Example:

| Generation Date | Rental Period |
| --------------- | ------------- |
| 25 July         | August        |
| 25 August       | September     |
| 25 September    | October       |

### PR-RENT-009 — Invoice Due Date

**Business-rule traceability:** `BR-RENT-009`

**Normative product behavior**

Recurring Rent Invoices shall have a standard payment due date of the **5th day of the billed month**, unless an alternative due date is explicitly specified in the Lease Agreement.

Example:

| Rental Month | Invoice Generated | Due Date    |
| ------------ | ----------------- | ----------- |
| August       | 25 July           | 5 August    |
| September    | 25 August         | 5 September |

### PR-RENT-010 — Invoice Generation Eligibility

**Business-rule traceability:** `BR-RENT-010`

**Normative product behavior**

Recurring Rent Invoices shall only be generated for Leases that are:

- Signed,
- contractually applicable to the billed rental period, and
- Not terminated before the beginning of that rental period.

The business shall not generate Rent Invoices for:

- Drafted Leases,
- Cancelled Leases,
- Terminated Leases.

This restriction governs recurring future-period generation. It does not prevent
authorized finalization of a valid unbilled rental period that occurred before
the approved termination date, subject to duplicate prevention and the applicable
final-month rule.

No Rent Invoice may be generated for a period after the contractual Lease End
Date unless an approved signed renewal covers that period. Continued occupancy
alone must not create automatic holdover Rent or a new tenancy.

### PR-RENT-011 — No Duplicate Monthly Billing

**Business-rule traceability:** `BR-RENT-011`

**Normative product behavior**

The business shall prevent duplicate recurring Rent Invoices.

A Lease shall never receive multiple Rent Invoices covering the same rental period.

Scheduled generation must be idempotent. A retry or recovery run must find the
existing Invoice rather than create another one.

### PR-RENT-012 — Final Rental Period

**Business-rule traceability:** `BR-RENT-012`

**Normative product behavior**

When an approved termination rule requires a prorated final rental period, that
period begins on the first calendar day of the month and ends on the approved
actual termination date.

Voluntary early termination processed under BR-LEASE-021 is not prorated. Its
final month is charged in full.

### PR-RENT-013 — Applicable Final Month Proration

**Business-rule traceability:** `BR-RENT-013`

**Normative product behavior**

When final-month proration is required by an approved rule or the signed Lease,
it uses the same inclusive actual-calendar-day calculation and final rounding as
the first partial month.

This rule must not override the full-month voluntary early-termination rule.

### PR-RENT-014 — Final Billing Independence

**Business-rule traceability:** `BR-RENT-014`

**Normative product behavior**

Final rent calculation is independent of:

- Security Deposit,
- Pet Deposit,
- Damage Charges,
- Utility Charges,
- Final Settlement.

Those financial obligations are handled separately under their respective business rules.

### PR-RENT-015 — Future Rent Changes

**Business-rule traceability:** `BR-RENT-015`

**Normative product behavior**

Monthly Rent may be revised only for future rental periods through the applicable
new or renewed signed Lease agreement.

An approved rent revision shall never retroactively modify completed rental periods.

### PR-RENT-016 — Effective Date

**Business-rule traceability:** `BR-RENT-016`

**Normative product behavior**

Every contractual Rent change shall have an effective date in that applicable
signed agreement.

The revised monthly rent applies only to rental periods beginning on or after that effective date.

Rental periods before the effective date continue using the previous rent.

### PR-RENT-017 — Historical Rent Preservation

**Business-rule traceability:** `BR-RENT-017`

**Normative product behavior**

Historical rent values shall remain permanently preserved.

The business shall never overwrite:

- historical monthly rent,
- prorated calculations,
- historical invoices,
- completed billing periods.

### PR-RENT-018 — Historical Invoice Integrity

**Business-rule traceability:** `BR-RENT-018`

**Normative product behavior**

Previously issued Rent Invoices shall permanently retain:

- the monthly rent used,
- the billing period,
- the calculation performed,
- the invoice amount,
- the invoice date.

Later rent revisions shall never alter existing Rent Invoices.

### PR-RENT-019 — Billing Period Consistency

**Business-rule traceability:** `BR-RENT-019`

**Normative product behavior**

Rental periods for the same Lease shall never overlap.

Every billable day shall belong to one—and only one—Rent Invoice.

The business shall reject any billing period that overlaps a previously billed rental period.

### PR-RENT-020 — Rent Calculation Consistency

**Business-rule traceability:** `BR-RENT-020`

**Normative product behavior**

The business shall use a single, consistent rent calculation methodology throughout the application.

Rent shall never be calculated using different formulas for different Customers.

### PR-RENT-021 — Historical Auditability

**Business-rule traceability:** `BR-RENT-021`

**Normative product behavior**

Every completed rent billing event forms part of the permanent financial history of the Property.

Historical rent records shall remain auditable and shall not be silently modified, deleted, recalculated, or replaced.

### PR-RENT-022 — Signed Lease Source of Truth

**Business-rule traceability:** `BR-RENT-022`

**Normative product behavior**

Every Rent Invoice requires a valid applicable signed Lease covering its rental
period. The Invoice Customer and Unit must be valid in that Lease context.

### PR-RENT-023 — No Manual Contractual Rent Override

**Business-rule traceability:** `BR-RENT-023`

**Normative product behavior**

The Rent line amount must be calculated from the contractual Rent in the
applicable signed Lease. Staff and automated processes must not replace it with an
arbitrary amount.

Legitimate financial changes after issuance use the approved Adjustment rules;
they do not rewrite contractual Rent.

### PR-RENT-024 — Voluntary Early-Termination Final Month

**Business-rule traceability:** `BR-RENT-024`

**Normative product behavior**

When a Customer voluntarily leaves before the Lease End Date and Property
Management processes the early termination, Rent for the calendar month
containing the approved actual termination/move-out date is charged in full.

### PR-RENT-025 — No Future Rent After Processed Early Termination

**Business-rule traceability:** `BR-RENT-025`

**Normative product behavior**

After voluntary early termination is processed, Rent must not be generated for
months after the approved actual termination date even though the original Lease
End Date was later.

### PR-RENT-026 — Advance-generated Invoice After Termination

**Business-rule traceability:** `BR-RENT-026`

**Normative product behavior**

If advance billing created a Rent Invoice for a period that is no longer valid
after an approved termination, the original Invoice must not be silently edited
or deleted. It must follow the controlled VOID or linked Adjustment process,
including resolution of active financial dependencies.

### PR-RENT-027 — Scheduled Billing Idempotency

**Business-rule traceability:** `BR-RENT-027`

**Normative product behavior**

Each generation attempt uses the applicable Lease and rental period as its stable
business key. Missed runs may be recovered, and repeated runs may be retried,
without creating duplicate Rent Invoices.

### PR-RENT-028 — Rent Calculation Traceability

**Business-rule traceability:** `BR-RENT-028`

**Normative product behavior**

Every Rent line must preserve the applicable Lease, contractual monthly Rent,
rental period, billable days when prorated, calendar days in the month,
calculation, rounding rule, and final USD amount.

## 8.10 Utility Management and Billing Requirements

### PR-UTIL-001 — Supported Utility Types

**Business-rule traceability:** `BR-UTIL-001`

**Normative product behavior**

The Property Rental Management System currently supports the following utility types:

- Electricity
- Water

No additional Utility Type is approved by this document.

### PR-UTIL-002 — Utility Billing Principle

**Business-rule traceability:** `BR-UTIL-002`

**Normative product behavior**

Utility charges shall be based on actual metered consumption.

Consumption shall be determined from validated Utility Readings recorded for the applicable billing period.

Estimated consumption may be used only for a confirmed broken Meter under
BR-UTIL-023 through BR-UTIL-028. An inaccessible or missing ordinary reading does
not authorize estimation.

### PR-UTIL-003 — Utility Consumption Ownership

**Business-rule traceability:** `BR-UTIL-003`

**Normative product behavior**

Utility consumption belongs to the Unit served by the Utility Meter.

Utility charges shall always be calculated using readings recorded from the meter assigned to that Unit.

### PR-UTIL-004 — Utility Billing Independence

**Business-rule traceability:** `BR-UTIL-004`

**Normative product behavior**

Electricity and Water shall be billed independently.

Each utility shall be calculated using:

- its own Utility Meter,
- its own Utility Readings,
- its own historical utility rate.

Changes affecting one utility shall never modify the billing of another utility.

### PR-UTIL-005 — One Active Meter Per Utility Type

**Business-rule traceability:** `BR-UTIL-005`

**Normative product behavior**

A Unit may have only one active Utility Meter for each Utility Type.

Examples:

**Valid**

- Unit 301
    - Electricity Meter A
    - Water Meter B

**Invalid**

- Unit 301
    - Electricity Meter A
    - Electricity Meter C (both active)

### PR-UTIL-006 — Meter Replacement

**Business-rule traceability:** `BR-UTIL-006`

**Normative product behavior**

A Utility Meter may be replaced when necessary.

Replacement does not remove the historical meter from the Property records.

Historical Utility Meters shall remain permanently preserved.

When a Meter is confirmed broken, it must be replaced. Failure and replacement
dates, the failed Meter, and the replacement Meter must remain linked.

### PR-UTIL-007 — Meter Replacement Boundary

**Business-rule traceability:** `BR-UTIL-007`

**Normative product behavior**

When a Utility Meter is replaced:

- all Utility Readings before the replacement belong to the previous meter,
- all Utility Readings recorded after installation belong to the replacement meter.

Actual consumption shall never be calculated by subtracting readings from two
different physical Meters. The first valid measurement day of the replacement
Meter must not also be counted in an approved estimate for the failed Meter.

### PR-UTIL-008 — Historical Meter Preservation

**Business-rule traceability:** `BR-UTIL-008`

**Normative product behavior**

Historical Utility Meters shall never be deleted solely because a replacement meter has been installed.

Historical meter information remains part of the permanent operational history of the Property.

### PR-UTIL-009 — Reading Sequence

**Business-rule traceability:** `BR-UTIL-009`

**Normative product behavior**

Utility Readings for the same Utility Meter shall follow chronological order.

Each new reading shall represent a later reading date than the previous validated reading.

### PR-UTIL-010 — Reading Validation

**Business-rule traceability:** `BR-UTIL-010`

**Normative product behavior**

Before utility billing is performed, Utility Readings shall be validated.

At a minimum, validation shall ensure:

- chronological reading dates,
- valid reading values,
- no negative consumption,
- no impossible consumption resulting from incorrect readings.

Utility Readings that fail validation shall not be used for billing.

### PR-UTIL-011 — Reading Corrections

**Business-rule traceability:** `BR-UTIL-011`

**Normative product behavior**

Incorrect Utility Readings may be corrected through an authorized business process before billing.

The correction shall preserve a complete audit history.

Historical Utility Readings shall never be silently overwritten.

If the reading has already been billed, its financial effect must be corrected
through the approved linked Invoice Adjustment process rather than by rewriting
the issued Invoice.

### PR-UTIL-012 — Consumption Calculation

**Business-rule traceability:** `BR-UTIL-012`

**Normative product behavior**

Utility consumption shall be calculated as the difference between two consecutive validated Utility Readings recorded for the same Utility Meter.

Consumption shall never be calculated using readings from different Utility Meters.

Start and end dates of the represented consumption period must be preserved and
must not overlap another billed period for the same Unit and Utility Type.

### PR-UTIL-013 — Historical Reading Integrity

**Business-rule traceability:** `BR-UTIL-013`

**Normative product behavior**

Every Utility Reading shall remain permanently associated with the exact Utility Meter that produced it.

Replacing a Utility Meter shall never alter historical Utility Readings.

### PR-UTIL-014 — Utility Rates

**Business-rule traceability:** `BR-UTIL-014`

**Normative product behavior**

Each Utility Type shall have its own billing rate.

Electricity and Water rates are maintained independently.

### PR-UTIL-015 — Rate Effective Date

**Business-rule traceability:** `BR-UTIL-015`

**Normative product behavior**

Every Utility Rate shall have an effective date.

The applicable rate is the Utility Rate effective on the date the Utility Invoice
is generated.

That one rate applies to the entire consumption period represented by the
Invoice.

### PR-UTIL-016 — Historical Rate Preservation

**Business-rule traceability:** `BR-UTIL-016`

**Normative product behavior**

Changes to Utility Rates shall never modify:

- historical Utility Invoices,
- historical Utility Charges,
- historical Utility Consumption,
- completed billing periods.

Historical Utility Rates shall remain permanently preserved.

Every issued Utility line must preserve the exact rate and rate effective date
actually used.

### PR-UTIL-017 — Future Rate Changes

**Business-rule traceability:** `BR-UTIL-017`

**Normative product behavior**

A revised Utility Rate becomes selectable on its approved effective date. The
Invoice generation date determines whether the old or revised rate applies.

A consumption period must not be split solely because the rate changed during
that period. Previously issued Invoices retain their historical rate.

### PR-UTIL-018 — No Duplicate Utility Billing

**Business-rule traceability:** `BR-UTIL-018`

**Normative product behavior**

The business shall prevent duplicate utility billing.

The same Unit, Utility Type, and consumption period shall never be billed more
once. Applicable Customer and Lease association must also be consistent.

A Utility billing period must not combine consumption assigned to different
financially responsible Customers. A move-in, move-out, or responsibility change
requires a validated Reading boundary or an approved broken-Meter estimation
boundary so each Customer is billed only for the applicable period.

### PR-UTIL-019 — Historical Utility Integrity

**Business-rule traceability:** `BR-UTIL-019`

**Normative product behavior**

Historical Utility Charges shall remain permanent financial records.

Historical Utility Billing shall never be silently:

- deleted,
- overwritten,
- recalculated,
- reassigned to another Utility Meter.

Corrections must preserve both the original operational source and every linked
financial correction.

### PR-UTIL-020 — Monthly Utility Billing

**Business-rule traceability:** `BR-UTIL-020`

**Normative product behavior**

Electricity and Water are billed monthly.

Each monthly period preserves its starting and ending Reading dates. For due-date
purposes, the billing month is the Property-local calendar month containing the
period's ending Reading date.

### PR-UTIL-021 — Utility Invoice Generation

**Business-rule traceability:** `BR-UTIL-021`

**Normative product behavior**

A Utility Invoice may be generated only after its ending Meter Reading has been
entered and validated, or after an authorized broken-Meter estimate is complete.

### PR-UTIL-022 — Utility Due Date

**Business-rule traceability:** `BR-UTIL-022`

**Normative product behavior**

A monthly Utility Invoice is due on the 5th day of the following month in the
Property's configured local timezone, where “following month” is relative to the
billing month defined in BR-UTIL-020.

### PR-UTIL-023 — Confirmed Broken-Meter Estimation

**Business-rule traceability:** `BR-UTIL-023`

**Normative product behavior**

Estimation is permitted only when a Meter is confirmed broken and valid actual
consumption for the unmeasured period cannot be obtained. The Meter must be
replaced, and the estimate must be explicitly identified as estimated
consumption caused by Meter failure.

### PR-UTIL-024 — Ordinary Missing Reading

**Business-rule traceability:** `BR-UTIL-024`

**Normative product behavior**

If staff cannot obtain a reading but the Meter is not confirmed broken, the
Utility must not be billed yet. The system must wait for a valid actual reading
and must not estimate merely because the Meter was inaccessible or the reading
was missed.

### PR-UTIL-025 — Three-complete-period Historical Basis

**Business-rule traceability:** `BR-UTIL-025`

**Normative product behavior**

When three or more complete historical actual periods exist for the same Unit and
Utility Type, use the three most recent complete historical actual periods before
the affected broken-Meter period as the historical basis.

```text
Weighted Historical Daily Average
=
Total Actual Consumption Across the Three Complete Periods
-----------------------------------------------------------
Total Calendar Days Represented by Those Periods
```

The system must not average three separately rounded period averages.

### PR-UTIL-026 — Basis Daily Average and Estimate Boundaries

**Business-rule traceability:** `BR-UTIL-026`

**Normative product behavior**

Every historical basis under BR-UTIL-025 and every complete future-period basis
under BR-UTIL-027 or BR-UTIL-028 uses one daily average:

```text
Basis Daily Average
=
Total Actual Consumption Across All Periods in the Basis
--------------------------------------------------------
Total Calendar Days Represented by All Periods in the Basis
```

The system must not average separately rounded period averages.

```text
Estimated Consumption
=
Basis Daily Average × Inclusive Unmeasured Calendar Days
```

The period begins when consumption became unmeasurable and ends on the last day
before the replacement Meter begins providing valid readings. A day must not be
counted in both the estimate and the replacement-Meter actual period.

### PR-UTIL-027 — Fewer-than-three Future-period Fallback

**Business-rule traceability:** `BR-UTIL-027`

**Normative product behavior**

If fewer than three, but at least one, complete historical actual period exists
for the same Unit and Utility Type, those one or two historical periods must not
be substituted for the approved three-period historical basis.

The system must wait until one complete future month or period of actual
consumption becomes available for that same Unit and Utility Type and use that
complete future actual period as the daily-average basis under BR-UTIL-026. It
must not substitute another or comparable Unit or invent an arbitrary estimate.

Until that future complete actual period exists, the broken-Meter estimate and
affected charge remain pending and unfinalized. The reason for delay and the
future actual data eventually used must be preserved.

### PR-UTIL-028 — Zero-history Future-period Fallback

**Business-rule traceability:** `BR-UTIL-028`

**Normative product behavior**

If zero complete historical actual periods exist for the same Unit and Utility
Type, there is no usable historical basis. The system must wait until one complete
future month or period of actual consumption becomes available for that same Unit
and Utility Type and use that complete future actual period as the daily-average
basis under BR-UTIL-026.

Until that future complete actual period exists, the broken-Meter estimate and
affected charge remain pending and unfinalized. The reason for delay and the
future actual data eventually used must be preserved.

### PR-UTIL-029 — Generation-date Rate Selection

**Business-rule traceability:** `BR-UTIL-029`

**Normative product behavior**

The Invoice generation date selects the effective Utility Rate. Selection uses
the Property's configured local timezone and is preserved on the Invoice.

### PR-UTIL-030 — Whole-period Rate Application

**Business-rule traceability:** `BR-UTIL-030`

**Normative product behavior**

The selected Utility Rate applies to the entire represented consumption period.
The system must not allocate consumption across old and new rates solely because
a rate effective date occurred within that period.

### PR-UTIL-031 — Advance Rate-change Notice

**Business-rule traceability:** `BR-UTIL-031`

**Normative product behavior**

Customers must be informed of a Utility Rate change before its effective date.
The effective date, not the notice date, controls automated rate selection.

### PR-UTIL-032 — Utility Charge Source of Truth

**Business-rule traceability:** `BR-UTIL-032`

**Normative product behavior**

```text
Utility Charge
=
Validated Actual Consumption or Authorized Broken-Meter Estimate
×
Applicable Generation-date Utility Rate
```

The final USD amount uses the approved monetary rounding rule. Staff must not
replace the calculated charge with an arbitrary amount.

## 8.11 Service Charge Requirements

### PR-SVC-001 — Fixed Monthly Services

**Business-rule traceability:** `BR-SVC-001`

**Normative product behavior**

The Property currently supports the following recurring fixed monthly service charges:

- Internet
- Trash Collection

These services are billed as fixed monthly charges rather than consumption-based charges.

This document approves no other Service type. A different Service requires a
separate Owner-approved rule before it may be configured or billed.

### PR-SVC-002 — Service Charge Independence

**Business-rule traceability:** `BR-SVC-002`

**Normative product behavior**

Service charges are independent of:

- Rent,
- Electricity,
- Water,
- Security Deposit,
- Pet Deposit.

Changes to one category shall not automatically affect another.

### PR-SVC-003 — Monthly Billing

**Business-rule traceability:** `BR-SVC-003`

**Normative product behavior**

Internet and Trash Collection are billed monthly in advance as separate line
items on the applicable Rent Invoice.

Separate Service Charge Invoices are not normally generated for these fixed
recurring monthly Services.

### PR-SVC-004 — Fixed Charges

**Business-rule traceability:** `BR-SVC-004`

**Normative product behavior**

Internet and Trash Collection are fixed monthly charges.

Their billing amount is not affected by:

- utility consumption,
- number of occupants,
- number of days within a normal full month.

The first partial month is prorated using actual calendar days. Final and
early-termination-month treatment follows the signed Lease and approved
termination rules and is not automatically prorated merely because the Customer
physically leaves during the month.

### PR-SVC-005 — Service Rate Effective Date

**Business-rule traceability:** `BR-SVC-005`

**Normative product behavior**

Every service charge revision shall have an effective date.

The revised amount applies only to billing periods beginning on or after that effective date.

The applicable configured Service terms remain the source of truth.

### PR-SVC-006 — Historical Service Rate Preservation

**Business-rule traceability:** `BR-SVC-006`

**Normative product behavior**

Historical service rates shall remain permanently preserved.

Changes to Internet or Trash charges shall never modify historical invoices.

### PR-SVC-007 — Future Service Rate Changes

**Business-rule traceability:** `BR-SVC-007`

**Normative product behavior**

Revised service charges shall only affect future billing periods.

Completed billing periods shall always retain the original service charge used during billing.

### PR-SVC-008 — Historical Financial Integrity

**Business-rule traceability:** `BR-SVC-008`

**Normative product behavior**

Historical Internet and Trash charges are permanent financial records.

They shall never be silently:

- deleted,
- recalculated,
- overwritten,
- replaced.

All revisions shall preserve complete historical traceability.

### PR-SVC-009 — Rent Invoice Line Items

**Business-rule traceability:** `BR-SVC-009`

**Normative product behavior**

Each fixed recurring Service is a separate categorized line item on the
applicable Rent Invoice. Its amount contributes to the Invoice total without
being reclassified as Rent.

### PR-SVC-010 — Line-level History

**Business-rule traceability:** `BR-SVC-010`

**Normative product behavior**

Each Service line preserves its Service identity, category, configured rate,
billing period, calculation when prorated, and final amount.

### PR-SVC-011 — Advance Billing Schedule

**Business-rule traceability:** `BR-SVC-011`

**Normative product behavior**

Fixed recurring Services use the same billing cycle as Rent: generation on the
25th in the Property's configured local timezone for the upcoming month and the
same applicable Due Date as the Rent Invoice.

### PR-SVC-012 — First Partial Month

**Business-rule traceability:** `BR-SVC-012`

**Normative product behavior**

The first partial-month Service amount is calculated using the same inclusive
actual-calendar-day formula and final half-up USD-cent rounding as Rent.

### PR-SVC-013 — Final and Early-termination Month

**Business-rule traceability:** `BR-SVC-013`

**Normative product behavior**

Fixed recurring Services are not automatically prorated because physical
occupancy ends during a month. The applicable signed Lease and approved
termination rules control the valid final charge.

### PR-SVC-014 — Configured Services Only

**Business-rule traceability:** `BR-SVC-014`

**Normative product behavior**

Only a configured Property Service that applies under the governing terms may be
billed. The system must not create a Service or charge from free-form Invoice
entry.

### PR-SVC-015 — Configured Rate Source of Truth

**Business-rule traceability:** `BR-SVC-015`

**Normative product behavior**

Each fixed recurring Service line is calculated from its applicable configured
Service terms and rate. Staff must not replace that amount with an arbitrary
value. Issued corrections use the linked Adjustment rules.

## 8.12 Invoice Requirements

### PR-INV-001 — Invoice as the Official Financial Record

**Business-rule traceability:** `BR-INV-001`

**Normative product behavior**

Every billable financial obligation owed by a Customer shall be represented by an Invoice.

Invoices serve as the official record of amounts due for services or charges provided by the Property.

Every Invoice has mandatory Customer ownership whether or not a Lease association
applies.

### PR-INV-002 — Invoice Ownership

**Business-rule traceability:** `BR-INV-002`

**Normative product behavior**

Every Invoice shall belong to exactly one Customer.

An Invoice may additionally be associated with zero or one Lease when the billed
obligation arises from that Lease.

When a Lease association exists, the Invoice Customer must not contradict the
Customer responsibility under that Lease, and all applicable Unit, contractual,
and billing facts must be consistent with it. The explicit Invoice Customer is
not replaced by the Lease association.

An Invoice without a Lease still requires an approved governing business event.
Optional Lease association does not approve a new Invoice Category or charge.

A Customer may have multiple Invoices.

### PR-INV-003 — Invoice Identification

**Business-rule traceability:** `BR-INV-003`

**Normative product behavior**

Each Invoice shall have a unique business identifier.

Once issued, the Invoice identity shall never be reused or reassigned.

### PR-INV-004 — Invoice Date

**Business-rule traceability:** `BR-INV-004`

**Normative product behavior**

Every Invoice shall record the official Invoice Date representing when the financial obligation was created.

The Invoice Date forms part of the permanent financial record.

### PR-INV-005 — Billing Period

**Business-rule traceability:** `BR-INV-005`

**Normative product behavior**

Where applicable, an Invoice shall record the billing period it represents.

Examples include:

- Monthly Rent
- Electricity
- Water
- Internet
- Trash Collection

Invoices that do not represent a recurring billing period (such as Damage Charges) may omit a billing period where appropriate.

When the Invoice is associated with a Lease, its billing period must not
contradict that Lease. A billing period does not by itself make Lease association
mandatory.

### PR-INV-006 — Supported Invoice and Line Categories

**Business-rule traceability:** `BR-INV-006`

**Normative product behavior**

Every Invoice shall have exactly one primary supported Invoice Category, and
every Invoice line shall have exactly one supported line category:

- Rent
- Utilities
- Service Charges
- Damage Charges
- Miscellaneous Charges

An Invoice may contain more than one line category only where an approved rule
requires combined billing, such as fixed recurring Service lines on a primary
Rent Invoice. No additional category is approved by this rule.

### PR-INV-007 — Deposit Exclusion

**Business-rule traceability:** `BR-INV-007`

**Normative product behavior**

Security Deposits and Pet Deposits are liabilities held by the Property.

Deposits are **not** Invoice Categories and shall never be billed as ordinary Invoices.

Deposit collection and application are governed by their own business rules.

### PR-INV-008 — Category Integrity

**Business-rule traceability:** `BR-INV-008`

**Normative product behavior**

The primary Invoice Category and each line's category determine their applicable
source-of-truth rules. Every line must preserve its category and source
independently.

Changing the primary Invoice Category or a line category after issuance is not
permitted.

### PR-INV-009 — Standard Invoice Statuses

**Business-rule traceability:** `BR-INV-009`

**Normative product behavior**

An Invoice shall exist in one of the following statuses:

- DRAFT
- UNPAID
- PARTIALLY_PAID
- PAID
- VOID

### PR-INV-010 — Draft Invoice

**Business-rule traceability:** `BR-INV-010`

**Normative product behavior**

A newly created Invoice shall initially have the status:

- DRAFT

A DRAFT Invoice may be reviewed and corrected before issuance. If it is abandoned
or invalidated, it becomes VOID with a reason; it is not deleted or described as
cancelled.

A DRAFT Invoice is not a Customer receivable, does not increase Accounts
Receivable, is excluded from outstanding balances, and cannot make a Customer
overdue.

### PR-INV-011 — Invoice Issuance

**Business-rule traceability:** `BR-INV-011`

**Normative product behavior**

When a Draft Invoice is officially issued to the Customer, its status shall become:

- UNPAID

Once issued, the Invoice becomes an official financial document.

The original Invoice Date, Invoice Number, Invoice Amount, and Billing Period become part of the permanent financial history.

Approved deterministic scheduled billing may generate and issue an Invoice
without manual approval of an intermediate DRAFT. Manual or exceptional charges
may remain DRAFT for review.

### PR-INV-012 — Partial Payment

**Business-rule traceability:** `BR-INV-012`

**Normative product behavior**

When active Payment Allocations, Customer Credit applications, or authorized
Final Settlement Deposit applications reduce an issued Invoice but leave a
positive outstanding balance, its status shall become:

- PARTIALLY_PAID

### PR-INV-013 — Fully Paid

**Business-rule traceability:** `BR-INV-013`

**Normative product behavior**

When active Payment Allocations, Customer Credit applications, or authorized
Final Settlement Deposit applications reduce the outstanding balance to exactly
zero, the Invoice status shall become:

- PAID

### PR-INV-014 — Void

**Business-rule traceability:** `BR-INV-014`

**Normative product behavior**

An Invoice may become:

- VOID

only through an authorized business process.

Voiding an Invoice permanently ends its billing lifecycle while preserving its historical record.

VOID is a controlled exceptional mechanism for an Invoice that fundamentally
should not exist. It is not the normal method for correcting an amount.

### PR-INV-015 — Allowed Invoice Status Transitions

**Business-rule traceability:** `BR-INV-015`

**Normative product behavior**

Invoices shall transition only through the business-approved lifecycle shown below.

```text
DRAFT
 ├──► UNPAID
 └──► VOID

UNPAID
 ├──► PARTIALLY_PAID
 ├──► PAID
 └──► VOID

PARTIALLY_PAID
 ├──► UNPAID (after authorized allocation/application reversal)
 ├──► PAID
 └──► VOID (only after all active Allocations and Credit applications have been
           explicitly reversed)

PAID
 ├──► PARTIALLY_PAID (after authorized allocation/application reversal)
 └──► UNPAID (after authorized allocation/application reversal)

VOID
 └──► (Terminal state)
```

Any transition not shown above shall be rejected. UNPAID, PARTIALLY_PAID, and
PAID are determined by the current adjusted obligation and active financial
applications; they must be recomputed after an authorized reversal or
Adjustment.

An Invoice that has received one or more Payments shall not be VOID until all associated Payment allocations have been properly reversed in accordance with the Payment business rules.

Financial corrections shall be performed through approved adjustment, reversal, or correction procedures while preserving the complete audit history.

### PR-INV-016 — Invoice Creation

**Business-rule traceability:** `BR-INV-016`

**Normative product behavior**

Invoices may be created through approved business events, including:

- recurring Rent billing,
- Utility billing,
- recurring Service Charges,
- Damage Charges,
- Miscellaneous Charges.

Every Invoice shall originate from a legitimate business event.

It must identify exactly one Customer. It identifies a Lease only when the
governing obligation is associated with that Lease.

### PR-INV-017 — Invoice Amount

**Business-rule traceability:** `BR-INV-017`

**Normative product behavior**

The Invoice Amount shall equal the total charges represented by that Invoice at the time it is issued.

Once issued, the original Invoice Amount forms part of the permanent financial history.

### PR-INV-018 — Due Date

**Business-rule traceability:** `BR-INV-018`

**Normative product behavior**

Every Invoice shall include a Due Date.

Recurring Due Dates follow their approved billing rules. For Damage Charges,
Miscellaneous Charges, debit Adjustments, and other non-recurring obligations,
the Due Date must come from the signed Lease or the approved business event or
document creating the obligation.

Authorized staff may record that applicable Due Date, but must not choose an
arbitrary date. Its source and reason must be auditable.

### PR-INV-019 — Adjustment Principle

**Business-rule traceability:** `BR-INV-019`

**Normative product behavior**

If an issued Invoice contains an error, the correction shall preserve the complete financial history.

Historical financial records shall never be silently modified.

### PR-INV-020 — No Silent Modification

**Business-rule traceability:** `BR-INV-020`

**Normative product behavior**

After issuance, the following shall never be silently changed:

- Invoice Amount
- Invoice Date
- Billing Period
- Invoice Category

Any correction shall remain fully auditable.

### PR-INV-021 — Linked Adjustment Method

**Business-rule traceability:** `BR-INV-021`

**Normative product behavior**

A legitimate correction to the financial amount of an issued Invoice must use an
explicit linked debit or credit Adjustment.

The Adjustment changes the current financial obligation without replacing the
original Invoice amount or contractual source. It must identify the original
Invoice, reason, amount, authorization, actor, and time.

### PR-INV-022 — Authorized Voiding

**Business-rule traceability:** `BR-INV-022`

**Normative product behavior**

Only authorized personnel may void an Invoice.

The reason for voiding shall be recorded.

VOID is permitted only when the Invoice fundamentally should not exist. Amount
corrections normally use BR-INV-021.

### PR-INV-023 — No Physical Deletion

**Business-rule traceability:** `BR-INV-023`

**Normative product behavior**

Voiding an Invoice shall never physically remove it from the financial history.

The original Invoice shall remain permanently available for audit purposes.

### PR-INV-024 — Restrictions on Voiding Paid Invoices

**Business-rule traceability:** `BR-INV-024`

**Normative product behavior**

An Invoice that has received one or more Payments shall not be voided directly.

Active Allocations, Customer Credit applications, Refunds, Adjustments, and other
financial dependencies must first be resolved through their explicit approved
processes before VOID may proceed.

### PR-INV-025 — Historical Preservation

**Business-rule traceability:** `BR-INV-025`

**Normative product behavior**

Voided Invoices remain part of the permanent financial records of the Property.

### PR-INV-026 — Duplicate Rent Billing

**Business-rule traceability:** `BR-INV-026`

**Normative product behavior**

The business shall prevent multiple Rent Invoices covering the same Lease and the same rental period.

### PR-INV-027 — Duplicate Utility Billing

**Business-rule traceability:** `BR-INV-027`

**Normative product behavior**

The business shall prevent utility consumption from being billed more than once.

The same Unit, Utility Type, and consumption period shall not produce duplicate
Utility billing. Applicable Customer and optional Lease association must be
consistent and must not be varied to bypass this rule.

### PR-INV-028 — Duplicate Service Charge Billing

**Business-rule traceability:** `BR-INV-028`

**Normative product behavior**

The business shall prevent recurring Internet and Trash Charges from being billed multiple times for the same Lease and billing period.

### PR-INV-029 — Duplicate Invoice Prevention Principle

**Business-rule traceability:** `BR-INV-029`

**Normative product behavior**

The application shall reject any Invoice that would create duplicate billing for the same financial obligation.

Examples include:

- duplicate Rent for the same billing period,
- duplicate Electricity billing for the same consumption period,
- duplicate Water billing for the same consumption period,
- duplicate Internet charges for the same month,
- duplicate Trash charges for the same month.

The governing source facts define duplicate identity. An obligation must not be
billed once with a Lease association and again without one.

### PR-INV-030 — Permanent Financial Record

**Business-rule traceability:** `BR-INV-030`

**Normative product behavior**

Every issued Invoice forms part of the permanent accounting history of the Property.

### PR-INV-031 — Historical Preservation

**Business-rule traceability:** `BR-INV-031`

**Normative product behavior**

Issued Invoices shall never be silently:

- deleted,
- overwritten,
- reused,
- recreated with the same identity.

### PR-INV-032 — Historical Accuracy

**Business-rule traceability:** `BR-INV-032`

**Normative product behavior**

Historical Invoices shall permanently preserve:

- Invoice Number,
- Invoice Date,
- Invoice Category,
- Billing Period,
- Original Charges,
- Due Date,
- Payment History,
- Final Status.

The Invoice must also preserve its Customer owner and the exact Lease association
or absence of Lease association that applied when issued.

These values represent the official historical financial record.

### PR-INV-033 — Independence from Future Changes

**Business-rule traceability:** `BR-INV-033`

**Normative product behavior**

Future changes to:

- Rent,
- Utility Rates,
- Service Charges,
- Customer Information,
- Lease Information,
- Utility Meters,

shall never modify previously issued Invoices.

Historical Invoices shall always reflect the business facts that existed at the time they were issued.

Future changes must not retroactively add, remove, or replace an Invoice's Lease
association or Customer ownership.

### PR-INV-034 — Financial Integrity

**Business-rule traceability:** `BR-INV-034`

**Normative product behavior**

Every Invoice-related business action shall preserve:

- financial accuracy,
- auditability,
- traceability,
- historical integrity.

The application shall reject any action that compromises the integrity of the Property's financial records.

### PR-INV-035 — Audit Requirement

**Business-rule traceability:** `BR-INV-035`

**Normative product behavior**

Every significant Invoice event shall be fully auditable, including but not limited to:

- Invoice creation,
- Invoice adjustment,
- Invoice voiding,
- status changes,
- due date revisions (where permitted),
- payment allocation changes.

Historical audit information shall remain permanently available and shall never be silently removed.

### PR-INV-036 — Mandatory Customer Ownership

**Business-rule traceability:** `BR-INV-036`

**Normative product behavior**

Every Invoice has exactly one explicit Customer owner from creation through
historical preservation. Customer ownership is required independently of whether
a Lease association exists.

### PR-INV-037 — Optional Lease Association

**Business-rule traceability:** `BR-INV-037`

**Normative product behavior**

An Invoice may be associated with zero or one Lease. A Lease is recorded only
when applicable to the governing obligation and never substitutes for mandatory
Customer ownership.

### PR-INV-038 — Lease Association Consistency

**Business-rule traceability:** `BR-INV-038`

**Normative product behavior**

When a Lease is associated, the Invoice Customer must be a Customer financially
responsible under that Lease. Applicable Unit, period, Rent, Service, and other
contractual facts must not contradict the Lease.

Choosing one Invoice Customer does not remove the joint Lease responsibility of
other Lease Signers. Lease association must not be added or removed to evade
source, duplicate, allocation, or settlement validation.

### PR-INV-039 — Mixed Line-item Integrity

**Business-rule traceability:** `BR-INV-039`

**Normative product behavior**

A Rent Invoice may include separately categorized fixed recurring Service lines.
Each line preserves its category, source, rate, calculation, and amount. Combined
billing must not reclassify a Service line as Rent.

### PR-INV-040 — Rent Invoice Source of Truth

**Business-rule traceability:** `BR-INV-040`

**Normative product behavior**

A Rent Invoice requires a valid applicable signed Lease covering the rental
period. The Invoice Customer and Unit must be valid in that Lease context, and
contractual Rent must come from the Lease.

This Rent-specific requirement does not make Lease association mandatory for all
Invoices.

### PR-INV-041 — Utility Invoice Source of Truth

**Business-rule traceability:** `BR-INV-041`

**Normative product behavior**

Utility charges come only from validated actual Meter Readings or the authorized
broken-Meter estimate, multiplied by the generation-date Utility Rate. Customer,
Unit, Meter, consumption period, and optional Lease association must be mutually
consistent.

Staff must not enter an arbitrary replacement Utility amount.

### PR-INV-042 — Fixed Service Source of Truth

**Business-rule traceability:** `BR-INV-042`

**Normative product behavior**

Fixed recurring Service lines come from configured Service terms and rates. When
included with Rent, they use the same applicable Customer and Lease context as
the Rent Invoice.

### PR-INV-043 — DRAFT Correction

**Business-rule traceability:** `BR-INV-043`

**Normative product behavior**

Before issuance, source data and calculations on a DRAFT Invoice may be corrected
subject to audit. DRAFT correction must not create Accounts Receivable or erase
the record.

### PR-INV-044 — Linked Debit and Credit Adjustments

**Business-rule traceability:** `BR-INV-044`

**Normative product behavior**

Issued amount corrections use explicit linked debit or credit Adjustments.
Original Invoice values and contractual terms remain unchanged.

### PR-INV-045 — Adjustment Source and Linkage

**Business-rule traceability:** `BR-INV-045`

**Normative product behavior**

Every Adjustment preserves its original Invoice, source obligation, amount,
reason, authorization, actor, and time. It follows the corrected obligation's
actual Customer and optional Lease context and must not manufacture a Lease
association for a non-Lease Invoice.

### PR-INV-046 — Exceptional VOID

**Business-rule traceability:** `BR-INV-046`

**Normative product behavior**

VOID is available only when an Invoice fundamentally should not exist. It is not
the ordinary amount-correction method, and it never removes the original record.

### PR-INV-047 — Financial Dependency Preservation

**Business-rule traceability:** `BR-INV-047`

**Normative product behavior**

Active Allocations, Customer Credit applications, Refunds, Adjustments, and other
linked financial events must be resolved through explicit processes. Nothing may
be silently deleted, detached, or reassigned to permit VOID or correction.

### PR-INV-048 — Correction Authorization and Reason

**Business-rule traceability:** `BR-INV-048`

**Normative product behavior**

An issued-Invoice correction requires appropriate authorization, a mandatory
reason, timestamp, user identity, preserved original values, and linkage between
the source and correction.

### PR-INV-049 — Non-recurring Due Date Source

**Business-rule traceability:** `BR-INV-049`

**Normative product behavior**

The Due Date for a Damage Charge, Miscellaneous Charge, debit Adjustment, or
other non-recurring obligation comes from the signed Lease or approved governing
business event or document. It must not be arbitrary, automatically set to the
monthly 5th, or automatically made immediate unless its governing source requires
that result.

### PR-INV-050 — Deterministic Scheduled Issuance

**Business-rule traceability:** `BR-INV-050`

**Normative product behavior**

Approved scheduled billing may generate and issue Invoices automatically from
deterministic source rules. Rent and its fixed recurring Service lines require an
applicable signed Lease. Other Invoices follow their approved source rules.

## 8.13 Payment and Allocation Requirements

### PR-PAY-001 — Payment Ownership

**Business-rule traceability:** `BR-PAY-001`

**Normative product behavior**

Every Payment shall identify exactly one payer Customer.

A Customer may have multiple Payments throughout their business relationship with the Property.

A third-party payer does not become a financially responsible Customer under a
Lease merely by making the Payment.

### PR-PAY-002 — Lease Association

**Business-rule traceability:** `BR-PAY-002`

**Normative product behavior**

A Payment may optionally be associated with a Lease.

Lease association provides business context but does not determine how the Payment is allocated.

Payments received before Move-in or after Lease termination may not have an associated Lease.

For a third-party Payment, an optional Lease or Invoice designation records the
payer's identified intent and must not be treated as ownership of that obligation.

### PR-PAY-003 — Payment Represents Money Received

**Business-rule traceability:** `BR-PAY-003`

**Normative product behavior**

A Payment records the receipt of funds from a Customer.

A Payment itself does not determine which Invoice has been paid.

Invoices are settled only through Payment Allocation.

Payment receipt, Payment Allocation, Payment Reversal, Customer Credit, and
Refund are separate financial concepts and events.

### PR-PAY-004 — Unique Payment Identification

**Business-rule traceability:** `BR-PAY-004`

**Normative product behavior**

Every Payment shall have a unique business identifier.

Once assigned, the Payment identifier shall never be reused or modified.

### PR-PAY-005 — Payment Date

**Business-rule traceability:** `BR-PAY-005`

**Normative product behavior**

Every Payment shall record the official Payment Date representing the date the Property received the funds.

The Payment Date forms part of the permanent financial history.

For a KHR Payment, confirmation of receipt is also the event at which the
applicable exchange rate is selected and preserved.

### PR-PAY-006 — Configurable Payment Methods and Currencies

**Business-rule traceability:** `BR-PAY-006`

**Normative product behavior**

Accepted Payment Methods are configured business data and are not hard-coded by
this document. Only a currently accepted configured method may be used.

Supported Payment currencies are USD and KHR under BR-MONEY-002.

### PR-PAY-007 — Payment Method Preservation

**Business-rule traceability:** `BR-PAY-007`

**Normative product behavior**

The Payment Method recorded when the Payment is received shall remain permanently preserved.

Historical Payments shall never be modified solely because a Payment Method is renamed or retired.

The Payment currency and, for KHR, all exchange and source values must likewise
remain permanent.

### PR-PAY-008 — Payment Receipt Statuses

**Business-rule traceability:** `BR-PAY-008`

**Normative product behavior**

Payment receipt status may be only:

- RECEIVED
- REVERSED

Allocation progress is derived from active Allocation records. Refund is a
separate financial event and is not a Payment status.

### PR-PAY-009 — Initial Status

**Business-rule traceability:** `BR-PAY-009`

**Normative product behavior**

A newly received Payment shall initially have the status:

- RECEIVED

### PR-PAY-010 — Partially Allocated

**Business-rule traceability:** `BR-PAY-010`

**Normative product behavior**

When active Allocations use part, but not all, of a RECEIVED Payment's available
USD accounting value, the Payment is partially allocated as a derived condition.
Its receipt status remains RECEIVED.

### PR-PAY-011 — Fully Allocated

**Business-rule traceability:** `BR-PAY-011`

**Normative product behavior**

When active Allocations use the Payment's entire available USD accounting value,
the Payment is fully allocated as a derived condition. Its receipt status remains
RECEIVED.

No remaining unallocated balance shall exist.

### PR-PAY-012 — Reversed

**Business-rule traceability:** `BR-PAY-012`

**Normative product behavior**

A Payment becomes REVERSED only through an authorized explicit Payment Reversal
event linked to the original Payment.

A reversed Payment shall remain permanently preserved for audit purposes.

All active Allocations and any Customer Credit recognition sourced from the
Payment must first be reversed through their explicit linked processes. A
completed Refund sourced from the Payment prevents reversal unless an authorized
linked correction first resolves that Refund without rewriting history.

A Payment Reversal recomputes every affected Invoice balance and status.

### PR-PAY-013 — Refund Is Separate From Payment

**Business-rule traceability:** `BR-PAY-013`

**Normative product behavior**

Returning money uses a separate linked Refund event. A Refund does not change the
original Payment amount, erase its Allocations, or create a REFUNDED Payment
status.

### PR-PAY-014 — Payment Lifecycle and Allocation Condition

**Business-rule traceability:** `BR-PAY-014`

**Normative product behavior**

The permitted receipt lifecycle is:

```text
RECEIVED -> REVERSED
REVERSED -> terminal
```

Posting or reversing Allocations changes the derived allocated and unallocated
amounts without changing RECEIVED status. A Refund follows its source-specific
rules and does not require falsifying the original receipt lifecycle.

### PR-PAY-015 — Payment Amount

**Business-rule traceability:** `BR-PAY-015`

**Normative product behavior**

The original Payment Amount represents the amount of money received from the
payer in its received currency.

Once recorded, the original Payment Amount shall never be silently modified.

### PR-PAY-016 — No Physical Deletion

**Business-rule traceability:** `BR-PAY-016`

**Normative product behavior**

Payments form part of the permanent financial history.

Payments shall never be physically deleted.

### PR-PAY-017 — Historical Preservation

**Business-rule traceability:** `BR-PAY-017`

**Normative product behavior**

Historical Payments shall permanently preserve:

- Payment Number
- Customer
- Lease (if applicable)
- Payment Date
- Payment Method
- Received Currency and Original Amount
- USD accounting value
- KHR amount and exact exchange information when applicable
- Current Status
- payer intent or designation when applicable

These values constitute the official financial record.

### PR-PAY-018 — Audit Requirement

**Business-rule traceability:** `BR-PAY-018`

**Normative product behavior**

Every significant Payment event shall be fully auditable, including:

- Payment creation
- receipt-status changes
- Allocation changes
- Reversal
- Refund

Historical audit information shall never be silently removed.

### PR-PAY-019 — Allocation Is a Separate Financial Event

**Business-rule traceability:** `BR-PAY-019`

**Normative product behavior**

A Payment Allocation links part of one RECEIVED Payment's USD accounting value
to one issued Customer Invoice. It does not rewrite either source record.

### PR-PAY-020 — Manual Authorized Posting

**Business-rule traceability:** `BR-PAY-020`

**Normative product behavior**

Payment Allocation is manual and performed by authorized staff. The system may
calculate and present a proposal, but it must not post that proposal without
authorized staff confirmation.

### PR-PAY-021 — Deterministic Default Proposal

**Business-rule traceability:** `BR-PAY-021`

**Normative product behavior**

When the payer has not designated a specific Invoice, the system proposes
allocation across the applicable outstanding Invoices using the approved FIFO
rules.

### PR-PAY-022 — Oldest-due Ordering

**Business-rule traceability:** `BR-PAY-022`

**Normative product behavior**

The default proposal applies value to the oldest Due Date first and continues
through applicable outstanding Invoices until the Payment is exhausted or all
applicable obligations are satisfied.

No category preference, such as Rent before Electricity, is permitted.

### PR-PAY-023 — Deterministic Ties

**Business-rule traceability:** `BR-PAY-023`

**Normative product behavior**

Invoices with the same Due Date are ordered by Invoice issue or generation order
and then by a stable Invoice sequence or identifier.

### PR-PAY-024 — Customer-designated Allocation

**Business-rule traceability:** `BR-PAY-024`

**Normative product behavior**

When the Customer explicitly identifies an Invoice, authorized staff may post the
Payment to that valid designated Invoice instead of the default FIFO proposal.
The designation and posted Allocation must be preserved.

### PR-PAY-025 — Normal Customer Scope

**Business-rule traceability:** `BR-PAY-025`

**Normative product behavior**

For a normal Customer Payment, the default proposal includes applicable
outstanding Invoices belonging to the financially responsible Customer,
including across that Customer's applicable Lease relationships where permitted
by the approved rules.

An Invoice without a Lease remains eligible when it belongs to that Customer and
is otherwise a valid applicable obligation.

### PR-PAY-026 — Third-party Payment Scope

**Business-rule traceability:** `BR-PAY-026`

**Normative product behavior**

A third-party Payment follows the payer's identified Invoice or Lease intent. It
must not be automatically spread across unrelated obligations of either the payer
or another Customer.

The third-party payer does not become the Invoice Customer or a Lease Signer by
making the Payment.

For allocation purposes, a jointly responsible Lease Signer who is not the
Invoice Customer uses this designated-payment path. That treatment does not
remove or change the Signer's approved joint Lease responsibility.

### PR-PAY-027 — Allocation Amount Limits

**Business-rule traceability:** `BR-PAY-027`

**Normative product behavior**

An Allocation must be positive and must not exceed either:

- the Payment's remaining unallocated USD accounting value; or
- the target Invoice's current outstanding balance.

### PR-PAY-028 — No Negative Invoice Balance

**Business-rule traceability:** `BR-PAY-028`

**Normative product behavior**

Posting an Allocation must never cause an Invoice outstanding balance to become
negative. Payment value beyond applicable outstanding balances remains
unallocated excess.

### PR-PAY-029 — Allocation History and Reversal

**Business-rule traceability:** `BR-PAY-029`

**Normative product behavior**

Every posted Allocation permanently preserves its Payment, Invoice, amount,
posting time, and authorized user. A correction uses an explicit linked
Allocation Reversal and recomputes affected balances and statuses; it never
deletes or overwrites the original Allocation.

### PR-PAY-030 — True Overpayment

**Business-rule traceability:** `BR-PAY-030`

**Normative product behavior**

An overpayment exists only after all applicable outstanding obligations have been
handled and a positive amount remains unallocated from the Payment.

### PR-PAY-031 — Unallocated Excess

**Business-rule traceability:** `BR-PAY-031`

**Normative product behavior**

Unallocated excess remains part of the original RECEIVED Payment until the payer
chooses an approved disposition. It does not automatically become Customer
Credit.

Once excess is recognized as Customer Credit or committed to a Refund, that
disposed amount is excluded from the Payment's allocatable available value. The
original received Payment amount remains unchanged.

### PR-PAY-032 — Customer Coordination

**Business-rule traceability:** `BR-PAY-032`

**Normative product behavior**

When overpayment is identified, Property Management must coordinate with the
payer and ask whether the excess should be retained as Customer Credit or
refunded. The decision, amount, date and time, and user recording it must be
audited.

### PR-PAY-033 — Credit Choice

**Business-rule traceability:** `BR-PAY-033`

**Normative product behavior**

Only the amount the payer authorizes for retention may be recognized as Customer
Credit. The resulting Credit remains linked to the original Payment and belongs
to the recorded payer Customer.

Recognition of the Credit consumes that excess from the Payment's allocatable
available value without reducing or rewriting the original Payment amount.

### PR-PAY-034 — Refund Choice

**Business-rule traceability:** `BR-PAY-034`

**Normative product behavior**

When the payer requests return of the excess, the Refund workflow must link the
Refund to that original Payment and excess. The original Payment amount and every
Allocation remain unchanged.

The amount committed to the Refund is excluded from the Payment's allocatable
available value so that the same excess cannot be reused.

### PR-PAY-035 — No Early Future Invoice for Advance Money

**Business-rule traceability:** `BR-PAY-035`

**Normative product behavior**

An unallocated Payment or Customer Credit must not cause a future Rent Invoice to
be generated before its approved billing schedule merely to absorb advance
money.

## 8.14 Customer Credit Requirements

### PR-CREDIT-001 — USD Accounting Balance

**Business-rule traceability:** `BR-CREDIT-001`

**Normative product behavior**

Customer Credit is maintained as a USD accounting value. No separate
KHR-denominated Customer Credit balance is approved.

### PR-CREDIT-002 — Authorized Creation

**Business-rule traceability:** `BR-CREDIT-002`

**Normative product behavior**

Unallocated excess becomes Customer Credit only after the payer authorizes
Property Management to retain the identified amount. Recognition must not be
automatic.

### PR-CREDIT-003 — Payment Source Linkage

**Business-rule traceability:** `BR-CREDIT-003`

**Normative product behavior**

Every Customer Credit created from overpayment identifies the original Payment,
the retained excess amount, the payer Customer, and the authorization event.

### PR-CREDIT-004 — Separate From Deposit

**Business-rule traceability:** `BR-CREDIT-004`

**Normative product behavior**

Customer Credit is distinct from Security Deposit and Pet Deposit. It must not be
represented as, pooled with, or converted silently into either Deposit type.

### PR-CREDIT-005 — Future Valid Invoice Application

**Business-rule traceability:** `BR-CREDIT-005`

**Normative product behavior**

Authorized Customer Credit may be applied only to a valid issued Invoice. It
must not create or accelerate an Invoice solely to consume the Credit.

### PR-CREDIT-006 — Authorized Application

**Business-rule traceability:** `BR-CREDIT-006`

**Normative product behavior**

A Customer Credit application is a separate authorized financial event.
It identifies the Credit source, target Invoice, amount, actor, and time.

### PR-CREDIT-007 — Application Limits

**Business-rule traceability:** `BR-CREDIT-007`

**Normative product behavior**

A Credit application must be positive and cannot exceed either the available
Customer Credit balance or the target Invoice's outstanding balance. It must not
produce a negative balance.

### PR-CREDIT-008 — Same-Customer Scope

**Business-rule traceability:** `BR-CREDIT-008`

**Normative product behavior**

Customer Credit may be applied only to obligations belonging to that same
Customer, including valid Invoices across that Customer's applicable Lease
relationships. It cannot be transferred to another Customer.

### PR-CREDIT-009 — Application History and Reversal

**Business-rule traceability:** `BR-CREDIT-009`

**Normative product behavior**

The original Credit and every application remain permanent. A correction uses an
explicit linked reversal and recomputes affected balances and statuses.

### PR-CREDIT-010 — KHR-origin Source Preservation

**Business-rule traceability:** `BR-CREDIT-010`

**Normative product behavior**

When Credit originates from a KHR Payment, preserve the original KHR amount,
exact receipt exchange rate, USD accounting value, and source relationship. The
Credit balance itself remains USD.

### PR-CREDIT-011 — Later KHR Refund

**Business-rule traceability:** `BR-CREDIT-011`

**Normative product behavior**

If USD Customer Credit is later refunded in KHR, calculate the Refund using the
exchange rate applicable when that Refund is processed. Preserve the Credit's USD
value, Refund KHR value, Refund exchange rate, and source linkage.

### PR-CREDIT-012 — Permanent Credit History

**Business-rule traceability:** `BR-CREDIT-012`

**Normative product behavior**

Creation, application, reversal, Refund, remaining balance, and source values of
Customer Credit must remain permanently reconstructable and auditable.

## 8.15 Refund Requirements

### PR-REFUND-001 — Refund Is a Separate Event

**Business-rule traceability:** `BR-REFUND-001`

**Normative product behavior**

A Refund is an explicit outbound financial event. It does not rewrite, delete,
or replace the Payment, Customer Credit, or Deposit from which it originates.

### PR-REFUND-002 — Required Financial Source

**Business-rule traceability:** `BR-REFUND-002`

**Normative product behavior**

Every Refund must identify one valid source and the amount available from that
source. The source may be unallocated Payment excess, Customer Credit, or a
refundable Deposit balance under an approved rule.

### PR-REFUND-003 — Refund Amount Limit

**Business-rule traceability:** `BR-REFUND-003`

**Normative product behavior**

A Refund amount must be positive and must not exceed the refundable amount
remaining at its identified source.

### PR-REFUND-004 — Property-caused Reservation Refund

**Business-rule traceability:** `BR-REFUND-004`

**Normative product behavior**

When a Reservation is cancelled because the Property cannot provide the Unit as
agreed and the Customer rejects the coordinated delay or alternative, all
Security Deposit received for that Reservation must be refunded in full through
an explicit Refund.

### PR-REFUND-005 — Original KHR Excess Refund

**Business-rule traceability:** `BR-REFUND-005`

**Normative product behavior**

If unallocated excess from a KHR Payment is refunded before becoming Customer
Credit, refund the corresponding original KHR excess. Preserve its original USD
accounting value and receipt exchange rate.

### PR-REFUND-006 — USD Credit Refunded in KHR

**Business-rule traceability:** `BR-REFUND-006`

**Normative product behavior**

If USD Customer Credit is refunded in KHR, use the System Exchange Rate applicable
to the Refund and the approved upward KHR amount rounding. Preserve both currency
values and that Refund rate.

### PR-REFUND-007 — Final Settlement Deposit Refund

**Business-rule traceability:** `BR-REFUND-007`

**Normative product behavior**

Remaining refundable Security Deposit and Pet Deposit balances after Final
Settlement are refunded through separate explicit Refund events so each Deposit
type remains traceable.

### PR-REFUND-008 — Currency and Value Preservation

**Business-rule traceability:** `BR-REFUND-008`

**Normative product behavior**

Every KHR Refund preserves the USD accounting value, KHR amount, applicable
exchange rate, rate date and time, calculation, and original source relationship.

### PR-REFUND-009 — Authorization and Reason

**Business-rule traceability:** `BR-REFUND-009`

**Normative product behavior**

Every Refund requires appropriate authorization and a recorded reason, actor,
date and time, recipient, and source.

### PR-REFUND-010 — No Original-record Rewrite

**Business-rule traceability:** `BR-REFUND-010`

**Normative product behavior**

A later Refund must never reduce the recorded original Payment amount, original
Customer Credit creation amount, or original Deposit receipt.

### PR-REFUND-011 — Refund History

**Business-rule traceability:** `BR-REFUND-011`

**Normative product behavior**

Every Refund and any authorized linked correction must preserve complete history.
A Refund must never be physically deleted or rewritten. This rule does not create
additional Refund statuses or a new Refund right.

### PR-REFUND-012 — Reconstructable Source Chain

**Business-rule traceability:** `BR-REFUND-012`

**Normative product behavior**

The full chain from original receipt through Allocation, Credit recognition,
Deposit disposition or application, and Refund must be reconstructable without
relying on rewritten historical values.

## 8.16 Move-out Requirements

### PR-MOVEOUT-001 — Actual Move-out Date

**Business-rule traceability:** `BR-MOVEOUT-001`

**Normative product behavior**

Move-out records the actual date physical occupancy ends. It must not be inferred
solely from the contractual Lease End Date or a Notice date.

### PR-MOVEOUT-002 — Lease Coordination

**Business-rule traceability:** `BR-MOVEOUT-002`

**Normative product behavior**

Move-out must be coordinated with the applicable authorized Lease termination.
The Lease termination date and actual Move-out Date must represent the approved
business event accurately.

### PR-MOVEOUT-003 — Occupancy Closure

**Business-rule traceability:** `BR-MOVEOUT-003`

**Normative product behavior**

Every open Occupancy that physically ends must receive its actual Move-out Date.
Occupancy history remains permanent.

### PR-MOVEOUT-004 — Unit Operational Transition

**Business-rule traceability:** `BR-MOVEOUT-004`

**Normative product behavior**

After physical move-out, the Unit leaves OCCUPIED and enters the status matching
its actual condition, normally CLEANING. It must not become available merely
because the Lease was terminated.

### PR-MOVEOUT-005 — Final Utility Handling

**Business-rule traceability:** `BR-MOVEOUT-005`

**Normative product behavior**

Final actual Utility Readings must be obtained and validated where possible. If
a Meter is confirmed broken, only the approved estimation process may be used.

An ordinary missing reading delays the charge. A fewer-than-three-history
broken-Meter estimate remains pending until the approved complete future-period
basis exists.

### PR-MOVEOUT-006 — Inspection and Final Charges

**Business-rule traceability:** `BR-MOVEOUT-006`

**Normative product behavior**

Authorized inspection results and all valid Rent, Utility, fixed Service, Damage,
Miscellaneous, and Adjustment obligations that properly belong in Final
Settlement must be finalized from their approved sources.

This rule does not create a new charge, fee, or damage policy.

### PR-MOVEOUT-007 — Normal Lease End

**Business-rule traceability:** `BR-MOVEOUT-007`

**Normative product behavior**

By the Lease End Date, an approved signed renewal should be in place or the
applicable termination and move-out process should proceed. The system must not
assume either outcome without the corresponding authorized records.

### PR-MOVEOUT-008 — Continued Occupancy After End Date

**Business-rule traceability:** `BR-MOVEOUT-008`

**Normative product behavior**

If physical occupancy continues, the Move-out Date remains empty and the Lease
must not be automatically marked TERMINATED. Property Management action under
the signed Lease is required.

### PR-MOVEOUT-009 — No Invented Holdover Terms

**Business-rule traceability:** `BR-MOVEOUT-009`

**Normative product behavior**

Continued occupancy after the End Date must not automatically create
month-to-month tenancy, holdover Rent, penalties, fees, or a new tenancy.

### PR-MOVEOUT-010 — Voluntary Early Move-out

**Business-rule traceability:** `BR-MOVEOUT-010`

**Normative product behavior**

Voluntary early move-out follows BR-LEASE-021, including the full final calendar
month of Rent, applicable final obligations, Security Deposit disposition, and no
future Rent after the processed termination.

### PR-MOVEOUT-011 — Move-out History

**Business-rule traceability:** `BR-MOVEOUT-011`

**Normative product behavior**

The Lease, Occupancy, Unit status, readings, inspection, notices, authorization,
actual dates, and corrections associated with move-out must remain permanently
auditable.

### PR-MOVEOUT-012 — Final Settlement Sequence

**Business-rule traceability:** `BR-MOVEOUT-012`

**Normative product behavior**

Move-out and Lease termination provide inputs to Final Settlement. Final
Settlement must not close until all required valid charges are final, including
any approved pending broken-Meter estimate.

## 8.17 Final Settlement Requirements

### PR-SETTLE-001 — One Settlement per Terminated Lease

**Business-rule traceability:** `BR-SETTLE-001`

**Normative product behavior**

Every TERMINATED Lease must complete exactly one Final Settlement. The Settlement
belongs to exactly one TERMINATED Lease and may remain pending until all
finalization prerequisites are satisfied.

### PR-SETTLE-002 — Settlement Inputs

**Business-rule traceability:** `BR-SETTLE-002`

**Normative product behavior**

Final Settlement must identify the Lease, responsible Customers, actual
termination and Move-out dates, outstanding Invoices, Customer Credit, Security
Deposit, Pet Deposit, final Utility handling, Adjustments, and other valid linked
financial events applicable to that Lease.

### PR-SETTLE-003 — Finalize Valid Outstanding Charges

**Business-rule traceability:** `BR-SETTLE-003`

**Normative product behavior**

Before applying Credit or Deposits, finalize every valid outstanding obligation
that properly belongs in the Settlement from its approved source. No new fee,
penalty, category, or obligation may be invented for Settlement.

### PR-SETTLE-004 — Apply Authorized Customer Credit First

**Business-rule traceability:** `BR-SETTLE-004`

**Normative product behavior**

After valid charges are finalized, apply authorized Customer Credit to applicable
Settlement obligations through separate auditable Credit-application events.

### PR-SETTLE-005 — Pet Deposit Application

**Business-rule traceability:** `BR-SETTLE-005`

**Normative product behavior**

Pet Deposit may be applied only to authorized pet-related damage. It must not be
applied to ordinary Rent, Utility, fixed Service, Miscellaneous, unrelated damage,
or another general obligation.

### PR-SETTLE-006 — Security Deposit Application

**Business-rule traceability:** `BR-SETTLE-006`

**Normative product behavior**

After authorized Customer Credit and permitted Pet Deposit application, Security
Deposit may be applied to remaining authorized Final Settlement obligations using
oldest Due Date first where Due Dates apply. Deterministic Invoice tie ordering
follows BR-PAY-023.

### PR-SETTLE-007 — Remaining Customer Balance

**Business-rule traceability:** `BR-SETTLE-007`

**Normative product behavior**

After all authorized applications, any unpaid amount remains a Customer balance.
Settlement must record it without changing the original obligations.

### PR-SETTLE-008 — Refund Remaining Deposit Balances

**Business-rule traceability:** `BR-SETTLE-008`

**Normative product behavior**

Every remaining refundable Security Deposit and Pet Deposit balance must be
refunded explicitly and separately under the Refund rules.

### PR-SETTLE-009 — Separate Traceability

**Business-rule traceability:** `BR-SETTLE-009`

**Normative product behavior**

Every Customer Credit application, Pet Deposit application, Security Deposit
application, forfeiture/disposition, remaining balance, and Refund must remain a
separate linked financial event and be independently auditable.

### PR-SETTLE-010 — No Deposit Use Before Settlement

**Business-rule traceability:** `BR-SETTLE-010`

**Normative product behavior**

Security Deposit and Pet Deposit must not be used for ordinary unpaid Invoices
before Final Settlement. A Customer instruction cannot override this rule.

An approved non-refundable Deposit disposition remains separate from Invoice
application and does not create a new forfeiture circumstance.

### PR-SETTLE-011 — Finalization Prerequisites

**Business-rule traceability:** `BR-SETTLE-011`

**Normative product behavior**

Final Settlement begins as a pending process and must not close until the Lease is
TERMINATED and every required
valid final charge is determined. An ordinary missing Utility Reading or a
pending fewer-than-three-history broken-Meter estimate keeps the affected charge
and Settlement unfinalized as necessary.

### PR-SETTLE-012 — Permanent Closure

**Business-rule traceability:** `BR-SETTLE-012`

**Normative product behavior**

Final Settlement may close only once. Once closed, its identity, source balances,
application order, calculations, dispositions, Refunds, and resulting balance are
permanent. Source records must never be erased.

### PR-SETTLE-013 — Post-closure Correction

**Business-rule traceability:** `BR-SETTLE-013`

**Normative product behavior**

A legitimate correction after closure uses explicit linked Adjustment,
application reversal, disposition correction, or other applicable authorized
linked financial correction. The closed Settlement and original financial events
are not reopened or rewritten.

### PR-SETTLE-014 — Forfeiture Is Separate

**Business-rule traceability:** `BR-SETTLE-014`

**Normative product behavior**

A Deposit already resolved through an approved forfeiture/disposition event is
shown as such and is not fabricated as an ordinary Invoice Payment or pooled with
an available Deposit balance.

### PR-SETTLE-015 — Settlement Audit

**Business-rule traceability:** `BR-SETTLE-015`

**Normative product behavior**

Settlement must preserve every input, ordering decision, calculation, application,
disposition, Refund, authorization, actor, date and time, source link, and final
result necessary to reconstruct it.

## 8.18 Money, Currency, Dates, and Timezone Requirements

### PR-MONEY-001 — Base and Accounting Currency

**Business-rule traceability:** `BR-MONEY-001`

**Normative product behavior**

USD is the Property's base and accounting currency.

All Invoices and Customer Credit balances are denominated and displayed in USD.
Receiving a Payment in KHR must not turn an Invoice into a dual-currency Invoice.

### PR-MONEY-002 — Supported Payment Currencies

**Business-rule traceability:** `BR-MONEY-002`

**Normative product behavior**

Payments may be received in USD or KHR only.

When KHR is selected, the Payment interface may display the KHR equivalent of the
USD obligation using the applicable System Exchange Rate.

### PR-MONEY-003 — Safe Monetary Arithmetic

**Business-rule traceability:** `BR-MONEY-003`

**Normative product behavior**

Authoritative monetary calculation must use integer minor units or exact-decimal
arithmetic. Binary floating-point must not be used as the authoritative
representation of money.

### PR-MONEY-004 — Preferred Exchange-rate Source

**Business-rule traceability:** `BR-MONEY-004`

**Normative product behavior**

The preferred external reference for USD/KHR conversion is the ABA Bank USD/KHR
Sell rate. No different external exchange-rate provider is approved by this
document.

### PR-MONEY-005 — System Exchange Rate

**Business-rule traceability:** `BR-MONEY-005`

**Normative product behavior**

The System Exchange Rate is calculated as:

```text
ABA-equivalent USD/KHR Sell Reference Rate × 1.005
```

The 1.005 multiplier represents the approved 0.5% markup.

### PR-MONEY-006 — Exchange-rate Rounding

**Business-rule traceability:** `BR-MONEY-006`

**Normative product behavior**

If the marked-up KHR-per-USD System Exchange Rate has a fractional result, it is
rounded upward to the next whole KHR.

Example:

```text
4,062 × 1.005 = 4,082.31
System Exchange Rate = 4,083 KHR/USD
```

### PR-MONEY-007 — Rate Selection at Payment Confirmation

**Business-rule traceability:** `BR-MONEY-007`

**Normative product behavior**

The applicable System Exchange Rate is selected and preserved when receipt of the
Payment is actually confirmed. A later rate change must never recalculate that
historical Payment.

### PR-MONEY-008 — Manual Reference-rate Fallback

**Business-rule traceability:** `BR-MONEY-008`

**Normative product behavior**

If the automatic ABA reference cannot be obtained, an authorized user may enter
the ABA-equivalent reference Sell rate manually.

The system must then apply the same 0.5% markup and upward whole-KHR
exchange-rate rounding. Manual entry must not bypass the standard formula.

### PR-MONEY-009 — Final KHR Payable-amount Rounding

**Business-rule traceability:** `BR-MONEY-009`

**Normative product behavior**

The KHR equivalent is calculated using the rounded System Exchange Rate. If the
resulting payable KHR amount is fractional, the final payable amount is rounded
upward to the next whole KHR, not half-up.

### PR-MONEY-010 — Exchange-rate Audit History

**Business-rule traceability:** `BR-MONEY-010`

**Normative product behavior**

Every KHR Payment must preserve:

- reference rate;
- approved 0.5% markup;
- resulting System Exchange Rate;
- applicable date and time;
- automatic source or manual-entry information;
- USD accounting value; and
- KHR amount.

### PR-MONEY-011 — Authoritative Payment-channel Settlement

**Business-rule traceability:** `BR-MONEY-011`

**Normative product behavior**

When KHQR or another accepted bank Payment channel provides an authoritative
actual conversion, settlement amount, or settlement rate, the actual transaction
information must be preserved. It must not later be rewritten using a different
rate.

### PR-MONEY-012 — General Proration and Monetary Rounding

**Business-rule traceability:** `BR-MONEY-012`

**Normative product behavior**

Where proration is approved:

```text
Prorated Amount
=
Monthly Amount × Inclusive Billable Calendar Days
-------------------------------------------------
Actual Calendar Days in That Month
```

The intermediate daily result is not rounded. The final USD monetary result is
rounded to the nearest cent using half-up rounding unless a specific approved
rule requires different rounding.

### PR-MONEY-013 — Business Dates and Timezone

**Business-rule traceability:** `BR-MONEY-013`

**Normative product behavior**

Start and end dates are inclusive where the applicable rule defines an inclusive
date range. Scheduled business actions and end-of-date processing use the
Property's configured local timezone.

## 8.19 Audit and History Requirements

### PR-AUDIT-001 — Minimum Audit Content

**Business-rule traceability:** `BR-AUDIT-001`

**Normative product behavior**

Every auditable event must identify the actor, action, date and time, reason,
previous state or value, resulting state or value, and affected business record.

### PR-AUDIT-002 — Reservation Audit

**Business-rule traceability:** `BR-AUDIT-002`

**Normative product behavior**

Reservation activation, extension, expiration, cancellation classification,
Unit release, and move-in transition must preserve their source, authorization,
dates, reasons, and prior values.

### PR-AUDIT-003 — Lease and Occupancy Audit

**Business-rule traceability:** `BR-AUDIT-003`

**Normative product behavior**

Signing, renewal records, Notices, warning letters, termination, Move-in,
Move-out, Occupancy corrections, and Unit transitions must remain historically
traceable.

### PR-AUDIT-004 — Meter and Estimation Audit

**Business-rule traceability:** `BR-AUDIT-004`

**Normative product behavior**

Reading corrections, Meter failure and replacement, estimation authorization,
period boundaries, historical or future actual data used, calculations, and
resulting consumption must remain reconstructable.

### PR-AUDIT-005 — Rate Audit

**Business-rule traceability:** `BR-AUDIT-005`

**Normative product behavior**

Rent, Utility, Service, and exchange-rate history must preserve source, effective
date and time, selected historical value, calculation, and authorization where
applicable.

### PR-AUDIT-006 — Invoice and Adjustment Audit

**Business-rule traceability:** `BR-AUDIT-006`

**Normative product behavior**

Invoice creation, DRAFT correction, issuance, line sources, status changes,
Adjustments, Due Date source, and VOID events must preserve original and resulting
financial facts and all linkages.

### PR-AUDIT-007 — Payment and Allocation Audit

**Business-rule traceability:** `BR-AUDIT-007`

**Normative product behavior**

Payment confirmation, payer intent, currency conversion, Allocation proposal and
posting, Allocation Reversal, Payment Reversal, Customer Credit recognition and
application, and Refund must remain separately traceable.

### PR-AUDIT-008 — Deposit Audit

**Business-rule traceability:** `BR-AUDIT-008`

**Normative product behavior**

Every Deposit receipt, required amount, balance, application,
forfeiture/disposition, reason, governing event, and Refund must remain linked and
reconstructable by Deposit type.

### PR-AUDIT-009 — Final Settlement Audit

**Business-rule traceability:** `BR-AUDIT-009`

**Normative product behavior**

Final Settlement must preserve every input, ordering step, calculation,
application, disposition, Refund, remaining balance, authorization, and
post-closure correction.

### PR-AUDIT-010 — Permanent Audit History

**Business-rule traceability:** `BR-AUDIT-010`

**Normative product behavior**

Audit history is permanent. It must not be physically deleted, silently
rewritten, or replaced by only the latest value.

## 8.20 Authorization Requirements

### PR-AUTH-001 — Explicit Authorization

**Business-rule traceability:** `BR-AUTH-001`

**Normative product behavior**

Every action described as authorized in this document requires an authenticated
user with permission for that action. The complete role and permission matrix is
defined in the later Security Model and must not weaken these requirements.

### PR-AUTH-002 — Reservation Authorization

**Business-rule traceability:** `BR-AUTH-002`

**Normative product behavior**

Reservation extension, exceptional cancellation classification, and correction
of Reservation dates or reasons require authorization and audit.

### PR-AUTH-003 — Exchange-rate Authorization

**Business-rule traceability:** `BR-AUTH-003`

**Normative product behavior**

Manual entry of the ABA-equivalent reference Sell rate is permitted only when the
automatic source cannot be obtained and requires authorization and audit.

### PR-AUTH-004 — Utility Estimate Authorization

**Business-rule traceability:** `BR-AUTH-004`

**Normative product behavior**

Confirmed broken-Meter estimation, its inputs, and any correction require
authorization. Ordinary missing readings cannot be authorized into estimates.

### PR-AUTH-005 — Lease and Move-out Authorization

**Business-rule traceability:** `BR-AUTH-005`

**Normative product behavior**

Lease signing, renewal records, Termination Notices, violation warning letters,
termination, and correction of actual Move-in or Move-out facts require their
applicable authorization.

### PR-AUTH-006 — Invoice Authorization

**Business-rule traceability:** `BR-AUTH-006`

**Normative product behavior**

Manual or exceptional Invoice issuance, issued-Invoice Adjustment, Due Date
recording for a non-recurring obligation, dependency correction, and VOID require
authorization and reason as applicable.

### PR-AUTH-007 — Payment and Allocation Authorization

**Business-rule traceability:** `BR-AUTH-007`

**Normative product behavior**

Payment confirmation or correction, manual Allocation posting, Allocation
Reversal, and Payment Reversal require authorization and audit. A deterministic
proposal is not authorization to post.

### PR-AUTH-008 — Credit, Refund, and Deposit Authorization

**Business-rule traceability:** `BR-AUTH-008`

**Normative product behavior**

Customer Credit recognition and application, Refund, and Deposit
forfeiture/disposition require authorization, source linkage, reason, and audit.
Customer authorization required by the Credit-versus-Refund decision must also be
preserved.

### PR-AUTH-009 — Final Settlement Authorization

**Business-rule traceability:** `BR-AUTH-009`

**Normative product behavior**

Final Settlement application, finalization, closure, and post-closure correction
require authorization and complete audit history.

# 9. Traceability and Acceptance Coverage

Every Section 8 `PR-*` maps to exactly one same-suffix `BR-*`; capability, workflow, and quality mappings are supplemental. Acceptance evidence shall cite both identifiers. No source `BR-*` may be omitted, duplicated under another detailed requirement, or reinterpreted. Later numbered specifications shall cite implemented or verified `PR-*` identifiers.

End-to-end acceptance shall cover: Unit availability and Reservation; extension and expiration boundaries; customer- and Property-caused cancellation; Deposit continuity; Lease signing and move-in; active Occupancy and all recurring billing; Payment, allocation, partial Payment, overpayment/Advance Payment, Credit, Refund, and Reversal; meter replacement and approved broken-meter estimation; normal end, continued Occupancy, violation process, and processed voluntary early termination only as authorized; move-out, final Utilities, charges, Deposit disposition, and Settlement; historical correction and reconstruction; and rejection of conflicts, invalid transitions, duplicate billing, unauthorized actions, and policy assumptions.

# 10. Open Owner Decisions

## OOD-PR-001 — First Partial-month Rent Due Date

`OOD-BR-001` remains open: the Due Date for a first partial-month Rent Invoice
issued after the billed month's 5th has not been approved. The product must preserve
an explicit Due Date and its governing source, must not invent a retroactive,
immediate, or next-month policy, and must keep this case configurable pending Owner
decision. Affected requirements include `PR-RENT-005`, `PR-RENT-009`, and
`PR-INV-018`.

# 11. Completion Criteria

This specification is ready for Owner review when status remains Owner Review; every `BR-*` has exactly one matching, unique, stable detailed `PR-*`; capabilities and lifecycle workflows trace upstream; acceptance covers applicable valid, invalid, boundary, calculation, authorization, and history behavior; terminology and policy match upstream; no placeholder influenced the result; and no feature, policy, status, fee, penalty, right, role, permission, or exception was invented.

# 12. Summary

The product shall provide a complete, auditable, single-Property residential tenancy workflow from Unit readiness and Reservation through Lease, Occupancy, billing, Payment, move-out, and Final Settlement. Every significant event shall remain historically accurate and reconstructable, and every action, calculation, transition, rejection, and correction shall conform to its stable product requirement and traced business rule.
