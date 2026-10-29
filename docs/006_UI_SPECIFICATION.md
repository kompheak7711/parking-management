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

Amended by DL-074 (owner, 2026-10-20): riel is written with ៛ after the number.

## UI-006 — Historical Visibility

Current views link to complete history. History must not be concealed behind an
edit mode or replaced by only the latest value.

## UI-007 — Accessible Operation

All workflows support keyboard navigation, visible focus, semantic labels, error
association, accessible tables/dialogs, and status announcements.

Amended by DL-074 (owner, 2026-10-04): the accessibility target is WCAG 2.2 level AA.

Amended by DL-107 (V1-060 B6, 2026-10-28): a button never looks like a text box. Buttons have a light green fill, green words and a green edge (words 4.5:1, edges 3:1, in light and dark); text boxes stay Paper with a grey edge.

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

Amended by DL-074 (owner, 2026-10-20): the app names itself "CHETANA Residence Management" and uses the CHETANA brand kit. Screens are in Khmer and English, with a ខ្មែរ / EN switch that changes every label; the app name stays in English in both. A native Khmer speaker checks the Khmer text before release.

## UI-010 — Global Search

Authorized users may search by stable identifiers and approved identifying fields
for Units, Customers, Reservations, Leases, Invoices, and Payments. Results are
grouped by type and Property scope and reveal only authorized summary fields.

Amended by DL-074 (owner, 2026-10-04): the top bar search finds Units, Customer names, phone numbers, and Invoice, Receipt and Refund numbers. It never searches or shows ID numbers. Leases and Reservations are found by their Unit, and a Payment by its Receipt number.

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

Amended by DL-072 (owner, 2026-10-04): "Leases approaching End Date" means 60 days or less before the End Date, and "ACTIVE Reservations nearing expiration" means 14 days or less before the Expiration Date. The dashboard also shows: Rent nonpayment day-20 warnings and day-30 defaults that are due, overdue Initial Rent, financial drafts waiting for approval, Deposits waiting for a decision, and Final Settlements not yet closed. Not built yet (V1-057).

Amended by DL-079 (owner, 2026-10-20): the Home page has eight cards in two rows with counts and totals (for example occupancy, outstanding Invoices, unallocated Payments, broken-meter charges, failed jobs). The dated items (expiring Reservations, Leases near their End Date, missing Readings, day-20 and day-30 letters, overdue Initial Rent, drafts waiting for approval, Deposits waiting for a decision, open Final Settlements, "Refund due by") go in a to-do list grouped Overdue, Today, This week, Later. Each card and to-do shows its as-of time and opens its page. Not built yet (V1-057).

## UI-024 — Financial Dashboard Values

Dashboard totals are server-calculated, currency-separated unless an approved
conversion basis is explicit, and never silently sum USD and KHR.

Amended by DL-072 (owner, 2026-10-04): the approved basis is DL-060: totals are in USD; KHR is never added to USD.

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

Amended by DL-078 (owner, 2026-10-20): Unit detail shows floor, Unit Type, size in m², bedrooms, bathrooms, view, kitchen, Room features, notes and the Unit inventory with its History.

Amended by DL-110 (V1-061, owner 2026-10-29): Unit detail shows the default Rent and the required Services, and a Manager or the Owner changes them with "Rent and Services". It shows "Electricity and water": each Meter (working, or broken since a day), the price in force with its start day and the next price; a kind with no Meter says the Unit is not billed for it. The Units list shows today's electricity and water prices. New Lease and Make Reservation start at the default Rent; New Lease ticks the required Services and they cannot be unticked; a Rent below the default shows that a Manager or the Owner must agree it.

## UI-027 — Unit Actions

Authorized actions may update editable Unit source data or start an approved
Reservation/Lease/Meter workflow. The UI must not offer generic deletion for a Unit
with historical references.

Amended by DL-078 (owner, 2026-10-20): New Unit and Update Unit pick from the DL-075 lists; the Unit number cannot be changed.

Amended by DL-107 (V1-060 B6, 2026-10-28): New Lease on the Unit page opens the New Lease form with that Unit chosen (with an active Reservation, the draft from that Booking); Open Lease, Open draft Lease and Open Reservation open that record.

# 8. Customer Screens

## UI-028 — Customer List

Search and display approved identifying/contact fields and concise current
relationship indicators. Do not assign permanent Customer types.

Amended by DL-078 (owner, 2026-10-20): the Customers page search may find a Customer by ID or passport number; the result list does not show the ID number (SEC-041). The top bar search never searches ID numbers.

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

Amended by DL-078 (owner, 2026-10-20): Customer detail shows legal name, date of birth, gender, nationality, ID number / Passport number, phone, email, address and memo.

## UI-030 — Customer Financial Summary

Display currency-separated outstanding Invoice and separate Late-payment Charge
obligations, unallocated Payment, and available Customer Credit values with links to
underlying events. Deposit liability is shown separately and never merged into Credit.

## UI-104 — Customer Account Ledger

Provide a dedicated read-only chronological Customer Account Ledger view sourced from
API-093. It shows authoritative obligation composition, Invoices, separate Late-payment
Charges, Payments and applications, Customer Credit events, Refunds, separately
identifiable Deposit liabilities, current amount owed, available Customer Credit,
timestamps, and stable source links.

The UI must not present this view as a General Ledger, journal-entry workspace,
Accounts Payable system, or editable financial source of truth.

