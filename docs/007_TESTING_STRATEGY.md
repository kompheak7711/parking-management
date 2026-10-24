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

Verify Reservation activation requires valid Customer/Unit/dates and receipt of the
explicitly accepted initial Security Deposit amount. Verify the normal suggested
amount is calculated as 20% of agreed monthly Rent, while an authorized accepted
variance may be below or above that suggestion with preserved authorization,
reason, and calculation trace.

Verify no separate Reservation Deposit type is created and the accepted initial
amount does not alter the full required Security Deposit liability.

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

Verify signing the resulting Lease changes the Reservation `ACTIVE → COMPLETED` and
the Unit to `OCCUPIED` in one transition with Security Deposit continuity, and that a
COMPLETED Reservation cannot expire. Verify a later physical move-in only begins the
Occupancy and changes neither status. Historical Reservations completed at move-in
remain valid. Verify `MOVED_IN` and `EXPIRED` are
rejected as Reservation statuses.

Covered for migration `20261005_69` by
`backend/tests/test_lease_signing_reservation_migration.py` (Reservation and walk-in
signing, rejected signings, move-in without a payment gate, the legacy move-in path and a
byte-identical upgrade of earlier Leases, Reservations, deposits, Invoices and Units).

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

Verify all approved move-in prerequisites, including a SIGNED Lease and a valid
move-in date, are enforced atomically, and that an unpaid Security Deposit, Pet Deposit
or Initial Rent never blocks move-in. Verify a walk-in Lease signed without a
Reservation makes the Unit OCCUPIED. Failure leaves Reservation, Lease,
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

Verify Security Deposit and Pet Deposit cannot pay ordinary Invoices during an active
Lease. Deposit application to Invoice obligations is permitted only through Final
Settlement after Lease termination.

Verify the active-Lease Pet Deposit Refund exception is a Refund workflow rather than
an Invoice application and does not permit Security Deposit Refund while the Lease
remains SIGNED.

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

Verify the proposed Initial Rent Invoice Due Date is the Lease Start Date plus five
calendar days, including cross-month results:

- issued 1 July or 10 July for a 10 July Lease Start Date → 15 July; and
- a 27 July Lease Start Date → 1 August.

Verify an authorized override requires a reason and records the actor and timestamp,
the Due Date is fixed after issuance, and coverage uses the Lease Start Date (a 20
September start with a 25 September arrival → $110.00 for $300 Rent). Verify historical
seven-day Invoices are unchanged.

Verify recurring Rent Invoices are due on the fifth day of the billed calendar month.
The Lease must not override the application's recurring Rent Due Date. No fallback,
alternative signed-Lease recurring Due Date, or arbitrary 1–28-day rule is permitted.

## TEST-044 — Fixed Services

Verify Trash Collection can be billed only when its configured Service identity,
Owner-approved Service approval period, applicable Lease Service term, and effective
Service Rate all authorize the represented period.

Verify Internet and Monthly Cleaning are not currently billable because they have no
approved active period. A future Service must not become billable merely because a
configured identity or rate exists. No one-time Service category or free-form
applicability is inferred.

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
- exactly one or two complete historical actual periods use all available one or two
  periods for the same Unit and Utility Type as the weighted historical basis;
- zero complete historical actual periods keep the estimate/charge pending until one
  complete future actual period for the same Unit and Utility Type exists;
- the basis daily average equals total actual consumption divided by total represented
  calendar days;
- separately rounded period averages are not averaged;
- another/comparable Unit and arbitrary estimates are prohibited; and
- available one/two-period history must not be discarded.

## TEST-051 — Broken-meter Future-basis Pending Charge

Verify only the zero-history case remains pending for a future complete actual basis.
Until that future basis exists, the affected estimate/charge cannot be finalized,
issued, allocated, or included as an arbitrary receivable.

Verify one-history and two-history cases do not enter this pending state when their
available complete historical periods provide the approved basis.

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

Verify debit rejection on a fully paid line, including a mixed Invoice whose Rent line is
paid and whose Service line is unpaid. Verify debit re-allowed after a Payment reversal.
Verify credit on any issued line and excess credit becoming Customer Credit. Verify an
Adjustment concurrent with a final late-payment decision is strictly ordered by the
Invoice lock.

