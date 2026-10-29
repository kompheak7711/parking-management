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

The product shall support one Property's complete residential tenancy lifecycle:
Property and Unit management; canonical Customers; Reservations; Security and
conditional Pet Deposits; Leases, Occupancy, move-in, termination, and move-out;
Utility Meters and Readings; Rent, Utility, configured recurring-Service, damage, and
miscellaneous Invoices; Late-payment Charge decisions and obligations; Payments;
Receipts; authorized Payment Allocations and Customer Credit applications; Customer
Credit, Reversals, and Refunds; one unified Customer Account Ledger view per Customer;
Final Settlement; and permanent operational, financial, and audit history.

The product may calculate deterministic Payment Allocation proposals. Posting remains
manual and requires authorized staff confirmation; no proposal may be silently posted.

## 3.2 Out of Scope

The product shall not provide multi-property portfolio management, commercial leasing,
a General Ledger, Chart of Accounts, full accounting, general supplier or vendor
Accounts Payable, Owner accounting, government tax reporting, payroll, Human Resources,
construction management, maintenance work-order management, procurement, inventory,
automatic posting of Payment Allocation proposals, or smart-meter integration.

The operational preservation of approved Payment-channel transaction and conversion
facts does not create a broader banking, bank-reconciliation, or accounting system.

Amended by DL-115 (owner, 2026-10-29): V1.1 brings into scope new-customer requests (from the Telegram bot, the website form through Telegram, or typed by staff), Repair Requests with Repair Checks and Repair Quotations, the move-in Joint Inspection and the Unit Check, staff reports from Telegram, photos, Customer birthdays, the Unit care history, "Paid on time", Unit features and the Services Invoice kind. "Maintenance work-order management" above still excludes planned maintenance, supplier lists and repair-cost records; "inventory" means stock and procurement, not the Unit inventory. Not in V1.1: a CRM for current tenants, the General Ledger, an automatic birthday message, online hosting.

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
The product shall support Reservation activation using the explicitly accepted partial
Security Deposit amount, Unit holding, one authorized extension, end-of-date expiration,
cancellation and responsibility classification, Deposit receipt and disposition, and
coordinated completion when the resulting Lease is signed (BR-RES-013, DL-064).
**Traceability:** `BR-RES-001`–`BR-RES-022`; `BR-DEP-001`–`BR-DEP-025`.

## PR-CAP-003 — Lease, Occupancy, Termination, and Move-out
The product shall support Lease drafting and signing, Primary Tenant and signer
relationships, actual Occupancy, coordinated move-in, Rent-specific nonpayment warning
and default history, separately authorized termination, actual move-out, and operational
Unit transition without fabricating tenancy terms.
**Traceability:** `BR-LEASE-001`–`BR-LEASE-030`; `BR-OCC-001`–`BR-OCC-009`;
`BR-MOVEOUT-001`–`BR-MOVEOUT-012`.

## PR-CAP-004 — Billing and Invoices
The product shall generate deterministic Rent, configured recurring-Service, Utility,
damage, and miscellaneous charges; manage the complete Invoice lifecycle; and support
one final late-payment decision and any resulting separate Late-payment Charge using
only approved sources, categories, dates, rates, calculations, statuses, and correction
events.
**Traceability:** `BR-RENT-001`–`BR-RENT-029`; `BR-UTIL-001`–`BR-UTIL-032`;
`BR-SVC-001`–`BR-SVC-015`; `BR-INV-001`–`BR-INV-055`;
`BR-LATE-001`–`BR-LATE-006`.

## PR-CAP-005 — Payments, Receipts, Allocation, Credit, and Refunds
The product shall record Payments as money-received facts; issue and reprint distinct
Receipts; preserve currency and exchange facts; support authorized detailed Payment
Allocation; derive allocation condition; and process approved Credit, Refund, and
Reversal events without rewriting sources.
**Traceability:** `BR-PAY-001`–`BR-PAY-040`; `BR-RECEIPT-001`–`BR-RECEIPT-006`;
`BR-CREDIT-001`–`BR-CREDIT-013`; `BR-REFUND-001`–`BR-REFUND-013`;
`BR-MONEY-001`–`BR-MONEY-013`.

## PR-CAP-006 — Final Settlement
The product shall coordinate final charges, Credit and Deposit application, Refund or balance due, permanent closure, and auditable correction for exactly one Settlement per terminated Lease.
**Traceability:** `BR-SETTLE-001`–`BR-SETTLE-015`.

## PR-CAP-007 — Authorization, Audit, and History
The product shall require explicit authorization for controlled actions and preserve permanent, reconstructable audit history.
**Traceability:** `BR-AUTH-001`–`BR-AUTH-009`; `BR-AUDIT-001`–`BR-AUDIT-011`;
`BR-PROP-002`.

## PR-CAP-008 — Customer Account Ledger
The product shall provide one chronological, reconstructable Customer Account Ledger
view per Customer showing complete financial history, obligation composition, current
amount owed, separately identifiable Deposit liabilities, and available Customer
Credit without replacing the authoritative underlying records or becoming a General
Ledger.
**Traceability:** `BR-LEDGER-001`–`BR-LEDGER-007`.

## Production Authentication and Account Recovery (`PR-CAP-009`)

The product shall authenticate human users through unique local usernames and passwords
without depending on an external identity provider for normal operation. Owner and
Manager accounts require standards-based MFA before normal privileged use; MFA is
optional for Staff. Browser sessions expire after 30 minutes of inactivity and after an
absolute 24 hours regardless of activity. Recovery uses single-use recovery codes or a
controlled, auditable server-side procedure: Owner may recover Manager and Staff
accounts, while Staff cannot recover Owner or Manager accounts and Manager recovery of
Staff is not granted by this requirement. The first Owner is created only through a
protected one-time command-line bootstrap that does not expose secrets in arguments,
logs, source control, or an unauthenticated web workflow.

This authentication policy does not replace capability-based, deny-by-default,
server-side authorization or any business/financial approval boundary.
**Traceability:** `SEC-009`–`SEC-018`, `SEC-071`–`SEC-075`; `DL-055`–`DL-059`.

# 6. End-to-End User Workflows

## PR-WF-001 — Prepare and Reserve a Unit
An authorized user shall be able to identify a legally available Unit from authoritative
facts, reuse or record one Customer, review the normal 20% suggested Reservation
Security Deposit, explicitly accept an authorized partial amount below, at, or above
that suggestion, receive that accepted amount, and activate one Reservation. Conflicting
availability or unmet activation conditions shall be rejected. The suggestion, accepted
amount, override actor, timestamp, and reason shall remain auditable.
**Traceability:** `BR-UNIT-001`–`BR-UNIT-013`; `BR-CUST-001`–`BR-CUST-003`; `BR-RES-001`–`BR-RES-006`; `BR-DEP-001`–`BR-DEP-005`.

## PR-WF-002 — Extend, Cancel, or Expire a Reservation
The product shall grant only the eligible single extension with Notice history; cancel expiration at the local end-of-date boundary; classify the actual cause; preserve history; release the Unit; and perform only the required Deposit disposition or Refund.
**Traceability:** `BR-RES-007`–`BR-RES-012`; `BR-RES-015`–`BR-RES-022`; `BR-UNIT-010`; `BR-DEP-015`–`BR-DEP-019`; `BR-REFUND-004`.

## PR-WF-003 — Draft, Sign, and Move In
An authorized user shall be able to create the zero-or-one resulting DRAFTED Lease,
identify the Primary Tenant and signers, record contractual terms, sign only when valid,
and complete move-in only after the Reservation, Unit, Lease, date, and Deposit
conditions are met. Completion shall coordinate terminal Reservation COMPLETED with
exactly one resulting Lease, Unit OCCUPIED, opened Occupancy, and continuation of the
same Security Deposit. A CANCELLED Reservation shall have no resulting Lease.
**Traceability:** `BR-RES-013`, `BR-RES-014`; `BR-LEASE-001`–`BR-LEASE-016`; `BR-OCC-001`–`BR-OCC-004`; `BR-DEP-005`–`BR-DEP-010`; `BR-UNIT-005`, `BR-UNIT-007`.

## PR-WF-004 — Operate and Bill an Active Tenancy
Authorized users shall be able to maintain actual Occupancy, approved pets and separate
Deposits; refund a remaining Pet Deposit through the approved active-Lease pet-departure
exception; generate Initial and recurring Rent and configured recurring-Service billing
without overlap; maintain Utility meters, audited Reading corrections, rates, and
approved estimates; issue Invoices; record Payments; provide Receipts; confirm detailed
Allocations; apply Customer Credit; make authorized late-payment decisions; and review
the Customer Account Ledger with full source and audit history.
**Traceability:** detailed `BR-OCC-*`, `BR-DEP-*`, `BR-RENT-*`, `BR-SVC-*`,
`BR-UTIL-*`, `BR-INV-*`, `BR-LATE-*`, `BR-PAY-*`, `BR-RECEIPT-*`,
`BR-CREDIT-*`, `BR-LEDGER-*`, and `BR-REFUND-*` requirements in Section 8.

## PR-WF-005 — Terminate and Move Out
An authorized user shall be able to act under the signed Lease, separately review
historical 20-day Rent Nonpayment Warning Notices and 30-day Serious Nonpayment Default
conditions, authorize any actual termination process, record actual termination and
Move-out Dates, close Occupancy only after departure, set the Unit to its actual
condition, capture final Utility handling and valid charges, and initiate Settlement.
Lease End Date, a Rent warning/default milestone, or elapsed time alone shall not
fabricate termination, move-out, renewal, holdover terms, Rent, fees, or penalties.
**Traceability:** `BR-LEASE-017`–`BR-LEASE-030`; `BR-MOVEOUT-001`–`BR-MOVEOUT-012`;
`BR-OCC-005`, `BR-OCC-007`–`BR-OCC-009`; `BR-UNIT-008`, `BR-UNIT-011`.

## PR-WF-006 — Finalize Settlement
An authorized user shall be able to create the one required Settlement, finalize valid
Invoice and applicable Late-payment Charge obligations, apply Credit and Deposits under
their approved rules, record each application separately, produce a balance or
authorized Refund, reflect the effects in the Customer Account Ledger, and permanently
close only after all prerequisites.
**Traceability:** `BR-SETTLE-001`–`BR-SETTLE-015`; `BR-DEP-014`,
`BR-DEP-023`–`BR-DEP-025`; `BR-REFUND-007`; applicable `BR-LATE-*` and
`BR-LEDGER-*` requirements in Section 8.

## PR-WF-007 — Correct Without Rewriting History
Corrections shall use only the explicit modification, Adjustment, Reversal, Refund,
replacement, disposition, or post-closure mechanism allowed by the governing rule and
shall preserve the original fact and source chain. A Utility Reading correction before
Invoice issuance changes the billing input; after issuance, any financial difference
uses a linked Invoice Adjustment without silently rewriting the original Invoice,
regardless of Invoice payment status.
**Traceability:** `BR-PROP-002`, `BR-PROP-003`; applicable `BR-UTIL-*`, `BR-INV-*`, `BR-PAY-*`, `BR-CREDIT-*`, `BR-REFUND-*`, `BR-SETTLE-013`, and `BR-AUDIT-*` detailed requirements.

## PR-WF-008 — Receive, Acknowledge, and Apply Money
An authorized user shall be able to confirm one Payment, issue its numbered Receipt,
record a valid Customer designation, review the deterministic between-Invoice FIFO and
within-mixed-Invoice Rent-first proposal where applicable, confirm sufficient
line/obligation allocation detail, and reprint the same Receipt without creating
another Payment. The resulting Invoice, Late-payment Charge, Customer Credit, and
Customer Account Ledger balances shall remain reconstructable.
**Traceability:** `BR-PAY-001`–`BR-PAY-040`; `BR-RECEIPT-001`–`BR-RECEIPT-006`;
`BR-CREDIT-001`–`BR-CREDIT-013`; `BR-LEDGER-001`–`BR-LEDGER-007`.

## PR-WF-009 — Review Late Payment and Rent Nonpayment
Authorized management shall be able to review one applicable overdue source Invoice,
confirm, reduce, or waive its single final late-payment decision, and create a separate
immediately payable Late-payment Charge only for a positive amount. The product shall
evaluate 20-day and 30-day Rent-specific milestones from remaining Rent after confirmed
applications, preserve cure history, and require a separate authorized termination
process.
**Traceability:** `BR-INV-051`–`BR-INV-055`; `BR-LATE-001`–`BR-LATE-006`;
`BR-LEASE-026`–`BR-LEASE-030`; `BR-PAY-036`–`BR-PAY-040`.

# 7. Product-Wide Quality Requirements

## PR-QUAL-001 — Consistent Enforcement
The product shall enforce the same rules for UI, API, scheduled process, administrative workflow, and automated billing origins.
**Traceability:** all `BR-*`.

## PR-QUAL-002 — Deterministic Rejection
A violating action shall be rejected without silent input mutation.
**Traceability:** all `BR-*`; `002_BUSINESS_RULES.md` Section 14.

