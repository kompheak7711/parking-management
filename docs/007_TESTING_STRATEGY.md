# 007 — Testing Strategy

**Document Status:** Owner Review
**Authority:** Downstream of `001_DOMAIN_MODEL.md` through `006_UI_SPECIFICATION.md`
**Scope:** Verification strategy for domain, database, API, UI, security, deployment, migrations, and operations
**Requirement identifiers:** `TEST-*`

---

# 1. Purpose

This document defines how the Property Rental Management System will demonstrate
that it implements the authoritative specifications without corrupting financial
history, weakening data integrity, or bypassing authorization.

A passing test suite is necessary but not sufficient: database constraints,
transactional behavior, migration verification, audit reconstruction, and restore
tests are also release gates.

# 2. Testing Principles

## TEST-001 — Authority-driven Tests

Tests derive expected behavior from `BR-*` rules and `PR-*` product requirements.
A test must not normalize implementation behavior that contradicts an upstream
specification.

## TEST-002 — Traceability

Every material `BR-*` rule and `PR-*` requirement must map to one or more test
cases. Every test case records its test identifier and upstream references in its
name, metadata, or traceability manifest.

## TEST-003 — Determinism

Time, timezone, exchange-rate references, random identifiers, and external systems
must be controllable in tests. Financial expected values use exact integer/minor-
unit or rational/decimal arithmetic, never binary floating-point approximations.

## TEST-004 — Independent Layers

Unit, service/domain, database, API, integration, UI, migration, security, and
operational tests provide separate evidence. UI tests must not substitute for
database-constraint or service-layer tests.

## TEST-005 — Historical Assertions

Financial tests assert both current results and preserved source/history records.
A correction test fails if it obtains the right balance by erasing the original
event.

## TEST-006 — Negative Paths

Every significant command has success, validation failure, authorization failure,
conflict/concurrency, duplicate/idempotent replay, and persistence-failure coverage
where applicable.

## TEST-007 — Production Safety

Automated tests run only against disposable test data and isolated test databases.
Test tooling must refuse known production database identifiers or credentials.

# 3. Test Levels

## TEST-008 — Pure Unit Tests

Pure functions and value objects are tested without network or database access,
including:

- date/period boundaries;
- proration;
- weighted Utility daily-average calculations;
- Meter delta calculations;
- exchange-rate markup and upward rounding;
- Invoice and Payment derived balances;
- status derivation;
- validation of money, dates, and identifiers; and
- idempotency-key construction.

## TEST-009 — Domain and Service Tests

Domain/service tests exercise business actions and lifecycle guards using real
domain objects and controlled repositories. They verify coordinated changes and
audit-event intent before transport concerns.

## TEST-010 — Database Tests

Database tests use real PostgreSQL and verify constraints, transactions, indexes,
locking, triggers where used, append-only behavior, and SQL query semantics.
In-memory database substitutes are not accepted as the only database evidence.

## TEST-011 — API Tests

API tests exercise HTTP validation, schemas, authentication, capability checks,
object scope, errors, pagination, idempotency, optimistic concurrency, and
transactional outcomes.

## TEST-012 — Integration Tests

Integration tests run the backend, worker, and PostgreSQL together and cover
scheduled jobs, external-rate-source failure/fallback, retries, and audit chains.

## TEST-013 — UI Component Tests

UI component tests verify rendering, validation, accessibility, loading/empty/error
states, calculated/read-only distinctions, confirmations, and capability-sensitive
controls.

## TEST-014 — End-to-end Tests

Browser end-to-end tests cover representative complete workflows through the
actual API and PostgreSQL database. They assert durable outcomes rather than only
visible success messages.

## TEST-015 — Deployment and Recovery Tests

Container health, startup ordering, migration execution, backup integrity, restore,
worker restart/catch-up, and selected host-failure procedures are exercised in a
production-like environment.

# 4. Test Data and Fixtures

## TEST-016 — Synthetic Fixtures

Fixtures contain synthetic Customers, Units, Leases, and financial records. Real
Customer or production data is prohibited unless explicitly authorized and
sanitized.

## TEST-017 — Canonical Scenario Builders

Reusable builders create valid baseline Property, Unit, Customer, Reservation,
Lease, Meter, Rate, Invoice, Payment, Deposit, and authorization states. Each test
changes only facts relevant to the behavior under test.