Amended by V1-056 sub-slice 8a-2: the history labels the event `DEPOSIT_APPLIED` "Deposit
applied". The Deposit history screen lists each Final Settlement Deposit application with
its amount, target and governing Final Settlement.

Amended by V1-056 sub-slice 10c-2a-1: the history labels the event
`DEPOSIT_APPLICATION_REVERSED` "Deposit application reversed"; the Deposit history screen lists
each reversal with its amount and governing Final Settlement.

# 9. Reservation Workflow

## UI-031 — Reservation List

List `ACTIVE`, `CANCELLED`, and `COMPLETED` Reservations only; do not display or
create `EXPIRED` or `MOVED_IN` Reservation statuses. Show Unit, Customer, date range,
Expiration Date, Security Deposit progress, and next permitted action.

## UI-032 — Create Reservation

The form selects one Customer and one available Unit, captures authoritative dates
and agreed monthly Rent inputs, and shows the minimum partial Security Deposit
requirement. Creation must not invent a Reservation Deposit type.

The form sends no receipt time; the server records the database's own time as the holding
deposit's receipt and acceptance time (owner answer (a) to Q-2026-10-20-147, V1-056
sub-slice 10i-4b).

Amended by DL-109 (V1-060 B7 second review, 2026-10-28): after a lost answer every box that makes up the Payment or the Reservation stays fixed until the server answers, and Try again sends the very same requests. A refusal after a lost Reservation answer looks the Reservation up by its own id and opens it when it is there. When the money is saved but the Reservation is not, the dialog says so with the Receipt number and says not to receive the money again; while the money may be saved, Close asks once more. Less than the suggested Security Deposit waits until the person's rights are read, and a Unit that is not vacant is never kept from the address.

Amended by DL-109 (V1-060 B7 third review, 2026-10-28): in Make Reservation and Receive Security Deposit, a Try again after a lost answer that never leaves the browser stays not known. While the money may be saved, Escape only asks, and only the "Close anyway" button closes the dialog. Closing Make Reservation reads the Reservations list again, and closing Receive Security Deposit reads the Lease again. When the money is saved but the Reservation is refused as changed, the words do not ask to change the Unit or the Customer, which stay fixed. A whole day pasted as eight digits over a date box gets its slashes.

## UI-033 — Reservation Detail

Show current status, Property-local expiration, source dates, Security Deposit
receipts, extension Notice history, resulting Lease when any, and cancellation or
move-in event history.

## UI-034 — Extend Reservation

The action is available only when the server reports eligibility. The dialog shows
remaining days, maximum 14-day extension, resulting Expiration Date, one-extension
limit, and Notice to be recorded.

The screen sends no approval time; the server records the database's own time and the
Notice shows it (BR-RES-010, owner answer (a) to Q-2026-10-14-112 point 1, V1-056
sub-slice 10i-3).

Amended by DL-080 (owner, 2026-10-20): Extend Reservation needs a Manager.

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

Amended by DL-080 (owner, 2026-10-20): a Lease has no number; it is named by its Unit, for example "Lease · U204".

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

Amended by DL-111 (V1-061, owner 2026-10-29): each person living there has Move out on the Lease page, except the Primary Tenant (who leaves with the Lease). The dialog asks for the day and a reason; for a Joint Signer it lists every other Signer, each to tick that they agree, and says the person stays a Signer of the Lease. The only Signer still living there sees why they cannot move out yet, with no Move out.

## UI-040 — Sign Lease

Show a pre-signing summary and server validation of non-overlapping contractual
period, required parties/terms, and source values. Signing is an explicit auditable
action, not a generic status edit.

The screen sends no signing time with a Signer signature (UI-038) or the Lease
signing; it shows the times the server records, which are the database's own time,
in the Signer rows and the Lease timeline (BR-AUDIT-003, Q-2026-10-14-110).

Amended by DL-080 (owner, 2026-10-20): Sign Lease needs a Manager.

Amended by DL-108 (V1-060 B7, 2026-10-28): Sign Lease sends the ticked Signers, the reason and the money received as one request at the Lease version it showed; the server saves the Payment, the signatures, the signing, the Initial Rent Invoice and the Security Deposit together, or nothing, and the dialog says so. After no answer, Try again sends the very same request with the same key, and nothing can be changed until an answer comes; after a refusal nothing was saved, so the values may change, and changed values are a new request.

Amended by DL-109 (V1-060 B7 second review, 2026-10-28): a draft whose Reservation ended, or whose Unit another Reservation holds, is refused before any money, and the dialog says to ask the Owner or a Manager; dates that another signed Lease covers are refused by name. Closing Sign Lease reads the Lease again. The Lease page says when a draft's Security Deposit is being read or could not be read, never none.

## UI-041 — Renewal

Create a successor Lease linked to the current Lease, allowing preparation and
signing before current End Date only when periods do not overlap. Do not label it
automatic month-to-month renewal.

## UI-042 — Lease Timeline

Show drafting, signing, move-in, Lease-violation warnings, Rent-nonpayment case/events,
Termination Notices, occupancy changes, renewal, termination, move-out, and Settlement
events in chronological order with links to their distinct source records. The UI must
not merge Lease-violation warnings with Rent-nonpayment milestones.