## PR-QUAL-003 — Financial Reconstructability
Every Invoice line, Invoice, Late-payment Charge, Payment allocation condition, Customer
Credit, Deposit, Customer outstanding position, and Settlement result shall be
reproducible from permanent source records, rates, Allocations, applications,
Adjustments, Reversals, Credits, Refunds, dispositions, and Settlement events. A
Customer Account Ledger projection shall reconcile to those authoritative records and
shall never become a second source of truth.
**Traceability:** `BR-PROP-002`; all financial and audit rules in Section 8.

## PR-QUAL-004 — Historical Availability
Required operational, financial, rate, Receipt issuance/reprint, warning/default,
correction, Ledger reconstruction, and audit histories shall remain retrievable for
reporting and audit.
**Traceability:** `BR-PROP-002`; `BR-CUST-003`; applicable history requirements in Section 8; all `BR-AUDIT-*`.

## PR-QUAL-005 — Authoritative Facts
Availability, occupancy, consumption, line and obligation balances, Invoice status,
allocation condition, Customer Account Ledger, and calculated summaries shall derive
from authoritative records; a summary or projection shall not authorize a conflicting
action.
**Traceability:** `BR-UNIT-013`; `BR-UTIL-003`, `BR-UTIL-012`; `BR-INV-017`;
`BR-PAY-008`–`BR-PAY-014`; `BR-LEDGER-001`–`BR-LEDGER-007`;
`BR-SETTLE-002`–`BR-SETTLE-009`.

## PR-QUAL-006 — Date, Time, and Monetary Exactness
The product shall use actual business dates, configured local timezone boundaries, safe monetary arithmetic, and the exact specified precision, rounding stage, currency, exchange rate, proration, and payment-channel settlement rules.
**Traceability:** `BR-PROP-003`; `BR-MONEY-001`–`BR-MONEY-013`; every referenced calculation rule.

## PR-QUAL-007 — Coordinated Transitions
Move-in, Reservation completion, automatic expiration cancellation, Allocation and
Payment Reversal effects, Receipt history, move-out, and Settlement finalization shall
not leave authoritative records in a partially contradictory state.
**Traceability:** `BR-RES-016`; `BR-LEASE-016`; `BR-PAY-012`, `BR-PAY-014`, `BR-PAY-029`; `BR-OCC-009`; `BR-MOVEOUT-002`–`BR-MOVEOUT-012`; `BR-SETTLE-011`, `BR-SETTLE-012`.

## PR-QUAL-008 — Business-facing Financial View
The Customer Account Ledger and related staff/Customer presentation shall use
business-facing terms such as Amount charged, Payment received, Credit, Refund,
Outstanding balance, and Customer Credit. The product shall not require formal
debit/credit bookkeeping terminology or introduce General Ledger or vendor Accounts
Payable behavior.
**Traceability:** `BR-LEDGER-001`–`BR-LEDGER-007`; `BR-CREDIT-013`.

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

The Property's authoritative business timezone is `Asia/Phnom_Penh`. Scheduled
business actions and end-of-date processing must use that timezone. A business date
remains in effect through the end of that local calendar date unless a rule explicitly
states otherwise.

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

Amended by DL-075 (owner, 2026-10-20): as BR-UNIT-001: Unit Types are a Settings list (the Owner or a user with Settings access, DL-074), no longer the four fixed types above, which are today's values. A Unit Type used by a Unit cannot be removed. Commercial Unit stays unsupported (DL-001).

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

Amended by DL-078 (owner, 2026-10-20): as BR-UNIT-003: the Unit number cannot change after the Unit is created.

### PR-UNIT-004 — Reservation Availability

**Business-rule traceability:** `BR-UNIT-004`

**Normative product behavior**

A new Reservation may be created only when the Unit is legally available to be reserved.

A Unit must not receive a second active Reservation while another Reservation is ACTIVE.

An ACTIVE Reservation always holds its Unit. A Reservation releases its Unit only
when it becomes CANCELLED or COMPLETED through an approved business transition.

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


When the Lease becomes SIGNED, the Unit status becomes:

```text
OCCUPIED
```

The Unit is OCCUPIED from signing, even before physical move-in.

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

When a Lease is terminated before any move-in under BR-LEASE-005, the Unit is released
without an Occupancy or physical move-out. It returns to VACANT, or to CLEANING when a
user holding the Unit management capability records a reason.

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

Amended by DL-071 (owner, 2026-10-20; answer 11): a Customer has an "ID number / Passport number" field. A Customer with the same ID number as another Customer is refused; staff must use the existing Customer. The same phone number or the same email address as another Customer shows a warning, and staff may still save. The ID number is required for every Customer, and two ID numbers are the same when they match after removing spaces and dashes and ignoring capital letters (owner, 2026-10-21). Not built yet.

### PR-CUST-003 — Customer History

**Business-rule traceability:** `BR-CUST-003`

**Normative product behavior**

Changing current Customer contact information must not alter the historical meaning of previous:

- Reservations
- Leases
- Payments
- Occupancies
- financial records

Amended by DL-078 (owner, 2026-10-20): as BR-CUST-003: Customer details are legal name (required), date of birth, gender (Female or Male), nationality, ID number / Passport number (required and unique, DL-071), phone, email, address and memo; changing them never changes past records.

## 8.5 Reservation Requirements

### PR-RES-001 — Reservation Is Mandatory

**Business-rule traceability:** `BR-RES-001`

**Normative product behavior**


A Customer may reserve a Unit before signing its Lease. A Lease may also be signed
without a Reservation for a walk-in Customer; then no Reservation is completed and the
Unit still becomes OCCUPIED at signing under BR-UNIT-007.

Replaced by DL-066 (noted 2026-10-21, docs-only rules update 2b, part 9): the title "Reservation Is Mandatory" is old; a Reservation is optional (BR-RES-001). The title is kept because the traceability audit maps this identifier by its heading.

