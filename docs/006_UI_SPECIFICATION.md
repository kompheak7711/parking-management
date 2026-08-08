# 006 — UI Specification

**Document Status:** Owner Review
**Authority:** Downstream of `001_DOMAIN_MODEL.md` through `005_API_SPECIFICATION.md`
**Scope:** Staff-facing web interface for approved Property Rental Management workflows
**Requirement identifiers:** `UI-*`

---

# 1. Purpose

This document defines a practical, accessible React/TypeScript user interface for
Property Management staff. The UI exposes only actions authorized by upstream
business rules and the API. It must not create policy through labels, defaults, or
editable fields.

The backend remains authoritative for calculations, authorization, status
transitions, concurrency, and financial integrity.

# 2. UX Principles

## UI-001 — Current, Historical, Calculated, and Editable Distinction

Every record view must visually distinguish:

- current authoritative state;
- historical events and superseded values;
- server-calculated values;
- editable source data; and
- auditable actions that create a new event.

## UI-002 — No Silent Financial Editing

Issued Invoices, confirmed Payments, Allocations, Credits, Refunds, Reversals,
Deposit dispositions, and closed Settlements must not appear as ordinary editable
forms. Corrections use explicit authorized actions with reason and consequence.

## UI-003 — Server Authority

Client validation improves usability but never substitutes for API validation.
After every command, the UI renders the server-returned result rather than
predicting success.

## UI-004 — Capability-sensitive Controls

Navigation, actions, fields, exports, and audit views reflect the authenticated
user's capabilities. Hidden or disabled controls are usability features; API
authorization remains mandatory.

## UI-005 — Financial Clarity

Amounts always display currency, exact formatting, source/selected rate when
relevant, and whether a value is source, calculated, outstanding, available,
held, applied, refunded, or reversed.

## UI-006 — Historical Visibility

Current views link to complete history. History must not be concealed behind an
edit mode or replaced by only the latest value.

## UI-007 — Accessible Operation

All workflows support keyboard navigation, visible focus, semantic labels, error
association, accessible tables/dialogs, and status announcements.

# 3. Application Shell and Navigation

## UI-008 — Primary Navigation

The application shell provides capability-sensitive navigation to:

1. Dashboard
2. Units
3. Customers
4. Reservations
5. Leases
6. Billing
7. Utilities
8. Payments and Credits
9. Move-out and Settlements
10. Reports
11. Audit History
12. Configuration and Administration

Items with no permitted content are hidden or shown as unavailable according to
security design; direct URL access still uses server authorization.

## UI-009 — Global Context

The shell displays Property name, Property-local date/time context, authenticated
user, environment indicator outside production, and application build identifier
in an appropriate support area.

## UI-010 — Global Search

Authorized users may search by stable identifiers and approved identifying fields
for Units, Customers, Reservations, Leases, Invoices, and Payments. Results are
grouped by type and Property scope and reveal only authorized summary fields.

## UI-011 — Breadcrumbs and Deep Links

Record screens provide breadcrumbs and stable deep links. Links between Customer,
Unit, Reservation, Lease, Invoice, Payment, and Settlement preserve workflow
context without duplicating state in the URL.

# 4. Common Screen States

## UI-012 — Loading

Use a visible loading state that preserves page structure where practical. Buttons
that submitted an in-flight command prevent accidental duplicate submission while
allowing navigation warnings when appropriate.

## UI-013 — Empty

Empty states explain what the list represents and present an authorized next action
only when upstream rules permit it. An empty state must not imply missing data is
zero financial value unless the server confirms that value.

## UI-014 — Error

Errors display a safe summary, correlation identifier, retry option for retryable
reads, and field-level details for validation. They never expose stack traces,
SQL, secrets, or unauthorized record existence.

## UI-015 — Conflict

Concurrency or stale-version conflicts state that data changed, reload the current
server record, preserve the user's unsent source input where safe, and require a
fresh decision. The UI must not overwrite automatically.

## UI-016 — Forbidden