Unpaid Initial obligation (V1-055 slice 9c): a signed Lease the viewer may terminate offers the form
"Terminate for an unpaid Initial obligation" with the governing reference BR-LEASE-005, the signed clause, approved
grounds, authorization and evidence references, and either an applicable notice or the reason none applies. A
TERMINATED Lease offers the explicit follow-up forms "Customer never moved in" (VOID or credit the Initial Rent
Invoice, release the Unit to VACANT or CLEANING with a reason; since V1-056 slice 6 the Security Deposit stays held until
a forfeiture draft is confirmed by a `financial.approve` holder) and "Customer moved in" (credit the Rent after the
termination date). Each follow-up asks for confirmation, is recorded once, and a retry of an
unchanged form reuses its identities. The Rent nonpayment workflow also lists unpaid Initial Rent alerts read only. The permanent Lease timeline names each follow-up and links it to its termination event.

Lease Utility records (V1-055 slice 9d): the Utility workspace offers, for one Lease, the Utility baseline (one validated
Reading per Meter dated on the baseline date), the final Utility inputs for a departure (a Reading, an approved estimate
or an explicit unresolved reason per Meter), the final Utility Invoice and the catch-up Invoice, each with an optional
authorized Due Date that needs its reason. A list of unbilled Utility periods shows why a period is unbilled and lets
staff select an eligible period for the explicit catch-up. Commands ask for confirmation, create no Reading, and a retry of
an unchanged form is replayed. Refusals show a plain-language text for the server's stable reason code.

Billing run diagnostics and Adjustment refusals (V1-055 slice 9d): an inspected billing run shows its item counts by outcome, each
attempt, and a table of every item with the reason in plain language (already invoiced, no longer eligible, not moved in,
Property-borne consumption, failed). A refused debit Adjustment on a fully paid line says so and points to a one-time
charge; a refused Adjustment amount states both balance rules.

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
`COMPLETED`, Unit `OCCUPIED`, and Security Deposit continuity. Partial failure must
not be shown as success.

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

Amended by DL-080 (owner, 2026-10-20): the printed Invoice is A4: Khmer above English, dates dd/mm/yyyy, 24-hour times, riel as ៛ after the number, Invoice spelled វិក្កយបត្រ everywhere, no address or phone in the header, the full-colour logo, the ABA KHQR code, and on a reprint the mark "REPRINT · ច្បាប់ចម្លង" with the reprint date. No VAT. "Move-out" is a screen label only; the records keep the DL-020 categories.

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

The debit option is unavailable for a fully paid line and explains that the amount must
be billed as a one-time charge. A credit preview shows any amount that will become
Customer Credit.

## UI-052 — Void Invoice

Exceptional voiding requires capability, reason, consequence preview, and explicit
confirmation. If active applications block voiding, link to required reversal
workflows. The original remains visible as `VOID`.

## UI-105 — Late-payment Review, Decision, and Charge

Provide an authorized workspace corresponding to API-091. For an eligible overdue
Invoice, show:

- source Invoice and Customer;
- Due Date;
- remaining overdue balance at assessment;
- normal/default rate of exactly 10%;
- calculated default Charge amount;
- prior-decision/blocking state; and
- final management action.

The final action offers only `CONFIRMED_DEFAULT`, `REDUCED`, or `WAIVED`. REDUCED
captures the exact approved USD amount below the calculated default amount. The UI must
not force an approved reduced amount into whole-basis-point percentage precision or
invent an additional rounding rule.

After confirmation, display the immutable final decision and, when positive, the
resulting separate immediately payable Late-payment Charge. The UI must clearly state
that the Charge is not an Invoice, Invoice line, Invoice category, Miscellaneous
Charge, or increase to the source Invoice balance/status.

Authorized Charge corrections/reversals use explicit DB-INV-009/API-091 actions,
reason, consequence preview, confirmation, and append-only history. They never reopen
or replace the final decision.

Amended by DL-076 (owner, 2026-10-20): the screen shows the charges the app added and lets the Owner or a Manager reduce or waive one after a Customer complaint, with one of three fixed reasons and a required "What happened" text. Next month's Invoice shows "Unpaid late-payment charge" with its amount outside the Invoice total, and the Receipt has a "Paid for" table.

# 13. Rent and Fixed Service UI

## UI-053 — Scheduled Rent Runs

Show Property-local logical billing period, eligible Leases, generated/skipped/
failed results, duplicate prevention outcome, timestamps, and links to Invoices.
Retries use the same logical run identity.

## UI-054 — Rent Calculation Detail

Show monthly Rent source, represented period, proration inputs/formula when
applicable, exact rounding result, fixed Service lines, and applicable Lease.

## UI-055 — Service Configuration

Authorized users may maintain configured Service identities and effective-dated rates
permitted by the API. A Service becomes billable only when an applicable
Owner-approved Service approval period and applicable Lease Service term exist.

The initial production UI treats Trash Collection as the currently approved billable
Service. Internet and Monthly Cleaning must not be presented as currently provided or
billable because they have no approved active period. Historical selections are
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

Display the authoritative basis used by the server:

- when three or more complete historical actual periods exist for the same Unit and
  Utility Type, use and show the three most recent complete prior periods;
- when exactly one or two complete historical actual periods exist, use and show all
  available one or two periods as the weighted historical basis; or
- when zero complete historical actual periods exist, show
  `PENDING_FUTURE_ACTUAL_BASIS` until one complete future actual period for the same
  Unit and Utility Type exists.