## TEST-018 — Boundary Dataset

The suite includes:

- leap years and February boundaries;
- months with 28, 29, 30, and 31 days;
- Property-local midnight and UTC date differences;
- same-day and adjacent Lease boundaries;
- zero, one, two, three, and more than three Utility history periods;
- very small and large exact money amounts;
- exact and fractional KHR conversion results;
- partial/full/overpayment values; and
- concurrent actions against the same balance or period.

## TEST-019 — Clock Control

All time-dependent services accept a controlled clock. Tests must not depend on the
machine's current time or timezone.

## TEST-020 — External Source Fakes

Automatic exchange-rate source tests use deterministic fakes for success, timeout,
malformed response, stale response, and unavailability. No core test depends on a
live external service.

# 5. Property, Unit, and Customer Coverage

## TEST-021 — Property Timezone

Verify Property-local business dates are derived from the configured timezone and
remain stable across host/container timezone differences (`BR-PROP-001`–
`BR-PROP-003`).

## TEST-022 — Unit Identity and History

Verify Unit identity is stable, historical Leases/Reservations/Meters remain
linked, and state changes do not delete history.

## TEST-023 — Customer Identity

Verify one Customer can occupy multiple domain roles without fixed customer-type
mutation and that Customers cannot be silently merged or deleted when referenced.

# 6. Reservation Coverage

## TEST-024 — Reservation Creation

Verify Reservation activation requires valid Customer/Unit/dates and at least the
approved 20% partial Security Deposit. Verify no separate Reservation Deposit type
is created.

## TEST-025 — Reservation Exclusivity

Verify at most one ACTIVE Reservation holds a Unit and conflicting creation is
rejected transactionally.

## TEST-026 — Reservation Expiration

At the end of the full Expiration Date in Property-local time, verify
`ACTIVE → CANCELLED` with reason `RESERVATION_EXPIRED`, preserved history, and no
invented `EXPIRED` status. When Security Deposit was received, verify customer-caused
expiration posts the required explicit non-refundable disposition with governing
Reservation/cause, amount, authorization, and audit history.

## TEST-027 — Reservation Extension Notice

Verify only one extension, fewer-than-14-days eligibility, maximum 14 calendar
days, notice preservation, recalculated expiration scheduling, and rejection of a
second or excessive extension.

## TEST-028 — Reservation Move-in

Verify successful move-in changes `ACTIVE → MOVED_IN`, preserves Reservation
history, and coordinates the approved Lease/Occupancy/Deposit continuity.

## TEST-029 — Reservation Cancellation Deposit Outcomes

Verify approved Property-caused cancellation creates the required Security Deposit
Refund path before a Lease exists and does not require Final Settlement. Verify
customer-caused cancellation instead posts the required non-refundable Security
Deposit disposition, never a Refund, and preserves the original receipt. Reject any
free-form disposition without the approved governing cause.

# 7. Lease, Signer, Occupancy, and Move-in Coverage

## TEST-030 — Lease Lifecycle

Test every permitted Lease status transition and reject unsupported transitions.
A future non-overlapping successor may be DRAFTED/SIGNED before the current Lease
ends; overlapping signed contractual periods are rejected. Renewal preserves the
same-Unit predecessor link without inferring Deposit or financial transfer policy.

## TEST-031 — No Automatic Month-to-month

Verify End Date alone does not create a month-to-month Lease, new status, new Rent,
fee, or automatic termination.

## TEST-032 — Signers and Joint Responsibility

Verify one Primary Tenant, one or more Lease Signers as required, signer history,
and joint responsibility without conflating Signers with Occupants.

## TEST-033 — Occupants

Verify Occupancy records may represent non-signers, preserve actual move-in/out
dates, and do not independently grant signer responsibility.

## TEST-034 — Move-in Preconditions

Verify all approved move-in prerequisites, including SIGNED Lease and required
Deposit state, are enforced atomically. Failure leaves Reservation, Lease,
Occupancy, and Deposit state unchanged.

## TEST-035 — Deposit Continuity

Verify Reservation Security Deposit receipts continue into the resulting Lease
without reclassification, duplication, income recognition, or history loss.