A walk-in Lease is subject to the same Unit exclusivity as any other Lease under
BR-UNIT-005 and BR-UNIT-006.

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
COMPLETED
```

The system must not introduce an EXPIRED Reservation status.

ACTIVE means the Reservation currently holds the Unit. CANCELLED means it ended
without successfully proceeding to tenancy. COMPLETED means it successfully
proceeded to its resulting signed Lease; physical move-in may follow later. CANCELLED and
COMPLETED are terminal.

### PR-RES-004 — Initial Reservation Status

**Business-rule traceability:** `BR-RES-004`

**Normative product behavior**

A newly accepted Reservation begins in ACTIVE status only after all Reservation
activation conditions, including receipt of the explicitly accepted initial Security
Deposit amount, are met.

Amended by DL-077 (owner, 2026-10-20): as BR-RES-004: Make Reservation receives the accepted initial Security Deposit on a Receipt in the same save step, and the Reservation becomes active when that amount is received in full.

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

Amended by DL-075 (owner, 2026-10-20): as BR-RES-006: the 21 days are the Settings default for the longest first expiry. A new value applies only to new Reservations.

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

Amended by DL-075 (owner, 2026-10-20): as BR-RES-008: the 14 days are the Settings default for the one extension. A new value applies only to new Reservations. The extension window of BR-RES-007 stays fixed.

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
timezone, an ACTIVE Reservation that has not become COMPLETED and has no valid
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

A CANCELLED Reservation cannot later become ACTIVE or COMPLETED.

### PR-RES-013 — Reservation Completion at Lease Signing

**Business-rule traceability:** `BR-RES-013`

**Normative product behavior**


A Reservation becomes COMPLETED when its resulting Lease becomes SIGNED, in the same
coordinated transition. At that moment the Reservation must be ACTIVE and not expired.
A COMPLETED Reservation cannot expire.

The COMPLETED Reservation must reference exactly one resulting Lease. COMPLETED is
terminal. The holding deposit received during the Reservation continues as the Security
Deposit under BR-DEP-005. Physical move-in, when it occurs, is recorded separately under
BR-LEASE-016.

### PR-RES-014 — Reservation to Lease Relationship

**Business-rule traceability:** `BR-RES-014`

**Normative product behavior**

A Reservation may result in zero or one Lease.

The system must not create multiple resulting Leases from one Reservation.
A COMPLETED Reservation references exactly one resulting Lease. A CANCELLED
Reservation produces no resulting Lease.

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

A Reservation may become ACTIVE only after the explicitly accepted initial partial
Security Deposit amount has been received. Authorized management may accept an
amount below or above the normal 20% suggestion.

The business does not use a separate Reservation Deposit.

### PR-DEP-002 — Initial Security Deposit May Be Partial

**Business-rule traceability:** `BR-DEP-002`

**Normative product behavior**

The initial payment may be less than the total required Security Deposit, but it
must equal the initial amount explicitly accepted for that Reservation. The accepted
amount and authorization must be audited.

Every receipt remains part of the same Security Deposit obligation.

### PR-DEP-003 — Suggested Initial Security Deposit

**Business-rule traceability:** `BR-DEP-003`

**Normative product behavior**

The normal/default suggested amount when reserving a Unit is 20% of the agreed
monthly Rent. It is not a hard minimum.

```text
Suggested Initial Security Deposit
=
Agreed Monthly Rent × 20%
```

The final monetary result uses the approved monetary rounding rule.

Example:

```text
Agreed Monthly Rent:                  $500
Suggested Initial Security Deposit:   $100
```

Authorized management may accept another explicit amount, including an amount below
or above 20%, based on the actual Reservation arrangement. The system must preserve
the suggested amount, accepted required amount, override authorization, actor,
timestamp, and reason. It must not reject a Reservation merely because the collected
Security Deposit is below 20%. A lower accepted amount may legitimately hold the Unit
for a short Reservation period when authorized management accepts that arrangement.
This amount is Security Deposit, not a fee or separate Deposit type.

Amended by DL-075 (owner, 2026-10-20): as BR-DEP-003: the 20 percent is the Settings default for the suggested deposit. A new value applies only to new Reservations.

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

Any Security Deposit received during Reservation remains the same Security Deposit when the resulting Lease is signed.

Money received for a Deposit must be linked explicitly from the Payment to the
applicable Deposit liability and Deposit balance. This Payment-to-Deposit link is
not an Invoice Payment Allocation and does not require a Deposit Invoice.

The system must not:

- refund it and recollect it
- create a second deposit
- record a conversion transaction
- recognize it as rental income

### PR-DEP-006 — Remaining Deposit No Later Than Move-in Completion

**Business-rule traceability:** `BR-DEP-006`

**Normative product behavior**


The Security Deposit balance remaining after the holding deposit is due within five
calendar days after the Lease Start Date, together with the Initial Rent Invoice.

Move-in is always recorded when it happens and is never blocked by an unpaid Security
Deposit or Initial Rent. If the Security Deposit balance or the Initial Rent is unpaid
after that period, the owner may terminate under the standard Lease clause in
BR-LEASE-025.

Replaced by DL-066 (noted 2026-10-21, docs-only rules update 2b, part 9): the title "No Later Than Move-in Completion" is old; the remaining Security Deposit is due within five calendar days after the Lease Start Date and never blocks move-in (BR-DEP-006). The title is kept because the traceability audit maps this identifier by its heading.

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

Pet Deposit primarily secures demonstrable pet-caused property damage or
extraordinary/deep cleaning beyond normal turnover cleaning. It does not cap the
Customer's liability for the full valid repair or deep-cleaning cost.

Examples include pet damage to furniture, doors, walls, or flooring; cleaning beyond
normal turnover cleaning; and other demonstrable pet-caused property damage or
deep-cleaning cost.

```text
Pet Deposit:                    $200
Valid Pet-caused Cost:          $500
Remaining Customer Liability:  $300
```

If a valid pet-caused damage or deep-cleaning obligation becomes payable while the
Lease remains active, the Customer must pay that valid charge directly. The Pet
Deposit must not be consumed automatically and remains held unless BR-DEP-012 later
permits its Refund.

```text
Active-Lease Pet-caused Charge: $500
Customer Owes Directly:         $500
Pet Deposit Remains Held:       unchanged
```

### PR-DEP-010 — Pet Deposit Timing

**Business-rule traceability:** `BR-DEP-010`

**Normative product behavior**

When a Customer will keep an approved pet from the beginning of occupancy, the
Pet Deposit required by the applicable signed Lease terms is due within five calendar
days after the Lease Start Date. An unpaid Pet Deposit never blocks move-in.

When a Customer introduces or acquires a pet later, the Customer must notify
Property Management. If the pet is approved and the applicable signed Lease terms
require a Pet Deposit, that Deposit must be paid before or when the pet begins
staying in the Unit.

### PR-DEP-011 — Deposit Held During Active Lease

**Business-rule traceability:** `BR-DEP-011`

**Normative product behavior**

Security Deposit and Pet Deposit are held during the active Lease, except that the
remaining refundable Pet Deposit may be returned under BR-DEP-012 after the pet
permanently leaves and applicable pet-related obligations are resolved.

They remain distinct liabilities with separately traceable balances.

### PR-DEP-012 — No Normal Deposit Refund During Active Lease

**Business-rule traceability:** `BR-DEP-012`

**Normative product behavior**

Security Deposit must not be refunded while the Lease remains SIGNED.

Pet Deposit remains held while an approved pet is kept at the Unit. If the tenant
permanently stops keeping the pet during an active Lease, the system must record that
fact and determine any valid pet-caused property damage or extraordinary/deep-cleaning
obligation. The Customer remains responsible for the full valid cost. Once applicable
pet-related obligations are resolved, any remaining refundable Pet Deposit may be
returned through an explicit Refund event with complete history. Lease termination is
not required for this Refund.

This rule does not prevent an explicit disposition required by an approved
non-refundable policy or an explicit Property-caused Reservation Refund before a
Lease begins.

### PR-DEP-013 — Deposits Are Not Monthly Payment Funds

**Business-rule traceability:** `BR-DEP-013`

**Normative product behavior**

A Customer must not use Security Deposit or Pet Deposit to pay ordinary monthly:

- Rent
- Utilities
- recurring Service Charges
- other ordinary current Invoice obligations

while the Lease remains active.

The Customer cannot direct staff to treat a Deposit as an ordinary Payment, and
staff cannot allocate it to an ordinary Invoice before Final Settlement.

### PR-DEP-014 — Deposit Application During Final Settlement Only

**Business-rule traceability:** `BR-DEP-014`

**Normative product behavior**

Deposits may be applied to Invoice obligations and Late-payment Charges only as part
of the Final Settlement process after Lease termination. An active-Lease Pet Deposit Refund under BR-DEP-012
is a separate Refund process, not Deposit application to an Invoice.

An explicit forfeiture/disposition event under an approved non-refundable policy
is not an Invoice allocation and must remain separate from Final Settlement
application. This distinction does not create any new reason for forfeiture.

Amended by the owner answers to Q-2026-10-05-20 and Q-2026-10-05-21 (2026-10-05): a Deposit may pay a Late-payment Charge like any other debt; the first sentence now names Late-payment Charges.

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

Amended by DL-068 and DL-069 (2026-10-03): the whole Security Deposit is forfeited and never applied to what the Customer owes (BR-DEP-026).

Amended by the owner answer to Q-2026-10-05-24 (2026-10-05): when a confirmed forfeiture of the Security Deposit is reversed, the Deposit is held again; at Final Settlement it follows DL-032 (it pays open debt and the rest is refunded) unless a new forfeiture draft is confirmed (BR-DEP-026).

### PR-DEP-024 — Pet Deposit During Voluntary Early Termination

**Business-rule traceability:** `BR-DEP-024`

**Normative product behavior**

Voluntary early termination does not automatically make the Pet Deposit
non-refundable. It remains separately tracked through Final Settlement, may be
applied under BR-SETTLE-005 and BR-SETTLE-006, and is refundable to the extent not
validly applied or otherwise validly forfeited under an explicitly approved rule.

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

When a Lease is terminated because the Initial Rent Invoice is unpaid:

- If the tenant never moved in, any Security Deposit paid is forfeited. If nothing was
  paid on the Initial Rent Invoice, it is VOIDed with a mandatory reason under
  BR-INV-046. If it was partly paid, the Property keeps the paid amount without Refund
  and the unpaid remainder is removed by a linked credit Adjustment with a mandatory
  reason, so the Customer owes nothing more. No Utility charge applies to the Customer.
  The Unit returns to VACANT under BR-UNIT-010 without an Occupancy or physical
  move-out.
- If the tenant moved in, the Initial Rent Invoice is kept and is never VOIDed. Rent is
  owed only through the termination date; the remaining days are removed by a linked
  credit Adjustment calculated with BR-RENT-007 proration. Utility through the actual
  Move-out Date and any Damage charges are charged, and the move-out process applies.
  Final Settlement remains governed by its own rules.

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

Amended by DL-068 and DL-069 (2026-10-03): the End Date must also be the last day of a calendar month (BR-LEASE-031).

### PR-LEASE-014 — Non-overlapping Signed Lease Coverage

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

- Lease is SIGNED
- any Reservation for this Lease is COMPLETED with this Lease as its resulting Lease
- Unit is not UNDER_MAINTENANCE
- Unit is not OUT_OF_SERVICE
- move-in date is valid

An unpaid Security Deposit, Pet Deposit or Initial Rent never blocks move-in under
BR-DEP-006 and BR-DEP-010.

### PR-LEASE-016 — Move-in Completion

**Business-rule traceability:** `BR-LEASE-016`

**Normative product behavior**


When the Lease becomes SIGNED:

- any Reservation for this Lease becomes COMPLETED; a walk-in Lease has none
- Unit becomes OCCUPIED
- Security Deposit remains associated with the Lease

These actions represent one coordinated business transition.

When physical move-in is completed later, the Occupancy begins with the actual Move-in
Date under BR-OCC-004. Move-in does not change the Reservation or Unit status. The
move-in transition must not complete until all conditions in BR-LEASE-015 are true.

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

Amended by DL-068 and DL-069 (2026-10-03): the month is the month of the actual hand-back date; a hand-back before the 5th follows BR-RENT-030; Late-payment Charges and the Unit cleaning charge are owed; the whole Security Deposit is forfeited and never applied (BR-DEP-026).

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

### PR-LEASE-024 — General Violation Warning Minimum

**Business-rule traceability:** `BR-LEASE-024`

**Normative product behavior**

Property Management must issue at least three documented warning letters before
terminating a Lease for a Customer violation.

Each warning must identify the violation, date, Lease provision, communication,
and history. The undisclosed-pet process follows this rule if noncompliance
proceeds toward termination.

The specific 20-day Rent Nonpayment Warning Notice under BR-LEASE-027 does not
automatically replace or satisfy this broader three-warning-letter requirement.
Nothing in the 30-day Serious Nonpayment Default rule bypasses any warning requirement
that applies to the eventual termination process. Counting one record toward another
procedure requires an expressly approved basis rather than an implementation
assumption.

Amended by DL-070 (owner, 2026-10-15; the new standard Lease agreement): a serious breach by the Customer, meaning a crime or danger to people or the building, may end the Lease at once, without the three warning letters. The authority still comes from the signed Lease (BR-LEASE-025), and the termination is still an explicit action by an authorized user with its grounds recorded; nothing is automatic. Every other Customer violation still needs the three warning letters. Not built yet.

Amended by DL-073 (owner, 2026-10-20): for a Rent nonpayment termination the day-20 Nonpayment Warning Notice (BR-LEASE-027) is letter 1, the day-30 default notice (BR-LEASE-028) is letter 2 and the termination notice (BR-LEASE-022) is letter 3; such a termination needs no other warning letters (the owner's explicit approval under this rule). Not built yet.

### PR-LEASE-025 — Signed-Lease Termination Authority

**Business-rule traceability:** `BR-LEASE-025`

**Normative product behavior**

A violation and the authority to terminate for it must come from the signed
Lease. The system must not invent a violation, penalty, fee, forfeiture, or
termination right.

The standard Lease used for all Customers contains a clause giving a termination right
if either the Security Deposit or the Initial Rent Invoice is not fully paid within five
calendar days after the Lease Start Date. That clause is the governing signed-Lease ground for
termination. BR-LEASE-024's three warning letters do not apply to this ground. The
termination records the Lease clause reference.

Amended by DL-070 (owner, 2026-10-15; the new standard Lease agreement): this clause is Article 2.5 of the standard Lease agreement, and a termination on this ground records "Article 2.5" as its clause reference. Not built yet: staff still enter the clause reference as text.

### PR-LEASE-026 — Rent Nonpayment Day Count

**Business-rule traceability:** `BR-LEASE-026`

**Normative product behavior**

Rent nonpayment days are counted in `Asia/Phnom_Penh` calendar days from a fixed day
one, independent of the Invoice Due Date.

The Rent nonpayment process under BR-LEASE-026 through BR-LEASE-030 applies only to
recurring monthly Rent Invoices. Day one is the first calendar day of the billed month.
The Initial Rent Invoice never opens a Rent nonpayment case; BR-RENT-009 governs its
follow-up.

Day N is day one plus N − 1 calendar days. Day 20 is therefore the 20th and day 30 is
the 1st plus 29 days; in a normal-year February, day 30 is 2 March.

The Invoice Due Date under BR-RENT-009 and the overdue boundary under BR-INV-051
continue to govern the late-payment decision. They do not change the nonpayment day
count.

When one Invoice contains both Rent and recurring-Service lines, the nonpayment
process uses the remaining Rent line balance after valid confirmed Payment
Allocations, Customer Credit applications and Adjustments. The whole mixed-Invoice
balance is not a substitute for the remaining Rent balance.

A case recorded under an earlier count keeps its recorded values; the count applies to
cases opened after this rule took effect.

Example:

```text
Recurring Rent for August:                 day 1 = 1 August,   day 20 = 20 August,   day 30 = 30 August
Recurring Rent for February:               day 1 = 1 February, day 20 = 20 February, day 30 = 2 March (normal year)
```

### PR-LEASE-027 — Twenty-day Rent Nonpayment Warning Notice

**Business-rule traceability:** `BR-LEASE-027`

**Normative product behavior**

If a positive balance of the applicable Rent obligation remains unpaid on day 20 under
BR-LEASE-026, the system must alert authorized staff or management and
require or support issuance and recording of a formal Nonpayment Warning Notice to the
Customer. The Notice states that continued nonpayment through 30 days overdue may
result in authorized management initiating the approved Lease termination or
surrender process.

When a case is opened after day 20 has passed, the system alerts authorized staff at
once.

The Notice is a permanent auditable business record, not an ephemeral UI warning. It
preserves at minimum, where applicable:

- Customer;
- Lease;
- applicable overdue Rent Invoice or obligation;
- Due Date;
- remaining Rent amount at Notice time;
- Notice issue date/time;
- issuer;
- Notice type;
- delivery or communication information when recorded;
- document or reference to the actual Notice; and
- subsequent status and history.

### PR-LEASE-028 — Thirty-day Serious Nonpayment Default

**Business-rule traceability:** `BR-LEASE-028`

**Normative product behavior**

If a positive balance of the applicable Rent obligation remains unpaid on day 30 under
BR-LEASE-026, the system records a Serious Nonpayment Default condition.
Authorized management may then initiate the approved Lease termination or surrender
process. When a case is opened after day 30 has passed, the system alerts authorized
staff at once.

The condition must not automatically:

- change the Lease to TERMINATED;
- mark the Unit VACANT;
- end Occupancy;
- create Move-out;
- create Final Settlement;
- surrender the Unit; or
- delete or end the Customer's legal or operational tenancy record.

Actual Lease termination remains a separate explicit authorized business action under
BR-LEASE-005, BR-LEASE-023, BR-LEASE-024, and BR-LEASE-025. Until termination and
physical Move-out actually occur, the Lease remains in its appropriate existing
status, normally SIGNED, and the Unit remains OCCUPIED while the Customer still
physically occupies it.

A remaining recurring-Service balance alone does not satisfy the Rent-balance condition
for this rule.

Amended by DL-073 (owner, 2026-10-20): the day-30 default notice is a letter the system records, like the day-20 Notice of BR-LEASE-027, and it counts as letter 2 of a Rent nonpayment termination (BR-LEASE-024). The condition itself and its no-automatic-action list are unchanged. Not built yet.

### PR-LEASE-029 — Cure After Warning and Before Thirty Days

**Business-rule traceability:** `BR-LEASE-029`

**Normative product behavior**

If the Customer fully cures the applicable Rent nonpayment after its 20-day Warning
Notice but before day 30 under BR-LEASE-026, the current 30-day trigger for that cured
obligation stops. The system must not initiate termination at day 30 merely because
the obligation was previously late.

The Invoice's overdue history, Warning Notice, cure Payment and Allocation history,
and all related dates remain permanent and auditable.

### PR-LEASE-030 — Payment After Serious Nonpayment Default

**Business-rule traceability:** `BR-LEASE-030`

**Normative product behavior**

Payment after a Serious Nonpayment Default does not erase that historical condition,
its Warning Notice, or any already initiated authorized termination process.

The system must not automatically decide whether an initiated termination process
continues or stops solely because later Payment occurs. Authorized management retains
control under the existing approved termination rules, and the Payment, Allocations,
default history, management actions, and resulting outcome remain auditable.

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

### PR-RENT-005 — Initial Rent Invoice Period

**Business-rule traceability:** `BR-RENT-005`

**Normative product behavior**


The Initial Rent Invoice is calculated from the Lease Start Date in the signed Lease,
not the actual Move-in Date. For a Lease Start Date on day 1 through day 20 inclusive,
it covers the Lease Start Date through the last calendar day of that month. Only the
portion after a Lease Start Date later than day 1 is prorated. For a Lease Start Date on
day 21 or later, it combines the prorated remainder of the start month and the entire
following calendar month. BR-RENT-007 proration applies.

Examples: a 10 July Lease Start Date covers 10–31 July; a 27 July Lease Start Date
covers 27 July–31 August, and recurring billing resumes on 25 August for the 1–30
September period. A Lease Start Date of 20 September with a $300 monthly Rent is
charged from 20 September even if the tenant arrives on 25 September:
$300 × 11/30 = $110.00. The actual Move-in Date does not change Initial Rent coverage.
Initial and recurring Rent periods must not duplicate or overlap.

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
The recurring process must not generate a period that BR-RENT-005 reserves for the
Initial Rent Invoice, even if the Lease was signed before that 25th. Recurring billing
resumes with the first complete calendar month after the Initial Rent period.

Example:

| Generation Date | Rental Period |
| --------------- | ------------- |
| 25 July         | August        |
| 25 August       | September     |
| 25 September    | October       |

Amended by DL-075 (owner, 2026-10-20): as BR-RENT-008: the 25th is the Settings default issue day (day 1 to 28, after the reading day). A change starts with the next billing month.

### PR-RENT-009 — Rent Invoice Due Dates

**Business-rule traceability:** `BR-RENT-009`

**Normative product behavior**

Recurring Rent Invoices have a Due Date of the **5th day of the billed month**. This
Due Date is established by the application/business rule; the Lease Agreement does
not define an alternative recurring Invoice Due Date.

The system proposes an Initial Rent Invoice Due Date of the Lease Start Date plus five
calendar days, including when that date falls in the following month. An authorized user
may set a different Due Date before issuance with a mandatory reason; the actor and
timestamp are recorded. The Due Date is fixed once the Invoice is issued. The Initial
Rent Invoice references the signed Lease, not a recorded Occupancy, and may be issued
before the Lease Start Date.

Example:

| Rental Month | Invoice Generated | Due Date    |
| ------------ | ----------------- | ----------- |
| August       | 25 July           | 5 August    |
| September    | 25 August         | 5 September |

Examples: issued 1 July or 10 July for a 10 July Lease Start Date, proposed Due Date
15 July; a 27 July Lease Start Date, proposed Due Date 1 August.

The Initial Rent Invoice never opens a Rent nonpayment case and has no late-payment
charge. If it remains unpaid after its Due Date, the system alerts authorized management
on the following calendar day in `Asia/Phnom_Penh`. Any response, including termination
under BR-LEASE-005 and BR-LEASE-025, is a separate manual authorized action; nothing is
automatic. The actual Move-in Date is recorded when move-in occurs, whether or not the
Invoice is paid.

Amended by DL-075 (owner, 2026-10-20): as BR-RENT-009: the 5th is the Settings default Due Date day for recurring Rent and monthly Utility Invoices (day 1 to 28). A change starts with the next billing month; an issued Due Date never changes. The Initial Rent Due Date of the Lease Start Date plus five calendar days stays fixed.

### PR-RENT-010 — Invoice Generation Eligibility

**Business-rule traceability:** `BR-RENT-010`

**Normative product behavior**

Recurring Rent Invoices shall only be generated for Leases that are:

- Signed,
- contractually applicable to the billed rental period, and
- Not terminated before the beginning of that rental period.

The period must also fall wholly after the Initial Rent period defined by
BR-RENT-005. No recurring generation may duplicate or overlap Initial Rent coverage.

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

Amended by DL-068 and DL-069 (2026-10-03): the final month is the month of the actual hand-back date, with the before-the-5th exception in BR-RENT-030.

### PR-RENT-013 — Applicable Final Month Proration

**Business-rule traceability:** `BR-RENT-013`

**Normative product behavior**

When final-month proration is required by an approved rule or the signed Lease,
it uses the same inclusive actual-calendar-day calculation and final rounding as
the prorated portion of the Initial Rent Invoice.

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

Amended by DL-068 and DL-069 (2026-10-03): the month is the month of the actual hand-back date; the exception for a hand-back before the 5th is BR-RENT-030.

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

Amended by DL-068 and DL-069 (2026-10-03): a VOID under BR-RENT-030 VOIDs the whole Invoice, including its fixed Service lines.

Amended by the owner's answer to Q-2026-10-04-9 (2026-10-04): Under BR-RENT-030, a fully paid Rent Invoice for the hand-back month, or for the next month when the hand-back is between the 25th and the month end, is kept as issued with no VOID, Refund or credit Adjustment (DL-068, Q-2026-10-04-8).

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

### PR-RENT-029 — Contractual Late-payment Policy

**Business-rule traceability:** `BR-RENT-029`

**Normative product behavior**

The signed Lease policy is substantially that Rent or any other amount payable under
the Lease must be paid by the Due Date on the applicable Invoice or Bill. When a
balance remains unpaid after that Due Date, the normal/default late-payment charge is
10% of the remaining unpaid overdue amount of that Invoice. Authorized management may
reduce or waive the charge but must not increase it above 10%.

BR-INV-051 through BR-INV-055 govern the Invoice-wide calculation and one final
management decision. BR-LEASE-026 through BR-LEASE-030 govern the separate 20-day
Rent nonpayment warning, 30-day Serious Nonpayment Default, cure history, and explicit
termination boundary.

The Initial Rent Invoice is not an applicable source Invoice for a late-payment charge.

Amended by DL-075 (owner, 2026-10-20): as BR-RENT-029: the 10% is the Settings default late-payment rate, a whole percent from 0 to 10 (Lease Article 2.3 allows up to 10%). A new rate starts with the next billing month and applies to charges added after the change, for every Lease, never above 10%.

Amended by DL-076 (owner, 2026-10-20): as BR-RENT-029: the charge is added automatically under DL-076; the Owner or a Manager may reduce or waive it only after a Customer complaint of a staff mistake, never above the Settings rate (at most 10%).

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

Amended by DL-071 (owner, 2026-10-05; answer 12): a Meter serial number is unique across all Meters of the Property, whatever the Utility Type. Staff enter the serial printed on the Meter, or a unique Property code (for example `EL-U101`) when none is printed. A replaced Meter keeps its serial in history, and that serial cannot be used again. Not built yet.

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

Incorrect Utility Readings may be corrected through an authorized business process
both before and after Utility Invoice issuance. The system must not use Invoice
payment status as the correction boundary.

Every correction preserves original Reading value, corrected Reading value, actor,
date/time, reason, and complete audit history. Historical Utility Readings shall
never be silently overwritten, deleted, or reassigned.

Before issuance, the corrected Reading becomes the valid billing input. After
issuance, correction remains permitted whether the Invoice is UNPAID,
PARTIALLY_PAID, or PAID, but the issued Invoice must not be silently rewritten. If
the correction changes the amount that should have been billed, the system preserves
the original Invoice, calculates the difference, and posts that financial difference
through the approved linked Invoice Adjustment process. The original Reading,
corrected Reading, original Invoice, and complete Adjustment chain remain
reconstructable.

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

Replacing a Utility Meter shall never reassign, delete, or silently overwrite a
historical Utility Reading. An authorized correction under BR-UTIL-011 preserves the
original and corrected values and does not change Meter ownership.

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

Amended by DL-075 (owner, 2026-10-20): as BR-UTIL-015: a new Utility Rate starts on a reading day (UI-091). The Rate effective on the Invoice generation date still applies.

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

Before the Lease Start Date, after cleaning and repair, staff record a validated Reading
for each Utility Meter of the Unit with an evidence reference and turn Electricity and
Water off. That Reading is the Customer's starting responsibility boundary, whether the
tenant arrives on the Lease Start Date or later. If staff switch the Utilities on again
before handover, they record a new baseline Reading. The Property bears all consumption
between the previous tenant's final Reading and the new Customer's baseline Reading,
including cleaning and repair, and any consumption when the tenant never moved in.

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

Staff record every Utility Meter every month, including Meters of VACANT Units with
Electricity and Water off.

### PR-UTIL-021 — Utility Invoice Generation

**Business-rule traceability:** `BR-UTIL-021`

**Normative product behavior**

A Utility Invoice may be generated only after its ending Meter Reading has been
entered and validated, or after an authorized broken-Meter estimate is complete.

At move-out, the final Utility Invoice is created off-cycle immediately from the final
validated Readings or approved estimate. Its Due Date follows BR-INV-018. It must not
duplicate a consumption period billed by the monthly run under BR-UTIL-018 and
BR-INV-027.

Amended by DL-075 (owner, 2026-10-20): as BR-UTIL-021: the final Utility Invoice is due 7 days after issue (Lease Article 14.3), whatever the "days after issue" setting says.

### PR-UTIL-022 — Utility Due Date

**Business-rule traceability:** `BR-UTIL-022`

**Normative product behavior**

A monthly Utility Invoice is due on the 5th day of the following month in the
Property's configured local timezone, where “following month” is relative to the
billing month defined in BR-UTIL-020.

The final Utility Invoice created at move-out follows BR-INV-018 instead.

Amended by DL-075 (owner, 2026-10-20): as BR-UTIL-022: the 5th is the Settings default Due Date day (day 1 to 28). A change starts with the next billing month.

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

Every historical basis under BR-UTIL-025 or BR-UTIL-027 and every complete
future-period basis under BR-UTIL-028 uses one weighted daily average:

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

### PR-UTIL-027 — One-or-two-period Historical Basis

**Business-rule traceability:** `BR-UTIL-027`

**Normative product behavior**

If fewer than three, but at least one, complete historical actual period exists
before the affected broken-Meter period for the same Unit and Utility Type, use all
one or two available complete historical actual periods for that same Unit and
Utility Type as the basis.

```text
Weighted Historical Daily Average
=
Total Actual Consumption Across All Available Complete Historical Periods
--------------------------------------------------------------------------
Total Calendar Days Represented by Those Periods
```

Estimated Consumption is that weighted daily average multiplied by the applicable
unmeasured calendar days under BR-UTIL-026. The system must not discard the one or
two available periods and must not average separately rounded period averages.

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

The system must never substitute another or comparable Unit, invent arbitrary
consumption, or average separately rounded period averages.

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

The Property currently approves and provides this recurring fixed monthly Service:

- Trash Collection

Trash Collection is billed as a fixed monthly charge rather than a
consumption-based charge.

Internet and Monthly Cleaning are not currently provided and must not generate
charges. They are examples of Services the Property could approve and configure in
the future. This document approves no other Service type. Any different Service
requires a separate Owner-approved rule and explicit configuration before billing;
staff must not create an arbitrary Service through a generic or miscellaneous field.

Amended by DL-075 (owner, 2026-10-20): as BR-SVC-001: widened. Services are added in Settings by the Owner or a user with Settings access (DL-074), each with an English and a Khmer name, a Service type and a monthly rate. A Service type is "Only one per Lease" or "One or more per Lease"; changing a type to "Only one per Lease" is refused while a Lease holds two Services of that type, and a type that has Services cannot be removed. Trash Collection is chosen by default on a new Lease.

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

Each active, approved, and applicable configured recurring Service is billed monthly
in advance as a separate line item on the applicable Rent Invoice. Trash Collection
is the current such Service.

For the Initial Service period under BR-SVC-012, that separate line appears on the
Initial Rent Invoice. Later normal recurring Service lines appear on the applicable
recurring Rent Invoice.

Separate Service Charge Invoices are not normally generated for these fixed
recurring monthly Services.

### PR-SVC-004 — Fixed Charges

**Business-rule traceability:** `BR-SVC-004`

**Normative product behavior**

An approved configured recurring Service uses its configured fixed monthly charge.

Their billing amount is not affected by:

- utility consumption,
- number of occupants,
- number of days within a normal full month.

The prorated move-in-month component of the Initial Service period uses actual
calendar days. Final and early-termination-month treatment follows the signed Lease
and approved termination rules and is not automatically prorated merely because the
Customer physically leaves during the month.

### PR-SVC-005 — Service Rate Effective Date

**Business-rule traceability:** `BR-SVC-005`

**Normative product behavior**

Every service charge revision shall have an effective date.

The revised amount applies only to billing periods beginning on or after that effective date.

The applicable configured Service terms remain the source of truth.

Amended by DL-075 (owner, 2026-10-20): as BR-SVC-005: a new Service rate starts on the first day of a later month. Issued Invoices keep the old rate, and a new Service name shows only on new Invoices.

### PR-SVC-006 — Historical Service Rate Preservation

**Business-rule traceability:** `BR-SVC-006`

**Normative product behavior**

Historical service rates shall remain permanently preserved.

Changes to configured Service charges shall never modify historical Invoices.
The Service identity, Owner approval, configuration, active/inactive effective
periods, and rate history must remain reconstructable.

### PR-SVC-007 — Future Service Rate Changes

**Business-rule traceability:** `BR-SVC-007`

**Normative product behavior**

Revised service charges shall only affect future billing periods.

Completed billing periods shall always retain the original service charge used during billing.

### PR-SVC-008 — Historical Financial Integrity

**Business-rule traceability:** `BR-SVC-008`

**Normative product behavior**

Historical configured Service charges are permanent financial records.

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

The initial line is placed on the Initial Rent Invoice and covers the complete Initial
Service period under BR-SVC-012, including both components for a day-21-or-later
move-in.

### PR-SVC-010 — Line-level History

**Business-rule traceability:** `BR-SVC-010`

**Normative product behavior**

Each Service line preserves its Service identity, category, configured rate,
billing period, calculation when prorated, and final amount. A day-21-or-later Initial
Service line preserves both the prorated move-in-month component and the full following
month component without collapsing or obscuring either period.

### PR-SVC-011 — Advance Billing Schedule

**Business-rule traceability:** `BR-SVC-011`

**Normative product behavior**

Initial recurring-Service lines follow BR-SVC-012 and are issued on the Initial Rent
Invoice and share its Due Date under BR-RENT-009. After that initial coverage, fixed
recurring Services use the normal Rent billing cycle: generation on the 25th in the
Property's authoritative `Asia/Phnom_Penh` timezone for the upcoming uncovered month
and the same applicable Due Date as the recurring Rent Invoice.

Normal recurring generation resumes with the first complete calendar month after the
Initial Service period under BR-SVC-012. A scheduled run must not generate a Service
period already covered by that Initial Service period.

Amended by DL-075 (owner, 2026-10-20): as BR-SVC-011: the 25th is the Settings default issue day. A change starts with the next billing month.

### PR-SVC-012 — Initial Recurring-Service Period

**Business-rule traceability:** `BR-SVC-012`

**Normative product behavior**

Each explicitly approved, configured, active, and applicable recurring Service
follows the same Initial Invoice period structure as Rent.

For a Lease Start Date on day 1 through day 20 inclusive, its Initial Service
period covers the Lease Start Date through the last calendar day of the start month.

For a Lease Start Date on day 21 or later, its Initial Service period combines:

1. the prorated remainder of the start month; and
2. the entire following calendar month.

Each component uses the applicable approved configured Service rate for its period.
The prorated component uses the inclusive actual-calendar-day formula and final
half-up USD-cent rounding under BR-MONEY-012. The Service appears as a separate line
on the Initial Rent Invoice and therefore shares the Initial Rent Invoice Due Date under BR-RENT-009.

Example:

```text
Lease Start Date:           27 July
Initial Service coverage:  27–31 July, prorated
                           plus 1–31 August, full month