Forbidden views/actions explain insufficient permission without revealing
restricted data. Authentication expiry directs the user through reauthentication
without replaying a financial command blindly.

## UI-017 — Success

Success feedback identifies the created event/record and links to its details.
Financial success messages include amount/currency and current resulting state.

# 5. Tables, Filters, Search, and Sorting

## UI-018 — Standard Table Behavior

Data tables support server-side pagination, deterministic sorting, accessible
headers, total/next-page context where available, and preserved filters during
detail navigation.

## UI-019 — Standard Filters

Only meaningful approved fields are filterable, including status, date/period,
Unit, Customer, Lease association, Invoice category, Payment method, and audit
actor/action where applicable.

## UI-020 — Monetary Columns

Monetary columns right-align values, include currency in header or each cell, avoid
ambiguous color-only meaning, and expose exact values to assistive technology.

## UI-021 — Export

Export appears only for supported reports/lists and authorized users. The dialog
shows filters, scope, sensitive-data warning, and audit consequence. Export does
not introduce a new report calculation.

# 6. Dashboard

## UI-022 — Dashboard Purpose

The dashboard summarizes existing authoritative records for operational attention.
It must not create a new financial status or policy.

## UI-023 — Dashboard Cards

Where supported by existing data, show:

- Unit occupancy/reservation state counts;
- ACTIVE Reservations nearing expiration;
- Leases approaching End Date;
- missing or pending monthly Utility Readings;
- broken-Meter charges pending future history;
- outstanding Invoice totals by currency/status;
- unallocated Payment totals;
- pending authorized workflow items; and
- failed or overdue scheduled jobs visible to operators.

Each card links to its filtered source list and states the as-of time.

## UI-024 — Financial Dashboard Values

Dashboard totals are server-calculated, currency-separated unless an approved
conversion basis is explicit, and never silently sum USD and KHR.

# 7. Unit Screens

## UI-025 — Unit List

Display Unit identifier/name, current occupancy/reservation summary, active Meter
summary, current Lease summary, and operational alerts. Filters include current
state and Meter/Reading attention where supported.

## UI-026 — Unit Detail

Tabs or sections include:

- Overview
- Reservations
- Leases and Occupancy
- Meters and Readings
- Billing history
- Audit history

Historical and future non-overlapping Leases are distinct from current occupancy.

## UI-027 — Unit Actions

Authorized actions may update editable Unit source data or start an approved
Reservation/Lease/Meter workflow. The UI must not offer generic deletion for a Unit
with historical references.

# 8. Customer Screens

## UI-028 — Customer List

Search and display approved identifying/contact fields and concise current
relationship indicators. Do not assign permanent Customer types.

## UI-029 — Customer Detail

Show identity/contact source data and role-based relationships:

- Reservations;
- Leases as Primary Tenant or Signer;
- Occupancy;
- Invoices;
- Payments and active Allocations;
- Customer Credit;
- Refunds; and
- audit history.

## UI-030 — Customer Financial Summary

Display currency-separated outstanding Invoice, unallocated Payment, and available
Customer Credit values with links to underlying events. Deposit liability is shown
separately and never merged into Credit.

# 9. Reservation Workflow

## UI-031 — Reservation List

List `ACTIVE`, `CANCELLED`, and `MOVED_IN` Reservations only; do not display or
create an `EXPIRED` status. Show Unit, Customer, date range, Expiration Date,
Security Deposit progress, and next permitted action.

## UI-032 — Create Reservation

The form selects one Customer and one available Unit, captures authoritative dates
and agreed monthly Rent inputs, and shows the minimum partial Security Deposit
requirement. Creation must not invent a Reservation Deposit type.

## UI-033 — Reservation Detail

Show current status, Property-local expiration, source dates, Security Deposit
receipts, extension Notice history, resulting Lease when any, and cancellation or
move-in event history.

## UI-034 — Extend Reservation

The action is available only when the server reports eligibility. The dialog shows
remaining days, maximum 14-day extension, resulting Expiration Date, one-extension
limit, and Notice to be recorded.