The debit rules are covered by `backend/tests/test_debit_adjustment_line_block_migration.py`
(Payment and Customer Credit paid lines, mixed Rent and Service Invoice, reversal reopening
the line, direct storage rejection, and debit before, after and concurrent with the final
late-payment decision).
Credit excess is covered by `backend/tests/test_credit_adjustment_excess_migration.py`
(within and beyond the unpaid value, fully paid line, newest-first release, multi-line
re-post, Credit application release, third-party payer, VOID and over-obligation
rejection, and proof that late-fee, Rent nonpayment, Payment, receipt and original
allocation history are unchanged).

## TEST-058 — Exceptional Void

Verify voiding follows authorized preconditions, preserves the issued record, and
requires reversal of affected active financial applications where specified.

## TEST-123 — Late-payment Decision and Charge

Verify the complete BR/PR-INV-051..055 and API-091 lifecycle:

- review is available only for an applicable Invoice with remaining overdue balance
  after its Due Date;
- default rate is exactly 10%;
- default amount is calculated from the remaining overdue balance at assessment;
- exactly one final decision may be recorded;
- permitted outcomes are only `CONFIRMED_DEFAULT`, `REDUCED`, and `WAIVED`;
- `CONFIRMED_DEFAULT` requires the calculated default amount;
- `WAIVED` requires zero;
- `REDUCED` requires a positive exact approved USD amount below default;
- management cannot increase the Charge above the default;
- a reduced approval such as $15 on a $310 overdue balance is accepted without
  forcing whole-basis-point percentage precision;
- a positive decision creates exactly one separate Late-payment Charge;
- a waiver creates no positive Charge;
- the Charge does not alter source Invoice principal, lines, balance, or status;
- the Charge cannot itself generate another Late-payment Charge; and
- final-decision history is immutable.

Verify concurrent/replayed final-decision commands cannot create duplicate decisions
or Charges.

Verify an Adjustment recorded before the final decision is in its balance, and that a
debit Adjustment recorded after the final decision is allowed but does not change it.

Amended by DL-076 (owner, 2026-10-20): tests cover the automatic 00:00 charge (eligibility, one per Invoice, Settings rate, rounding, no charge on Initial Rent, no-Lease Invoices or charges) instead of a manual decision.

## TEST-124 — Late-payment Charge Corrections and Applications

Verify DB-INV-009/API-091 authorized Charge reduction/reversal behavior preserves the
original Charge and final decision, enforces remaining-obligation bounds, and creates
append-only correction history.

Verify Payment Allocation and Customer Credit may target an eligible separate
Late-payment Charge. Such application reduces only that Charge and never its source
Invoice. Test direct designation, availability limits, over-application rejection,
reversal, concurrency, and historical reconstruction.

Amended by DL-076 (owner, 2026-10-20): tests cover reductions and waivers after a complaint (three fixed reasons, "What happened", only down) and the paid part going to Customer Credit under BR-CREDIT-014.

# 12. Payment, Allocation, Credit, Refund, and Reversal Coverage

## TEST-059 — Payment Confirmation

Verify confirmed Payment stores Customer, received amount/currency, method,
immutable method code/name snapshots, timestamp, payer/reference evidence,
exchange-rate facts where applicable, and `RECEIVED` status without automatic
Allocation. API reads still return those snapshots after a configurable method is
renamed or retired.

## TEST-060 — Payment Allocation

Verify authorized staff manually post allocations to an eligible Invoice or separate
Late-payment Charge, total active allocations never exceed Payment availability or
the selected target's outstanding balance, and allocation is transactional.

Verify the default proposal orders a normal Customer's applicable Invoices by oldest
Due Date, then issue/generation order and stable identifier for ties, but does not
post automatically. Verify Customer designation may select its eligible Invoice or
Late-payment Charge and third-party Payment is restricted to recorded intent without
changing the financially responsible Customer.

A Late-payment Charge allocation reduces only the Charge and never the source Invoice.