Show total basis consumption, represented basis days, weighted daily average, affected
unmeasured days, calculation result, and whether the charge remains pending. Do not
offer another/comparable Unit, arbitrary-estimate input, omission of available
one/two-period history, or averaging of separately rounded period averages.

# 15. Payments and Allocations UI

## UI-063 — Confirm Payment

Capture Customer, amount/currency, method, received timestamp, payer/reference, and
required evidence. Payment confirmation does not auto-select Invoices or create
Credit.

Replaced by DL-077 (owner, 2026-10-20): "Payment confirmation does not auto-select Invoices" is replaced: when the amount is entered, the app ticks Invoices oldest Due Date first, each late-payment charge right after its own Invoice. Staff change the ticks only when the Customer names an Invoice, and changing the ticks sets the amount to the ticked total. A third-party payer's money gets no automatic ticks. Pressing Receive payment saves the Payment and its Allocations in one step. Money waits only when it is more than everything owed or nothing is owed, and is not called Credit before the Customer chooses. No upload button until the later file storage step.

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

Authorized staff choose a RECEIVED Payment and eligible obligation targets: an
Invoice or separate Late-payment Charge. The UI shows Payment availability and each
target's outstanding balance, prevents obvious over-allocation, and submits explicit
Allocation commands. Server transaction rules remain authoritative.

For a normal undesignated Customer Payment, show the server's FIFO proposal across
applicable Invoices by oldest Due Date with stable tie ordering; staff must still
confirm/post it. Show Customer-designated eligible Invoice or Late-payment Charge
intent when present. A third-party payer remains distinct from the financially
responsible Customer and its Payment remains limited to the recorded designation
rather than spread across unrelated obligations.

A Late-payment Charge target is displayed as a separate obligation and Allocation to
it must never appear to reduce the source Invoice.

Amended by DL-077 (owner, 2026-10-20): the allocation workspace is used for money that waits and after a reversal; ordinary payments are allocated on the Receive payment screen in the same step (UI-063).

## UI-067 — Allocation Reversal

Show original Allocation, resulting Payment/target-obligation effects, reason, and
explicit confirmation. Record a reversal event; do not delete the Allocation.

## UI-106 — Receipt and Reprint

Payment detail links to the one immutable numbered Receipt created for the confirmed
Payment. The Receipt screen displays its stable Receipt identity/number, Payment,
Customer, issuance facts, and current joined Payment/application context without
turning displayed derived amounts into Receipt-owned financial values.

Authorized reprint uses the same Receipt UUID and Receipt Number and requires the
API-092 reprint action. Show actor, timestamp, required reason, and optional delivery
reference in reprint history. Reprinting must never appear to create another Payment,
another Receipt identity, or another money-received event. A reversed Payment retains
its original Receipt as historical evidence.

Amended by DL-080 (owner, 2026-10-20): the printed Receipt is A5, with the same language, date, time, riel, header and logo rules as the printed Invoice (UI-048) and the reprint mark "REPRINT · ច្បាប់ចម្លង" with the reprint date.

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

Authorized action selects an eligible Invoice or separate Late-payment Charge target
and exact amount, validates availability and context, shows the resulting target
balance/status or Charge balance, and records a Customer Credit application. It is not
implemented as Payment Allocation.

A Late-payment Charge application reduces only that separate Charge and must never be
displayed as reducing the source Invoice.

## UI-071 — Refund Workspace

Create a Refund only from an API-reported eligible source: Property-caused
Reservation Security Deposit Refund, eligible unallocated Payment value, eligible
Customer Credit, a Deposit Refund required by Final Settlement, or the qualifying
active-Lease Pet Deposit Refund path under UI-107.

Show authoritative source, maximum refundable amount, currency and applicable
exchange facts, reason, authorization, and consequence. Do not invent a delivery
method or pending/failed business status absent from the authoritative API/model.

Show only USD as the payout and accounting currency for every Refund (DL-060).
For eligible KHR-origin Payment excess or Credit, show the available recorded USD
value and original KHR/FX source evidence for audit. Do not offer a KHR Refund,
convert a KHR remainder, or request a Refund-date rate.

## UI-072 — Refund History

Display the authoritative completed Refund event, its source, amount/currency,
exchange facts where applicable, processing facts, authorization, and linked
corrections. Do not invent requested/pending/failed Refund business statuses.

For an erroneous completed Refund, the correction action records only verified
returned value in exact USD cents with return timestamp/method reference, reason,
and authorization; it does not imply a collection right or erase the payout. The UI
must not imply a Refund right absent from upstream rules. Partial returns of USD
Refunds require no KHR rounding; historical source and conversion facts remain intact.

## UI-107 — Active-Lease Pet Deposit Refund

For a SIGNED Lease with an approved pet, provide the authorized API-094 workflow:

1. record that the approved pet permanently left;
2. display the Pet Deposit and relevant pet-related obligations;
3. perform the qualifying refund review after those obligations are resolved; and
4. when the server reports a refundable balance, continue to the explicit Refund
   action using that Pet Deposit and review.

The pet-departure event does not terminate the Lease or itself authorize a Refund.
The qualifying review shows permanent-departure evidence, reviewed obligations,
resolved finding/reference, remaining refundable Pet Deposit, reason, actor, and
authorization.