# 8. Deposit and Pet Coverage

## TEST-036 — Deposit Separation

Verify Security and Pet Deposit balances are separate liabilities with independent
receipt/disposition histories.

## TEST-037 — Conditional Pet Deposit

Test the full matrix:

- pet not approved;
- pet approved but signed Lease does not require Deposit;
- signed Lease requires Deposit but pet not approved;
- both approved and required; and
- approved pet introduced after move-in.

Only the final applicable cases require Pet Deposit, at the approved timing.

## TEST-038 — Undisclosed Pet

Verify discovery records/informs the violation without automatic Lease termination,
new penalty, or unconditional Deposit requirement. Approved warning and
Lease-required Deposit rules remain applicable.

## TEST-039 — No Ordinary Deposit Allocation

Verify Deposit cannot pay ordinary Invoices during an active Lease and can be
applied only through Final Settlement disposition.

# 9. Rent and Service Billing Coverage

## TEST-040 — Monthly Rent Generation

Verify eligible signed Lease periods generate the approved Rent Invoice on the
25th for the next billing period, with exact Customer and applicable Lease.

## TEST-041 — Rent Duplicate Prevention

Concurrent and retried generation for the same Lease/period/source produces one
Rent obligation and one approved Invoice result.

## TEST-042 — Rent Proration

Verify approved first/last partial-period formulas across all month lengths,
rounding behavior, and preserved calculation inputs.

## TEST-043 — Rent Due Date

Verify recurring due-date behavior and any authoritative partial-period behavior
without inventing a due-date fallback. If a scenario remains an OPEN OWNER
DECISION, it must be excluded from assumed pass criteria and tracked explicitly.
Verify exact alternative signed-Lease Due Date terms are preserved without an
unsupported 1-28 day restriction.

## TEST-044 — Fixed Services

Verify only approved fixed recurring Internet and Trash Collection Service lines,
whose Lease Service applicability relation is effective for the period, using the
effective Service Rate, are included in the approved Rent Invoice workflow. No
one-time Service category or free-form applicability is inferred.

## TEST-045 — Service Rate History

Verify new rates affect only permitted future generation and issued Invoice lines
retain the selected historical rate and source.

# 10. Utility Coverage

## TEST-046 — Meter Installation and Replacement

Verify one active Meter assignment per Unit/Utility Type where required,
non-overlapping installation periods, replacement history, and Reading ownership by
the correct Meter.

## TEST-047 — Reading Validation

Verify chronology, non-negative values, duplicate-period prevention, replacement
boundaries, correction history, and authorized actor/audit data.

## TEST-048 — Consumption Calculation

Verify consumption is based on valid current/previous readings and cannot cross an
invalid Meter replacement boundary without the specified handling.

## TEST-049 — Utility Rate Selection

Verify the rate effective on Utility Invoice generation date applies to the entire
represented consumption period, even when a rate changes during that period.
Issued Utility Invoices do not recalculate after a later rate change. Utility Rate
creation is rejected unless evidenced notice occurred before the Effective Date in
Property-local time.

## TEST-050 — Broken-meter History Hierarchy

Verify:

- three or more complete prior actual periods use the three most recent complete
  periods before the affected period;
- one or two historical periods are not substituted and keep the charge pending
  until one complete future actual period for the same Unit and Utility Type exists;
- the basis daily average equals total actual consumption divided by total represented
  calendar days;
- separately rounded period averages are not averaged;
- another Unit and arbitrary estimates are prohibited; and
- zero history uses the same pending one-complete-future-period fallback.

## TEST-051 — Broken-meter Future-basis Pending Charge

Verify charges with fewer than three complete historical actual periods cannot be
finalized, issued, allocated, or included as an arbitrary receivable before the
future basis becomes calculable.

## TEST-052 — Utility Invoice Generation

Verify validated readings, consumption/rate evidence, Customer, optional Lease when
factually applicable, period, line source, and duplicate-prevention key.

# 11. Invoice and Adjustment Coverage

## TEST-053 — Invoice Ownership

Every Invoice test asserts exactly one explicit Customer and zero or one Lease.
Rent requires the applicable signed Lease; valid non-Lease Customer obligations do
not receive fabricated Lease associations.

## TEST-054 — Lease-associated Consistency