## TEST-061 — Partial and Full Allocation

Verify derived Payment allocation condition and Invoice status after partial,
multiple, and full Invoice allocations. Verify partial/full Late-payment Charge
applications independently derive Charge remaining balance without changing the source
Invoice status. These derived conditions do not create unsupported Payment statuses.

## TEST-062 — Concurrent Allocation

Two concurrent allocations against the same Payment and target obligation are
serialized or one conflicts; committed active amounts never exceed Payment
availability or the Invoice/Late-payment Charge target balance.

## TEST-063 — Allocation Reversal

Verify reversal creates a linked event, restores availability/outstanding balance,
recomputes status, and preserves original Allocation.

## TEST-064 — Overpayment

Verify excess remains part of the RECEIVED Payment until payer authorization. It
does not automatically become Customer Credit or make an Invoice negative.

## TEST-065 — Customer Credit

Verify Credit recognition/application/reversal are distinct authorized events;
Credit cannot exceed available balance or silently become a Deposit/Payment.

Verify an application may target an eligible Invoice or separate Late-payment Charge.
A Charge application reduces only that Charge and never the source Invoice. Test
designation, target-balance bounds, reversal, and concurrent application safety.

## TEST-066 — Refund

Verify Refund requires an approved authoritative source and authorization, does not
create an unsupported right, preserves source identity, exact amount/currency,
applicable exchange facts, processing facts, authorization, and correction history,
and updates only the source balance/event chain permitted by rules.

Do not require or invent a generic Refund delivery method, pending/failed status, or
other business state absent from the authoritative model.

An approved correction links an append-only verified-return event with exact returned
amount/currency and evidence, cannot exceed the Refund, creates no collection right,
and never mutates the original Refund. Payment reversal remains blocked until required
value is verified returned.

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

## TEST-125 — Receipt and Reprint

Verify a confirmed Payment normally creates exactly one immutable business Receipt in
the same transaction. Assert stable unique Receipt Number, correct Payment/Customer
linkage, issuance facts, and preserved identity snapshot where applicable.

Verify a Receipt reprint:

- uses the same Receipt UUID and Receipt Number;
- creates one append-only reprint event with actor, timestamp, reason, and optional
  delivery reference;
- does not create another Payment;
- does not create another Receipt identity;
- does not create another money-received event; and
- remains available as historical evidence after Payment reversal.

## TEST-126 — Active-Lease Pet Deposit Refund

For a SIGNED Lease, verify Security Deposit cannot be refunded before Final Settlement.

For the approved Pet Deposit exception, verify:

- the approved pet is recorded as permanently departed;
- departure alone does not terminate the Lease or authorize Refund;
- the qualifying review matches Pet approval, Lease, Customer, and Pet Deposit;
- applicable pet-related obligations must be resolved;
- remaining refundable Pet Deposit is server-recomputed;
- a qualifying DB-LEASE-011/API-094 review is required;
- the resulting Refund uses the Pet Deposit and review as authoritative sources;
- Final Settlement is neither required nor created;
- the Deposit is not applied to an Invoice;
- the Lease remains SIGNED; and
- Customer liability is not capped by the refunded Pet Deposit.

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
evidence. Under DL-060 all Refunds, including eligible KHR-origin Payment excess and
Credit, are paid and recorded in USD. Preserve original Payment/FX records byte-for-
byte; do not compute KHR remainder allocation or a Refund-date rate. Reject KHR
Refunds. Test one-cent and repeated partial USD returns, exact opposite reversals,
bounded net/source balances and unchanged KHR provenance. Existing Payment-conversion
rounding and authoritative channel-value rules remain unchanged.

# 14. Warning, Termination, Move-out, and Settlement Coverage

## TEST-075 — Lease Violation Warning Letters

Verify DB-LEASE-005/API-067 Lease-violation warning sequence, violation/warning dates,
description, governing Lease provision, communication evidence, actor, Lease linkage,
and history. A Lease-violation warning cannot silently create a Rent-nonpayment
milestone, fee, or automatic termination.