This workflow must not create or require Final Settlement, apply the Pet Deposit to an
Invoice, refund Security Deposit during the SIGNED Lease, or imply that the Refund
limits any remaining Customer liability.

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

## UI-075 — Lease Violation Warning Letters

Show DB-LEASE-005/API-067 Lease-violation warnings by Lease with warning sequence,
violation date, warning date, violation description, governing Lease provision,
communication evidence, and actor. Creating a Lease-violation warning does not create
a Rent-nonpayment milestone, fee, or automatic termination.

## UI-108 — Rent Nonpayment Cases and Events

Provide a separate workspace for API-095 Rent-nonpayment cases and events. Opening a
case requires selection of the applicable issued, non-VOID Rent Invoice line for the
same Lease and financially responsible Customer. Show the Rent line, source Invoice,
Due Date snapshot, current remaining Rent balance, and case history. Do not derive the
case from a mixed Invoice's total balance.

Only the authoritative event actions are available:

- `TWENTY_DAY_WARNING`;
- `THIRTY_DAY_SERIOUS_DEFAULT`;
- `CURE`; and
- `AUTHORIZED_FOLLOW_UP`.

The UI shows server-evaluated milestone eligibility and remaining Rent. The 20-day
warning requires its Notice/document reference; the 30-day Serious Nonpayment Default
requires the approved milestone and positive remaining Rent. Cure and authorized
follow-up preserve prior history.

No event control may imply automatic Lease termination, Occupancy closure, Move-out,
Unit status change, Final Settlement, fee, or separate penalty. Any termination
continues through the explicit Lease termination workflow.

Show day one, the current day number and the day 20 and day 30 dates. A case already
past day 20 or day 30 shows a prominent staff alert. The Invoice Due Date is shown
separately and labelled as the late-payment boundary.

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

For an unpaid Initial Rent Invoice, show the signed-Lease clause reference and the path
that applies: never moved in (Invoice VOID or credit Adjustment of the unpaid remainder
with reason, Unit returned to VACANT; the Security Deposit stays held until a forfeiture
draft is confirmed by a `financial.approve` holder, V1-056 slice 6) or moved in (Invoice kept, prorated credit Adjustment for the
days after termination, move-out). Every step requires explicit authorized confirmation.

Neither termination form sends a termination time; the server records the database's
own time, and a retry of the same form replays the first result (BR-AUDIT-003, owner
answer (a) to Q-2026-10-14-112 point 1, V1-056 sub-slice 10i-1).

Amended by DL-080 (owner, 2026-10-20): Terminate Lease needs a Manager.

## UI-077 — Continued Occupancy

When occupancy continues after contractual End Date, show the mismatch and require
an authorized Property Management action under the signed Lease. Do not label it
automatic month-to-month tenancy.

## UI-078 — Move-out Checklist

Capture actual Move-out Date, Occupancy closure, final Meter Readings, inspection
findings, approved final charge sources, keys/evidence where upstream requirements
support them, and unresolved items. Completing Move-out does not imply Settlement
closure.

Show the final Utility Invoice created from the final Readings and its proposed Due Date.
A Damage charge is entered per finding with amount, reason and evidence reference by an
authorized user.

Amended by DL-105 (V1-060 B6, 2026-10-28): when the final Utility Invoice is refused because no electricity or water rate is in effect today, the dialog says so and points to Settings, Rates and services; any other refusal says the step was not saved, never that the hand-back was not saved.

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

Inputs are limited to approved source evidence and explicitly authorized actions.
Calculated totals, Deposit availability, and resulting balances are server-owned and
read-only.

Present the approved order explicitly:

1. finalize valid charges;
2. apply authorized Customer Credit first;
3. apply Pet Deposit to authorized pet-related Invoice lines under
   `PET_RELATED_FIRST`;
4. permit explicitly authorized Security Deposit applications under
   `SECURITY_EXPLICIT`;
5. permit any remaining Pet Deposit to be explicitly applied to any valid remaining
   Settlement Invoice line under `PET_REMAINDER_EXPLICIT`;
6. record the remaining Customer balance; and
7. explicitly Refund remaining refundable Deposit balances.

Every Deposit target and amount requires explicit authorization. Do not reuse Payment
FIFO, an inferred Deposit-type FIFO, or oldest-Due ordering for Deposit applications.

Amended by DL-106 (V1-060 B6, 2026-10-28): when the termination keeps a Deposit and its kept record is not confirmed, the Final Settlement step offers the Owner or a Manager (`deposits.dispose`) "Record kept Security Deposit" or "Record kept Pet Deposit". The dialog names the whole held amount and the ground, asks for a reason and records a draft that the Owner or a Manager confirms in Waiting for approval; while it waits, the step says so and links to Waiting for approval for a person who may approve.

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

Amended by DL-072 (owner, 2026-10-04): every audit search writes an audit event. By default only the Owner and the Manager may search audit.

## UI-086 — Reversal Chains

Financial history views render original event, application/allocation, reversal or
Adjustment, and resulting state as a linked chain rather than a flattened mutable
row.

## UI-087 — Audit Export

Authorized export states filters/scope, produces a tamper-evident or integrity-
verifiable artifact where specified technically, and creates its own audit event.

Amended by DL-072 (owner, 2026-10-04): the file is CSV, and its SHA-256 fingerprint is saved in its own audit event.

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