Initial Invoice Due Date:  1 August (proposed)
Normal generation resumes: 25 August for 1–30 September
Normal Due Date:            5 September
```

Initial and recurring Service periods must not overlap or duplicate one another.

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
billed. The Service must also be active and actually provided for the billed period.
The system must not create a Service or charge from free-form Invoice entry.

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
- each applicable approved and configured recurring Service

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

For an Invoice with multiple lines or obligation categories, confirmed applications
reduce the identified underlying balances and roll up to the Invoice outstanding
balance. For example, applying $300 to the Rent line of a $500 Rent plus $10 recurring
Service Invoice leaves $200 Rent and $10 Service, so the Invoice outstanding balance is
$210 and the status is PARTIALLY_PAID.

### PR-INV-013 — Fully Paid

**Business-rule traceability:** `BR-INV-013`

**Normative product behavior**

When active Payment Allocations, Customer Credit applications, or authorized
Final Settlement Deposit applications reduce the outstanding balance to exactly
zero, the Invoice status shall become:

- PAID

The Invoice may become PAID only when all of its underlying line or obligation balances
roll up to zero. A separate Late-payment Charge balance does not affect the source
Invoice's status.

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
 └──► VOID (only after all active financial applications and dependencies have been
           resolved through their explicit approved processes under BR-INV-024)

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

The regressions `PARTIALLY_PAID → UNPAID`, `PAID → PARTIALLY_PAID`, and
`PAID → UNPAID` are permitted only as derived consequences of authorized financial
reversals or corrections that change valid remaining applications/allocations. They
must never represent manual status editing, partial Invoice voiding, partial Refund
semantics, arbitrary reopening, or a Refund represented merely by changing status.
VOID remains a separate action under BR-INV-014.

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


Every issued Invoice has exactly one Due Date; a DRAFT may have none. Recurring Due
Dates follow their approved billing rules, and the Initial Rent Invoice follows
BR-RENT-009. For a one-time Damage or Miscellaneous charge created manually by
authorized staff, and for the final Utility Invoice under BR-UTIL-021, the system
proposes a Due Date of the issue date plus the Property's configured number of calendar
days, seven by default. An authorized user may set a different Due Date with a mandatory
reason; the actor and timestamp are recorded. The Due Date is fixed once issued. Debit
Adjustments use their Invoice's Due Date under BR-INV-044.

Amended by DL-075 (owner, 2026-10-20): as BR-INV-018: the configured number of days is the Settings "days after issue" (1 to 90, default 7), which applies at once to Invoices issued after the change. The move-out cleaning charge, move-out Damage Charges and the final Utility Invoice are due 7 days after issue (Lease Article 14.3), whatever the setting says; the authorized override with a mandatory reason stays.

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

The business shall prevent any approved and configured recurring Service Charge from
being billed multiple times or for overlapping coverage for the same Lease and
Service. Normal generation must skip every period already included in the Initial
Service period under BR-SVC-012.

### PR-INV-029 — Duplicate Invoice Prevention Principle

**Business-rule traceability:** `BR-INV-029`

**Normative product behavior**

The application shall reject any Invoice that would create duplicate billing for the same financial obligation.

Examples include:

- duplicate Rent for the same billing period,
- duplicate Electricity billing for the same consumption period,
- duplicate Water billing for the same consumption period,
- duplicate or overlapping configured Service coverage for the same Lease and Service.

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

An Adjustment is recorded against one line of an issued Invoice and uses that Invoice's
single Due Date. Invoice lines have no Due Dates of their own.

A debit Adjustment is allowed only while its line has a positive remaining balance. It
is rejected once the line is fully paid; a missed amount on a fully paid line is billed
as a normal one-time Miscellaneous or Damage Charge. A Payment or Credit reversal that
restores a positive balance on the line allows debit Adjustments again.

A credit Adjustment is allowed on any issued, non-VOID Invoice line. Any credit beyond
that line's remaining balance becomes Customer Credit for the Invoice Customer.

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

When a Lease is terminated and the tenant never moved in under BR-LEASE-005, an Initial
Rent Invoice with nothing paid is VOIDed with a mandatory reason. A partly paid one is
not VOIDed; its unpaid remainder is removed by a linked credit Adjustment.

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


The Due Date of a one-time Damage or Miscellaneous charge follows BR-INV-018. It no
longer has to come from a governing Lease provision, event or document. A debit
Adjustment has no Due Date of its own and uses its Invoice's Due Date under BR-INV-044.

### PR-INV-050 — Deterministic Scheduled Issuance

**Business-rule traceability:** `BR-INV-050`

**Normative product behavior**

Approved scheduled billing may generate and issue Invoices automatically from
deterministic source rules. Rent and its fixed recurring Service lines require an
applicable signed Lease. Other Invoices follow their approved source rules.

### PR-INV-051 — Due Date and Overdue Boundary

**Business-rule traceability:** `BR-INV-051`

**Normative product behavior**

An applicable source Invoice is an issued Invoice for Rent or another amount payable
under the signed Lease under BR-RENT-029. Its stated Due Date is the last calendar day
on which payment is timely. Payment received on that Due Date is not late.

In the Property's authoritative business timezone, `Asia/Phnom_Penh`, any positive
remaining unpaid balance becomes overdue on the next calendar day after the Due Date.
There is no additional ten-day grace period.

Example:

```text
Due Date:                     5 August
Payment received 5 August:   On time
Remaining balance 6 August:  Overdue and eligible for proposal
```

Eligibility does not automatically post a charge.

The Initial Rent Invoice is not an applicable source Invoice for a late-payment charge.

Amended by DL-076 (owner, 2026-10-20): as BR-INV-051: "Eligibility does not automatically post a charge" is replaced: at 00:00 Property time on the first day after the Due Date, the app adds the late-payment charge by itself, at the Settings rate (DL-075, default 10%) of the amount unpaid at that moment, rounded half-up; no management decision is needed.

### PR-INV-052 — Invoice-wide Late-payment Calculation

**Business-rule traceability:** `BR-INV-052`

**Normative product behavior**

At assessment, the default late-payment charge is calculated once against the total
remaining unpaid overdue balance of the applicable source Invoice as a whole:

```text
Default Late-payment Charge
=
Remaining Unpaid Overdue Source-Invoice Balance at Assessment
×
10%
```

The balance reflects valid financial applications and allocations in effect at
assessment. Amounts already validly paid or otherwise validly applied must not be
charged again. The system must not calculate separate late-payment percentages for
individual lines of the same applicable overdue Invoice. The final USD result uses
the general half-up cent rounding rule in BR-MONEY-012.

Example:

```text
Rent:                                      $500
Trash Collection:                          $10
Electricity:                               $80
Water:                                     $20
Original source-Invoice total:             $610