## TEST-127 — Rent Nonpayment Cases and Events

Verify API-095 opens a case only from an applicable issued, non-VOID Rent Invoice line
for the same Lease and financially responsible Customer. Preserve Invoice, Rent-line,
Lease, Customer, and Due Date snapshots. A mixed Invoice's total outstanding balance
must not substitute for remaining Rent.

Verify only:

- `TWENTY_DAY_WARNING`;
- `THIRTY_DAY_SERIOUS_DEFAULT`;
- `CURE`; and
- `AUTHORIZED_FOLLOW_UP`

are accepted event kinds.

Verify the 20-day warning requires positive remaining Rent at the approved milestone
and required Notice/document reference. Verify the 30-day Serious Nonpayment Default
requires positive remaining Rent at its approved milestone. Posting recomputes
remaining Rent from authoritative applications and corrections.

Verify `CURE` preserves prior warning/default history and records zero remaining Rent
when applicable. Verify no Rent-nonpayment event automatically terminates the Lease,
closes Occupancy, moves out the Customer, changes Unit status, creates Final Settlement,
or creates a new fee/penalty.

Verify day one on the 1st of the billed month for recurring Rent. Verify a case cannot be
opened for an Initial Rent Invoice, the unpaid-Initial management alert appears the day
after its Due Date, and no late-payment charge is proposed for it. Verify day 30 in February is 2 March in a normal
year and 1 March in a leap year. Verify immediate alerts for late-opened cases, and that
cases recorded earlier are unchanged.

Covered by `backend/tests/test_rent_nonpayment_recurring_only_migration.py`, including a
byte-identical comparison of cases, events, late-payment decisions and Charges across the
upgrade and the limits on a case opened earlier on Initial Rent.

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

Verify an unpaid-Initial termination: never moved in (Invoice VOIDed with reason when
nothing was paid or its unpaid remainder credited when partly paid, Unit returned to VACANT;
since V1-056 slice 6 the Security Deposit stays held until a forfeiture draft is confirmed,
covered by `backend/tests/test_lease_deposit_forfeiture_migration.py`) and moved in (Invoice kept, prorated credit Adjustment for the remaining days,
move-out applies). Covered for migration `20261005_70` by
`backend/tests/test_unpaid_initial_termination_migration.py`, including the ground check at
termination time and CLEANING with a reason and the Unit management capability. Verify the final Utility Invoice is created off-cycle from the final
Readings without duplicating a monthly-run period, the pre-Lease baseline Reading is the
starting boundary, and a Damage charge requires the capability, reason and evidence, is
billed once and matches its finding.
Verify the Utility baseline Reading (migration `20261006_71`, covered by
`backend/tests/test_utility_baseline.py` and `backend/tests/test_utility_baseline_migration.py`): it
may be dated on or before the Lease Start Date and never after it, needs a validated Reading
for every applicable Meter on that date, is rejected for an unsigned, occupied or unknown Lease,
supersedes only when dated later and only once, never splits a finalized period, and moves the
Customer's responsibility boundary for that Lease only. Verify the first partial period after a
baseline is billed once by a run with its exact dates, a Lease with no Occupancy yet is skipped
as NOT_MOVED_IN without failing the run, a period no Lease covers is skipped as
PROPERTY_BORNE_CONSUMPTION, and a Lease without a baseline keeps its exact earlier results.
Verify the final Utility Invoice and the catch-up Invoice (migration `20261007_72`, covered by
`backend/tests/test_final_utility_invoice.py` and `backend/tests/test_final_utility_invoice_migration.py`):
a Lease leaving in its first month is billed once from the baseline to the final Readings; an earlier
finalized unbilled period is included; the Invoice waits for every Meter and a superseded event cannot
be billed; a NOT_MOVED_IN period is billed once by the catch-up command and the next monthly run still
bills the next month; a Lease that never moved in stays unbilled; the Due Date is the issue date plus
the Property's configured days or an authorized override with reason; and replay, key reuse,
authorization and append-only history hold.
Verify slice 7b (migration `20261008_73`, `backend/tests/test_utility_unbilled_periods_migration.py`): a partial-period run and a
monthly run with overlapping dates coexist in either order and bill each period once; Rent runs keep the
no-overlap rule; a late period is listed and billed only by the explicit catch-up command and never twice
(unique line per period, no-overlap rule per Meter); a Meter replaced after the baseline starts at its
installation Reading; and the final Invoice never bills a period the monthly run already billed.