Amended by DL-072 (owner, 2026-10-04; answer 10 changed 2026-10-20 and 2026-10-21): all 9 reports are built. Staff get only reports 1, 2 and 7 (report 7 shows consumption without Rate or Invoice amounts), with no money totals. Overdue groups are 1 to 19, 20 to 29, and 30 days or more; a recurring monthly Rent Invoice counts from the 1st of the billed month (BR-LEASE-026), every other Invoice from the day after its Due Date (BR-INV-051). The monthly money-collected summary shows the money received in a month as: Paid to Invoices by DL-020 category, Late-payment Charges paid, money to a Deposit, money kept as Customer Credit, Refunded from the Payment, and not yet allocated; a Payment reversal is a minus line in the month of the reversal; the lines add up to the money received less reversals. No printable Customer statement. Not built yet (V1-057).

Amended by DL-079 (owner, 2026-10-20): four "Totals by Unit and month" reports come first (Total Income, Total Payment, Total Electricity, Total Water; Owner and Manager only), then the nine above in this order: Invoice register and balances, Payments and allocations, Utility consumption, Customer Credit ledger, Deposit liability and disposition, Final Settlement register, Unit occupancy, Lease dates, Audit activity. Staff keep Unit occupancy, Lease dates and Utility consumption (without amounts). The Payments report has no separate "Move-out charges" line, and its Paid to Invoices equals the Invoice register Paid total. Not built yet (V1-057).

## UI-089 — Report Parameters

Every report shows Property scope, as-of or date range, filters, currencies,
calculation basis, generated timestamp, and source links where interactive.

Amended by DL-072 (owner, 2026-10-04): totals are in USD; the Payment register also shows the KHR amount received and the exchange rate, as information only.

Amended by DL-079 (owner, 2026-10-20): every report summary has a chart; money charts are in USD only (riel at its recorded USD value), and a report without money gets a count bar chart.

Amended by DL-108 (V1-060 B7, 2026-10-28): a Totals table counts whole months, so picked days widen to their whole months and the parameter bar says "Totals count whole months."; while only some rows are shown, the table footer says "Total, all N rows"; a chart that shows only the last 31 days with events says so in its title.

Amended by DL-109 (V1-060 B7 second review, 2026-10-28): the table footer says "Total, all rows", with no number, because a report may join the server's rows into fewer lines; Pick dates pressed again keeps the days typed.

## UI-090 — Currency Separation

Unless an explicitly authorized historical conversion basis exists, reports keep
USD and KHR amounts separate rather than adding them.

Amended by DL-072 (owner, 2026-10-04): DL-060 is that basis: report totals are the recorded USD accounting values, and KHR amounts are shown only as information, never added to USD.

# 22. Configuration and Administration

## UI-091 — Business Configuration

Capability-authorized screens manage approved configured data such as accepted
Payment Methods, Utility Rates, Service Rates, Property timezone, and capability
bundles. Effective-dated history is visible and protected.

Amended by DL-074 (owner, 2026-10-20): the Owner, or a user the Owner ticks for "Settings access", may change the settings. Only the Owner gives or removes Settings access, and the Owner always has it. Every change is dated, written to the audit history, and never changes an issued Invoice, Receipt or Refund.

Amended by DL-075 (owner, 2026-10-20): the Settings screens hold the billing calendar, Reservation limits, Payment Methods, number letters and next numbers, Utility Rates (a new Rate starts on a reading day), Services, move-out cleaning rate groups and the Unit setup lists (Floors, Unit Types, Views, Kitchens, Room features), with today's values as defaults.

## UI-092 — User and Capability Administration

Authorized administrators may create/disable accounts, configure role bundles and
capabilities, revoke sessions, and inspect authorization history. Role labels do
not imply hard-coded business authority.

Amended by DL-074 (owner, 2026-10-04): the default bundles are Owner (every capability, including user accounts, role bundles and settings), Manager (no user or role administration) and Staff (daily data entry only); the bundles stay configurable. Only the Owner may reset Manager and Staff accounts (DL-058).

## UI-093 — Operational Status

Authorized operators can view deployed version, API/worker health, last scheduled
runs, migration version, and backup freshness without seeing secrets.

Amended by DL-074 (owner, 2026-10-04): the health page is for the Owner and the Manager.

## UI-109 — Local Sign-in and Enumeration Safety

The sign-in experience accepts local username and password and does not require an
external identity provider. It uses generic failure and recovery responses that do not
reveal account existence, lifecycle state, MFA enrollment, or privilege class. The UI
does not offer security questions or SMS authentication/recovery.

Amended by DL-080 (owner, 2026-10-20): after 5 wrong tries the person waits 15 minutes; the wait message is the same whether or not the account exists.