Verify Customer, Unit, obligation, period, and Lease context are mutually
consistent whenever Invoice Lease is present.

## TEST-055 — Invoice Categories

Verify only approved categories/sources are accepted. Optional Lease association
must not authorize arbitrary charges or categories. Damage and Miscellaneous lines
require a relational authorized-obligation source; pet-damage eligibility resolves
through the linked inspection finding rather than JSON or free text.

## TEST-056 — Invoice Lifecycle

Test `DRAFT`, `UNPAID`, `PARTIALLY_PAID`, `PAID`, and `VOID` transitions and guards.
Reject direct status assignment and destructive edits to issued Invoices.

## TEST-057 — Invoice Adjustment

Test debit and Credit Adjustments as append-only linked events with reason,
authorization, exact amount, source Invoice, recalculated balance/status, and
preserved original.

## TEST-058 — Exceptional Void

Verify voiding follows authorized preconditions, preserves the issued record, and
requires reversal of affected active financial applications where specified.

# 12. Payment, Allocation, Credit, Refund, and Reversal Coverage

## TEST-059 — Payment Receipt

Verify confirmed Payment stores Customer, received amount/currency, method,
immutable method code/name snapshots, timestamp, payer/reference evidence,
exchange-rate facts where applicable, and `RECEIVED` status without automatic
Allocation. API reads still return those snapshots after a configurable method is
renamed or retired.

## TEST-060 — Payment Allocation

Verify authorized staff manually post allocations, total active allocations never
exceed Payment availability or Invoice outstanding balance, and allocation is
transactional.

Verify the default proposal orders a normal Customer's applicable Invoices by
oldest Due Date, then issue/generation order and stable identifier for ties, but
does not post automatically. Verify Customer designation may select its eligible
Invoice and third-party Payment is restricted to recorded intent without changing
the financially responsible Customer.

## TEST-061 — Partial and Full Allocation

Verify derived Payment allocation condition and Invoice status after partial,
multiple, and full allocations. These derived conditions do not create unsupported
Payment statuses.

## TEST-062 — Concurrent Allocation

Two concurrent allocations against the same Payment/Invoice are serialized or one
conflicts; committed active amounts never exceed either limit.

## TEST-063 — Allocation Reversal

Verify reversal creates a linked event, restores availability/outstanding balance,
recomputes status, and preserves original Allocation.

## TEST-064 — Overpayment

Verify excess remains part of the RECEIVED Payment until payer authorization. It
does not automatically become Customer Credit or make an Invoice negative.

## TEST-065 — Customer Credit

Verify Credit recognition/application/reversal are distinct authorized events;
Credit cannot exceed available balance or silently become a Deposit/Payment.

## TEST-066 — Refund

Verify Refund requires an approved source and authorization, does not create an
unsupported right, preserves payout method/reference and history, and updates only
the source balance/event chain permitted by rules. An approved correction links an
append-only verified-return event with exact returned amount/currency and evidence,
cannot exceed the Refund, creates no collection right, and never mutates the original
Refund. Payment reversal remains blocked until required value is verified returned.

## TEST-067 — Payment Reversal

Verify complete reversal handling across active Allocations/Credit dispositions,
Deposit Receipts, linked event history, Payment `REVERSED` state, and recomputed
Invoice/Deposit/Credit balances and statuses. Reversal is rejected while a dependent
Deposit disposition, application, or unreturned Refund remains active. Verify a
Deposit Receipt reversal restores Payment availability and reduces Deposit received
and held balances without deleting either event.

## TEST-068 — Idempotent Financial Requests

Replay each supported financial command with the same idempotency key and verify no
duplicate event. Reusing a key with different input returns a conflict.

# 13. Currency and Exchange-rate Coverage

## TEST-069 — Money Representation

Verify money storage and API values use integer minor units or exact whole-KHR
units as specified, never binary floating point.

## TEST-070 — Automatic Rate Selection

At confirmed receipt, verify the authorized ABA-equivalent Sell reference source,
source timestamp, and reference value are preserved.

## TEST-071 — System Exchange Rate

For boundary tables, verify:

```text
System Exchange Rate = ceil(reference Sell rate × 1.005) KHR per USD
```

The upward whole-KHR rounding is mandatory, including when the unrounded result is
fractional by the smallest amount.