## TEST-079 — Final Settlement Cardinality

Every terminated Lease completes exactly one Final Settlement. Concurrent creation
attempts cannot create two.

## TEST-080 — Final Settlement Calculation

Verify approved obligations, Adjustments, active applications, separate Deposit
dispositions, Credits, Refunds, and resulting receivable/refundable values reconcile
exactly and remain auditable.

Assert the approved order: finalize valid charges; apply authorized Customer Credit
first; apply Pet Deposit to authorized pet-related Invoice lines under
`PET_RELATED_FIRST`; permit explicitly authorized Security Deposit applications under
`SECURITY_EXPLICIT`; then permit any remaining Pet Deposit to be explicitly applied to
any valid remaining Settlement Invoice line under `PET_REMAINDER_EXPLICIT`; record the
remaining Customer balance; and explicitly Refund remaining refundable Deposit
balances.

Verify every Deposit target and amount is explicitly authorized and that Payment FIFO,
an inferred Deposit-type FIFO, and oldest-Due ordering are not reused for Deposit
applications.

The immutable closing balance is the nonnegative post-Refund Customer receivable,
never a negative proxy for an omitted Refund. Every event remains separately
traceable. The close response and later reads expose that snapshot separately from any
corrected current position.

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

Verify Payment receipt/confirmation, Receipt reprint, Allocation, Credit, Refund,
Reversal, Adjustment, void, Late-payment final decision, Late-payment Charge
correction, active-Lease Pet Deposit refund review, Rent-nonpayment milestone/follow-up,
Settlement, and permission-administration capabilities can be granted and denied
independently where exposed as distinct capabilities by the approved API/security
design.

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

Financially significant actions display action-specific consequences and require the
specified reason/confirmation. Generic confirmation text is insufficient for void,
Refund, Reversal, Deposit disposition/application, Settlement closure, final
Late-payment Decision, Late-payment Charge correction/reversal, active-Lease Pet
Deposit qualifying review/Refund, Receipt reprint where audited confirmation is
required, or Rent-nonpayment milestone/follow-up posting.

## TEST-094 — Accessibility

Keyboard navigation, focus order, labels, accessible names, error association,
status announcements, table semantics, contrast, and confirmation dialogs meet the
project's accessibility requirements.

Amended by DL-074 (owner, 2026-10-04 and 2026-10-20): the requirement is WCAG 2.2 level AA, with touch targets at least 44px tall.

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

Test successful local username/password authentication, incorrect credentials, unique
username enforcement, shared-account prohibition, guessing/rate-limit controls, account
enumeration resistance, disabled accounts, secure salted adaptive password hashing,
secure cookies/tokens, and credential-reset audit.

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

Amended by DL-071 (owner, 2026-10-05): the V1-060 release candidate also has no open security warning (the `braces` advisory of DL-067 included), passes a speed test with 300 Units and 10 years of made-up history, and is not done until the Owner or the Manager has run one scripted test session with made-up data (reserve, sign, move in, bill, pay, move out, settle) and the owner says it passed.

## TEST-114 — No Placeholder Verification

Commands that only print `Not implemented yet.` do not satisfy a quality gate even
when they exit successfully.

## TEST-115 — Flaky Test Handling

A flaky test is a defect. Quarantine requires an owner, documented risk, tracking
reference, and deadline; retries must not conceal deterministic business failures.

Amended by DL-071 (owner, 2026-10-05): the V1-060 release candidate has no flaky tests. A flaky test is fixed, not run again until it passes; this includes TEST-FE-087, TEST-FE-128, TEST-FE-488 and the DL-067 `LockNotAvailable` full-run failure.

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
representation, Payment/Allocation limits, separate Late-payment Decision/Charge
calculation and reduced-amount precision, Charge applications/corrections,
Receipt/reprint history, Credit/Refund/Reversal chains, Deposit separation/application,
active-Lease Pet Deposit Refund, Final Settlement, exchange-rate markup/rounding, and
audit preservation.