If remaining unpaid overdue balance:       $610
Default late-payment charge at 10%:         $61

If valid Payments already applied:         $300
Remaining unpaid overdue balance:          $310
Default late-payment charge at 10%:         $31
```

Amended by DL-076 (owner, 2026-10-20): as BR-INV-052: the rate is the Settings rate (DL-075, default 10%), and the calculation is made once by the app at 00:00 on the first day after the Due Date.

### PR-INV-053 — Authorized Late-payment Decision

**Business-rule traceability:** `BR-INV-053`

**Normative product behavior**

The system detects the overdue source Invoice, calculates and presents the proposed
default charge, and flags it for authorized management. It must not post the charge
automatically merely because the Due Date has passed.

Authorized management makes one final decision for the source Invoice:

- confirm the default 10% charge;
- approve a reduced charge below the 10% default; or
- waive the charge, equivalent to 0% and $0.

Management must not increase the contractual percentage or approved amount above the
10% default calculation. Ordinary staff must not arbitrarily change the percentage
or amount.

The decision preserves at minimum the source Customer, source Invoice, source Invoice
Due Date, remaining overdue balance at assessment, default percentage, actual approved
percentage, calculated default amount, actual approved amount, decision outcome,
authorized management actor, reason, assessment timestamp, and confirmation or waiver
timestamp.

Replaced by DL-076 (owner, 2026-10-20): as BR-INV-053: no management decision. At 00:00 Property time on the first day after the Due Date, the app adds the late-payment charge by itself, at the Settings rate (DL-075, default 10%) of the amount unpaid at that moment, rounded half-up; no management decision is needed. The Owner or a Manager may only reduce or waive it after the Customer complains that it is wrong because of a staff mistake, with one of three fixed reasons ("Staff recorded the payment on the wrong Invoice", "Paid on time but recorded late", "Other staff mistake") and a required "What happened" text. The amount only goes down.

### PR-INV-054 — One Final Non-compounding Decision per Invoice

**Business-rule traceability:** `BR-INV-054`

**Normative product behavior**

Each applicable source Invoice may have only one final late-payment decision. A
confirmed default charge, reduced charge, or waiver is final for that source Invoice.

The late-payment charge must not repeat daily, weekly, monthly, or on any other
cadence. It must not compound, generate another late-payment charge, or create a
recursive penalty. Continued nonpayment of the source principal does not reopen the
decision. A reduced charge must not later be supplemented with the difference, and a
waiver must not later be replaced by a charge. Payment received after the final
decision does not recalculate or replace that decision.

The Invoice is locked while an Adjustment or the final late-payment decision is
recorded, so the two are strictly ordered. An Adjustment recorded before the final
decision is included in that decision's balance. A debit Adjustment recorded after the
final decision is allowed but is not counted in that decision, and a credit Adjustment
never changes a final decision.

Example: if the default is $31 and management approves $15, the remaining $16 must
never be imposed as a second late-payment charge for that source Invoice.

Amended by DL-076 (owner, 2026-10-20): as BR-INV-054: one automatic charge per Invoice replaces the one final decision; money paid later does not change it. A reduction or waiver never raises it.

### PR-INV-055 — Explicit Linked Late-payment Financial Record

**Business-rule traceability:** `BR-INV-055`

**Normative product behavior**

A final late-payment decision is a permanent auditable business event linked to its
source Invoice. A positive approved amount must remain an explicit linked auditable
financial charge and must not be hidden in an undifferentiated entry.

The source Invoice's original principal, lines, and issued amount must not be silently
altered to incorporate the charge. A confirmed positive amount creates the separate
Late-payment Charge obligation defined by BR-LATE-001. It does not create another
Invoice, Invoice Category, Miscellaneous Charge, or historical source-Invoice line. A
waiver records the final decision and audit history without creating a receivable.

Amended by DL-076 (owner, 2026-10-20): as BR-INV-055: the linked record is the automatic charge and its reductions and waivers; history keeps every change.

## 8.13 Late-payment Charge Requirements

### PR-LATE-001 — Positive Late-payment Charge Obligation

**Business-rule traceability:** `BR-LATE-001`

**Normative product behavior**

Authorized management confirmation of a positive default or reduced amount creates
exactly one separate Late-payment Charge obligation. It belongs to exactly one Customer
and links to exactly one source overdue Invoice and its final late-payment decision.
The obligation Customer must be the source Invoice Customer.

The obligation is part of the Customer's overall outstanding balance but is not an
Invoice and does not affect the source Invoice's principal, lines, outstanding balance,
or derived status.

Amended by DL-076 (owner, 2026-10-20): as BR-LATE-001: the app creates the charge by itself (DL-076); no management confirmation.

### PR-LATE-002 — Immediate Payability

**Business-rule traceability:** `BR-LATE-002`

**Normative product behavior**

A positive Late-payment Charge becomes payable immediately at its management
confirmation timestamp. It requires no new Invoice and no Invoice Due Date. Its
confirmation timestamp is the date and time the obligation becomes payable.

Amended by DL-076 (owner, 2026-10-20): as BR-LATE-002: the charge is payable at once from the moment the app adds it (00:00 on the first day after the Due Date).

### PR-LATE-003 — Waived and Reduced Decisions

**Business-rule traceability:** `BR-LATE-003`

**Normative product behavior**

A WAIVED or equivalent final outcome preserves the proposal and waiver decision and
creates no positive receivable. A REDUCED or equivalent final outcome creates only the
approved reduced Late-payment Charge amount. The waived or reduced difference must
never be added later for that source Invoice.

Amended by DL-076 (owner, 2026-10-20): as BR-LATE-003: a reduction or waiver is made after the charge exists, by the Owner or a Manager after a Customer complaint of a staff mistake; a paid charge may still be reduced or waived, and paid money above the new amount goes to Customer Credit under BR-CREDIT-014.

### PR-LATE-004 — Remaining Balance and Satisfaction

**Business-rule traceability:** `BR-LATE-004`

**Normative product behavior**

The original confirmed Late-payment Charge amount remains historically unchanged. Its
remaining outstanding balance equals that original amount less valid Payment
Allocations and Customer Credit applications, adjusted only by explicit authorized
reversals or corrections. The remaining balance cannot become negative.

A zero remaining balance means the obligation is fully satisfied. No additional manual
status lifecycle is required, and no Late-payment Charge balance affects the source
Invoice's balance or status.

### PR-LATE-005 — Explicit Correction and Reversal

**Business-rule traceability:** `BR-LATE-005`

**Normative product behavior**

If a confirmed Late-payment Charge later requires correction or reversal, the original
decision and obligation remain permanent. An authorized linked correction or reversal
records the reason, actor, date/time, previous amount or balance, resulting amount or
balance, and all affected applications. Silent deletion or rewriting is prohibited.
Correction must obey the approved maximum and final-decision rules and must not be used
to supplement a reduced charge or replace a waived decision.

### PR-LATE-006 — No Recursive Charge

**Business-rule traceability:** `BR-LATE-006`

**Normative product behavior**

A proposed, confirmed, reduced, waived, partially satisfied, fully satisfied, corrected,
or reversed Late-payment Charge must never itself be assessed for another late-payment
charge.

## 8.14 Payment and Allocation Requirements

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

An Invoice balance may be settled through authorized Payment Allocations, Customer
Credit applications, or Final Settlement Deposit applications under the applicable
rules. Recording a Payment settles no Invoice until value from that Payment is
explicitly allocated.

Payment, Receipt, Payment Allocation, Payment Reversal, Customer Credit, and
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

Amended by DL-075 (owner, 2026-10-20): as BR-PAY-006: Payment Methods are added, edited and turned off in Settings. Each method says whether it needs a reference. A method used on a Receipt is never deleted, only turned off. At least one method stays on, and only methods that are on can be chosen.

### PR-PAY-007 — Payment Method Preservation

**Business-rule traceability:** `BR-PAY-007`

**Normative product behavior**

The Payment Method recorded when the Payment is received shall remain permanently preserved.

Historical Payments shall never be modified solely because a Payment Method is renamed or retired.

The Payment currency and, for KHR, all exchange and source values must likewise
remain permanent.

### PR-PAY-008 — Payment Record Statuses

**Business-rule traceability:** `BR-PAY-008`

**Normative product behavior**

Payment record status may be only:

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
Its Payment record status remains RECEIVED.

### PR-PAY-011 — Fully Allocated

**Business-rule traceability:** `BR-PAY-011`

**Normative product behavior**

When active Allocations use the Payment's entire available USD accounting value,
the Payment is fully allocated as a derived condition. Its Payment record status remains
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

The permitted Payment lifecycle is:

```text
RECEIVED -> REVERSED
REVERSED -> terminal
```

Posting or reversing Allocations changes the derived allocated and unallocated
amounts without changing RECEIVED status. A Refund follows its source-specific
rules and does not require falsifying the original Payment lifecycle.

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

Amended by DL-071 (owner, 2026-10-20; answer 10b): a Payment has one Receipt, and the Payment Number is that Receipt's number, for example `RCP260001` (type code, 2-digit year of the confirmation date, 4-digit running number). This replaces the separate Payment Number. Not built yet.

### PR-PAY-018 — Audit Requirement

**Business-rule traceability:** `BR-PAY-018`

**Normative product behavior**

Every significant Payment event shall be fully auditable, including:

- Payment creation
- Payment record-status changes
- Receipt issuance and reprint
- Allocation changes
- Reversal
- Refund

Historical audit information shall never be silently removed.

### PR-PAY-019 — Allocation Is a Separate Financial Event

**Business-rule traceability:** `BR-PAY-019`

**Normative product behavior**

A Payment Allocation links part of one RECEIVED Payment's USD accounting value to one
or more identified obligations belonging to the applicable Customer. A target may be
an issued Customer Invoice with sufficient Invoice-line or obligation-category detail,
or a separate confirmed Late-payment Charge. It does not rewrite any source record.

A Deposit receipt remains the separate Payment-to-Deposit link in BR-DEP-005 and is not
silently converted into an ordinary Payment Allocation. Customer Credit, unallocated
Payment, Refund, and Deposit balances likewise remain distinct.

### PR-PAY-020 — Manual Authorized Posting

**Business-rule traceability:** `BR-PAY-020`

**Normative product behavior**

Payment Allocation is manual and performed by authorized staff. The system may
calculate and present a proposal, but it must not post that proposal without
authorized staff confirmation.

Amended by DL-077 (owner, 2026-10-20): as BR-PAY-020: pressing Receive payment is the staff confirmation. The app ticks the proposal when the amount is entered, and one command saves the Payment and its Allocations in one database transaction. There is no "match later" while the Customer owes anything.

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
applicable outstanding Invoices are satisfied.

No line-category preference may reorder the selected Invoices. After an Invoice is
selected, the within-Invoice rules in BR-PAY-036 apply.

### PR-PAY-023 — Deterministic Ties

**Business-rule traceability:** `BR-PAY-023`

**Normative product behavior**

Invoices with the same Due Date are ordered by Invoice issue or generation order
and then by a stable Invoice sequence or identifier.

### PR-PAY-024 — Customer-designated Allocation

**Business-rule traceability:** `BR-PAY-024`

**Normative product behavior**

When the Customer explicitly identifies a valid Invoice, Invoice line or obligation
category, or separate Late-payment Charge, authorized staff may post the Payment to
that valid designated target instead of the applicable default proposal. The Customer
designation and posted Allocation must be preserved.

### PR-PAY-025 — Normal Customer Scope

**Business-rule traceability:** `BR-PAY-025`

**Normative product behavior**

For a normal Customer Payment, the default proposal includes applicable
outstanding Invoices belonging to the financially responsible Customer,
including across that Customer's applicable Lease relationships where permitted
by the approved rules.

An Invoice without a Lease remains eligible when it belongs to that Customer and
is otherwise a valid applicable obligation.

Amended by the owner's answer to Q-2026-10-05-16 (2026-10-05): under BR-PAY-042, a confirmed wrong-Unit Payment move may allocate a normal Customer Payment to an Invoice of another Customer or outside the Payment's identified Invoice; only that move, or a credit Adjustment's re-post of such an allocation on the same Invoice, does so.

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

Amended by the owner's answer to Q-2026-10-05-16 (2026-10-05): under BR-PAY-042, a confirmed wrong-Unit Payment move may allocate a third-party Payment outside its identified Invoice or Lease intent; only that move, or a credit Adjustment's re-post of such an allocation on the same Invoice, does so.

### PR-PAY-027 — Allocation Amount Limits

**Business-rule traceability:** `BR-PAY-027`

**Normative product behavior**

An Allocation must be positive and must not exceed either:

- the Payment's remaining unallocated USD accounting value; or
- the identified target obligation's current outstanding balance.

### PR-PAY-028 — No Negative Obligation Balance

**Business-rule traceability:** `BR-PAY-028`

**Normative product behavior**

Posting an Allocation must never cause an Invoice-line, Invoice, Late-payment Charge,
or other target obligation balance to become negative. Payment value beyond applicable
outstanding balances remains unallocated excess.

### PR-PAY-029 — Allocation History and Reversal

**Business-rule traceability:** `BR-PAY-029`

**Normative product behavior**

Every posted Allocation permanently preserves its Payment, target Invoice or other
obligation, Invoice-line or obligation category where applicable, allocated amount,
Customer designation if any, proposed default if any, posting time, and authorized
user confirmation. A correction uses an explicit linked Allocation Reversal and
recomputes affected line, obligation, Invoice, and Customer balances and derived
statuses; it never deletes or overwrites the original Allocation.

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

Amended by DL-077 (owner, 2026-10-20): as BR-PAY-031: money waits on the Receipt only when it is more than everything owed, or when nothing is owed; it is never called Credit before the Customer chooses Credit or a refund.

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

Amended by DL-068 and DL-069 (2026-10-03): Credit released by a credit Adjustment belongs to the Invoice Customer (BR-CREDIT-014).

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

### PR-PAY-036 — Within-Invoice Default Proposal

**Business-rule traceability:** `BR-PAY-036`

**Normative product behavior**

After the applicable Invoice is selected under BR-PAY-021 through BR-PAY-025, if that
Invoice contains Rent and recurring-Service lines and the Customer did not designate
the within-Invoice target, the system proposes value in this order:

1. Rent line or obligation;
2. then recurring-Service lines on that same Invoice.

This is a proposal only. Authorized staff must confirm it before posting under
BR-PAY-020. The system must not silently post the proposal.

Example: for $500 Rent plus $10 Trash Collection, an unspecified $300 Payment produces
a proposal of $300 to Rent, leaving $200 Rent and $10 Trash Collection. An unspecified
$505 Payment proposes $500 to Rent and $5 to Trash Collection, leaving Rent fully paid
and $5 Service outstanding. A $510 Payment proposes full satisfaction of both lines.

### PR-PAY-037 — Customer-designated Within-Invoice Allocation

**Business-rule traceability:** `BR-PAY-037`

**Normative product behavior**

When the Customer clearly identifies a valid line or obligation category within a
mixed Invoice, authorized staff may confirm that designation instead of the default
within-Invoice proposal. The designation, confirmed target, amount, actor, and date/time
must be preserved.

### PR-PAY-038 — Between-Invoice FIFO Remains First

**Business-rule traceability:** `BR-PAY-038`

**Normative product behavior**

When the Customer has not designated an Invoice, the system first proposes applicable
Invoices by oldest Due Date and the existing deterministic tie-breakers in BR-PAY-022
and BR-PAY-023. BR-PAY-036 then orders lines only within each selected mixed Invoice.
Rent-first within one Invoice must not reorder multiple Invoices.

### PR-PAY-039 — Invoice Rollup and Rent Determination

**Business-rule traceability:** `BR-PAY-039`

**Normative product behavior**

Confirmed Payment Allocations reduce their identified Invoice-line or obligation
balances. Those remaining balances roll up exactly to the Invoice outstanding balance
and its derived status under BR-INV-012 and BR-INV-013.

The remaining Rent obligation after valid confirmed Payment Allocations and Customer
Credit applications—not the total mixed-Invoice balance—determines Rent nonpayment
under BR-LEASE-027 through BR-LEASE-030. An unpaid Service-only balance must not be
misclassified as unpaid Rent.

### PR-PAY-040 — Late-payment Charge Allocation

**Business-rule traceability:** `BR-PAY-040`

**Normative product behavior**

Authorized staff may allocate Payment value directly to a positive confirmed
Late-payment Charge. The Allocation reduces only that separate obligation's remaining
balance and does not rewrite or increase its original amount or the source Invoice.

If a Customer designates an amount for the Late-payment Charge, apply no more than its
remaining balance. Any remaining Payment value follows the Customer's other valid
designation or the normal confirmed Allocation rules and remains unallocated until
posted or otherwise disposed under an approved rule.

Example: if the source Invoice remains $310 outstanding and its separate Late-payment
Charge is $31, a Customer-designated $100 Payment to the Late-payment Charge applies $31
there and leaves $69 for another valid confirmed Allocation or disposition. The source
Invoice remains $310 outstanding until value is separately allocated to it. A Receipt
may show both the $100 Payment and the confirmed $31 application.

Replaced by DL-076 (owner, 2026-10-20): as BR-PAY-040: the proposal pays oldest Due Date first, and a late-payment charge right after its own Invoice, before newer Invoices. Staff change the ticks only when the Customer names what to pay (BR-PAY-024) and confirm with Receive payment (DL-029). A third-party payer's money gets no automatic ticks.

## 8.15 Receipt Requirements

### PR-RECEIPT-001 — Receipt Acknowledges Payment

**Business-rule traceability:** `BR-RECEIPT-001`

**Normative product behavior**

A Receipt is the numbered customer-facing acknowledgment that money was received under
one existing Payment. Receipt does not replace Payment, create Payment, settle an
obligation independently, or serve as the authoritative receipt-of-money event.

### PR-RECEIPT-002 — Receipt Identity and Source

**Business-rule traceability:** `BR-RECEIPT-002`

**Normative product behavior**

Every Receipt has a unique Receipt Number and identifies exactly one source Payment and
that Payment's payer Customer. One Payment normally produces one business Receipt.
Persistence of safely derived display fields is decided by `004_DATABASE_MODEL.md`.

Amended by DL-071 (owner, 2026-10-20; answer 10): the Receipt Number is `RCP`, the 2-digit year of the confirmation date in the Property's local time and a 4-digit running number that restarts at 0001 each year, with no dashes or spaces (for example `RCP260001`); it grows to 5 digits after 9999 and is never reused. It is also the Payment Number. Not built yet.

### PR-RECEIPT-003 — Customer-facing Content

**Business-rule traceability:** `BR-RECEIPT-003`

**Normative product behavior**

A Receipt may present, as applicable, its Receipt Number, Payment, Customer, Payment
Date, Payment Method, received currency and amount, USD accounting value, KHR conversion
details, confirmed Invoice-line or other obligation applications, Late-payment Charge
amount paid, Deposit purpose, allocation/application breakdown, issuer, and issue time.

Every presented amount and application must be traceable to the immutable Payment and
linked authoritative Allocation, Credit-application, Deposit, or obligation records.

### PR-RECEIPT-004 — Reprint Is Not New Money

**Business-rule traceability:** `BR-RECEIPT-004`

**Normative product behavior**

Reprinting a Receipt preserves the same original Receipt Number, source Payment,
Customer, and business identity. A reprint must not create a second Payment, duplicate
the received amount, or represent another receipt of money. The reprint event, actor,
and date/time remain auditable.

### PR-RECEIPT-005 — Receipt History

**Business-rule traceability:** `BR-RECEIPT-005`

**Normative product behavior**

Receipt issuance and reprint history must remain reconstructable. Correction of a
Payment or Allocation uses the applicable explicit correction or reversal process and
must not silently rewrite or delete the original Receipt history.

### PR-RECEIPT-006 — Refund Remains Separate

**Business-rule traceability:** `BR-RECEIPT-006`

**Normative product behavior**

A Receipt acknowledges inbound money. A Refund remains a distinct outbound financial
event under BR-REFUND-001 and must not be represented as a negative Payment or as
deletion or rewriting of the original Payment or Receipt. This rule creates no separate
Refund-receipt document.

## 8.16 Customer Credit Requirements

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

### PR-CREDIT-005 — Valid Obligation Application

**Business-rule traceability:** `BR-CREDIT-005`

**Normative product behavior**

Authorized Customer Credit may be applied only to a valid outstanding obligation,
including an issued Invoice or a positive confirmed Late-payment Charge belonging to
the same Customer. It must not create or accelerate an Invoice solely to consume the
Credit.

### PR-CREDIT-006 — Authorized Application

**Business-rule traceability:** `BR-CREDIT-006`

**Normative product behavior**

A Customer Credit application is a separate authorized financial event.
It identifies the Credit source, target Invoice or other obligation, sufficient
Invoice-line or obligation-category detail where applicable, amount, Customer
designation if any, proposed default if any, actor confirmation, and time.

For a selected mixed Rent Invoice without Customer designation, the application follows
the Rent-first then recurring-Service proposal and authorized confirmation requirements
in BR-PAY-036 through BR-PAY-039.

Amended by DL-077 (owner, 2026-10-20): as BR-CREDIT-006: on issue day, "One tap" fills in the use of the Customer's Credit for the new Invoice, and staff confirm it.

### PR-CREDIT-007 — Application Limits

**Business-rule traceability:** `BR-CREDIT-007`

**Normative product behavior**

A Credit application must be positive and cannot exceed either the available
Customer Credit balance or the target obligation's outstanding balance. It must not
produce a negative Invoice-line, Invoice, Late-payment Charge, or Credit balance.

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
exact Payment-confirmation exchange rate, USD accounting value, and source
relationship. The Credit balance itself remains USD.

### PR-CREDIT-011 — USD-only Credit Refund

**Business-rule traceability:** `BR-CREDIT-011`

**Normative product behavior**

Refund Customer Credit only in USD, paid and recorded in exact USD cents. Preserve
its USD value and original source linkage, including any KHR Payment and immutable
conversion-rate evidence. Do not convert Credit into a KHR Refund (DL-060).

### PR-CREDIT-012 — Permanent Credit History

**Business-rule traceability:** `BR-CREDIT-012`

**Normative product behavior**

Creation, application, reversal, Refund, remaining balance, and source values of
Customer Credit must remain permanently reconstructable and auditable.

### PR-CREDIT-013 — Not Vendor Accounts Payable

**Business-rule traceability:** `BR-CREDIT-013`

**Normative product behavior**

Customer Credit retained for a Customer remains a distinct customer-related liability
concept. It must not be called or modeled as ordinary vendor Accounts Payable. General
supplier and vendor Accounts Payable is outside this application's scope.

## 8.17 Customer Account Ledger Requirements

### PR-LEDGER-001 — One Unified Customer View

**Business-rule traceability:** `BR-LEDGER-001`

**Normative product behavior**

Each Customer must have a unified Customer Account Ledger view that presents the
Customer's complete chronological financial history and current financial position.
It must be reconstructable from the Customer's authoritative underlying records.

### PR-LEDGER-002 — Underlying Records Remain Authoritative

**Business-rule traceability:** `BR-LEDGER-002`

**Normative product behavior**

The Customer Account Ledger does not replace, merge, or rewrite Invoice lines,
Invoices, Payments, Payment Allocations, Customer Credit, Credit applications,
Adjustments, Refunds, Security Deposits, Pet Deposits, Deposit applications or
dispositions, Late-payment Charges, Payment or Allocation Reversals, or Final
Settlement records.

Whether `004_DATABASE_MODEL.md` derives the view directly or uses a reconciled
materialized structure is an implementation choice. A Ledger representation must never
become a second conflicting source of financial truth.

### PR-LEDGER-003 — Complete Financial Position

**Business-rule traceability:** `BR-LEDGER-003`

**Normative product behavior**

The Ledger must make it possible to determine, for one Customer:

- amounts charged and their source obligations;
- Payments received and confirmed applications;
- Customer Credit created, available, applied, reversed, or refunded;
- Refunds and Adjustments;
- Security Deposit and Pet Deposit amounts received, held, applied, disposed, or refunded;
- Late-payment Charges and their remaining balances;
- obligations that remain unpaid and their composition;
- total current amount the Customer owes; and
- available Customer Credit.

Deposits remain separately identifiable liabilities and must not be pooled into ordinary
Customer Credit or netted away by the Ledger view.

### PR-LEDGER-004 — Business-facing Language

**Business-rule traceability:** `BR-LEDGER-004`

**Normative product behavior**

Customer-facing and staff-facing Ledger presentation uses operational terms such as
Amount charged, Payment received, Credit, Refund, Outstanding balance, and Customer
Credit. It must not require formal debit/credit bookkeeping terminology and must not
introduce a Chart of Accounts, journal-entry posting, General Ledger, or vendor Accounts
Payable workflow.

### PR-LEDGER-005 — Chronology and Reconstruction

**Business-rule traceability:** `BR-LEDGER-005`

**Normative product behavior**

Every displayed event must retain or derive its event date/time, source record,
Customer, amount, direction or business effect, and resulting position. Corrections and
reversals remain separate events so the historical and current positions can be
reconstructed without silent deletion or rewriting.

### PR-LEDGER-006 — Balance Composition

**Business-rule traceability:** `BR-LEDGER-006`

**Normative product behavior**

The Customer's total outstanding amount includes valid Invoice outstanding balances and
separate positive Late-payment Charge outstanding balances. Customer Credit,
unallocated Payment, Security Deposit, and Pet Deposit remain distinct balances and
must not be silently treated as reductions of an obligation without an authorized
application.

### PR-LEDGER-007 — Illustrative Ledger

**Business-rule traceability:** `BR-LEDGER-007`

**Normative product behavior**

For an Invoice with $500 Rent and $10 Trash Collection, an authorized $300 Rent
Allocation leaves $200 Rent and $10 Service outstanding. If authorized management then
confirms a $21 Late-payment Charge, the Customer's total outstanding amount is $231
while the Invoice remains $210 outstanding. A later $231 Payment may be allocated as
$200 Rent, $10 Trash Collection, and $21 Late-payment Charge, resulting in zero total
outstanding without changing the original Invoice or Late-payment Charge amounts.

This example does not require physical duplication of every amount in a Ledger table.

## 8.18 Refund Requirements

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

### PR-REFUND-005 — USD Refund of KHR-origin Excess

**Business-rule traceability:** `BR-REFUND-005`

**Normative product behavior**

Refund eligible unallocated excess from a KHR Payment only in USD, using the
remaining recorded USD accounting value after authorized dispositions. Preserve
the original KHR Payment amount and Payment-confirmation exchange evidence for
audit. Do not recalculate the Refund from a KHR remainder or a new rate (DL-060).

### PR-REFUND-006 — USD-only Credit Refund Currency

**Business-rule traceability:** `BR-REFUND-006`

**Normative product behavior**

All Customer Credit Refunds must be paid and recorded in USD. KHR is a Payment
conversion option only, not a Refund currency. No Refund-date exchange rate or
KHR Refund rounding is used; retain original KHR source evidence (DL-060).

### PR-REFUND-007 — Final Settlement Deposit Refund

**Business-rule traceability:** `BR-REFUND-007`

**Normative product behavior**

Remaining refundable Security Deposit and Pet Deposit balances after Final
Settlement are refunded through separate explicit Refund events so each Deposit
type remains traceable.

### PR-REFUND-008 — Currency and Value Preservation

**Business-rule traceability:** `BR-REFUND-008`

**Normative product behavior**

Every Refund is paid and recorded in USD, with its amount in cents equal to its
USD accounting value. Preserve source relationships and any original KHR amounts,
exchange rates, timestamps and calculation evidence for audit. Historical records
must not be rewritten. Partial verified returns of USD Refunds use exact USD cents,
not KHR conversion or proportional KHR rounding (DL-060).

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

### PR-REFUND-013 — Active-Lease Pet Deposit Refund

**Business-rule traceability:** `BR-REFUND-013`

**Normative product behavior**

When the approved pet permanently leaves during an active Lease, BR-DEP-012 may make
the remaining Pet Deposit refundable after all applicable pet-related obligations are
resolved. Its return uses an explicit Refund event linked to that Pet Deposit, the
recorded permanent pet departure, the obligation review, authorization, reason,
actor, and date/time. The Lease need not terminate, and full history is preserved.

## 8.19 Move-out Requirements

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

An ordinary missing reading delays the charge. A zero-history broken-Meter estimate
remains pending until the approved complete future-period basis exists. One or two
complete historical actual periods are usable immediately under BR-UTIL-027.

When final validated Readings or an approved estimate are recorded at move-out, the
system creates the final Utility Invoice off-cycle under BR-UTIL-021. When the tenant
never moved in, no Utility or Damage charge applies to the Customer; the Property bears
any Utility consumption.

### PR-MOVEOUT-006 — Inspection and Final Charges

**Business-rule traceability:** `BR-MOVEOUT-006`

**Normative product behavior**

Authorized inspection results and all valid Rent, Utility, fixed Service, Damage,
Miscellaneous, and Adjustment obligations that properly belong in Final
Settlement must be finalized from their approved sources.

This rule does not create a new charge, fee, or damage policy.

A Damage charge is created only from a recorded inspection damage finding, by an
authorized manager or staff member holding the Damage-charge capability, who enters the
amount with a mandatory reason and evidence reference (a note or document reference).
Each finding is billed at most once. The charge must match the finding's Customer,
Lease and Unit. Inspection alone creates no charge; there is no standard damage fee and
no automatic Pet Deposit forfeiture. Its Due Date follows BR-INV-018.

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

Amended by DL-068 and DL-069 (2026-10-03): the final month follows BR-RENT-024 and BR-RENT-030; the Security Deposit follows BR-DEP-026.

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

## 8.20 Final Settlement Requirements

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
termination and Move-out dates, outstanding Invoices, applicable outstanding
Late-payment Charges, Customer Credit, Security Deposit, Pet Deposit, final Utility
handling, Adjustments, and other valid linked financial events applicable to that Lease.

### PR-SETTLE-003 — Finalize Valid Outstanding Charges

**Business-rule traceability:** `BR-SETTLE-003`

**Normative product behavior**

Before applying Credit or Deposits, finalize every valid outstanding obligation
that properly belongs in the Settlement from its approved source. No new fee,
penalty, category, or obligation may be invented for Settlement.

Amended by DL-068 and DL-069 (2026-10-03): the Unit cleaning charge (BR-MOVEOUT-013) and outstanding Late-payment Charges are valid Settlement obligations.

### PR-SETTLE-004 — Apply Authorized Customer Credit First

**Business-rule traceability:** `BR-SETTLE-004`

**Normative product behavior**

After valid charges are finalized, apply authorized Customer Credit to applicable
Settlement obligations through separate auditable Credit-application events.

### PR-SETTLE-005 — Pet Deposit Identification and Application

**Business-rule traceability:** `BR-SETTLE-005`

**Normative product behavior**

Pet Deposit remains separately identifiable first for valid pet-caused property
damage or extraordinary/deep-cleaning obligations where applicable. Pet Deposit does
not cap the Customer's full liability for those valid costs.

After Customer Credit and explicitly selected Security Deposit applications, if a
valid Settlement balance remains unpaid and the Customer has not paid or will not
pay it, authorized management may explicitly select remaining Pet Deposit for that
valid Settlement balance. This later application is not limited to pet-related
obligations.

### PR-SETTLE-006 — Explicit Deposit Selection

**Business-rule traceability:** `BR-SETTLE-006`

**Normative product behavior**

After authorized Customer Credit, authorized management must explicitly select and
confirm every Security Deposit or Pet Deposit application to a valid Final Settlement
obligation. Security Deposit may be applied to valid remaining Settlement
obligations. Each application records its Deposit source, target obligation, amount,
actor, timestamp, reason, and authorization.

The system must not infer an additional FIFO ordering between Deposit types beyond
BR-SETTLE-005 and must not apply either Deposit automatically merely because a
Settlement balance exists.

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

The Customer must not receive refundable Deposit money while leaving a valid
Settlement balance unpaid when that available Deposit has been authorized for
application. Every such application must be recorded before the remaining refundable
balance is determined.

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
pending zero-history broken-Meter estimate keeps the affected charge and Settlement
unfinalized as necessary. One or two complete historical actual periods use
BR-UTIL-027 and do not wait for future data.

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

## 8.21 Money, Currency, Dates, and Timezone Requirements

### PR-MONEY-001 — Base and Accounting Currency

**Business-rule traceability:** `BR-MONEY-001`

**Normative product behavior**

USD is the Property's base and accounting currency.

All financial transactions are recorded in USD. Every Refund must be paid and
recorded in USD; KHR is only a Payment-conversion option. Original KHR and
conversion-rate facts remain audit evidence and are never rewritten (DL-060).

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
date range. Scheduled business actions and end-of-date processing use the Property's
authoritative `Asia/Phnom_Penh` timezone under BR-PROP-003.

## 8.22 Audit and History Requirements

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

Nonpayment Warning Notices and Serious Nonpayment Default conditions must preserve
their source Rent obligation, elapsed-day boundary, amount snapshot, issue or event
time, actor, communication or document linkage where recorded, cure history, and
subsequent management action.

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

### PR-AUDIT-006 — Invoice, Adjustment, and Late-payment Audit

**Business-rule traceability:** `BR-AUDIT-006`

**Normative product behavior**

Invoice creation, DRAFT correction, issuance, line sources, status changes,
Adjustments, Due Date source, and VOID events must preserve original and resulting
financial facts and all linkages.

Late-payment proposals and final decisions must preserve the source Invoice and its
Due Date, assessment balance, default and actual percentages, default and actual
amounts, management actor, reason, assessment timestamp, confirmation or waiver
timestamp, final confirmed, reduced, or waived outcome, and any resulting positive
Late-payment Charge obligation.

The obligation's original amount, remaining balance, Payment and Customer Credit
application history, satisfaction, correction, and reversal history must remain linked
to the decision, Customer, and source Invoice.

### PR-AUDIT-007 — Payment and Allocation Audit

**Business-rule traceability:** `BR-AUDIT-007`

**Normative product behavior**

Payment confirmation, payer intent, currency conversion, Allocation proposal and
posting, target obligation and line/category breakdown, Customer designation,
authorized confirmation, Allocation Reversal, Payment Reversal, Customer Credit
recognition and application, Receipt issuance and reprint, and Refund must remain
separately traceable.

### PR-AUDIT-008 — Deposit Audit

**Business-rule traceability:** `BR-AUDIT-008`

**Normative product behavior**

Every Deposit receipt, suggested amount, accepted required amount, authorized
Reservation-stage override, actor, timestamp, reason, balance, application,
forfeiture/disposition, governing event, and Refund must remain linked and
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

### PR-AUDIT-011 — Customer Account Ledger Reconciliation

**Business-rule traceability:** `BR-AUDIT-011`

**Normative product behavior**

The Customer Account Ledger must be reconstructable and reconcilable to its underlying
authoritative financial events. Every displayed charge, Payment, Credit, Refund,
Adjustment, Deposit event, Late-payment Charge, application, reversal, and balance must
retain or derive its source linkage. A derived or materialized Ledger representation
must not conceal disagreement with the authoritative records.

## 8.23 Authorization Requirements

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

Issuance of a formal Rent Nonpayment Warning Notice, recording and acting on a
Serious Nonpayment Default, and every resulting termination decision require their
applicable authorization. Elapsed time alone grants no termination authority.

### PR-AUTH-006 — Invoice and Late-payment Authorization

**Business-rule traceability:** `BR-AUTH-006`

**Normative product behavior**

Manual or exceptional Invoice issuance, issued-Invoice Adjustment, Due Date
recording for a non-recurring obligation, dependency correction, and VOID require
authorization and reason as applicable.

Confirming, reducing, or waiving a proposed late-payment charge is restricted to
authorized management. A positive approved charge requires the linked explicit
Late-payment Charge obligation in BR-INV-055 and BR-LATE-001; ordinary staff cannot
post, vary, correct, or reverse it arbitrarily.

### PR-AUTH-007 — Payment and Allocation Authorization

**Business-rule traceability:** `BR-AUTH-007`

**Normative product behavior**

Payment confirmation or correction, manual Allocation posting, Allocation
Reversal, and Payment Reversal require authorization and audit. A deterministic
proposal is not authorization to post. This includes confirmation of Customer-
designated targets, between-Invoice FIFO proposals, within-Invoice Rent-first proposals,
Invoice-line or obligation detail, and Late-payment Charge applications.

### PR-AUTH-008 — Credit, Refund, and Deposit Authorization

**Business-rule traceability:** `BR-AUTH-008`

**Normative product behavior**

Customer Credit recognition and application, Refund, and Deposit
forfeiture/disposition require authorization, source linkage, reason, and audit.
Customer authorization required by the Credit-versus-Refund decision must also be
preserved.

An override of the suggested Reservation Security Deposit amount requires authorized
management and preservation of the accepted amount, actor, timestamp, and reason.

### PR-AUTH-009 — Final Settlement Authorization

**Business-rule traceability:** `BR-AUTH-009`

**Normative product behavior**

Final Settlement application, finalization, closure, and post-closure correction
require authorization and complete audit history.

# 9. Traceability and Acceptance Coverage

Every current `BR-*` in `docs/002_BUSINESS_RULES.md` has exactly one same-suffix
Section 8 `PR-*`. Each detailed requirement reproduces the complete business meaning of
its governing rule. Capability, workflow, and quality mappings are supplemental and do
not replace the one-to-one mapping. Acceptance evidence shall cite both identifiers. No
source `BR-*` may be omitted, duplicated under another detailed requirement, or
reinterpreted. Later numbered specifications shall cite implemented or verified `PR-*`
identifiers.

End-to-end acceptance shall cover at least:

- Property timezone, historical integrity, Unit status, authoritative availability,
  Customer identity, and conflict rejection;
- Reservation statuses `ACTIVE`, `CANCELLED`, and `COMPLETED`; expiration and
  cancellation boundaries; zero-or-one resulting Lease; exactly one resulting Lease for
  `COMPLETED`; no resulting Lease for `CANCELLED`; and coordinated Unit release;
- the normal 20% suggested Reservation Security Deposit, authorized acceptance below or
  above the suggestion, activation only after receipt of the accepted amount, complete
  override audit, and the full required Security Deposit by move-in;
- Pet Deposit separation, pet departure during an active Lease, resolution of applicable
  pet-related obligations, explicit Refund of any remaining refundable Pet Deposit,
  uncapped Customer liability, no ordinary active-Lease Deposit payment use, and
  Final-Settlement-only Deposit application to Invoice obligations;
- Lease signing and non-overlapping contractual periods; coordinated move-in and
  Reservation completion; Occupancy; warning-letter rules for general violations; and
  the separate Rent-specific nonpayment workflow;
- Initial Rent and recurring-Service coverage for move-in days 1–20 and 21 or later,
  the proposed Initial Rent Invoice Due Date of the Lease Start Date plus five days, the recurring fifth-day Due Date, the
  27 July boundary example, generation resumption, and rejection of overlapping or
  duplicate billing periods;
- Trash Collection as the only currently approved recurring Service, separate categorized
  Service lines, and rejection of Internet or Monthly Cleaning charges unless a later
  Owner-approved configuration exists;
- actual Utility billing; broken-Meter estimation using the latest three complete
  historical periods, all available one or two complete historical periods, or one
  future complete actual period only when history is zero; move-out pending behavior;
  and no substitute Unit or arbitrary estimate;
- Utility Reading corrections before and after Invoice issuance, irrespective of payment
  status, with the original Reading, corrected Reading, original Invoice, and linked
  Adjustment chain reconstructable;
- the complete Invoice lifecycle, derived status regression after authorized reversals,
  immutability after issuance, duplicate prevention, and separation of a source Invoice
  from any Late-payment Charge;
- the Due Date as the final timely day, overdue beginning the next Property-local
  calendar day, the 10% default late-payment calculation, authorized reduction or
  waiver, the single final decision, and rejection of increase, replacement, recurrence,
  supplementation, or compounding;
- creation of one positive Late-payment Charge as a separate immediately payable
  non-Invoice obligation, separate balance contribution, authorized satisfaction,
  correction/reversal history, and rejection of a Due Date, Invoice category/line,
  Miscellaneous Charge treatment, source-Invoice modification, negative balance, or
  recursive late charge;
- remaining Rent derived from confirmed line/obligation attribution; the formal warning
  at 20 calendar days and Serious Nonpayment Default at 30 calendar days; preservation
  of later cure; and rejection of automatic Lease termination, Occupancy closure, Unit
  status change, Move-out, or Final Settlement;
- Payment as the authoritative money-received record; Payment record statuses; Receipt
  issuance and reprint for one existing Payment; unique and stable Receipt identity;
  traceable displayed amounts; and separation from Allocation, Refund, Credit, and
  Deposit receipt/application;
- authorized Payment Allocation proposal and confirmation; valid Customer designation;
  FIFO ordering between Invoices; Rent-first then recurring-Service proposal within a
  selected mixed Invoice; line/obligation detail; reversal history; and rejection of
  silent automatic posting, over-allocation, negative balances, or cross-Customer use;
- direct Allocation to a positive confirmed Late-payment Charge without changing the
  source Invoice and valid disposition of any remaining Payment value;
- Customer Credit creation, same-Customer Invoice or Late-payment Charge application,
  mixed-Invoice attribution, limits, reversals, Refunds, permanent source history, and
  separation from unallocated Payment, Deposits, and vendor Accounts Payable;
- one Customer Account Ledger view per Customer, chronological reconstruction of all
  applicable underlying financial events, obligation composition, current amount owed,
  available Customer Credit, separately identifiable Deposit liabilities, reconciliation,
  separate corrections/reversals, and rejection of independent editing or use as a
  General Ledger, Chart of Accounts, vendor Accounts Payable, or second source of truth;
- USD/KHR Payment confirmation and Receipt presentation, ABA Sell reference, the 1.005
  multiplier, upward whole-KHR System Exchange Rate and final payable rounding,
  confirmation-time rate preservation, permitted manual fallback, and authoritative
  Payment-channel conversion facts; and
- normal Lease end, continued Occupancy, authorized termination, move-out, final Utility
  handling, Final Settlement, Deposit disposition, Refund, historical correction,
  financial reconstruction, and rejection of invalid transitions, unauthorized actions,
  invented policies, or silent historical rewrites.

# 10. Open Owner Decisions

There are currently no unresolved Owner decisions blocking this Product Requirements
Specification. `OOD-BR-001` through `OOD-BR-008` are resolved in the approved
authoritative foundation and are incorporated into the detailed requirements above.

Later technical specifications may choose conforming implementation designs, but those
choices do not create an unresolved product-policy decision in this document.

# 11. Completion Criteria

This specification is ready for Owner review when status remains Owner Review; every
current `BR-*` has exactly one matching, unique, stable detailed `PR-*`; capabilities and
lifecycle workflows trace upstream; acceptance covers applicable valid, invalid,
boundary, calculation, authorization, and history behavior; terminology and policy
match upstream; no placeholder influenced the result; no unresolved Owner decision
remains; and no feature, policy, status, fee, penalty, right, role, permission, or
exception was invented.

# 12. Summary

The product shall provide a complete, auditable, single-Property residential tenancy
workflow from Unit readiness and Reservation through Lease, Occupancy, billing,
late-payment review, Payment, Receipt and confirmed Allocation, Customer Account Ledger,
move-out, and Final Settlement. Every significant event shall remain historically
accurate and reconstructable, and every action, calculation, transition, rejection, and
correction shall conform to its stable product requirement and traced business rule.