## TEST-072 — Final KHR Payable

Verify USD amount multiplied by the stored System Exchange Rate is rounded upward
again if the final payable contains fractional KHR. Test exact and fractional
results separately.

## TEST-073 — Manual Rate Fallback

Verify fallback is available only after source failure and with authorization;
server logic still applies markup and both upward-rounding rules and audits the
actor/source/reason.

## TEST-074 — Historical FX Evidence

Verify later rate changes do not alter confirmed Payment records and all required
USD/KHR/reference/markup/timestamp facts remain reconstructable.

Also verify Customer Credit remains USD-denominated while preserving KHR-origin
evidence; direct Refund of unrecognized KHR excess returns the corresponding
original KHR amount, while a later KHR Refund of USD Credit uses and preserves the
Refund-date exchange rate and both values.

# 14. Warning, Termination, Move-out, and Settlement Coverage

## TEST-075 — Warning Letters

Verify warning sequence, reason, delivery/effective dates, actor, Lease linkage,
and history. A warning cannot silently create a fee or automatic termination.

## TEST-076 — Termination Notice

Verify only approved grounds/actions, notice evidence, authorization, and status
transitions. End Date alone does not invent termination behavior.

## TEST-077 — Early Termination

Verify early termination uses only obligations and rights in approved signed-Lease
terms and business rules. Unsupported penalties, Refunds, or forfeitures are
rejected.

For processed voluntary early termination, assert full Rent for the move-out
calendar month, applicable Utility/fixed Service/other approved obligations,
explicit Security Deposit non-refundable disposition, no automatic Pet Deposit
forfeiture, no standard early-termination fee, no future-month Rent after
termination, and at least three warning letters plus signed-Lease authority for a
violation termination.

## TEST-078 — Move-out

Verify actual occupancy end, readings, inspection evidence, and final-charge inputs
are recorded without falsely marking financial closure complete.

## TEST-079 — Final Settlement Cardinality

Every terminated Lease completes exactly one Final Settlement. Concurrent creation
attempts cannot create two.

## TEST-080 — Final Settlement Calculation

Verify approved obligations, Adjustments, active applications, separate Deposit
dispositions, Credits, Refunds, and resulting receivable/refundable values reconcile
exactly and remain auditable.

Assert the approved order: finalize valid charges; apply authorized Customer
Credit; apply Pet Deposit only to authorized pet-related damage; apply Security
Deposit to remaining authorized obligations in oldest-Due order where applicable;
record remaining Customer balance; and explicitly Refund remaining refundable
Deposit balances. The immutable closing balance is the nonnegative post-Refund
Customer receivable, never a negative proxy for an omitted Refund. Every event
remains separately traceable. The close response and later reads expose that snapshot
separately from any corrected current position.

## TEST-081 — Settlement Corrections

Verify corrections preserve the original Settlement/event chain and do not
retroactively rewrite issued financial history. A closed Settlement stays closed;
its correction row links an existing approved typed event carrying the effect.
Exercise Deposit Application reversal through API and UI and verify restored Invoice
and Deposit balances.

# 15. Audit and Authorization Coverage

## TEST-082 — Audit Minimum Fields

For every material action, assert actor/system identity, timestamp, Property scope,
action, target, prior/resulting state or source link, mandatory reason, and
correlation identifier.

## TEST-083 — Append-only Audit

Verify ordinary application and staff database identities cannot update or delete
audit events. Corrections create new linked events.

## TEST-084 — Capability Matrix

Generate authorization tests from the API capability catalog: allowed capability,
missing capability, wrong Property/object scope, disabled account, and stale/revoked
session.

## TEST-085 — No UI-only Authorization

Direct API calls remain forbidden when a control is hidden or disabled in the UI.

## TEST-086 — Financial Capability Separation

Verify receipt, allocation, Credit, Refund, Reversal, Adjustment, void, Settlement,
and permission-administration capabilities can be granted and denied independently.

# 16. API Contract Coverage

## TEST-087 — Schema Validation

For each endpoint, test required/optional fields, nullability, enums, ranges,
formats, unknown fields, identifiers, and cross-resource consistency.

## TEST-088 — Error Contract