## TEST-121 — Critical Lifecycle Suite

A mandatory suite covers Reservation expiration/extension/completion, Lease
non-overlap, move-in, renewal, Lease-violation warnings, Rent-nonpayment 20-day and
30-day milestones/cure history, explicit termination boundaries, move-out, and
exactly-one Final Settlement.

## TEST-122 — Critical Utility Suite

A mandatory suite covers Meter replacement, Reading validation, generation-date
rate selection, weighted broken-Meter history hierarchy, pending future-basis
charge, and duplicate Utility billing.

## TEST-128 — MFA Policy Matrix

Verify Owner and Manager require standards-based MFA before normal privileged access;
Staff without MFA can authenticate within granted capabilities; Staff with MFA enabled
must complete its challenge. Cover enrollment, correct and incorrect challenges,
reset/disablement authorization, and immutable audit evidence. Reject SMS-based MFA.

## TEST-129 — Recovery Codes

Verify secure generation and one-time presentation, protected/non-plaintext server
verification material, successful use, reuse rejection, regeneration invalidation,
rate limiting, enumeration resistance, appropriate session revocation, and audit.

Amended by DL-081 (login sub-slice L3d-2b): right after a sign-in with the sign-in code, the
session cookie alone, another session's reauthentication cookie, an empty or too long one get
no recovery codes; the session's own cookie does; after a later reauthentication only the new
cookie works.

## TEST-130 — Administrative and Emergency Recovery

Verify Owner can recover/reset Manager and Staff; ordinary Staff cannot recover Owner or
Manager; Manager-to-Staff recovery is denied unless a later explicit authority grants
it. Verify Owner recovery by recovery code and the controlled server-side emergency
procedure, including authorization, deliberate operator controls, session revocation,
secret-free logs, and immutable audit evidence.