## UI-035 — Cancel Reservation

Cancellation requires an approved reason and confirmation. Property-caused
cancellation clearly shows the required Security Deposit Refund consequence when
applicable. Customer-caused cancellation or expiration shows the received Security
Deposit as non-refundable and previews the required explicit linked disposition
event, amount, governing Reservation/cause, authorization, and audit facts before
confirmation. Expiration displays reason `RESERVATION_EXPIRED` rather than a new
status; no path offers a free-form forfeiture.

# 10. Lease Workflow

## UI-036 — Lease List

Support status, Unit, Customer, date, current/future/historical period, and
approaching-End-Date filters. A future signed non-overlapping renewal is visually
distinct from the current Lease.

## UI-037 — Lease Draft

Capture Unit, Primary Tenant, contractual dates, Rent terms, approved fixed Service
terms, pet terms, Deposit terms, and Signers/Occupants without treating common
rental behavior as policy defaults.

## UI-038 — Signers

Allow multiple Lease Signers with Primary Tenant identification and joint-
responsibility disclosure. Signer rows are editable only while the Lease is DRAFTED
and become immutable after signing.

## UI-039 — Occupants

Manage Occupants separately from Signers. Clearly label that occupancy does not
itself establish signer responsibility.

## UI-040 — Sign Lease

Show a pre-signing summary and server validation of non-overlapping contractual
period, required parties/terms, and source values. Signing is an explicit auditable
action, not a generic status edit.

## UI-041 — Renewal

Create a successor Lease linked to the current Lease, allowing preparation and
signing before current End Date only when periods do not overlap. Do not label it
automatic month-to-month renewal.

## UI-042 — Lease Timeline

Show drafting, signing, move-in, warnings, notices, occupancy changes, renewal,
termination, move-out, and Settlement events in chronological order with links to
source records.

# 11. Move-in Workflow

## UI-043 — Move-in Checklist

Show server-evaluated prerequisites, including signed Lease, Reservation/Unit
consistency, required Security and conditional Pet Deposit state, Signers,
Occupants, and move-in evidence/readings where required.

## UI-044 — Conditional Pet Deposit Display

Pet Deposit appears required only when both pet approval and applicable signed
Lease terms require it. Possible future pet ownership must not create a Deposit
requirement.

## UI-045 — Complete Move-in

One explicit confirmation coordinates actual move-in/Occupancy, Reservation
`MOVED_IN`, and Deposit continuity. Partial failure must not be shown as success.

# 12. Billing Workspace

## UI-046 — Billing Navigation

Billing contains Invoices, scheduled generation runs, Rates/Services where
permitted, and Adjustments. Utility source entry remains in Utilities but links to
resulting Invoices.

## UI-047 — Invoice List

Display Invoice number/ID, exactly one Customer, optional zero-or-one Lease,
category, issue date, due date, currency, original/adjusted amount, outstanding
balance, and status. Lease-less Invoices are valid where their approved obligation
requires no Lease.

## UI-048 — Invoice Detail

Separate:

- immutable issued header and lines;
- explicit Customer and optional Lease context;
- source records/calculation evidence;
- active and reversed Allocations/Credits/Deposit applications;
- Adjustments;
- derived balance/status; and
- audit timeline.

## UI-049 — Draft Invoice

Draft entry exposes only fields/categories authorized by API/product requirements.
Rent requires the applicable signed Lease. Optional Lease association does not
expose an arbitrary charge mechanism.

## UI-050 — Issue Invoice

Issue confirmation shows Customer, optional Lease, lines, currency, amount, period,
due date, and duplicate/source validation. Server-calculated fields are read-only.

## UI-051 — Adjust Invoice

The action selects debit or Credit Adjustment, exact amount/currency, reason, and
supporting source context. It previews resulting balance/status but records a new
Adjustment rather than editing the issued Invoice.

## UI-052 — Void Invoice

Exceptional voiding requires capability, reason, consequence preview, and explicit
confirmation. If active applications block voiding, link to required reversal
workflows. The original remains visible as `VOID`.