Verify consistent validation, authentication, authorization, not-found, conflict,
precondition, idempotency, and internal-error schemas without sensitive details.

## TEST-089 — Pagination and Filtering

Verify deterministic ordering, stable cursor/page behavior, bounded limits, allowed
filters, no duplicates/skips under normal use, and Property scope.

## TEST-090 — Concurrency Contract

Verify stale version/precondition tokens produce conflicts and never overwrite
newer source data or financial state.

# 17. UI and Accessibility Coverage

## TEST-091 — UI State Coverage

Every major view has tests for loading, empty, populated, validation error,
forbidden, conflict, retryable error, and successful action states.

## TEST-092 — Financial Distinctions

UI tests verify source inputs, calculated values, current state, historical events,
and auditable actions are visually and semantically distinct. Issued records are
not rendered as ordinary editable forms.

## TEST-093 — Confirmation

Financially significant actions display action-specific consequences and require
the specified reason/confirmation. Generic confirmation text is insufficient for
void, Refund, Reversal, Deposit disposition, or Settlement closure.

## TEST-094 — Accessibility

Keyboard navigation, focus order, labels, accessible names, error association,
status announcements, table semantics, contrast, and confirmation dialogs meet the
project's accessibility requirements.

## TEST-095 — Capability-sensitive UI

Controls are hidden or disabled consistently with user capability while the server
remains authoritative. The UI explains unavailable actions without exposing
sensitive authorization details.

# 18. Scheduled-job and Time-boundary Coverage

## TEST-096 — Singleton Job Execution

Run two workers concurrently for the same Property/business period and verify one
logical execution and no duplicate financial event.

## TEST-097 — Retry After Failure

Inject failure before transaction, during transaction, after commit before response,
and during audit writing. Verify rollback or idempotent recovery with visible job
outcome.

## TEST-098 — Property-local Midnight

Test each scheduled rule immediately before, at, and after Property-local midnight,
including when UTC is a different date.

## TEST-099 — Worker Downtime Catch-up

After simulated downtime, verify approved missed jobs catch up exactly once and do
not reinterpret the current date as the original business date.

# 19. Migration Testing

## TEST-100 — Migration Upgrade Paths

Apply all migrations from each supported prior release to current against
representative data. Verify schema version and authoritative constraints.

## TEST-101 — Migration Financial Integrity

Before and after migration, compare counts, sums, source links, statuses, selected
rates, audit actors, and reconstructable balances. A migration may change storage
shape but not business meaning silently.

## TEST-102 — Migration Failure

Inject failures and verify controlled rollback where transactional or a documented
recoverable state where not. Never reset/recreate a database automatically.

## TEST-103 — Constraint Introduction

Backfill and validation tests prove new constraints can be applied without silently
dropping invalid historical data.

## TEST-104 — Migration Performance/Locks

Measure expected lock duration and query impact on representative volume before
production deployment.

# 20. Backup, Restore, and Operational Testing

## TEST-105 — Backup Verification

Verify automated backup success metadata, encryption, integrity/checksum, retention
behavior, failure alerting, and absence of secrets in logs.

## TEST-106 — Restore Drill

Restore into an isolated environment and verify Customers, Leases, all financial
events, rates, audit history, users/capabilities, migrations, and scheduled-job
state.

## TEST-107 — Service Recovery

Verify API/worker restart, database unavailability behavior, low-disk handling,
external-rate-source failure, and safe recovery without false write success.

# 21. Security Testing

## TEST-108 — Authentication Security

Test guessing controls, account enumeration resistance, password hashing
configuration, session expiration/revocation, secure cookies/tokens, and credential
reset audit.

## TEST-109 — Input and Browser Security

Test SQL/command injection, XSS, CSRF where relevant, path traversal, unsafe
redirects, oversized inputs, and malformed content.

## TEST-110 — Sensitive-data Leakage

Scan errors, logs, browser storage, frontend bundles, exports, and metrics for
secrets, tokens, credentials, and unnecessary Customer/financial payloads.

## TEST-111 — Database Privileges

Verify runtime, migration, backup, and administration identities have distinct
least-privilege grants and ordinary runtime cannot alter schema or audit history.

# 22. Regression and Release Gates

## TEST-112 — Defect Regression