Amended by DL-081 (login sub-slice L4): covered on PostgreSQL by `test_one_time_password_migration.py` (the records, the reset with and without MFA, who may reset whom, the change, the 24-hour end, append-only, the lock order) and `test_one_time_password_flow_migration.py` (through the flows: first password, the Owner's reset, a Staff account that kept its own sign-in code, the 24-hour edge, Staff MFA off, a sign-in, a reauthentication or a forced change that meets a reset, a change step of an account disabled meanwhile); without a database by the API, password-rule, local-authentication and blocklist tests; on the screen by TEST-FE-682, TEST-FE-683, TEST-FE-684 and TEST-FE-AUTH-011.

Amended by DL-081 (login sub-slice L5, Q-2026-10-24-186): TEST-084, TEST-085 and TEST-109 are covered without a database by `test_route_authorization_inventory.py`, which walks every operation of the app's OpenAPI document and keeps the list of the 13 open operations (every other one answers 401 without a session whatever its body, every change 403 without the Origin or the CSRF pair, and nothing succeeds or is read for a signed-in user with no capability), and on PostgreSQL by `test_settings_access_routes_migration.py` (the five Settings changes through `create_app` with real sessions: refused for the default Manager bundle, allowed with Settings access and for the Owner).

## TEST-131 — Session Time Boundaries

With controlled clocks, verify expiration immediately after 30 minutes of inactivity and
after 24 hours absolute lifetime regardless of activity. Verify secure cookie/token
properties, logout, CSRF controls where applicable, and revocation following password or
MFA recovery, account disablement, and material privilege reduction.

## TEST-132 — High-risk Reauthentication

Verify high-risk administration requires recent authentication or an additional factor
where specified and still requires the independent server-side capability and business
authorization checks.

Amended by DL-081 (login sub-slice L3d-2): the PostgreSQL tests show each listed action refused
without a recent reauthentication or with a copied session cookie alone, writing nothing; a
names-only change and signing an account out are not checked; only the latest `totp`
reauthentication of the same session within 15 minutes counts (another session's cookie,
another account's cookies, a 16-minute-old row, a signed-out session, a sign-in code turned off
since and a password-only reauthentication are refused; 14 minutes is allowed); a sign-in with
the sign-in code reauthenticates its own session only; the capability is still checked (a
reauthenticated Manager is refused).

## TEST-133 — Initial Owner CLI Bootstrap

Verify bootstrap creates the initial unique Owner only when none exists, accepts the
password through protected interactive/secret input rather than command-line arguments,
and enforces 15/128 Unicode-code-point boundaries before NFC normalization, nonempty 15/128
boundaries after normalization, complete-normalized-value local blocklisting, and full-value
verification without truncation, space/paste/password-manager acceptance, no composition or
periodic-rotation rule, and local non-disclosing compromised/common/expected/project-context
blocklist rejection. Verify exactly 10 random single-use recovery codes are shown exactly
once only on the controlling TTY; password, TOTP, and recovery secrets never enter argv,
ordinary environment, redirectable stdout, logs, state, compact state, or audit; and only
protected verifier material persists. Verify one ceremony-wide absolute monotonic deadline
starts before TOTP confirmation and covers TOTP input, recovery presentation and complete
persistence writes, acknowledgement, and commit preparation without reset or extension by
writes, partial input, retries, or trickled input. Verify explicit acknowledgement precedes
commit and presentation, TTY, timeout, acknowledgement, or TOTP-confirmation failure rolls
back the complete account, credential, MFA, recovery, audit, closure, and privilege change.
Verify the dedicated least-privilege bootstrap database identity, root-controlled
descriptor/equivalent secret-file TOTP key input, one atomic PostgreSQL boundary, immutable
secret-free audit, and confirmed Owner MFA enrollment.

## TEST-134 — Bootstrap Backdoor Prevention

Verify repeated bootstrap and attempts to create an additional Owner are rejected,
there is no public “Create First Owner” web/API path, and recovery tooling cannot be used
as an ordinary unauthenticated Owner reset. Verify successful closure permanently revokes
bootstrap mutation capability, the identity has no table or out-of-boundary privilege,
every repeat fails closed with immutable secret-free rejection evidence, and no equivalent
guard, recovery path, redirect, argument, environment input, or ordinary runtime identity
can reopen or bypass bootstrap.

## TEST-135 — Authentication Integration Regression

Verify production normal login remains local-first without Google, Microsoft, Auth0, or
another external identity provider, while capability-based authorization, Property and
object scope, existing financial authority boundaries, TLS, remote-access controls, and
audit-history integrity remain unchanged.

# 25. OPEN OWNER DECISION

## OOD-TEST-001 — Supported Browser Matrix

**Question:** Which browser versions and managed devices must be certified?

**Current treatment:** Automated UI tests target current standards-compliant
Chromium plus cross-browser coverage selected during implementation. No business
policy depends on this choice.

**RESOLVED by DL-074 (owner, 2026-10-20):** the latest Chrome, Edge and Safari, Safari on iPad included; desktop, laptop and iPad in both directions; every screen displays on a phone.

**Blocking:** No.

## OOD-TEST-002 — Production Recovery Objectives

**Question:** What RPO/RTO values and restore-drill frequency must release testing
certify?

**Current treatment:** Restore tests are mandatory; exact objectives remain
configurable and align with `009_DEPLOYMENT_ARCHITECTURE.md`.

**RESOLVED by DL-071 (owner, 2026-10-05):** at most 1 hour of data loss, working again within 1 working day, and a full restore test every 3 months and before every release.

**Blocking:** No.


# 26. Completion Criteria

This Testing Strategy is complete for Owner Review when:

- every material business lifecycle and financial invariant has explicit coverage;
- database, API, UI, integration, migration, security, and operational levels are
  distinguished;
- timezone, concurrency, idempotency, audit history, FX rounding, and broken-Meter
  boundaries have dedicated tests;
- traceability is bidirectional and enforceable;
- placeholder commands are not reported as substantive tests; and
- the remaining nonblocking browser/device certification and production recovery
  objective questions are recorded without inventing business policy.