Amended by DL-081 (owner's wait rule, recorded 2026-10-23 with login sub-slice L3b; replaces the values above): after 3 wrong tries in a row the person waits 5 minutes; after 2 more wrong tries (5 in a row) 15 minutes; after that every 2 more wrong tries mean another 15-minute wait, until a correct sign-in. The wait message is the same whether or not the account exists; the sign-in screen shows it from the API's 429 answer (L6).

Amended by DL-081 (login sub-slice L6, Q-2026-10-24-187): the sign-in screens of the owner's mock-up in the CHETANA brand, in Khmer and English (a ខ្មែរ | EN switch kept on the device). A full-screen layer hides the whole app until the server says the sign-in is complete; a brand panel (logo, "Residence Management", three facts) sits beside one card, and below 900px the panel becomes a top bar. Every field has a visible label; a missing or badly shaped field shows its error under it (aria-invalid, aria-describedby) and gets focus, and nothing is sent; an answer from the server shows one notice (role alert) that gets focus. A wrong username or password gives one message ("The username or password is not right. Check both and try again."); a 429 gives "Too many tries. Wait N minutes, then try again." from the seconds of `Retry-After` (1 minute, or more rounded up). Password and code fields are cleared after every failed try. "Forgot your password?" explains that the Owner resets a Manager's or Staff member's password in person and that only the server emergency procedure resets the Owner's; it sends nothing.

## UI-110 — MFA Enrollment and Challenge

Owner and Manager are directed through protected standards-based MFA enrollment before
normal privileged use. Staff can operate without MFA unless enabled and can securely
enroll when authorized. Enrollment, verification, reset, disablement, and recovery
surfaces protect secret material and never imply authorization from a role label alone.

Amended by DL-081 (login sub-slice L6, Q-2026-10-24-187): the "Two-step sign-in" screen asks for the 6-digit code (numbers only, `one-time-code`) and can switch to a recovery code; a wrong code gives "That code is not right. Type the newest code from your phone."; a code step older than 5 minutes (10 for a new password) sends the person back to sign in. "Set up two-step sign-in" shows three numbered steps with the QR code the server makes and the key in groups of four; the key and the picture are dropped as soon as the code is confirmed. The first 10 recovery codes then show once in a numbered list with "Copy codes" and a box to tick before "Finish and open the app".

Amended by DL-081 (login sub-slice L7a, Q-2026-10-24-188): recovery codes are 12 symbols in three groups of four, such as 7KQ4-M2XD-9PRT, so a person can copy them by hand; the recovery-code box and its message show that example. The person may type a code in small or capital letters, with or without the dashes.

## UI-111 — Session Expiration and Reauthentication

The UI handles 30-minute inactivity expiry and 24-hour absolute expiry without claiming
unsaved commands succeeded, clears accessible session material, and returns the user to
sign-in. High-risk administration presents recent-reauthentication/additional-factor
requirements while preserving server-side capability checks.

Amended by DL-081 (login sub-slice L3d-2): when an administration action answers
`403 REAUTHENTICATION_REQUIRED`, the screen asks for the password and the sign-in code
(`POST /auth/reauthenticate`), keeps what the user typed, and sends the action again; the screens
come with login sub-slice L6.

Amended by DL-081 (login sub-slice L6, Q-2026-10-24-187): the session timer opens "You were signed out" with the text for 30 minutes without use, or for the 24-hour limit when that comes first, and "Sign in again"; Sign out opens the sign-in screen with "You are signed out." Before either signed-out screen the app asks the server, and a session it still holds for the same person keeps the app open (every request moves the 30 minutes on). The person's display name shows beside Sign out. A 401 on another page still shows that page's own message until the screen rebuild. While a request runs, its button reads "Please wait…" (`aria-busy` on the form), and "Back to sign in" drops the answer of a request still running; while the set-up picture is fetched the set-up screen says "Getting your QR code…" and shows no code box, and a set-up that cannot start sends the person back to sign in with the wait or the "could not reach" message. Passwords and codes are read from their boxes and never kept in the screen's state, so they never appear in the page's HTML. The account screen shows the live recovery-code set ("Your recovery codes: N still work.", with when and how they were made) and "Replace my recovery codes", which names that set, or "Generate one-time recovery codes" when there is none.

## UI-112 — Recovery Codes and Administrative Recovery

Recovery codes are presented once in a protected flow with secure-storage and single-use
guidance. Used codes cannot be displayed or reused. Authorized Owner administration may
initiate Manager/Staff recovery with explicit consequence and audit confirmation; Staff
is never shown recovery authority for Owner/Manager, and no Manager recovery of Staff is
implied.

Amended by DL-080 (owner, 2026-10-20): after an Owner reset, the one-time password works for 24 hours and must be changed at the first sign-in; the new password follows the 15 to 128 character rule.

Amended by DL-081 (login sub-slice L4): the account form shows a new account's one-time password, and the reset its new one, once in a "One-time password" box with its end time and the button "I gave it to the person—clear it"; the reset form asks only for the reason and "also reset MFA", and its confirmation says the person gets a one-time password. After a sign-in with a one-time password the sign-in screen asks "Choose your own password" (the new password twice); a rule refusal shows the server's rule and keeps the form; if the change did not finish, sign-in returns with "The password change did not finish. Sign in with your new password. If it is not accepted, sign in with your one-time password." The designed screens come with L6.

Amended by DL-081 (login sub-slice L6, Q-2026-10-24-187): the one-time password screen is "Choose a new password" with a live list (at least 15 characters with the count, no more than 128, not a common password checked when saving, both boxes match), characters counted as Unicode code points after NFC like the server; the server's rule refusal shows "This password is too common or too easy to guess. Choose another." under the field. After a sign-in with a recovery code the app shows "Recovery code used. If your phone is lost, ask the Owner to reset your two-step sign-in. Make new recovery codes after you sign in with your phone again." (the server does not give the number left at sign-in, and a recovery-code session cannot make new codes).

## UI-113 — No First-Owner Web Bootstrap

The web application exposes no “Create First Owner” route. Before bootstrap it may show
only a non-secret deployment-readiness message; initial Owner creation occurs through
the protected production-server command-line procedure.

# 23. Forms and Validation

## UI-094 — Field Requirements

Labels identify required fields, units, currency, timezone/date interpretation,
and valid formats before submission. Error summaries link to invalid fields.

## UI-095 — Dates and Periods

Display dates in Property-local business context and timestamps with timezone where
material. Consumption/billing periods show inclusive/exclusive boundaries
unambiguously.

Amended by DL-074 (owner, 2026-10-20): dates are shown as dd/mm/yyyy everywhere, for example 05/11/2026; periods as 01/11/2026 - 30/11/2026; times in 24-hour form in the Property's local time.

## UI-096 — Money Inputs

Money inputs accept only exact supported decimal formats, display currency, reject
excess precision, and convert to API minor/whole units deterministically. No binary
floating-point calculation is used for displayed authoritative results.

## UI-097 — Reasons

When upstream requires a reason, use an explicit required field and any configured
reason code plus explanatory text. Do not use a generic checkbox as the sole audit
reason.

Amended by DL-074 (owner, 2026-10-20): reasons are free text, with one exception: reducing or waiving a late-payment charge uses one of three fixed reasons plus a required "What happened" text.

# 24. Confirmation Dialogs

## UI-098 — Significant Action Confirmation

Confirmations are required for at least:

- Reservation cancellation;
- Lease signing and termination;
- Invoice issuance, Adjustment, and exceptional void;
- final Late-payment Decision and authorized Late-payment Charge correction/reversal;
- Payment confirmation and Reversal;
- Allocation and Allocation Reversal;
- Customer Credit recognition/application/reversal;
- Receipt reprint when submitted as an auditable reprint action;
- Refund;
- active-Lease Pet Deposit qualifying review and resulting Refund;
- Deposit disposition/application/reversal where applicable;
- Rent-nonpayment milestone/follow-up posting;
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

Amended by DL-074 (owner, 2026-10-20): full work is supported on desktop, laptop and iPad, in portrait and landscape, with touch targets at least 44px tall, in the latest Chrome, Edge and Safari (Safari on iPad included). Phones are for viewing and confirming, but every screen must still display on a phone.

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
| Active-Lease Pet Deposit Refund | `BR-DEP-*`, `BR-REFUND-*` |
| Rent/Services | `BR-RENT-*`, `BR-SVC-*` |
| Utilities | `BR-UTIL-*` |
| Invoices/Adjustments | `BR-INV-*` |
| Late-payment Decision/Charge | `BR-INV-051` through `BR-INV-055`, `BR-LATE-*` |
| Payments/Allocations | `BR-PAY-*` |
| Receipt/Reprint | `BR-RECEIPT-*` |
| Customer Account Ledger | `BR-LEDGER-*` |
| Credit/Refund/Reversal | `BR-CREDIT-*`, `BR-REFUND-*` |
| Rent Nonpayment | `BR-LEASE-026` through `BR-LEASE-030`, applicable `BR-PAY-*` |
| Termination/Move-out | `BR-LEASE-017` through `BR-LEASE-030`, `BR-MOVEOUT-*`, `BR-SETTLE-*` |
| Final Settlement | `BR-SETTLE-*` |
| Currency/FX | `BR-MONEY-*` |
| Audit/Authorization | `BR-AUDIT-*`, `BR-AUTH-*`, `008_SECURITY_MODEL.md` |
| Authentication, MFA, sessions, and recovery | `PR-CAP-009`, `SEC-009` through `SEC-018`, `SEC-071` through `SEC-075`, `DL-055` through `DL-059` |

# 27. OPEN OWNER DECISION

## OOD-UI-001 — Brand and Visual Design Tokens

**Question:** Which final brand colors, typography, logo, and visual design tokens
must the application use?

**Current treatment:** Use an accessible, neutral staff-oriented design system;
visual branding can change without changing business workflows.

**RESOLVED by DL-074 (owner, 2026-10-20):** the CHETANA brand kit (logo, colours and fonts) of the owner's design file DESIGN.md, which comes into the repository with the screen rebuild; the app name is "CHETANA Residence Management". Technical names do not change.

**Blocking:** No.

## OOD-UI-002 — Certified Browser/Device Matrix

**Question:** Which browsers and managed devices must be formally supported?

**Current treatment:** Implement standards-compliant responsive web behavior and
record the certification matrix in testing/deployment configuration.

**RESOLVED by DL-074 (owner, 2026-10-20):** desktop, laptop and iPad (both directions) in the latest Chrome, Edge and Safari, Safari on iPad included; phones for viewing and confirming, every screen still displays on a phone.

**Blocking:** No.


# 28. Completion Criteria

This UI Specification is complete for Owner Review when:

- navigation and every requested lifecycle workflow are defined;
- current, historical, calculated, and editable data are distinct;
- financial actions use explicit confirmations and append-only history;
- Pet Deposit, Invoice ownership, Utility Rate, broken-Meter, FX rounding, and
  Settlement rules are represented without reinterpretation;
- all major views include loading, empty, error, conflict, and authorization states;
- accessibility, tables, search, filters, sorting, and reports are specified; and
- the remaining nonblocking brand/design-token and browser/device certification
  questions are explicit and no fallback business policy is implied.