Every confirmed defect receives a focused regression test at the lowest useful
layer and, when risk warrants, a higher-level workflow test.

## TEST-113 — Required CI Gates

A release candidate must pass:

- formatting and linting;
- frontend and backend type checking;
- unit/domain tests;
- PostgreSQL database tests;
- API and integration tests;
- selected UI/end-to-end tests;
- migration tests;
- production builds; and
- security/dependency checks defined by release policy.

## TEST-114 — No Placeholder Verification

Commands that only print `Not implemented yet.` do not satisfy a quality gate even
when they exit successfully.

## TEST-115 — Flaky Test Handling

A flaky test is a defect. Quarantine requires an owner, documented risk, tracking
reference, and deadline; retries must not conceal deterministic business failures.

## TEST-116 — Coverage Use

Code coverage is monitored to find untested paths but is not a substitute for
`BR-*`/`PR-*` traceability and boundary-case evidence.

# 23. Traceability Mechanism

## TEST-117 — Traceability Manifest

Maintain a machine-readable or deterministically generated manifest containing:

| Field | Meaning |
|---|---|
| Test ID | Stable `TEST-*` identifier or executable test identifier |
| Upstream IDs | One or more `BR-*`, `PR-*`, `DB-*`, `API-*`, `UI-*`, or `SEC-*` identifiers |
| Test level | Unit, domain, DB, API, integration, UI, E2E, migration, security, operational |
| Test path | Executable test location |
| Status | Implemented, blocked by approved open decision, or planned |
| Notes | Boundary/scenario description without changing policy |

## TEST-118 — Rule Coverage Audit

CI must fail when a material new `BR-*` or `PR-*` identifier has no test mapping,
unless it is explicitly marked non-executable documentation with review rationale.

## TEST-119 — Bidirectional Review

Reviewers must be able to navigate from requirement to tests and from a failed test
to its controlling requirement. Duplicate mappings are permitted; orphan tests
that assert undocumented policy are not.

# 24. Priority Test Suites

## TEST-120 — Critical Financial Suite

A fast mandatory suite covers Invoice ownership, duplicate billing, money
representation, Payment/Allocation limits, Credit/Refund/Reversal chains, Deposit
separation/application, Final Settlement, exchange-rate markup/rounding, and audit
preservation.

## TEST-121 — Critical Lifecycle Suite

A mandatory suite covers Reservation expiration/extension, Lease non-overlap,
move-in, renewal, warnings/termination, move-out, and exactly-one Final Settlement.

## TEST-122 — Critical Utility Suite

A mandatory suite covers Meter replacement, Reading validation, generation-date
rate selection, weighted broken-Meter history hierarchy, pending future-basis
charge, and duplicate Utility billing.

# 25. OPEN OWNER DECISION

## OOD-TEST-001 — Supported Browser Matrix

**Question:** Which browser versions and managed devices must be certified?

**Current treatment:** Automated UI tests target current standards-compliant
Chromium plus cross-browser coverage selected during implementation. No business
policy depends on this choice.

**Blocking:** No.

## OOD-TEST-002 — Production Recovery Objectives

**Question:** What RPO/RTO values and restore-drill frequency must release testing
certify?

**Current treatment:** Restore tests are mandatory; exact objectives remain
configurable and align with `009_DEPLOYMENT_ARCHITECTURE.md`.

**Blocking:** No.

## OOD-TEST-003 — First Partial-month Rent Due Date

**Question:** Which expected Due Date should tests assert when the first
partial-month Rent Invoice is issued after the billed month's 5th and the signed
Lease specifies no alternative?

**Current treatment:** Tests verify that no fallback is silently inferred and mark
the exact expected-value case blocked by `OOD-BR-001`.

**Blocking:** No for the broader suite; blocks only this expected-value scenario.

# 26. Completion Criteria

This Testing Strategy is complete for Owner Review when:

- every material business lifecycle and financial invariant has explicit coverage;
- database, API, UI, integration, migration, security, and operational levels are
  distinguished;
- timezone, concurrency, idempotency, audit history, FX rounding, and broken-Meter
  boundaries have dedicated tests;
- traceability is bidirectional and enforceable;
- placeholder commands are not reported as substantive tests; and
- unresolved browser, recovery, and Due Date choices are recorded without
  inventing policy.