# 13. Rent and Fixed Service UI

## UI-053 — Scheduled Rent Runs

Show Property-local logical billing period, eligible Leases, generated/skipped/
failed results, duplicate prevention outcome, timestamps, and links to Invoices.
Retries use the same logical run identity.

## UI-054 — Rent Calculation Detail

Show monthly Rent source, represented period, proration inputs/formula when
applicable, exact rounding result, fixed Service lines, and applicable Lease.

## UI-055 — Service Configuration

Authorized users may maintain effective-dated fixed recurring Internet and Trash
Collection rates/terms permitted by upstream rules. Historical selections are
read-only. No generic one-time Service option is added.

# 14. Utilities UI

## UI-056 — Meter List and Detail

Show Unit, Utility Type, serial/identity, installation/replacement dates, current
assignment, and complete Reading history.

## UI-057 — Install or Replace Meter

Capture source identity/dates and required boundary Reading evidence. Preview which
Meter becomes current; preserve the replaced Meter history.

## UI-058 — Reading Entry

Support efficient authorized monthly entry with Unit/Meter context, previous
Reading, period, current value, validation, and clear per-row success/error. Bulk
entry, if implemented, must preserve item-level results and must not bypass rules.

## UI-059 — Reading Correction

A correction action displays original value and affected calculations, requires
reason/authorization, and records history. It must not silently rewrite an issued
Utility Invoice.

## UI-060 — Utility Rate History

Show effective-dated Rate history. New Rate entry is an auditable source-data action;
it captures and displays advance-notice timestamp/evidence and rejects an Effective
Date not later than the Property-local notice date. Issued Invoices retain their
selected generation-date Rate.

## UI-061 — Utility Calculation Detail

Show Meter/Readings, consumption period, consumption, Invoice generation date,
selected Rate/effective-date evidence, and line amount.

## UI-062 — Broken-meter Handling

Display the exact basis:

- three most recent complete prior actual periods when three or more exist;
- pending/unfinalized state when only one or two complete prior periods exist,
  until one complete future actual period for the same Unit and Utility Type; or
- the same pending future-period treatment when no complete prior period exists.

Show total consumption, represented days, basis daily average, affected days, and
result. Do not offer a one/two-period historical substitution, another Unit, or
arbitrary-estimate input.

# 15. Payments and Allocations UI

## UI-063 — Confirm Payment

Capture Customer, amount/currency, method, received timestamp, payer/reference, and
required evidence. Payment confirmation does not auto-select Invoices or create
Credit.

## UI-064 — Exchange-rate Panel

For required USD/KHR conversion, show:

- ABA-equivalent Sell reference source/value/timestamp;
- automatic-source success or authorized manual fallback reason;
- fixed `0.5%` markup;
- upward-rounded whole-KHR System Exchange Rate;
- USD amount;
- unrounded calculation where safe; and
- final upward-rounded KHR payable.

Markup and rounding fields are calculated and not editable.

## UI-065 — Payment Detail

Show `RECEIVED` or `REVERSED`, source receipt facts, currency/FX evidence, active and
reversed Allocations, authorized Credit/Refund dispositions, available unallocated
amount, and audit timeline.

## UI-066 — Manual Allocation Workspace

Authorized staff choose a RECEIVED Payment and one or more eligible Customer
Invoices. The UI shows Payment availability and each Invoice outstanding balance,
prevents obvious over-allocation, and submits explicit Allocation commands. Server
transaction rules remain authoritative.

For a normal undesignated Customer Payment, show the server's FIFO proposal by
oldest Due Date with stable tie ordering; staff must still confirm/post it. Show
Customer-designated eligible Invoice intent instead when present. A third-party
payer remains distinct from the Customer and its Payment is limited to the
recorded designation rather than spread across unrelated obligations.

## UI-067 — Allocation Reversal

Show original Allocation, resulting Payment/Invoice effects, reason, and explicit
confirmation. Record a reversal event; do not delete the Allocation.

## UI-068 — Overpayment Choices

Unallocated excess remains labeled as part of the Payment. Offer Customer Credit or
Refund disposition only through separately authorized actions. Do not label excess
as Credit before recognition.

# 16. Customer Credit and Refund UI

## UI-069 — Credit Ledger

Show each recognition/source, application, reversal, available balance, currency,
and linked Customer/financial events. Credit is separate from Deposit and Payment.
Customer Credit is shown in USD accounting value; KHR-originated source amount and
receipt exchange rate remain visible as historical evidence, not a KHR Credit
balance.

## UI-070 — Apply Credit

Authorized action selects eligible Invoice and amount, validates currency and
availability, shows resulting balance/status, and records a Credit application.
It is not implemented as Payment Allocation.

## UI-071 — Refund Workspace

Create Refund only from an API-reported eligible source such as approved
Property-caused Reservation cancellation, Payment excess/Credit, or Final
Settlement result. Show source, maximum refundable amount, currency, method/reference,
reason, authorization, and consequence.

For unallocated KHR excess refunded before Credit recognition, show the
corresponding original KHR excess. For USD Customer Credit later refunded in KHR,
show the Refund-date exchange rate and preserved USD/KHR values before confirmation.

## UI-072 — Refund History

Display requested/recorded/completed facts and corrections as defined by approved
statuses/events. For an erroneous completed Refund, the correction action records
only verified returned value with exact amount/currency, return timestamp/method
reference, reason, and authorization; it does not imply a collection right or erase
the payout. The UI must not imply a Refund right absent from upstream rules.

# 17. Reversal UI

## UI-073 — Payment Reversal

Present original Payment and complete active downstream impact. Require resolution
or coordinated reversal of affected Allocations/Credit events, Deposit Receipts,
Deposit Applications/Dispositions, and required verified Refund returns as specified.
Provide the authorized Deposit Receipt reversal action and require reason,
authorization, and explicit irreversible-action confirmation.

## UI-074 — Reversal Result

After success, display linked reversal event, Payment `REVERSED`, recomputed Invoice
balances/statuses, Deposit/Credit balances, and preserved original history.

# 18. Warning, Termination, and Move-out UI

## UI-075 — Warning Letters

Show warnings by Lease with sequence/order, reason, issue/delivery evidence, actor,
and status/effect defined upstream. Creating a warning does not display a fee or
automatic termination consequence unless explicitly authorized.

## UI-076 — Termination Workflow

Guide authorized staff through approved grounds, Notice/evidence, effective date,
and business-action confirmation. Avoid generic status PATCH or unsupported penalty,
forfeiture, Rent, or Refund promises.

For voluntary early termination, show full Rent for the move-out calendar month,
applicable Utility/fixed Service/other approved obligations, Security Deposit
non-refundability as an explicit disposition, separately settled Pet Deposit, no
standard early-termination fee, and no later-month Rent after termination. For
violation termination, show and validate at least three documented warning letters
and the signed-Lease authority.

## UI-077 — Continued Occupancy

When occupancy continues after contractual End Date, show the mismatch and require
an authorized Property Management action under the signed Lease. Do not label it
automatic month-to-month tenancy.

## UI-078 — Move-out Checklist

Capture actual Move-out Date, Occupancy closure, final Meter Readings, inspection
findings, approved final charge sources, keys/evidence where upstream requirements
support them, and unresolved items. Completing Move-out does not imply Settlement
closure.

# 19. Final Settlement UI

## UI-079 — Settlement Queue

List terminated Leases requiring their exactly one Final Settlement and Settlements
in preparation/closure states supported by the API.

## UI-080 — Settlement Detail

Display:

- terminated Lease and responsible Customers/Signers;
- outstanding approved obligations and Adjustments;
- active Allocations and Customer Credit applications;
- Security Deposit and Pet Deposit separately;
- each proposed Deposit disposition/application/Refund;
- resulting Customer amount due or Refund result;
- immutable closing-balance-due snapshot separately from later corrected position;
  and
- complete source/audit links.

## UI-081 — Settlement Preparation

Inputs are limited to approved source evidence and dispositions. Calculated totals,
Deposit availability, and resulting balances are server-owned and read-only.

Present the approved order explicitly: valid charges, authorized Customer Credit,
Pet Deposit only for authorized pet-related damage, Security Deposit against
remaining authorized obligations in oldest-Due order where applicable, remaining
Customer balance, then explicit Refund of remaining refundable Deposits.

## UI-082 — Close Settlement

Require all server preconditions, authorization, reason/confirmation, and an exact
final summary. Closure creates auditable events; it never rewrites ordinary
Invoices or treats Deposits as pre-settlement Credit.

## UI-083 — Settlement Correction

Any approved correction is an explicit linked event/action and preserves the
original closed Settlement. Provide the explicit Deposit Application reversal action
when applicable and render every source/application/reversal chain. Generic editing
is prohibited.

# 20. Audit and History Views

## UI-084 — Record Timeline

Each significant record provides a chronological timeline of source changes,
business actions, actor/system identity, timestamps, reasons, prior/resulting state,
and linked records as authorized.

## UI-085 — Global Audit Search

Authorized users may filter by date, actor, action, record type/ID, Customer, Unit,
Lease, and correlation identifier. Results paginate and protect sensitive data.

## UI-086 — Reversal Chains

Financial history views render original event, application/allocation, reversal or
Adjustment, and resulting state as a linked chain rather than a flattened mutable
row.

## UI-087 — Audit Export

Authorized export states filters/scope, produces a tamper-evident or integrity-
verifiable artifact where specified technically, and creates its own audit event.

# 21. Reports

## UI-088 — Supported Reports

Reports may present existing authoritative data for:

- Unit occupancy/reservation/Lease state;
- Lease dates and approaching End Dates;
- Invoice register and outstanding balances;
- Payment/Allocation register and unallocated amounts;
- Customer Credit ledger;
- Deposit liability and disposition ledger;
- Utility consumption/Rate/Invoice history;
- Final Settlement register; and
- audit activity.

These reports do not authorize forecasting, new accounting classifications, fees,
or financial consolidation rules.

## UI-089 — Report Parameters

Every report shows Property scope, as-of or date range, filters, currencies,
calculation basis, generated timestamp, and source links where interactive.

## UI-090 — Currency Separation

Unless an explicitly authorized historical conversion basis exists, reports keep
USD and KHR amounts separate rather than adding them.

# 22. Configuration and Administration

## UI-091 — Business Configuration

Capability-authorized screens manage approved configured data such as accepted
Payment Methods, Utility Rates, Service Rates, Property timezone, and capability
bundles. Effective-dated history is visible and protected.

## UI-092 — User and Capability Administration

Authorized administrators may create/disable accounts, configure role bundles and
capabilities, revoke sessions, and inspect authorization history. Role labels do
not imply hard-coded business authority.

## UI-093 — Operational Status

Authorized operators can view deployed version, API/worker health, last scheduled
runs, migration version, and backup freshness without seeing secrets.

# 23. Forms and Validation

## UI-094 — Field Requirements

Labels identify required fields, units, currency, timezone/date interpretation,
and valid formats before submission. Error summaries link to invalid fields.

## UI-095 — Dates and Periods

Display dates in Property-local business context and timestamps with timezone where
material. Consumption/billing periods show inclusive/exclusive boundaries
unambiguously.

## UI-096 — Money Inputs

Money inputs accept only exact supported decimal formats, display currency, reject
excess precision, and convert to API minor/whole units deterministically. No binary
floating-point calculation is used for displayed authoritative results.

## UI-097 — Reasons

When upstream requires a reason, use an explicit required field and any configured
reason code plus explanatory text. Do not use a generic checkbox as the sole audit
reason.

# 24. Confirmation Dialogs

## UI-098 — Significant Action Confirmation

Confirmations are required for at least:

- Reservation cancellation;
- Lease signing and termination;
- Invoice issuance, Adjustment, and exceptional void;
- Payment confirmation and Reversal;
- Allocation and Allocation Reversal;
- Customer Credit recognition/application/reversal;
- Refund;
- Deposit disposition;
- Final Settlement closure/correction;
- Meter replacement/Reading correction affecting billing; and
- authorization/role changes.

## UI-099 — Confirmation Content

A confirmation identifies the action, target, amount/currency where applicable,
resulting status/consequence, reason requirement, and whether a new immutable audit
or financial event will be created.

## UI-100 — No Misleading Destructive Language

Use “void,” “reverse,” “adjust,” “cancel,” or “deactivate” according to the actual
business action. Do not label an append-only correction as “delete.”

# 25. Responsive and Browser Behavior

## UI-101 — Desktop-first Staff Workflow

The primary layout supports desktop/laptop property-management work with efficient
tables and keyboard entry. Essential review and confirmation remains usable on
smaller screens without hiding financial context.

## UI-102 — Unsaved Changes

Editable source-data forms warn before losing unsaved changes. Auditable commands
are not stored for blind automatic replay after navigation or connectivity loss.

## UI-103 — Connectivity Loss

The UI reports offline/API-unavailable state and does not claim success. Financial
commands require a confirmed server response or later explicit reconciliation by
idempotency key.

# 26. Traceability

Every `BR-X-NNN` reference below also cites the exact same-suffix `PR-X-NNN` under
the 003 bijection; wildcards and inclusive ranges expand identically.

| UI area | Upstream authority |
|---|---|
| Reservation | `BR-RES-*`, applicable `PR-*` |
| Lease/Occupancy | `BR-LEASE-*`, `BR-OCC-*`, `BR-DEP-*` |
| Deposits/Pets | `BR-DEP-*` |
| Rent/Services | `BR-RENT-*`, `BR-SVC-*` |
| Utilities | `BR-UTIL-*` |
| Invoices/Adjustments | `BR-INV-*` |
| Payments/Allocations | `BR-PAY-*` |
| Credit/Refund/Reversal | `BR-CREDIT-*`, `BR-REFUND-*` |
| Termination/Move-out | `BR-LEASE-017` through `BR-LEASE-025`, `BR-MOVEOUT-*`, `BR-SETTLE-*` |
| Final Settlement | `BR-SETTLE-*` |
| Currency/FX | `BR-MONEY-*` |
| Audit/Authorization | `BR-AUDIT-*`, `BR-AUTH-*`, `008_SECURITY_MODEL.md` |

# 27. OPEN OWNER DECISION

## OOD-UI-001 — Brand and Visual Design Tokens

**Question:** Which final brand colors, typography, logo, and visual design tokens
must the application use?

**Current treatment:** Use an accessible, neutral staff-oriented design system;
visual branding can change without changing business workflows.

**Blocking:** No.

## OOD-UI-002 — Certified Browser/Device Matrix

**Question:** Which browsers and managed devices must be formally supported?

**Current treatment:** Implement standards-compliant responsive web behavior and
record the certification matrix in testing/deployment configuration.

**Blocking:** No.

## OOD-UI-003 — First Partial-month Rent Due Date

**Question:** What Due Date must the UI display when a first partial-month Rent
Invoice is issued after the normal 5th-day Due Date and the signed Lease is silent?

**Current treatment:** The UI displays only the Due Date returned by an
authoritative server rule or explicit signed-Lease term. It must not select a
fallback or imply a fee, penalty, default, or collection right.

**Blocking:** No for UI architecture; blocks final behavior for this exact case.

# 28. Completion Criteria

This UI Specification is complete for Owner Review when:

- navigation and every requested lifecycle workflow are defined;
- current, historical, calculated, and editable data are distinct;
- financial actions use explicit confirmations and append-only history;
- Pet Deposit, Invoice ownership, Utility Rate, broken-Meter, FX rounding, and
  Settlement rules are represented without reinterpretation;
- all major views include loading, empty, error, conflict, and authorization states;
- accessibility, tables, search, filters, sorting, and reports are specified; and
- every remaining open item is explicit and no fallback business policy is implied.
